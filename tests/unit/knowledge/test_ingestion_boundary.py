"""Comprehensive unit test suite for Knowledge Ingestion Boundary (Gate 7D.5B).

Verifies:
1. Corpus eligibility policy (D05 customer attachment, D08 live CRM/customer export rejection).
2. Secret detection and fail-closed rejection.
3. Incidental PII redaction, documentation exemptions, and mass-PII fail-closed limits.
4. Document and structured artifact parsers (Markdown, PlainText, Runbook, Known Issue).
5. Canonical text normalization invariants.
6. Admission coordinator service (admit and admit_or_raise).
"""

import json
import logging
from datetime import datetime
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from kb_mcp.contracts.constants import (
    MAX_CANONICAL_TEXT_BYTES,
    MAX_SOURCE_FILE_BYTES,
)
from kb_mcp.contracts.errors import (
    KnowledgeContentRejectedError,
    KnowledgeSizeLimitExceededError,
    KnowledgeSourceFormatError,
)
from kb_mcp.contracts.ingestion import (
    AdmissionDecision,
    AdmissionReasonCode,
    AdmissionSourceInputDTO,
    CorpusCategory,
    IngestionSourceKind,
    ProhibitedSourceClassification,
    SanitizedDocumentPayloadDTO,
    SanitizedKnownIssuePayloadDTO,
    SanitizedRunbookPayloadDTO,
)
from kb_mcp.ingestion.eligibility import CorpusEligibilityPolicy
from kb_mcp.ingestion.normalization import normalize_text
from kb_mcp.ingestion.parsers import (
    KnownIssueJsonParser,
    MarkdownParser,
    PlainTextParser,
    RunbookJsonParser,
)
from kb_mcp.ingestion.sanitizer import KnowledgeSanitizer, is_safe_placeholder
from kb_mcp.ingestion.service import KnowledgeAdmissionService

# ============================================================================
# 1. Corpus Eligibility Tests (D05 / D08 / Bounds)
# ============================================================================


class TestCorpusEligibility:
    """Test CorpusEligibilityPolicy for security boundary classification and format support."""

    @pytest.fixture
    def policy(self) -> CorpusEligibilityPolicy:
        return CorpusEligibilityPolicy()

    def test_rejects_customer_attachment_classification(
        self, policy: CorpusEligibilityPolicy
    ) -> None:
        """D05: Sources classified as customer attachments must be rejected."""
        source = AdmissionSourceInputDTO(
            source_name="ticket_attachment.pdf",
            source_kind=IngestionSourceKind.TEXT_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"Some customer attachment data here...",
            classification="customer_attachment",
        )
        res = policy.evaluate(source)
        assert not res.is_eligible
        assert res.reason_code == AdmissionReasonCode.CUSTOMER_ATTACHMENT_DETECTED

    @pytest.mark.parametrize(
        "prohibited",
        [
            ProhibitedSourceClassification.LIVE_CRM.value,
            ProhibitedSourceClassification.CUSTOMER_EXPORT.value,
            ProhibitedSourceClassification.RAW_TICKET_DUMP.value,
            ProhibitedSourceClassification.CUSTOMER_INTERACTION_TRANSCRIPT.value,
        ],
    )
    def test_rejects_d08_prohibited_classifications(
        self,
        policy: CorpusEligibilityPolicy,
        prohibited: str,
    ) -> None:
        """D08: Live CRM, exports, raw ticket dumps, transcripts must be rejected."""
        source = AdmissionSourceInputDTO(
            source_name="export.txt",
            source_kind=IngestionSourceKind.TEXT_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"Sensitive export content...",
            classification=prohibited,
        )
        res = policy.evaluate(source)
        assert not res.is_eligible
        assert res.reason_code == AdmissionReasonCode.PROHIBITED_SOURCE_CLASSIFICATION

    @pytest.mark.parametrize(
        "empty_name",
        ["", "   "],
    )
    def test_rejects_empty_source_name_at_dto(self, empty_name: str) -> None:
        """Empty or whitespace-only source names fail DTO validation."""
        with pytest.raises(ValidationError):
            AdmissionSourceInputDTO(
                source_name=empty_name,
                source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
                corpus_category=CorpusCategory.DOCUMENTATION,
                raw_bytes=b"# Header\nContent.",
            )

    @pytest.mark.parametrize(
        "invalid_name",
        [
            "../secret.md",
            r"..\secret.md",
            r"C:\logs\app.log",
            "/etc/passwd",
            r"\\server\share\doc.md",
            "folder/sub/file.md",
        ],
    )
    def test_rejects_unsafe_source_names(
        self,
        policy: CorpusEligibilityPolicy,
        invalid_name: str,
    ) -> None:
        """Source names must be safe basenames without slashes, drive letters, or UNC paths."""
        source = AdmissionSourceInputDTO(
            source_name=invalid_name,
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"# Valid Document Header\nSome content.",
        )
        res = policy.evaluate(source)
        assert not res.is_eligible
        assert res.reason_code == AdmissionReasonCode.INVALID_SOURCE_NAME

    def test_rejects_oversized_raw_bytes(self, policy: CorpusEligibilityPolicy) -> None:
        """Sources exceeding MAX_SOURCE_FILE_BYTES (2 MiB) must be rejected."""
        oversized = b"A" * (MAX_SOURCE_FILE_BYTES + 1)
        source = AdmissionSourceInputDTO(
            source_name="large.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=oversized,
        )
        res = policy.evaluate(source)
        assert not res.is_eligible
        assert res.reason_code == AdmissionReasonCode.SIZE_LIMIT_EXCEEDED

    def test_rejects_undersized_raw_bytes(self, policy: CorpusEligibilityPolicy) -> None:
        """Sources below MIN_SOURCE_TEXT_BYTES (10 bytes) must be rejected."""
        source = AdmissionSourceInputDTO(
            source_name="tiny.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"abc",
        )
        res = policy.evaluate(source)
        assert not res.is_eligible
        assert res.reason_code == AdmissionReasonCode.SOURCE_TOO_SHORT

    def test_rejects_category_mismatch(self, policy: CorpusEligibilityPolicy) -> None:
        """RUNBOOK_JSON must be category 'runbook';
        KNOWN_ISSUE_JSON must be category 'known_issue'.
        """
        mismatched = AdmissionSourceInputDTO(
            source_name="rb.json",
            source_kind=IngestionSourceKind.RUNBOOK_JSON,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b'{"runbook_id": "rb-1"}',
        )
        res = policy.evaluate(mismatched)
        assert not res.is_eligible
        assert res.reason_code == AdmissionReasonCode.CATEGORY_MISMATCH

    def test_approves_valid_eligibility(self, policy: CorpusEligibilityPolicy) -> None:
        """Valid source metadata passes eligibility evaluation."""
        valid = AdmissionSourceInputDTO(
            source_name="arch_guide.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"# Architecture Guide\nSuperOffice architecture overview.",
        )
        res = policy.evaluate(valid)
        assert res.is_eligible
        assert res.reason_code is None


