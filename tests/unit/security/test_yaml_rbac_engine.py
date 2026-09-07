"""Unit tests for YamlPolicyEngine and declarative YAML RBAC compliance with ADR 010."""

from pathlib import Path

import pytest

from platform_core.errors import ConfigurationError
from platform_core.models import PrincipalIdentity
from platform_security.interfaces import Authorizer, PolicyEngine
from platform_security.models import SecurityContext
from platform_security.rbac import YamlPolicyEngine


@pytest.fixture
def default_engine() -> YamlPolicyEngine:
    return YamlPolicyEngine(attachment_access_enabled=False)


@pytest.fixture
def attachment_enabled_engine() -> YamlPolicyEngine:
    return YamlPolicyEngine(attachment_access_enabled=True)


def test_engine_implements_protocols(default_engine: YamlPolicyEngine) -> None:
    assert isinstance(default_engine, PolicyEngine)
    assert isinstance(default_engine, Authorizer)


def test_l1_allowed_on_l1_tools(default_engine: YamlPolicyEngine) -> None:
    decision_ticket = default_engine.evaluate_policy("L1", "get_ticket")
    assert decision_ticket.is_allowed is True

    decision_kb = default_engine.evaluate_policy("L1", "search_knowledge")
    assert decision_kb.is_allowed is True

    decision_att_meta = default_engine.evaluate_policy("L1", "list_attachments")
    assert decision_att_meta.is_allowed is True


def test_l1_denied_on_l2_and_l3_tools(default_engine: YamlPolicyEngine) -> None:
    decision_company = default_engine.evaluate_policy("L1", "get_company")
    assert decision_company.is_allowed is False
    assert decision_company.denial_code == "INSUFFICIENT_ROLE"

    decision_deadlocks = default_engine.evaluate_policy("L1", "find_deadlocks")
    assert decision_deadlocks.is_allowed is False
    assert decision_deadlocks.denial_code == "INSUFFICIENT_ROLE"


def test_l2_inherits_l1_and_accesses_l2(default_engine: YamlPolicyEngine) -> None:
    # Inherited L1
    assert default_engine.evaluate_policy("L2", "get_ticket").is_allowed is True
    assert default_engine.evaluate_policy("L2", "search_knowledge").is_allowed is True
    # Native L2
    assert default_engine.evaluate_policy("L2", "get_company").is_allowed is True
    assert default_engine.evaluate_policy("L2", "get_database_health").is_allowed is True
    assert default_engine.evaluate_policy("L2", "search_logs").is_allowed is True
    # Denied L3
    assert default_engine.evaluate_policy("L2", "find_deadlocks").is_allowed is False


def test_l3_inherits_l1_l2_and_accesses_l3(default_engine: YamlPolicyEngine) -> None:
    assert default_engine.evaluate_policy("L3", "get_ticket").is_allowed is True
    assert default_engine.evaluate_policy("L3", "get_company").is_allowed is True
    assert default_engine.evaluate_policy("L3", "find_deadlocks").is_allowed is True
    assert default_engine.evaluate_policy("L3", "get_host_metrics").is_allowed is True


def test_unknown_tool_denied_by_default(default_engine: YamlPolicyEngine) -> None:
    decision = default_engine.evaluate_policy("L3", "non_existent_arbitrary_tool")
    assert decision.is_allowed is False
    assert decision.denial_code == "UNKNOWN_TOOL"


def test_production_write_privilege_enforced(default_engine: YamlPolicyEngine) -> None:
    # L2 without write privilege
    decision_no_write = default_engine.evaluate_policy(
        "L2",
        "update_ticket_status",
        context_attributes={"production_write": False},
    )
    assert decision_no_write.is_allowed is False
    assert decision_no_write.denial_code == "MISSING_PRODUCTION_WRITE_PRIVILEGE"

    # L2 with write privilege
    decision_with_write = default_engine.evaluate_policy(
        "L2",
        "update_ticket_status",
        context_attributes={"production_write": True},
    )
    assert decision_with_write.is_allowed is True


def test_attachment_access_kill_switch_and_privilege(
    default_engine: YamlPolicyEngine,
    attachment_enabled_engine: YamlPolicyEngine,
) -> None:
    # When kill-switch is disabled (default_engine)
    dec_disabled = default_engine.evaluate_policy(
        "L3",
        "get_attachment_content",
        context_attributes={"attachment_access": True},
    )
    assert dec_disabled.is_allowed is False
    assert dec_disabled.denial_code == "ATTACHMENT_ACCESS_DISABLED"

    # When kill-switch is enabled, but caller lacks privilege
    dec_no_flag = attachment_enabled_engine.evaluate_policy(
        "L3",
        "get_attachment_content",
        context_attributes={"attachment_access": False},
    )
    assert dec_no_flag.is_allowed is False
    assert dec_no_flag.denial_code == "MISSING_ATTACHMENT_ACCESS_PRIVILEGE"

    # When kill-switch is enabled AND caller has privilege
    dec_authorized = attachment_enabled_engine.evaluate_policy(
        "L3",
        "get_attachment_content",
        context_attributes={"attachment_access": True},
    )
    assert dec_authorized.is_allowed is True


