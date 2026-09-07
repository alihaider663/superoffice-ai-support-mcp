"""Declarative YAML RBAC policy engine and permission evaluation."""

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import Field, field_validator, model_validator
from yaml.constructor import ConstructorError  # type: ignore[import-untyped]

from platform_core.errors import ConfigurationError
from platform_core.models import PlatformBaseModel
from platform_security.interfaces import Authorizer, PolicyEngine
from platform_security.models import AuthorizationDecision, SecurityContext

ALLOWED_ROLES = {"L1", "L2", "L3"}
ALLOWED_CLASSIFICATIONS = {"READ_ONLY", "SAFE_WRITE", "SENSITIVE_WRITE", "DESTRUCTIVE"}
ALLOWED_DATA_LEVELS = {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "SECRET"}
ALLOWED_PRIVILEGES = {"production_write", "attachment_access"}


class UniqueKeyYamlLoader(yaml.SafeLoader):  # type: ignore[misc]
    """YAML loader enforcing key uniqueness across mappings (detects duplicate tools)."""


def _construct_mapping_with_dup_check(
    loader: yaml.Loader,
    node: yaml.Node,
    deep: bool = False,
) -> dict[Any, Any]:
    if not isinstance(node, yaml.MappingNode):
        raise ConstructorError(
            None,
            None,
            f"Expected mapping node, found {node.id}",
            node.start_mark,
        )
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"Duplicate key '{key}' found in YAML document.",
                key_node.start_mark,
            )
        value = loader.construct_object(value_node, deep=deep)
        mapping[key] = value
    return mapping


UniqueKeyYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_with_dup_check,
)