# ============================================================================
# 2. Secret Detection & Sanitization Tests
# ============================================================================


class TestKnowledgeSanitizerSecrets:
    """Test KnowledgeSanitizer secret detection, unmasked credentials, and placeholder safety."""

    @pytest.fixture
    def sanitizer(self) -> KnowledgeSanitizer:
        return KnowledgeSanitizer()

    def test_detects_pem_private_keys(self, sanitizer: KnowledgeSanitizer) -> None:
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"
        assert sanitizer.contains_secret(pem)
        _, _, err, _ = sanitizer.sanitize_free_text(pem)
        assert err == AdmissionReasonCode.SECRET_DETECTED

    def test_detects_jwt_tokens(self, sanitizer: KnowledgeSanitizer) -> None:
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        assert sanitizer.contains_secret(jwt)
        _, _, err, _ = sanitizer.sanitize_free_text(f"Token: {jwt}")
        assert err == AdmissionReasonCode.SECRET_DETECTED

    def test_detects_real_bearer_tokens(self, sanitizer: KnowledgeSanitizer) -> None:
        bearer = "Bearer 9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d"
        assert sanitizer.contains_secret(bearer)
        _, _, err, _ = sanitizer.sanitize_free_text(f"Authorization: {bearer}")
        assert err == AdmissionReasonCode.SECRET_DETECTED

    def test_allows_placeholder_bearer_tokens(self, sanitizer: KnowledgeSanitizer) -> None:
        placeholder = "Authorization: Bearer <API_TOKEN>"
        assert not sanitizer.contains_secret(placeholder)
        _, _, err, _ = sanitizer.sanitize_free_text(placeholder)
        assert err is None

    def test_detects_credential_uris(self, sanitizer: KnowledgeSanitizer) -> None:
        uri = "postgresql://so_admin:SuperSecretPass123!@db.internal:5432/superoffice"
        assert sanitizer.contains_secret(uri)
        _, _, err, _ = sanitizer.sanitize_free_text(f"Connecting to {uri}")
        assert err == AdmissionReasonCode.SECRET_DETECTED

    def test_allows_placeholder_credential_uris(self, sanitizer: KnowledgeSanitizer) -> None:
        safe_uri = "postgresql://admin:<PASSWORD>@localhost:5432/db"
        assert not sanitizer.contains_secret(safe_uri)

    def test_detects_connection_string_passwords(self, sanitizer: KnowledgeSanitizer) -> None:
        conn = "Server=tcp:sql.local;Database=crm7;Uid=crm;Pwd=LiveProdPass987#;"
        assert sanitizer.contains_secret(conn)
        _, _, err, _ = sanitizer.sanitize_free_text(conn)
        assert err == AdmissionReasonCode.SECRET_DETECTED

    def test_detects_known_api_key_prefixes(self, sanitizer: KnowledgeSanitizer) -> None:
        sk = "sk" + "_live_" + "1234567890abcdef1234567890abcdef"
        assert sanitizer.contains_secret(sk)
        ghp = "ghp_1234567890abcdef1234567890abcdef"
        assert sanitizer.contains_secret(ghp)

    def test_allows_documentation_placeholders(self, sanitizer: KnowledgeSanitizer) -> None:
        doc = (
            "Set YOUR_API_KEY to your registered key.\n"
            "password: <PASSWORD>\n"
            "token: ${AUTH_TOKEN}\n"
            "apikey: EXAMPLE_TOKEN"
        )
        assert not sanitizer.contains_secret(doc)
        _, _, err, _ = sanitizer.sanitize_free_text(doc)
        assert err is None

    def test_is_safe_placeholder_utility(self) -> None:
        assert is_safe_placeholder("<TOKEN>")
        assert is_safe_placeholder("${MY_VAR}")
        assert is_safe_placeholder("{{SECRET}}")
        assert is_safe_placeholder("YOUR_PASSWORD")
        assert is_safe_placeholder("example_token")
        assert not is_safe_placeholder("SuperSecretPass123")


# ============================================================================
# 3. PII Detection, Redaction & Mass-PII Bounds Tests
# ============================================================================


