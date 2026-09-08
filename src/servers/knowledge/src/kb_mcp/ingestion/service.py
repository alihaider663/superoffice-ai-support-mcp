"""Admission coordinator and evaluation service for knowledge ingestion (Gate 7D.5B)."""

from typing import Final

from kb_mcp.contracts.constants import MAX_CANONICAL_TEXT_BYTES
from kb_mcp.contracts.errors import (
    KnowledgeContentRejectedError,
    KnowledgeSizeLimitExceededError,
    KnowledgeSourceFormatError,
)
from kb_mcp.contracts.ingestion import (
    AdmissionDecision,
    AdmissionReasonCode,
    AdmissionResult,
    AdmissionSourceInputDTO,
    IngestionSourceKind,
    SanitizedDocumentPayloadDTO,
    SanitizedKnownIssuePayloadDTO,
    SanitizedRunbookPayloadDTO,
)
from kb_mcp.ingestion.eligibility import CorpusEligibilityPolicy
from kb_mcp.ingestion.normalization import normalize_text
from kb_mcp.ingestion.parsers import (
    KnownIssueJsonParser,
    MarkdownParser,
    ParsedKnownIssueModel,
    ParsedRunbookModel,
    PlainTextParser,
    RunbookJsonParser,
)
from kb_mcp.ingestion.sanitizer import KnowledgeSanitizer

_MSG_SECRET_DETECTED: Final[str] = "Source content rejected: secret or credential detected."
_MSG_PII_DETECTED: Final[str] = (
    "Source content rejected: prohibited PII detected or threshold exceeded."
)


