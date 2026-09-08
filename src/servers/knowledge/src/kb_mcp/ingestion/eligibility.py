"""Corpus eligibility policy and admission boundary validation (Gate 7D.5B)."""

import re
from dataclasses import dataclass
from typing import Final

from kb_mcp.contracts.constants import (
    MAX_SOURCE_FILE_BYTES,
    MIN_SOURCE_TEXT_BYTES,
)
from kb_mcp.contracts.ingestion import (
    AdmissionReasonCode,
    AdmissionSourceInputDTO,
    CorpusCategory,
    IngestionSourceKind,
    ProhibitedSourceClassification,
)

# Prohibited classification keywords (D05 / D08)
_PROHIBITED_CLASSIFICATIONS: Final[set[str]] = {
    ProhibitedSourceClassification.CUSTOMER_ATTACHMENT.value,
    ProhibitedSourceClassification.LIVE_CRM.value,
    ProhibitedSourceClassification.CUSTOMER_EXPORT.value,
    ProhibitedSourceClassification.RAW_TICKET_DUMP.value,
    ProhibitedSourceClassification.CUSTOMER_INTERACTION_TRANSCRIPT.value,
}

# Regex to detect path traversal, directory slashes, drive letters, UNC paths in source_name
_RE_PATH_IN_NAME: Final[re.Pattern[str]] = re.compile(r"[/\\:]|^\\\\")


@dataclass(frozen=True)
class EligibilityResult:
    """Eligibility check outcome from CorpusEligibilityPolicy."""

    is_eligible: bool
    reason_code: AdmissionReasonCode | None = None
    message: str = ""


class CorpusEligibilityPolicy:
    """Evaluates candidate sources for corpus eligibility prior to parsing or sanitization.

    Enforces D05 (customer attachments prohibited) and D08 (live CRM / customer data prohibited).
    """

    def evaluate(self, source_input: AdmissionSourceInputDTO) -> EligibilityResult:
        """Evaluate a candidate source input against frozen eligibility rules."""
        # 1. D05 and D08 security classification checks
        classification_res = self._check_classification(source_input.classification)
        if classification_res is not None:
            return classification_res

        # 2. Source name check
        name_res = self._check_source_name(source_input.source_name)
        if name_res is not None:
            return name_res

        # 3. Source kind & category check
        kind_cat_res = self._check_kind_and_category(
            source_input.source_kind,
            source_input.corpus_category,
        )
        if kind_cat_res is not None:
            return kind_cat_res

        # 4. Raw byte size bounds check
        size_res = self._check_size(len(source_input.raw_bytes))
        if size_res is not None:
            return size_res

        return EligibilityResult(is_eligible=True)

    def _check_classification(self, classification: str | None) -> EligibilityResult | None:
        """Check for D05 customer attachment or D08 prohibited CRM/customer classifications."""
        cleaned = (classification or "").strip().lower()
        if cleaned in {
            ProhibitedSourceClassification.CUSTOMER_ATTACHMENT.value,
            "attachment",
            "customer_attachment",
        }:
            return EligibilityResult(
                is_eligible=False,
                reason_code=AdmissionReasonCode.CUSTOMER_ATTACHMENT_DETECTED,
                message="Source rejected: classified as customer attachment (D05 policy).",
            )

        if cleaned in _PROHIBITED_CLASSIFICATIONS:
            return EligibilityResult(
                is_eligible=False,
                reason_code=AdmissionReasonCode.PROHIBITED_SOURCE_CLASSIFICATION,
                message=(f"Source rejected: prohibited classification '{cleaned}' (D08 policy)."),
            )
        return None

    def _check_source_name(self, source_name: str) -> EligibilityResult | None:
        """Validate that source_name is a safe display name / basename."""
        name = source_name.strip()
        if not name or _RE_PATH_IN_NAME.search(name):
            return EligibilityResult(
                is_eligible=False,
                reason_code=AdmissionReasonCode.INVALID_SOURCE_NAME,
                message=(
                    "Source name must be a non-empty display name/basename without path separators."
                ),
            )
        return None

    def _check_kind_and_category(
        self,
        source_kind_raw: str,
        category_raw: str,
    ) -> EligibilityResult | None:
        """Validate source kind, corpus category, and category alignment."""
        try:
            source_kind = IngestionSourceKind(source_kind_raw)
        except ValueError:
            return EligibilityResult(
                is_eligible=False,
                reason_code=AdmissionReasonCode.UNSUPPORTED_SOURCE_KIND,
                message=f"Unsupported source kind: '{source_kind_raw}'.",
            )

        try:
            category = CorpusCategory(category_raw)
        except ValueError:
            return EligibilityResult(
                is_eligible=False,
                reason_code=AdmissionReasonCode.UNSUPPORTED_CATEGORY,
                message=f"Unsupported corpus category: '{category_raw}'.",
            )

        if source_kind == IngestionSourceKind.RUNBOOK_JSON:
            if category != CorpusCategory.RUNBOOK:
                return EligibilityResult(
                    is_eligible=False,
                    reason_code=AdmissionReasonCode.CATEGORY_MISMATCH,
                    message="RUNBOOK_JSON source kind must have corpus category 'runbook'.",
                )
        elif source_kind == IngestionSourceKind.KNOWN_ISSUE_JSON:
            if category != CorpusCategory.KNOWN_ISSUE:
                return EligibilityResult(
                    is_eligible=False,
                    reason_code=AdmissionReasonCode.CATEGORY_MISMATCH,
                    message=(
                        "KNOWN_ISSUE_JSON source kind must have corpus category 'known_issue'."
                    ),
                )
        elif category in (CorpusCategory.RUNBOOK, CorpusCategory.KNOWN_ISSUE):
            return EligibilityResult(
                is_eligible=False,
                reason_code=AdmissionReasonCode.CATEGORY_MISMATCH,
                message=(
                    f"Document source kind '{source_kind}' cannot use structured "
                    f"category '{category}'."
                ),
            )

        return None

    def _check_size(self, byte_len: int) -> EligibilityResult | None:
        """Validate raw byte size against frozen bounds."""
        if byte_len > MAX_SOURCE_FILE_BYTES:
            return EligibilityResult(
                is_eligible=False,
                reason_code=AdmissionReasonCode.SIZE_LIMIT_EXCEEDED,
                message=(
                    f"Source byte size ({byte_len}) exceeds maximum limit of "
                    f"{MAX_SOURCE_FILE_BYTES} bytes."
                ),
            )

        if byte_len < MIN_SOURCE_TEXT_BYTES:
            return EligibilityResult(
                is_eligible=False,
                reason_code=AdmissionReasonCode.SOURCE_TOO_SHORT,
                message=(
                    f"Source byte size ({byte_len}) is below minimum limit of "
                    f"{MIN_SOURCE_TEXT_BYTES} bytes."
                ),
            )

        return None