class TestKnowledgeSanitizerPII:
    """Test KnowledgeSanitizer PII redaction, documentation domain exemptions, and mass limits."""

    @pytest.fixture
    def sanitizer(self) -> KnowledgeSanitizer:
        return KnowledgeSanitizer()

    def test_redacts_email_addresses(self, sanitizer: KnowledgeSanitizer) -> None:
        text = "Contact support engineer john.doe@superoffice.no for escalation."
        sanitized, count, err, _ = sanitizer.sanitize_free_text(text)
        assert err is None
        assert count == 1
        assert "<EMAIL_REDACTED>" in sanitized
        assert "john.doe@superoffice.no" not in sanitized

    def test_preserves_exempt_documentation_email_domains(
        self, sanitizer: KnowledgeSanitizer
    ) -> None:
        text = "Use admin@example.com or support@example.org or info@example.net in config."
        sanitized, count, err, _ = sanitizer.sanitize_free_text(text)
        assert err is None
        assert count == 0
        assert "admin@example.com" in sanitized
        assert "support@example.org" in sanitized
        assert "info@example.net" in sanitized

    def test_redacts_phone_numbers(self, sanitizer: KnowledgeSanitizer) -> None:
        text = "Emergency hotline is +47 22 33 44 55 or (020) 7946 0912."
        sanitized, count, err, _ = sanitizer.sanitize_free_text(text)
        assert err is None
        assert count >= 1
        assert "<PHONE_REDACTED>" in sanitized

    def test_preserves_dates_and_dotted_versions(self, sanitizer: KnowledgeSanitizer) -> None:
        text = "Release date 2026-09-08 for SuperOffice version 10.2.1.0."
        sanitized, count, err, _ = sanitizer.sanitize_free_text(text)
        assert err is None
        assert count == 0
        assert "2026-09-08" in sanitized
        assert "10.2.1.0" in sanitized

    def test_redacts_national_ids_and_ssn(self, sanitizer: KnowledgeSanitizer) -> None:
        text = "Personal ID: 123456-12345 or SSN: 123-45-6789."
        sanitized, count, err, _ = sanitizer.sanitize_free_text(text)
        assert err is None
        assert count >= 2
        assert "<ID_REDACTED>" in sanitized

    def test_mass_pii_fails_closed(self, sanitizer: KnowledgeSanitizer) -> None:
        """More than 10 PII occurrences causes fail-closed rejection."""
        emails = " ".join(f"user{i}@customer{i}.com" for i in range(12))
        _, count, err, msg = sanitizer.sanitize_free_text(emails)
        assert count > 10
        assert err == AdmissionReasonCode.PII_DETECTED
        assert "Mass PII detected" in msg

    def test_check_identity_field_rejects_pii_and_secrets(
        self, sanitizer: KnowledgeSanitizer
    ) -> None:
        """Identity fields cannot be redacted; any secret or PII presence rejects."""
        assert (
            sanitizer.check_identity_field("user@company.com", "runbook_id")
            == AdmissionReasonCode.PII_DETECTED
        )
        assert (
            sanitizer.check_identity_field("sk" + "_live_" + "1234567890abcdef1234567890", "product")
            == AdmissionReasonCode.SECRET_DETECTED
        )
        assert sanitizer.check_identity_field("rb-crm-001", "runbook_id") is None


# ============================================================================
# 4. Text Normalization Invariant Tests
# ============================================================================


class TestTextNormalization:
    """Test text normalization rules.

    Covers CRLF/CR conversion, trailing whitespace, blank line boundaries.
    """

    def test_normalizes_line_endings_and_whitespace(self) -> None:
        raw = "Line 1   \r\n\r\n\r\n\r\nLine 2 \rLine 3  "
        normalized = normalize_text(raw)
        assert "\r" not in normalized
        lines = normalized.split("\n")
        assert lines[0] == "Line 1"
        assert lines[1] == ""
        assert lines[2] == ""
        assert lines[3] == ""
        assert lines[4] == "Line 2"
        assert lines[5] == "Line 3"


# ============================================================================
# 5. Format Parser Tests
# ============================================================================


class TestFormatParsers:
    """Test Markdown, PlainText, Runbook, and Known Issue parsers."""

    def test_markdown_parser_strict_utf8(self) -> None:
        parser = MarkdownParser()
        with pytest.raises(KnowledgeSourceFormatError) as exc_info:
            parser.parse(b"\xff\xfe\x00\x00Invalid")
        assert "not valid strict UTF-8" in str(exc_info.value)

    def test_markdown_parser_empty_content_rejected(self) -> None:
        parser = MarkdownParser()
        with pytest.raises(KnowledgeSourceFormatError) as exc_info:
            parser.parse(b"   \n\n\t  ")
        assert "empty or whitespace-only" in str(exc_info.value)

    def test_plain_text_parser_empty_content_rejected(self) -> None:
        parser = PlainTextParser()
        with pytest.raises(KnowledgeSourceFormatError) as exc_info:
            parser.parse(b"   \n\n\t  ")
        assert "empty or whitespace-only" in str(exc_info.value)

    def test_runbook_parser_valid(self) -> None:
        parser = RunbookJsonParser()
        raw = json.dumps(
            {
                "runbook_id": "rb-crm-restart",
                "title": "SuperOffice Service Restart",
                "problem_description": "Service hangs during high peak usage.",
                "diagnostic_steps": ["Check event log", "Verify CPU usage"],
                "remediation_steps": ["Restart SO_CS service", "Verify ping"],
                "source_reference": "runbook://ops/so-cs-restart",
                "product": "SuperOffice Service",
                "verified_version": "10.2.1",
            }
        ).encode("utf-8")
        model = parser.parse(raw)
        assert model.runbook_id == "rb-crm-restart"
        assert len(model.diagnostic_steps) == 2

    def test_runbook_parser_rejects_extra_fields(self) -> None:
        parser = RunbookJsonParser()
        raw = json.dumps(
            {
                "runbook_id": "rb-1",
                "title": "Title",
                "problem_description": "Desc",
                "diagnostic_steps": ["Step 1"],
                "remediation_steps": ["Step 2"],
                "source_reference": "runbook://ops/1",
                "unauthorized_field": "injected",
            }
        ).encode("utf-8")
        with pytest.raises(KnowledgeSourceFormatError):
            parser.parse(raw)

    def test_runbook_parser_rejects_unsafe_source_reference(self) -> None:
        parser = RunbookJsonParser()
        raw = json.dumps(
            {
                "runbook_id": "rb-1",
                "title": "Title",
                "problem_description": "Desc",
                "diagnostic_steps": ["Step 1"],
                "remediation_steps": ["Step 2"],
                "source_reference": "runbook://user:pass@internal/1",
            }
        ).encode("utf-8")
        with pytest.raises(KnowledgeSourceFormatError):
            parser.parse(raw)

    def test_known_issue_parser_valid(self) -> None:
        parser = KnownIssueJsonParser()
        raw = json.dumps(
            {
                "issue_id": "ki-crm-001",
                "title": "IIS Pool Recycling Under Load",
                "symptom_summary": "Clients receive HTTP 503 errors.",
                "root_cause_summary": "Worker pool memory limit reached.",
                "workaround": "Increase memory threshold in IIS Manager.",
                "permanent_fix_reference": "known-issue://patches/patch-10-2",
                "affected_products": ["SuperOffice Web Client"],
                "affected_versions": ["10.1.0", "10.2.0"],
                "category": "performance",
                "source_reference": "known-issue://kb/ki-crm-001",
            }
        ).encode("utf-8")
        model = parser.parse(raw)
        assert model.issue_id == "ki-crm-001"
        assert model.category == "performance"