class KnowledgeAdmissionService:
    """Coordinates corpus eligibility, parsing, secret rejection, PII redaction, and
    normalization."""

    def __init__(
        self,
        eligibility_policy: CorpusEligibilityPolicy | None = None,
        sanitizer: KnowledgeSanitizer | None = None,
    ) -> None:
        self._eligibility_policy = eligibility_policy or CorpusEligibilityPolicy()
        self._sanitizer = sanitizer or KnowledgeSanitizer()
        self._markdown_parser = MarkdownParser()
        self._plaintext_parser = PlainTextParser()
        self._runbook_parser = RunbookJsonParser()
        self._known_issue_parser = KnownIssueJsonParser()

    def admit(self, source_input: AdmissionSourceInputDTO) -> AdmissionResult:
        """Evaluate a candidate source through the complete ingestion admission boundary."""
        # Step 1: Eligibility check (D05 and D08 pre-filters, format support, bounds)
        eligibility = self._eligibility_policy.evaluate(source_input)
        if not eligibility.is_eligible:
            return AdmissionResult(
                decision=AdmissionDecision.REJECTED,
                reason_code=eligibility.reason_code,
                message=eligibility.message,
            )

        # Step 2: Format-specific parsing & schema validation
        try:
            return self._parse_and_admit(source_input)
        except KnowledgeSourceFormatError as exc:
            return AdmissionResult(
                decision=AdmissionDecision.FAILED,
                reason_code=AdmissionReasonCode.FORMAT_ERROR,
                message=exc.message,
            )

    def admit_or_raise(self, source_input: AdmissionSourceInputDTO) -> AdmissionResult:
        """Evaluate candidate source, raising KnowledgeAdmissionError subclasses on non-approval."""
        result = self.admit(source_input)
        if result.decision == AdmissionDecision.APPROVED:
            return result

        if result.reason_code == AdmissionReasonCode.SECRET_DETECTED:
            raise KnowledgeContentRejectedError(
                result.message or _MSG_SECRET_DETECTED,
                reason="SECRET_DETECTED",
            )
        if result.reason_code in (
            AdmissionReasonCode.PII_DETECTED,
            AdmissionReasonCode.CUSTOMER_ATTACHMENT_DETECTED,
            AdmissionReasonCode.PROHIBITED_SOURCE_CLASSIFICATION,
        ):
            raise KnowledgeContentRejectedError(
                result.message or _MSG_PII_DETECTED,
                reason=result.reason_code.value,
            )
        if result.reason_code in (
            AdmissionReasonCode.SIZE_LIMIT_EXCEEDED,
            AdmissionReasonCode.SOURCE_TOO_SHORT,
        ):
            raise KnowledgeSizeLimitExceededError(result.message)

        raise KnowledgeSourceFormatError(result.message)

    # ------------------------------------------------------------------------
    # Private parsing and admission dispatcher
    # ------------------------------------------------------------------------

    def _parse_and_admit(self, source_input: AdmissionSourceInputDTO) -> AdmissionResult:
        """Dispatch parsing and admission according to source kind."""
        kind = source_input.source_kind
        if kind == IngestionSourceKind.MARKDOWN_DOCUMENT:
            raw_text = self._markdown_parser.parse(source_input.raw_bytes)
            return self._admit_document(source_input, raw_text)

        if kind == IngestionSourceKind.TEXT_DOCUMENT:
            raw_text = self._plaintext_parser.parse(source_input.raw_bytes)
            return self._admit_document(source_input, raw_text)

        if kind == IngestionSourceKind.RUNBOOK_JSON:
            parsed_rb = self._runbook_parser.parse(source_input.raw_bytes)
            return self._admit_runbook(source_input, parsed_rb)

        if kind == IngestionSourceKind.KNOWN_ISSUE_JSON:
            parsed_ki = self._known_issue_parser.parse(source_input.raw_bytes)
            return self._admit_known_issue(source_input, parsed_ki)

        return AdmissionResult(
            decision=AdmissionDecision.REJECTED,
            reason_code=AdmissionReasonCode.UNSUPPORTED_SOURCE_KIND,
            message=f"Unsupported source kind: '{kind}'.",
        )

    # ------------------------------------------------------------------------
    # Document Admission
    # ------------------------------------------------------------------------

    def _admit_document(
        self,
        source_input: AdmissionSourceInputDTO,
        raw_text: str,
    ) -> AdmissionResult:
        """Sanitize and normalize a Markdown or PlainText document."""
        san_text, pii_cnt, err_code, err_msg = self._sanitizer.sanitize_free_text(raw_text)
        if err_code is not None:
            return AdmissionResult(
                decision=AdmissionDecision.REJECTED,
                reason_code=err_code,
                message=err_msg,
                pii_redaction_count=pii_cnt,
            )

        canonical_text = normalize_text(san_text)
        if not canonical_text:
            return AdmissionResult(
                decision=AdmissionDecision.REJECTED,
                reason_code=AdmissionReasonCode.EMPTY_CONTENT,
                message="Document content is empty or whitespace-only after normalization.",
            )

        canonical_bytes = len(canonical_text.encode("utf-8"))
        if canonical_bytes > MAX_CANONICAL_TEXT_BYTES:
            return AdmissionResult(
                decision=AdmissionDecision.REJECTED,
                reason_code=AdmissionReasonCode.SIZE_LIMIT_EXCEEDED,
                message=(
                    f"Canonical text byte size ({canonical_bytes}) exceeds maximum allowed "
                    f"limit of {MAX_CANONICAL_TEXT_BYTES} bytes."
                ),
            )

        payload = SanitizedDocumentPayloadDTO(
            source_name=source_input.source_name,
            source_kind=source_input.source_kind,
            corpus_category=source_input.corpus_category,
            canonical_text=canonical_text,
        )
        return AdmissionResult(
            decision=AdmissionDecision.APPROVED,
            sanitized_payload=payload,
            pii_redaction_count=pii_cnt,
        )

    # ------------------------------------------------------------------------
    # Runbook Admission
    # ------------------------------------------------------------------------

    def _admit_runbook(
        self,
        source_input: AdmissionSourceInputDTO,
        rb: ParsedRunbookModel,
    ) -> AdmissionResult:
        """Sanitize and normalize an operational Runbook."""
        # 1. Identity / Provenance validation
        identity_err = self._check_runbook_identity(rb)
        if identity_err is not None:
            return identity_err

        # 2. Free-text sanitization
        san_res = self._sanitize_runbook_content(rb)
        if isinstance(san_res, AdmissionResult):
            return san_res

        san_title, san_desc, san_diag, san_remed, total_pii = san_res

        # 3. Canonical text construction and bounding
        canonical_text = self._build_runbook_canonical(
            title=san_title,
            problem=san_desc,
            diag_steps=san_diag,
            remed_steps=san_remed,
            product=rb.product,
            verified_version=rb.verified_version,
        )
        canonical_bytes = len(canonical_text.encode("utf-8"))
        if canonical_bytes > MAX_CANONICAL_TEXT_BYTES:
            return AdmissionResult(
                decision=AdmissionDecision.REJECTED,
                reason_code=AdmissionReasonCode.SIZE_LIMIT_EXCEEDED,
                message=(
                    f"Canonical text ({canonical_bytes} bytes) exceeds "
                    f"{MAX_CANONICAL_TEXT_BYTES} limit."
                ),
            )

        payload = SanitizedRunbookPayloadDTO(
            source_name=source_input.source_name,
            runbook_id=rb.runbook_id.strip(),
            title=normalize_text(san_title),
            problem_description=normalize_text(san_desc),
            diagnostic_steps=tuple(san_diag),
            remediation_steps=tuple(san_remed),
            product=normalize_text(rb.product) if rb.product else None,
            verified_version=normalize_text(rb.verified_version) if rb.verified_version else None,
            last_reviewed=rb.last_reviewed,
            source_reference=rb.source_reference.strip(),
            canonical_text=canonical_text,
        )
        return AdmissionResult(
            decision=AdmissionDecision.APPROVED,
            sanitized_payload=payload,
            pii_redaction_count=total_pii,
        )

    def _check_runbook_identity(self, rb: ParsedRunbookModel) -> AdmissionResult | None:
        """Validate identity fields for runbook."""
        fields = [
            ("runbook_id", rb.runbook_id),
            ("source_reference", rb.source_reference),
            ("product", rb.product),
            ("verified_version", rb.verified_version),
        ]
        for field_name, val in fields:
            if val:
                code = self._sanitizer.check_identity_field(val, field_name)
                if code is not None:
                    msg = (
                        f"Runbook identity field '{field_name}' contains a secret."
                        if code == AdmissionReasonCode.SECRET_DETECTED
                        else f"Runbook identity field '{field_name}' contains PII."
                    )
                    return AdmissionResult(
                        decision=AdmissionDecision.REJECTED,
                        reason_code=code,
                        message=msg,
                    )
        return None

    def _sanitize_runbook_content(
        self,
        rb: ParsedRunbookModel,
    ) -> tuple[str, str, list[str], list[str], int] | AdmissionResult:
        """Sanitize runbook title, problem description, diagnostic steps, and remediation steps."""
        total_pii = 0

        san_title, c, err, msg = self._sanitizer.sanitize_free_text(rb.title)
        if err:
            return AdmissionResult(
                decision=AdmissionDecision.REJECTED,
                reason_code=err,
                message=msg,
            )
        total_pii += c

        san_desc, c, err, msg = self._sanitizer.sanitize_free_text(rb.problem_description)
        if err:
            return AdmissionResult(
                decision=AdmissionDecision.REJECTED,
                reason_code=err,
                message=msg,
            )
        total_pii += c

        san_diag: list[str] = []
        for step in rb.diagnostic_steps:
            s_step, c, err, msg = self._sanitizer.sanitize_free_text(step)
            if err:
                return AdmissionResult(
                    decision=AdmissionDecision.REJECTED,
                    reason_code=err,
                    message=msg,
                )
            total_pii += c
            san_diag.append(normalize_text(s_step))

        san_remed: list[str] = []
        for step in rb.remediation_steps:
            s_step, c, err, msg = self._sanitizer.sanitize_free_text(step)
            if err:
                return AdmissionResult(
                    decision=AdmissionDecision.REJECTED,
                    reason_code=err,
                    message=msg,
                )
            total_pii += c
            san_remed.append(normalize_text(s_step))

        if total_pii > 10:
            return AdmissionResult(
                decision=AdmissionDecision.REJECTED,
                reason_code=AdmissionReasonCode.PII_DETECTED,
                message=f"Total PII occurrences in runbook ({total_pii}) exceed limit of 10.",
                pii_redaction_count=total_pii,
            )

        return san_title, san_desc, san_diag, san_remed, total_pii

    def _build_runbook_canonical(
        self,
        *,
        title: str,
        problem: str,
        diag_steps: list[str],
        remed_steps: list[str],
        product: str | None,
        verified_version: str | None,
    ) -> str:
        """Construct canonical search text for runbook."""
        lines = [
            f"Title: {normalize_text(title)}",
            f"Problem: {normalize_text(problem)}",
        ]
        if product:
            lines.append(f"Product: {normalize_text(product)}")
        if verified_version:
            lines.append(f"Verified Version: {normalize_text(verified_version)}")
        lines.append("Diagnostic Steps:")
        for i, step in enumerate(diag_steps, 1):
            lines.append(f"{i}. {step}")
        lines.append("Remediation Steps:")
        for i, step in enumerate(remed_steps, 1):
            lines.append(f"{i}. {step}")
        return normalize_text("\n".join(lines))

    # ------------------------------------------------------------------------
    # Known Issue Admission
    # ------------------------------------------------------------------------

    def _admit_known_issue(
        self,
        source_input: AdmissionSourceInputDTO,
        ki: ParsedKnownIssueModel,
    ) -> AdmissionResult:
        """Sanitize and normalize a verified Known Issue."""
        # 1. Identity / Provenance validation
        identity_err = self._check_known_issue_identity(ki)
        if identity_err is not None:
            return identity_err

        # 2. Free-text sanitization
        san_res = self._sanitize_known_issue_content(ki)
        if isinstance(san_res, AdmissionResult):
            return san_res

        san_title, san_symptom, san_root, san_workaround, total_pii = san_res

        # 3. Canonical text construction and bounding
        canonical_text = self._build_known_issue_canonical(
            title=san_title,
            symptom=san_symptom,
            root_cause=san_root,
            workaround=san_workaround,
            fix_ref=ki.permanent_fix_reference,
            products=ki.affected_products,
            versions=ki.affected_versions,
            category=ki.category,
        )
        canonical_bytes = len(canonical_text.encode("utf-8"))
        if canonical_bytes > MAX_CANONICAL_TEXT_BYTES:
            return AdmissionResult(
                decision=AdmissionDecision.REJECTED,
                reason_code=AdmissionReasonCode.SIZE_LIMIT_EXCEEDED,
                message=(
                    f"Canonical text ({canonical_bytes} bytes) exceeds "
                    f"{MAX_CANONICAL_TEXT_BYTES} limit."
                ),
            )

        payload = SanitizedKnownIssuePayloadDTO(
            source_name=source_input.source_name,
            issue_id=ki.issue_id.strip(),
            title=normalize_text(san_title),
            symptom_summary=normalize_text(san_symptom),
            root_cause_summary=normalize_text(san_root),
            workaround=san_workaround,
            permanent_fix_reference=(
                normalize_text(ki.permanent_fix_reference) if ki.permanent_fix_reference else None
            ),
            affected_products=tuple(normalize_text(p) for p in ki.affected_products),
            affected_versions=tuple(normalize_text(v) for v in ki.affected_versions),
            category=normalize_text(ki.category),
            source_reference=ki.source_reference.strip(),
            canonical_text=canonical_text,
        )
        return AdmissionResult(
            decision=AdmissionDecision.APPROVED,
            sanitized_payload=payload,
            pii_redaction_count=total_pii,
        )

    def _check_known_issue_identity(self, ki: ParsedKnownIssueModel) -> AdmissionResult | None:
        """Validate identity fields for known issue."""
        scalar_fields = [
            ("issue_id", ki.issue_id),
            ("source_reference", ki.source_reference),
            ("permanent_fix_reference", ki.permanent_fix_reference),
            ("category", ki.category),
        ]
        for field_name, val in scalar_fields:
            if val:
                code = self._sanitizer.check_identity_field(val, field_name)
                if code is not None:
                    msg = (
                        f"Known issue field '{field_name}' contains a secret."
                        if code == AdmissionReasonCode.SECRET_DETECTED
                        else f"Known issue field '{field_name}' contains PII."
                    )
                    return AdmissionResult(
                        decision=AdmissionDecision.REJECTED,
                        reason_code=code,
                        message=msg,
                    )

        for prod in ki.affected_products:
            code = self._sanitizer.check_identity_field(prod, "affected_products")
            if code is not None:
                return AdmissionResult(
                    decision=AdmissionDecision.REJECTED,
                    reason_code=code,
                    message="Affected product in known issue contains sensitive data.",
                )

        for ver in ki.affected_versions:
            code = self._sanitizer.check_identity_field(ver, "affected_versions")
            if code is not None:
                return AdmissionResult(
                    decision=AdmissionDecision.REJECTED,
                    reason_code=code,
                    message="Affected version in known issue contains sensitive data.",
                )
        return None

    def _sanitize_known_issue_content(
        self,
        ki: ParsedKnownIssueModel,
    ) -> tuple[str, str, str, str | None, int] | AdmissionResult:
        """Sanitize known issue title, symptom, root cause, and workaround."""
        total_pii = 0

        san_title, c, err, msg = self._sanitizer.sanitize_free_text(ki.title)
        if err:
            return AdmissionResult(
                decision=AdmissionDecision.REJECTED,
                reason_code=err,
                message=msg,
            )
        total_pii += c

        san_symptom, c, err, msg = self._sanitizer.sanitize_free_text(ki.symptom_summary)
        if err:
            return AdmissionResult(
                decision=AdmissionDecision.REJECTED,
                reason_code=err,
                message=msg,
            )
        total_pii += c

        san_root, c, err, msg = self._sanitizer.sanitize_free_text(ki.root_cause_summary)
        if err:
            return AdmissionResult(
                decision=AdmissionDecision.REJECTED,
                reason_code=err,
                message=msg,
            )
        total_pii += c

        san_workaround: str | None = None
        if ki.workaround:
            san_w, c, err, msg = self._sanitizer.sanitize_free_text(ki.workaround)
            if err:
                return AdmissionResult(
                    decision=AdmissionDecision.REJECTED,
                    reason_code=err,
                    message=msg,
                )
            total_pii += c
            san_workaround = normalize_text(san_w)

        if total_pii > 10:
            return AdmissionResult(
                decision=AdmissionDecision.REJECTED,
                reason_code=AdmissionReasonCode.PII_DETECTED,
                message=f"Total PII occurrences in known issue ({total_pii}) exceed limit of 10.",
                pii_redaction_count=total_pii,
            )

        return san_title, san_symptom, san_root, san_workaround, total_pii

    def _build_known_issue_canonical(
        self,
        *,
        title: str,
        symptom: str,
        root_cause: str,
        workaround: str | None,
        fix_ref: str | None,
        products: list[str],
        versions: list[str],
        category: str,
    ) -> str:
        """Construct canonical search text for known issue."""
        lines = [
            f"Title: {normalize_text(title)}",
            f"Symptom: {normalize_text(symptom)}",
        ]
        if root_cause:
            lines.append(f"Root Cause: {normalize_text(root_cause)}")
        if workaround:
            lines.append(f"Workaround: {workaround}")
        if fix_ref:
            lines.append(f"Permanent Fix: {normalize_text(fix_ref)}")
        if products:
            lines.append(f"Affected Products: {', '.join(normalize_text(p) for p in products)}")
        if versions:
            lines.append(f"Affected Versions: {', '.join(normalize_text(v) for v in versions)}")
        lines.append(f"Category: {normalize_text(category)}")
        return normalize_text("\n".join(lines))