class ToolPermissionRule(PlatformBaseModel):
    """Declarative permission definition for a single MCP tool."""

    minimum_role: str = Field(..., description="Minimum role rank required (L1, L2, L3)")
    classification: str = Field(
        default="READ_ONLY",
        description="Side-effect classification tier",
    )
    data_level: str = Field(
        default="INTERNAL",
        description="Data classification level tier",
    )
    requires: tuple[str, ...] = Field(default=(), description="Orthogonal privileges required")
    description: str = Field(default="", description="Human-readable tool authorization scope")

    @field_validator("minimum_role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Enforce standard role tier vocabulary."""
        role = v.strip().upper()
        if role not in ALLOWED_ROLES:
            raise ValueError(f"Invalid minimum_role '{v}'. Allowed roles: {sorted(ALLOWED_ROLES)}")
        return role

    @field_validator("classification")
    @classmethod
    def validate_classification(cls, v: str) -> str:
        """Enforce standard side-effect classification vocabulary."""
        clf = v.strip().upper()
        if clf not in ALLOWED_CLASSIFICATIONS:
            raise ValueError(
                f"Invalid classification '{v}'. Allowed: {sorted(ALLOWED_CLASSIFICATIONS)}"
            )
        return clf

    @field_validator("data_level")
    @classmethod
    def validate_data_level(cls, v: str) -> str:
        """Enforce standard data classification level vocabulary."""
        lvl = v.strip().upper()
        if lvl not in ALLOWED_DATA_LEVELS:
            raise ValueError(f"Invalid data_level '{v}'. Allowed: {sorted(ALLOWED_DATA_LEVELS)}")
        return lvl

    @field_validator("requires")
    @classmethod
    def validate_requires(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        """Enforce standard orthogonal privilege flags."""
        for item in v:
            if item not in ALLOWED_PRIVILEGES:
                raise ValueError(
                    f"Invalid privilege '{item}' in requires. Allowed: {sorted(ALLOWED_PRIVILEGES)}"
                )
        return v

    @model_validator(mode="after")
    def validate_write_tool_privilege_invariant(self) -> "ToolPermissionRule":
        """Enforce ADR 010 invariant: write tools must require production_write."""
        if (
            self.classification in ("SAFE_WRITE", "SENSITIVE_WRITE", "DESTRUCTIVE")
            and "production_write" not in self.requires
        ):
            raise ValueError(
                f"Tool with classification '{self.classification}' must require the "
                "'production_write' privilege in 'requires'."
            )
        return self


class RbacPolicySchema(PlatformBaseModel):
    """Schema for validating tool_permissions.yaml files at startup."""

    version: str = Field(default="1.0", description="RBAC policy schema version")
    roles_hierarchy: dict[str, int] = Field(
        default_factory=lambda: {"L1": 1, "L2": 2, "L3": 3},
        description="Role hierarchy ranks",
    )
    tools: dict[str, ToolPermissionRule] = Field(
        default_factory=dict,
        description="Map of tool names to permission rules",
    )

    @field_validator("roles_hierarchy")
    @classmethod
    def validate_hierarchy(cls, v: dict[str, int]) -> dict[str, int]:
        """Validate that role hierarchy keys match approved roles."""
        for role in v:
            if role not in ALLOWED_ROLES:
                raise ValueError(
                    f"Invalid role '{role}' in hierarchy. Allowed: {sorted(ALLOWED_ROLES)}"
                )
        return v

    @model_validator(mode="after")
    def validate_attachment_content_gate_invariant(self) -> "RbacPolicySchema":
        """Enforce ADR 003/010 invariant: attachment content requires L3 & attachment_access."""
        for tool_name, rule in self.tools.items():
            if tool_name == "get_attachment_content":
                if rule.minimum_role != "L3":
                    raise ValueError(
                        f"Attachment content tool '{tool_name}' must require minimum role 'L3'."
                    )
                if "attachment_access" not in rule.requires:
                    raise ValueError(
                        f"Attachment content tool '{tool_name}' must require 'attachment_access'."
                    )
        return self


class YamlPolicyEngine(PolicyEngine, Authorizer):
    """Deterministic deny-by-default YAML policy engine enforcing cumulative RBAC."""

    def __init__(
        self,
        policy_path: str | Path | None = None,
        *,
        attachment_access_enabled: bool = False,
    ) -> None:
        self.attachment_access_enabled = attachment_access_enabled
        if policy_path is None:
            policy_path = Path(__file__).parent / "tool_permissions.yaml"

        self.policy_path = Path(policy_path)
        self.policy = self._load_and_validate_policy(self.policy_path)

    @classmethod
    def _load_and_validate_policy(cls, path: Path) -> RbacPolicySchema:
        """Load YAML file and validate structure with fail-fast semantics."""
        if not path.is_file():
            raise ConfigurationError(
                f"RBAC policy file not found at: {path}",
                details={"path": str(path)},
            )

        try:
            raw_text = path.read_text(encoding="utf-8")
            raw_yaml = yaml.load(raw_text, Loader=UniqueKeyYamlLoader)
            if not isinstance(raw_yaml, dict):
                raise ConfigurationError(
                    f"RBAC policy file at {path} does not contain a valid YAML dictionary.",
                    details={"path": str(path)},
                )
            return RbacPolicySchema.model_validate(raw_yaml)
        except Exception as e:
            if isinstance(e, ConfigurationError):
                raise
            raise ConfigurationError(
                f"Failed to parse and validate RBAC policy from {path}: {e}",
                details={"path": str(path), "raw_error": str(e)},
            ) from e

    def _check_privileges(
        self,
        tool_name: str,
        rule: ToolPermissionRule,
        attributes: dict[str, Any],
    ) -> AuthorizationDecision | None:
        """Evaluate orthogonal privilege flags (production_write, attachment_access)."""
        if "production_write" in rule.requires and not bool(
            attributes.get("production_write", False)
        ):
            return AuthorizationDecision(
                is_allowed=False,
                reason=f"Tool '{tool_name}' requires the explicit 'production_write' privilege.",
                denial_code="MISSING_PRODUCTION_WRITE_PRIVILEGE",
            )

        if "attachment_access" in rule.requires:
            if not self.attachment_access_enabled:
                return AuthorizationDecision(
                    is_allowed=False,
                    reason="Attachment content access is globally disabled by policy.",
                    denial_code="ATTACHMENT_ACCESS_DISABLED",
                )
            if not bool(attributes.get("attachment_access", False)):
                return AuthorizationDecision(
                    is_allowed=False,
                    reason=f"Tool '{tool_name}' requires explicit 'attachment_access' privilege.",
                    denial_code="MISSING_ATTACHMENT_ACCESS_PRIVILEGE",
                )

        return None

    def evaluate_policy(
        self,
        principal_role: str,
        tool_name: str,
        environment: str = "production",  # noqa: ARG002
        context_attributes: dict[str, Any] | None = None,
    ) -> AuthorizationDecision:
        """Synchronously evaluate security policy rules for a given principal and tool."""
        attributes = context_attributes or {}

        # 1. Deny-by-default: unknown tools are immediately rejected
        rule = self.policy.tools.get(tool_name)
        if rule is None:
            return AuthorizationDecision(
                is_allowed=False,
                reason=f"Tool '{tool_name}' is not registered in the RBAC policy.",
                denial_code="UNKNOWN_TOOL",
            )

        # 2. Evaluate cumulative role hierarchy
        caller_rank = self.policy.roles_hierarchy.get(principal_role, 0)
        required_rank = self.policy.roles_hierarchy.get(rule.minimum_role, 99)

        if caller_rank < required_rank:
            return AuthorizationDecision(
                is_allowed=False,
                reason=(
                    f"Principal role '{principal_role}' is insufficient for tool '{tool_name}'. "
                    f"Minimum required role is '{rule.minimum_role}'."
                ),
                denial_code="INSUFFICIENT_ROLE",
            )

        # 3. Evaluate orthogonal privilege requirements
        privilege_denial = self._check_privileges(tool_name, rule, attributes)
        if privilege_denial is not None:
            return privilege_denial

        return AuthorizationDecision(
            is_allowed=True,
            reason=f"Authorized for tool '{tool_name}' with role '{principal_role}'.",
        )

    async def authorize(
        self,
        context: SecurityContext,
        action: str,
        resource: str | None = None,  # noqa: ARG002
    ) -> AuthorizationDecision:
        """Asynchronously evaluate whether the security context is authorized for the action."""
        if not context.is_authenticated:
            return AuthorizationDecision(
                is_allowed=False,
                reason="Unauthenticated principal.",
                denial_code="UNAUTHENTICATED",
            )

        principal_role = context.principal.role
        attributes = dict(context.attributes)
        if "production_write" not in attributes:
            attributes["production_write"] = "production_write" in context.principal.scopes
        if "attachment_access" not in attributes:
            attributes["attachment_access"] = "attachment_access" in context.principal.scopes

        return self.evaluate_policy(
            principal_role=principal_role,
            tool_name=action,
            context_attributes=attributes,
        )