# ============================================================================
# 6. Admission Service End-to-End Tests
# ============================================================================


class TestAdmissionService:
    """Test KnowledgeAdmissionService coordinate pipeline."""

    @pytest.fixture
    def service(self) -> KnowledgeAdmissionService:
        return KnowledgeAdmissionService()

    def test_admit_markdown_document_success(self, service: KnowledgeAdmissionService) -> None:
        source = AdmissionSourceInputDTO(
            source_name="guide.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"# Architecture Guide\nOverview of SuperOffice database replication.",
        )
        res = service.admit(source)
        assert res.decision == AdmissionDecision.APPROVED
        assert res.reason_code is None
        assert isinstance(res.sanitized_payload, SanitizedDocumentPayloadDTO)
        assert "Architecture Guide" in res.sanitized_payload.canonical_text

    def test_admit_markdown_document_with_redacted_pii(
        self, service: KnowledgeAdmissionService
    ) -> None:
        source = AdmissionSourceInputDTO(
            source_name="guide.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"# Guide\nCreated by engineer john.smith@customer.no.",
        )
        res = service.admit(source)
        assert res.decision == AdmissionDecision.APPROVED
        assert res.pii_redaction_count == 1
        assert isinstance(res.sanitized_payload, SanitizedDocumentPayloadDTO)
        assert "<EMAIL_REDACTED>" in res.sanitized_payload.canonical_text

    def test_admit_markdown_document_rejected_for_secrets(
        self, service: KnowledgeAdmissionService
    ) -> None:
        source = AdmissionSourceInputDTO(
            source_name="guide.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"# Guide\nPassword: LiveProductionPassword123#\nConnect now.",
        )
        res = service.admit(source)
        assert res.decision == AdmissionDecision.REJECTED
        assert res.reason_code == AdmissionReasonCode.SECRET_DETECTED
        assert res.sanitized_payload is None

    def test_admit_document_rejected_for_canonical_size_exceeded(
        self, service: KnowledgeAdmissionService
    ) -> None:
        oversized_text = "A" * (MAX_CANONICAL_TEXT_BYTES + 10)
        source = AdmissionSourceInputDTO(
            source_name="large_canonical.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=oversized_text.encode("utf-8"),
        )
        res = service.admit(source)
        assert res.decision == AdmissionDecision.REJECTED
        assert res.reason_code == AdmissionReasonCode.SIZE_LIMIT_EXCEEDED

    def test_admit_runbook_success(self, service: KnowledgeAdmissionService) -> None:
        raw_rb = json.dumps(
            {
                "runbook_id": "rb-iis-01",
                "title": "IIS AppPool Crash",
                "problem_description": "AppPool crashes unexpectedly.",
                "diagnostic_steps": ["Check event viewer", "Verify memory usage"],
                "remediation_steps": ["Recycle pool", "Verify health endpoint"],
                "source_reference": "runbook://ops/iis-01",
                "product": "SuperOffice Core",
                "verified_version": "10.2",
            }
        ).encode("utf-8")
        source = AdmissionSourceInputDTO(
            source_name="rb_iis.json",
            source_kind=IngestionSourceKind.RUNBOOK_JSON,
            corpus_category=CorpusCategory.RUNBOOK,
            raw_bytes=raw_rb,
        )
        res = service.admit(source)
        assert res.decision == AdmissionDecision.APPROVED
        assert isinstance(res.sanitized_payload, SanitizedRunbookPayloadDTO)
        assert res.sanitized_payload.runbook_id == "rb-iis-01"
        assert "Title: IIS AppPool Crash" in res.sanitized_payload.canonical_text

    def test_admit_runbook_rejected_for_secret_in_identity(
        self, service: KnowledgeAdmissionService
    ) -> None:
        raw_rb = json.dumps(
            {
                "runbook_id": "rb-iis-01",
                "title": "Clean Title",
                "problem_description": "Clean problem description.",
                "diagnostic_steps": ["Step 1"],
                "remediation_steps": ["Step 2"],
                "source_reference": "runbook://ops/iis-01",
                "product": "sk" + "_live_" + "1234567890abcdef1234567890abcdef",
            }
        ).encode("utf-8")
        source = AdmissionSourceInputDTO(
            source_name="rb_bad.json",
            source_kind=IngestionSourceKind.RUNBOOK_JSON,
            corpus_category=CorpusCategory.RUNBOOK,
            raw_bytes=raw_rb,
        )
        res = service.admit(source)
        assert res.decision == AdmissionDecision.REJECTED
        assert res.reason_code == AdmissionReasonCode.SECRET_DETECTED

    def test_admit_known_issue_success(self, service: KnowledgeAdmissionService) -> None:
        raw_ki = json.dumps(
            {
                "issue_id": "ki-auth-01",
                "title": "OAuth Expiration Bug",
                "symptom_summary": "Session expires after 5 minutes instead of 60.",
                "root_cause_summary": "Clock skew on token provider.",
                "workaround": "Sync NTP time on server.",
                "permanent_fix_reference": "known-issue://patches/patch-10-2-1",
                "affected_products": ["SuperOffice Web"],
                "affected_versions": ["10.2.0"],
                "category": "authentication",
                "source_reference": "known-issue://kb/auth-01",
            }
        ).encode("utf-8")
        source = AdmissionSourceInputDTO(
            source_name="ki_auth.json",
            source_kind=IngestionSourceKind.KNOWN_ISSUE_JSON,
            corpus_category=CorpusCategory.KNOWN_ISSUE,
            raw_bytes=raw_ki,
        )
        res = service.admit(source)
        assert res.decision == AdmissionDecision.APPROVED
        assert isinstance(res.sanitized_payload, SanitizedKnownIssuePayloadDTO)
        assert res.sanitized_payload.issue_id == "ki-auth-01"
        assert "Category: authentication" in res.sanitized_payload.canonical_text

    def test_admit_or_raise_raises_on_rejection(self, service: KnowledgeAdmissionService) -> None:
        source = AdmissionSourceInputDTO(
            source_name="secret.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...",
        )
        with pytest.raises(KnowledgeContentRejectedError) as exc_info:
            service.admit_or_raise(source)
        assert exc_info.value.reason == "SECRET_DETECTED"

    def test_admit_or_raise_raises_on_size_limit(self, service: KnowledgeAdmissionService) -> None:
        source = AdmissionSourceInputDTO(
            source_name="tiny.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"abc",
        )
        with pytest.raises(KnowledgeSizeLimitExceededError):
            service.admit_or_raise(source)

    def test_admit_or_raise_returns_on_approval(self, service: KnowledgeAdmissionService) -> None:
        source = AdmissionSourceInputDTO(
            source_name="clean.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"# Valid Document\nClean content.",
        )
        res = service.admit_or_raise(source)
        assert res.decision == AdmissionDecision.APPROVED