@pytest.mark.asyncio
async def test_async_authorize_method(default_engine: YamlPolicyEngine) -> None:
    context = SecurityContext(
        principal=PrincipalIdentity(
            user_id="user_123",
            role="L2",
            scopes=("production_write",),
        ),
        token_id="tok_abc",
        is_authenticated=True,
    )
    decision = await default_engine.authorize(context, "update_ticket_status")
    assert decision.is_allowed is True

    decision_unauth = await default_engine.authorize(
        SecurityContext(
            principal=PrincipalIdentity(user_id="anon", role="L1"),
            token_id="tok_none",
            is_authenticated=False,
        ),
        "get_ticket",
    )
    assert decision_unauth.is_allowed is False
    assert decision_unauth.denial_code == "UNAUTHENTICATED"


def test_invalid_policy_file_fails_fast(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist.yaml"
    with pytest.raises(ConfigurationError):
        YamlPolicyEngine(policy_path=non_existent)

    corrupted_yaml = tmp_path / "corrupted.yaml"
    corrupted_yaml.write_text("invalid_yaml: [missing_close", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        YamlPolicyEngine(policy_path=corrupted_yaml)


def test_invalid_schema_roles_fail_fast(tmp_path: Path) -> None:
    bad_role_yaml = tmp_path / "bad_role.yaml"
    bad_role_yaml.write_text(
        """
version: "1.0"
roles_hierarchy:
  L1: 1
  L2: 2
  L3: 3
tools:
  bad_tool:
    minimum_role: "SUPERADMIN_ROOT"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        YamlPolicyEngine(policy_path=bad_role_yaml)


def test_invalid_classification_fails_fast(tmp_path: Path) -> None:
    bad_clf_yaml = tmp_path / "bad_clf.yaml"
    bad_clf_yaml.write_text(
        """
version: "1.0"
roles_hierarchy:
  L1: 1
  L2: 2
  L3: 3
tools:
  bad_tool:
    minimum_role: "L2"
    classification: "UNAPPROVED_CUSTOM_WRITE"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        YamlPolicyEngine(policy_path=bad_clf_yaml)


def test_invalid_data_level_fails_fast(tmp_path: Path) -> None:
    bad_lvl_yaml = tmp_path / "bad_lvl.yaml"
    bad_lvl_yaml.write_text(
        """
version: "1.0"
roles_hierarchy:
  L1: 1
  L2: 2
  L3: 3
tools:
  bad_tool:
    minimum_role: "L1"
    data_level: "TOP_SECRET_CLASSIFIED"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        YamlPolicyEngine(policy_path=bad_lvl_yaml)


def test_invalid_requires_flag_fails_fast(tmp_path: Path) -> None:
    bad_req_yaml = tmp_path / "bad_req.yaml"
    bad_req_yaml.write_text(
        """
version: "1.0"
roles_hierarchy:
  L1: 1
  L2: 2
  L3: 3
tools:
  bad_tool:
    minimum_role: "L2"
    requires:
      - arbitrary_unapproved_permission
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        YamlPolicyEngine(policy_path=bad_req_yaml)


def test_write_tool_missing_production_write_fails_fast(tmp_path: Path) -> None:
    bad_write_yaml = tmp_path / "bad_write.yaml"
    bad_write_yaml.write_text(
        """
version: "1.0"
roles_hierarchy:
  L1: 1
  L2: 2
  L3: 3
tools:
  safe_write_tool:
    minimum_role: "L2"
    classification: "SAFE_WRITE"
    # Missing required 'production_write' in requires
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        YamlPolicyEngine(policy_path=bad_write_yaml)


def test_attachment_content_tool_missing_privilege_fails_fast(tmp_path: Path) -> None:
    bad_att_yaml = tmp_path / "bad_att.yaml"
    bad_att_yaml.write_text(
        """
version: "1.0"
roles_hierarchy:
  L1: 1
  L2: 2
  L3: 3
tools:
  get_attachment_content:
    minimum_role: "L2"  # Invalid: must be L3
    requires:
      - attachment_access
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        YamlPolicyEngine(policy_path=bad_att_yaml)


def test_duplicate_tool_keys_fail_fast(tmp_path: Path) -> None:
    dup_yaml = tmp_path / "duplicate_tools.yaml"
    dup_yaml.write_text(
        """
version: "1.0"
roles_hierarchy:
  L1: 1
  L2: 2
  L3: 3
tools:
  get_ticket:
    minimum_role: "L1"
    classification: "READ_ONLY"
  get_ticket:
    minimum_role: "L3"
    classification: "READ_ONLY"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError) as exc_info:
        YamlPolicyEngine(policy_path=dup_yaml)
    assert "duplicate" in str(exc_info.value).lower()