# ============================================================================
# Additional Security Coverage Tests (Gate 7D.5B-R1)
# ============================================================================


class TestD05D08PreParserOrdering:
    """Prove D05 and D08 rejection occurs strictly BEFORE parser/sanitizer invocation."""

    @pytest.fixture
    def service(self) -> KnowledgeAdmissionService:
        return KnowledgeAdmissionService()

    def test_customer_attachment_rejected_before_parser_invoked(
        self, service: KnowledgeAdmissionService
    ) -> None:
        """Parser must NEVER be called when source is classified as customer attachment."""
        with patch.object(
            service._markdown_parser, "parse", wraps=service._markdown_parser.parse
        ) as mock_parse:
            source = AdmissionSourceInputDTO(
                source_name="attachment.md",
                source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
                corpus_category=CorpusCategory.DOCUMENTATION,
                raw_bytes=b"# Customer Attachment Content Here...",
                classification="customer_attachment",
            )
            res = service.admit(source)
            assert res.decision == AdmissionDecision.REJECTED
            assert res.reason_code == AdmissionReasonCode.CUSTOMER_ATTACHMENT_DETECTED
            assert mock_parse.call_count == 0

    @pytest.mark.parametrize(
        "prohibited",
        [
            ProhibitedSourceClassification.LIVE_CRM.value,
            ProhibitedSourceClassification.CUSTOMER_EXPORT.value,
            ProhibitedSourceClassification.RAW_TICKET_DUMP.value,
            ProhibitedSourceClassification.CUSTOMER_INTERACTION_TRANSCRIPT.value,
        ],
    )
    def test_prohibited_classifications_rejected_before_parser_invoked(
        self,
        service: KnowledgeAdmissionService,
        prohibited: str,
    ) -> None:
        """Parser must NEVER be called when source has a prohibited classification."""
        with patch.object(
            service._markdown_parser, "parse", wraps=service._markdown_parser.parse
        ) as mock_parse:
            source = AdmissionSourceInputDTO(
                source_name="export.md",
                source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
                corpus_category=CorpusCategory.DOCUMENTATION,
                raw_bytes=b"# Prohibited classification content here...",
                classification=prohibited,
            )
            res = service.admit(source)
            assert res.decision == AdmissionDecision.REJECTED
            assert res.reason_code == AdmissionReasonCode.PROHIBITED_SOURCE_CLASSIFICATION
            assert mock_parse.call_count == 0


class TestSecretAssignmentCoverageAndSeparators:
    """Section 4 & 5: Secret detection across required keys, separators, and placeholders."""

    @pytest.fixture
    def sanitizer(self) -> KnowledgeSanitizer:
        return KnowledgeSanitizer()

    @pytest.mark.parametrize(
        "secret_text",
        [
            "password=ActualSyntheticSecret123!",
            "passwd=ActualSyntheticSecret123!",
            "pwd: SyntheticPass123!",
            "api_key=sk_test_synthetic_123456789",
            "apikey=syntheticSecretValue123456",
            "client_secret=syntheticSecretValue123456",
            "access_token=syntheticTokenValue123456",
            "secret=syntheticSecretValue123456",
            "password = ActualSyntheticSecret123!",
            "pwd : SyntheticPass123!",
            "client_secret : syntheticSecretValue123456",
        ],
    )
    def test_detects_secret_assignments_with_separators(
        self, sanitizer: KnowledgeSanitizer, secret_text: str
    ) -> None:
        """Contextual secret detection across all required key names with = and :."""
        assert sanitizer.contains_secret(secret_text)
        _, _, err, _ = sanitizer.sanitize_free_text(f"Config: {secret_text}")
        assert err == AdmissionReasonCode.SECRET_DETECTED

    @pytest.mark.parametrize(
        "secret_text",
        [
            "password ActualSyntheticSecret123!",
            "secret syntheticSecretValue123456",
            "api_key sk_test_synthetic_123456789",
            "client_secret syntheticSecretValue123456",
            "access_token syntheticTokenValue123456",
            "pwd SyntheticPass123!",
        ],
    )
    def test_detects_secret_assignments_with_whitespace_separator(
        self, sanitizer: KnowledgeSanitizer, secret_text: str
    ) -> None:
        """Contextual secret detection where whitespace is used with substantive secret tokens."""
        assert sanitizer.contains_secret(secret_text)
        _, _, err, _ = sanitizer.sanitize_free_text(f"Config setting: {secret_text}")
        assert err == AdmissionReasonCode.SECRET_DETECTED

    @pytest.mark.parametrize(
        "placeholder_text",
        [
            "password=<PASSWORD>",
            "password=<PASSWORD_HERE>",
            "api_key=YOUR_API_KEY",
            "api_key=${API_KEY}",
            "password=${PASSWORD}",
            "access_token=${TOKEN}",
            "client_secret=REPLACE_ME",
            "api_key=example-token",
            "password: <PASSWORD>",
            "api_key: ${API_KEY}",
            "secret: REPLACE_ME",
        ],
    )
    def test_allows_safe_documentation_placeholders(
        self, sanitizer: KnowledgeSanitizer, placeholder_text: str
    ) -> None:
        """Documentation placeholders must be exempted from secret detection."""
        assert not sanitizer.contains_secret(placeholder_text)
        sanitized, _, err, _ = sanitizer.sanitize_free_text(f"Example config: {placeholder_text}")
        assert err is None
        assert placeholder_text in sanitized

    def test_placeholder_exemption_contrast(self, sanitizer: KnowledgeSanitizer) -> None:
        safe = "password=<PASSWORD>"
        substantive = "password=SyntheticRealLookingSecret123!"
        assert not sanitizer.contains_secret(safe)
        assert sanitizer.contains_secret(substantive)

    @pytest.mark.parametrize(
        "prose",
        [
            "Please review the password policy before changing settings.",
            "The admin initiated a password reset for the account.",
            "Password expiration is configured to 90 days.",
            "This is a secret recipe for SuperOffice maintenance.",
        ],
    )
    def test_preserves_english_prose_with_secret_keywords(
        self, sanitizer: KnowledgeSanitizer, prose: str
    ) -> None:
        """Standard prose with password keywords must not trigger secret detection."""
        assert not sanitizer.contains_secret(prose)
        sanitized, _, err, _ = sanitizer.sanitize_free_text(prose)
        assert err is None
        assert prose in sanitized


class TestLabelledPersonalIdentifiers:
    """Section 10 & 11: Labelled personal IDs, technical IDs, and mass PII limits."""

    @pytest.fixture
    def sanitizer(self) -> KnowledgeSanitizer:
        return KnowledgeSanitizer()

    @pytest.mark.parametrize(
        "labelled_id_text,expected_label",
        [
            ("personal id: 12345", "personal id: <ID_REDACTED>"),
            ("personal_id = 98765-ABC", "personal_id = <ID_REDACTED>"),
            ("national id: NO-123456", "national id: <ID_REDACTED>"),
            ("identity number: 55443322", "identity number: <ID_REDACTED>"),
            ("customer id number = CUST-887766", "customer id number = <ID_REDACTED>"),
            ("passport no: A1234567", "passport no: <ID_REDACTED>"),
        ],
    )
    def test_redacts_strongly_labelled_personal_ids(
        self, sanitizer: KnowledgeSanitizer, labelled_id_text: str, expected_label: str
    ) -> None:
        """Contextual strongly-labelled personal IDs must be redacted to <ID_REDACTED>."""
        text = f"Customer record details: {labelled_id_text} verified."
        sanitized, count, err, _ = sanitizer.sanitize_free_text(text)
        assert err is None
        assert count == 1
        assert expected_label in sanitized

    def test_preserves_technical_identifiers(self, sanitizer: KnowledgeSanitizer) -> None:
        """Technical IDs (ticket_id, session_id, build_id) must NOT be treated as personal PII."""
        tech_text = "Incident ticket_id: 12345 with session_id: abc-xyz-987 on build_id: 42."
        assert not sanitizer.contains_pii(tech_text)
        sanitized, count, err, _ = sanitizer.sanitize_free_text(tech_text)
        assert err is None
        assert count == 0
        assert "ticket_id: 12345" in sanitized
        assert "session_id: abc-xyz-987" in sanitized
        assert "build_id: 42" in sanitized

    def test_mass_pii_allows_up_to_10_occurrences(self, sanitizer: KnowledgeSanitizer) -> None:
        """Exactly 10 PII occurrences is admitted with all 10 redacted."""
        emails = " ".join(f"user{i}@customer{i}.com" for i in range(10))
        sanitized, count, err, _msg = sanitizer.sanitize_free_text(emails)
        assert count == 10
        assert err is None
        assert sanitized.count("<EMAIL_REDACTED>") == 10

    def test_mass_pii_fails_closed_over_10_occurrences(self, sanitizer: KnowledgeSanitizer) -> None:
        """11 or more PII occurrences causes fail-closed rejection."""
        emails = " ".join(f"user{i}@customer{i}.com" for i in range(11))
        sanitized, count, err, msg = sanitizer.sanitize_free_text(emails)
        assert count == 11
        assert err == AdmissionReasonCode.PII_DETECTED
        assert "Mass PII detected" in msg
        assert sanitized == ""


class TestRunbookAndKnownIssueSchemaCompletion:
    """Section 7 & 8: Complete coverage of Runbook and Known Issue schema constraints."""

    def test_runbook_parser_valid_with_datetime_last_reviewed(self) -> None:
        parser = RunbookJsonParser()
        raw = json.dumps(
            {
                "runbook_id": "rb-crm-restart",
                "title": "SuperOffice Service Restart",
                "problem_description": "Service hangs during high peak usage.",
                "diagnostic_steps": ["Check event log", "Verify CPU usage"],
                "remediation_steps": ["Restart SO_CS service", "Verify ping"],
                "source_reference": "runbook://ops/so-cs-restart",
                "product": "SuperOffice Service",
                "verified_version": "10.2.1",
                "last_reviewed": "2026-09-08T12:00:00Z",
            }
        ).encode("utf-8")
        model = parser.parse(raw)
        assert model.runbook_id == "rb-crm-restart"
        assert len(model.diagnostic_steps) == 2
        assert isinstance(model.last_reviewed, datetime)

    def test_runbook_parser_omitted_last_reviewed_is_none(self) -> None:
        parser = RunbookJsonParser()
        raw = json.dumps(
            {
                "runbook_id": "rb-crm-restart",
                "title": "SuperOffice Service Restart",
                "problem_description": "Service hangs during high peak usage.",
                "diagnostic_steps": ["Check event log"],
                "remediation_steps": ["Restart service"],
                "source_reference": "runbook://ops/so-cs-restart",
            }
        ).encode("utf-8")
        model = parser.parse(raw)
        assert model.last_reviewed is None

    def test_runbook_parser_rejects_more_than_30_steps(self) -> None:
        parser = RunbookJsonParser()
        steps = [f"Step {i}" for i in range(31)]
        raw = json.dumps(
            {
                "runbook_id": "rb-1",
                "title": "Title",
                "problem_description": "Desc",
                "diagnostic_steps": steps,
                "remediation_steps": ["Step 1"],
                "source_reference": "runbook://ops/1",
            }
        ).encode("utf-8")
        with pytest.raises(KnowledgeSourceFormatError):
            parser.parse(raw)

    def test_runbook_parser_rejects_step_exceeding_1000_chars(self) -> None:
        parser = RunbookJsonParser()
        oversized_step = "A" * 1001
        raw = json.dumps(
            {
                "runbook_id": "rb-1",
                "title": "Title",
                "problem_description": "Desc",
                "diagnostic_steps": [oversized_step],
                "remediation_steps": ["Step 1"],
                "source_reference": "runbook://ops/1",
            }
        ).encode("utf-8")
        with pytest.raises(KnowledgeSourceFormatError):
            parser.parse(raw)

    def test_runbook_parser_rejects_empty_step(self) -> None:
        parser = RunbookJsonParser()
        raw = json.dumps(
            {
                "runbook_id": "rb-1",
                "title": "Title",
                "problem_description": "Desc",
                "diagnostic_steps": ["   "],
                "remediation_steps": ["Step 1"],
                "source_reference": "runbook://ops/1",
            }
        ).encode("utf-8")
        with pytest.raises(KnowledgeSourceFormatError):
            parser.parse(raw)

    def test_runbook_parser_rejects_problem_desc_over_8192_chars(self) -> None:
        parser = RunbookJsonParser()
        raw = json.dumps(
            {
                "runbook_id": "rb-1",
                "title": "Title",
                "problem_description": "A" * 8193,
                "diagnostic_steps": ["Step 1"],
                "remediation_steps": ["Step 2"],
                "source_reference": "runbook://ops/1",
            }
        ).encode("utf-8")
        with pytest.raises(KnowledgeSourceFormatError):
            parser.parse(raw)

    def test_known_issue_parser_valid_with_defaults(self) -> None:
        parser = KnownIssueJsonParser()
        raw = json.dumps(
            {
                "issue_id": "ki-crm-001",
                "title": "IIS Pool Recycling Under Load",
                "symptom_summary": "Clients receive HTTP 503 errors.",
                "source_reference": "known-issue://kb/ki-crm-001",
            }
        ).encode("utf-8")
        model = parser.parse(raw)
        assert model.issue_id == "ki-crm-001"
        assert model.root_cause_summary == ""
        assert model.workaround is None
        assert model.permanent_fix_reference is None
        assert model.affected_products == []
        assert model.affected_versions == []
        assert model.category == "general"

    def test_known_issue_parser_rejects_more_than_20_products_or_versions(self) -> None:
        parser = KnownIssueJsonParser()
        products = [f"Product {i}" for i in range(21)]
        raw = json.dumps(
            {
                "issue_id": "ki-1",
                "title": "Title",
                "symptom_summary": "Symptom",
                "affected_products": products,
                "source_reference": "known-issue://kb/1",
            }
        ).encode("utf-8")
        with pytest.raises(KnowledgeSourceFormatError):
            parser.parse(raw)

    def test_known_issue_parser_rejects_product_over_100_chars(self) -> None:
        parser = KnownIssueJsonParser()
        raw = json.dumps(
            {
                "issue_id": "ki-1",
                "title": "Title",
                "symptom_summary": "Symptom",
                "affected_products": ["P" * 101],
                "source_reference": "known-issue://kb/1",
            }
        ).encode("utf-8")
        with pytest.raises(KnowledgeSourceFormatError):
            parser.parse(raw)

    def test_known_issue_parser_rejects_version_over_50_chars(self) -> None:
        parser = KnownIssueJsonParser()
        raw = json.dumps(
            {
                "issue_id": "ki-1",
                "title": "Title",
                "symptom_summary": "Symptom",
                "affected_versions": ["V" * 51],
                "source_reference": "known-issue://kb/1",
            }
        ).encode("utf-8")
        with pytest.raises(KnowledgeSourceFormatError):
            parser.parse(raw)

    @pytest.mark.parametrize(
        "bad_fix_ref",
        [
            r"D:\patches\fix.exe",
            r"\\patchserver\share\fix.exe",
            "https://user:pass@example.com/patches/fix",
        ],
    )
    def test_known_issue_parser_rejects_unsafe_permanent_fix_ref(self, bad_fix_ref: str) -> None:
        parser = KnownIssueJsonParser()
        raw = json.dumps(
            {
                "issue_id": "ki-1",
                "title": "Title",
                "symptom_summary": "Symptom",
                "permanent_fix_reference": bad_fix_ref,
                "source_reference": "known-issue://kb/1",
            }
        ).encode("utf-8")
        with pytest.raises(KnowledgeSourceFormatError):
            parser.parse(raw)


class TestStructuredIdentityIntegrity:
    """Section 9: Structured identity fields reject secrets and PII without silent redaction."""

    @pytest.fixture
    def service(self) -> KnowledgeAdmissionService:
        return KnowledgeAdmissionService()

    def test_rejects_pii_in_category(self, service: KnowledgeAdmissionService) -> None:
        raw_ki = json.dumps(
            {
                "issue_id": "ki-cat-01",
                "title": "Clean Title",
                "symptom_summary": "Clean Symptom",
                "category": "engineer.john@superoffice.no",
                "source_reference": "known-issue://kb/cat-01",
            }
        ).encode("utf-8")
        source = AdmissionSourceInputDTO(
            source_name="ki_cat.json",
            source_kind=IngestionSourceKind.KNOWN_ISSUE_JSON,
            corpus_category=CorpusCategory.KNOWN_ISSUE,
            raw_bytes=raw_ki,
        )
        res = service.admit(source)
        assert res.decision == AdmissionDecision.REJECTED
        assert res.reason_code == AdmissionReasonCode.PII_DETECTED
        assert "category" in res.message

    def test_rejects_secret_in_category(self, service: KnowledgeAdmissionService) -> None:
        raw_ki = json.dumps(
            {
                "issue_id": "ki-cat-02",
                "title": "Clean Title",
                "symptom_summary": "Clean Symptom",
                "category": "sk" + "_live_" + "1234567890abcdef1234567890abcdef",
                "source_reference": "known-issue://kb/cat-02",
            }
        ).encode("utf-8")
        source = AdmissionSourceInputDTO(
            source_name="ki_cat_sec.json",
            source_kind=IngestionSourceKind.KNOWN_ISSUE_JSON,
            corpus_category=CorpusCategory.KNOWN_ISSUE,
            raw_bytes=raw_ki,
        )
        res = service.admit(source)
        assert res.decision == AdmissionDecision.REJECTED
        assert res.reason_code == AdmissionReasonCode.SECRET_DETECTED
        assert "category" in res.message

    def test_rejects_pii_in_verified_version(self, service: KnowledgeAdmissionService) -> None:
        raw_rb = json.dumps(
            {
                "runbook_id": "rb-ver-01",
                "title": "Clean Title",
                "problem_description": "Clean Problem",
                "diagnostic_steps": ["Step 1"],
                "remediation_steps": ["Step 2"],
                "source_reference": "runbook://ops/ver-01",
                "verified_version": "user@realcompany.com",
            }
        ).encode("utf-8")
        source = AdmissionSourceInputDTO(
            source_name="rb_ver.json",
            source_kind=IngestionSourceKind.RUNBOOK_JSON,
            corpus_category=CorpusCategory.RUNBOOK,
            raw_bytes=raw_rb,
        )
        res = service.admit(source)
        assert res.decision == AdmissionDecision.REJECTED
        assert res.reason_code == AdmissionReasonCode.PII_DETECTED
        assert "verified_version" in res.message

    def test_rejects_secret_in_affected_product(self, service: KnowledgeAdmissionService) -> None:
        raw_ki = json.dumps(
            {
                "issue_id": "ki-prod-01",
                "title": "Clean Title",
                "symptom_summary": "Clean Symptom",
                "affected_products": ["sk" + "_live_" + "1234567890abcdef1234567890abcdef"],
                "source_reference": "known-issue://kb/prod-01",
            }
        ).encode("utf-8")
        source = AdmissionSourceInputDTO(
            source_name="ki_prod.json",
            source_kind=IngestionSourceKind.KNOWN_ISSUE_JSON,
            corpus_category=CorpusCategory.KNOWN_ISSUE,
            raw_bytes=raw_ki,
        )
        res = service.admit(source)
        assert res.decision == AdmissionDecision.REJECTED
        assert res.reason_code == AdmissionReasonCode.SECRET_DETECTED
        assert "Affected product in known issue contains sensitive data." in res.message


class TestSecretNonDisclosureAndLogSafety:
    """Section 17: Synthetic secret material is NEVER exposed in exceptions, results, or logs."""

    @pytest.fixture
    def service(self) -> KnowledgeAdmissionService:
        return KnowledgeAdmissionService()

    def test_secret_value_absent_from_admission_result_message(
        self, service: KnowledgeAdmissionService
    ) -> None:
        synthetic_secret = "SyntheticSecretValue_Unrevealed9988!"
        source = AdmissionSourceInputDTO(
            source_name="leak_test.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=f"# Notes\npassword={synthetic_secret}\n".encode(),
        )
        res = service.admit(source)
        assert res.decision == AdmissionDecision.REJECTED
        assert res.reason_code == AdmissionReasonCode.SECRET_DETECTED
        assert synthetic_secret not in res.message

    def test_secret_value_absent_from_exception_message(
        self, service: KnowledgeAdmissionService
    ) -> None:
        synthetic_secret = "SyntheticSecretValue_Unrevealed7766!"
        source = AdmissionSourceInputDTO(
            source_name="leak_test.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=f"# Notes\nclient_secret={synthetic_secret}\n".encode(),
        )
        with pytest.raises(KnowledgeContentRejectedError) as exc_info:
            service.admit_or_raise(source)
        exc_str = str(exc_info.value)
        assert synthetic_secret not in exc_str

    def test_secret_value_absent_from_captured_logs(
        self,
        service: KnowledgeAdmissionService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        synthetic_secret = "SyntheticSecretValue_Unrevealed5544!"
        source = AdmissionSourceInputDTO(
            source_name="leak_test.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=f"# Notes\napi_key={synthetic_secret}\n".encode(),
        )
        with caplog.at_level(logging.DEBUG):
            service.admit(source)
        assert synthetic_secret not in caplog.text

    def test_redacted_pii_absent_from_approved_payload(
        self, service: KnowledgeAdmissionService
    ) -> None:
        sensitive_email = "victim.user@sensitive-client.com"
        sensitive_phone = "+47 99 88 77 66"
        sensitive_id = "987654"
        raw_doc = f"""# Incident Report
Reported by {sensitive_email}
Call back on {sensitive_phone}
customer id number: {sensitive_id}
"""
        source = AdmissionSourceInputDTO(
            source_name="report.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=raw_doc.encode("utf-8"),
        )
        res = service.admit(source)
        assert res.decision == AdmissionDecision.APPROVED
        assert res.sanitized_payload is not None
        canonical = res.sanitized_payload.canonical_text
        assert sensitive_email not in canonical
        assert sensitive_phone not in canonical
        assert sensitive_id not in canonical
        assert "<EMAIL_REDACTED>" in canonical
        assert "<PHONE_REDACTED>" in canonical
        assert "<ID_REDACTED>" in canonical
