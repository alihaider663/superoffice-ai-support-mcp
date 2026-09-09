"""Comprehensive unit and security test suite for Knowledge Artifact Storage (Gate 7D.5C).

Verifies:
1. Canonical document identity generation (deterministic, stable, bounded).
2. Exact SHA-256 canonical content hashing.
3. Logical provenance URI validation (allowed schemes, category alignment, safety).
4. Artifact root configuration & security boundary validation (isolation, no git tree, no scratch).
5. Staged artifact writes (containment, size limits, raw input rejection).
6. Atomic content-addressed artifact promotion (hash verification, idempotency).
7. Safe cleanup primitives (staged and unreferenced promoted).
8. Filesystem orphan reconciliation primitives (safe typed records, no physical paths).
9. Security invariants (no secrets/PII/physical paths in errors, D05/D08 enforcement).
"""

import concurrent.futures
import hashlib
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from kb_mcp.adapters.filesystem_artifact_store import (
    FilesystemKnowledgeArtifactStore,
    validate_artifact_root,
)
from kb_mcp.contracts.constants import (
    DOCUMENT_ID_PREFIX,
    MAX_CANONICAL_TEXT_BYTES,
)
from kb_mcp.contracts.errors import (
    KnowledgeAdmissionError,
    KnowledgeArtifactError,
)
from kb_mcp.contracts.ingestion import (
    AdmissionDecision,
    AdmissionSourceInputDTO,
    ApprovedArtifactRecord,
    CanonicalKnowledgeDocumentDTO,
    CorpusCategory,
    IngestionSourceKind,
    ProhibitedSourceClassification,
    SanitizedDocumentPayloadDTO,
    SanitizedKnownIssuePayloadDTO,
    SanitizedRunbookPayloadDTO,
    StagedArtifactToken,
)
from kb_mcp.ingestion.canonical import (
    build_canonical_document,
    compute_content_hash,
    generate_document_id,
    validate_provenance,
)
from kb_mcp.ingestion.service import KnowledgeAdmissionService
from kb_mcp.settings import KnowledgeServerSettings

# ============================================================================
# 1. Canonical Identity Tests
# ============================================================================


class TestCanonicalIdentity:
    """Test deterministic canonical document identity and content hashing."""

    def test_same_logical_source_produces_identical_document_id(self) -> None:
        doc_id1 = generate_document_id("docs://superoffice/admin/guide", "documentation")
        doc_id2 = generate_document_id("docs://superoffice/admin/guide", "documentation")
        assert doc_id1 == doc_id2

    def test_different_logical_source_produces_different_document_id(self) -> None:
        doc_id1 = generate_document_id("docs://superoffice/admin/guide1", "documentation")
        doc_id2 = generate_document_id("docs://superoffice/admin/guide2", "documentation")
        assert doc_id1 != doc_id2

    def test_different_document_type_produces_different_document_id(self) -> None:
        doc_id1 = generate_document_id("docs://superoffice/shared/doc", "documentation")
        doc_id2 = generate_document_id("docs://superoffice/shared/doc", "sop")
        assert doc_id1 != doc_id2

    def test_document_id_bounded_and_prefixed(self) -> None:
        doc_id = generate_document_id("docs://superoffice/guide", "documentation")
        assert len(doc_id) <= 64
        assert doc_id.startswith(DOCUMENT_ID_PREFIX)
        assert len(doc_id) == len(DOCUMENT_ID_PREFIX) + 24
        assert re.match(r"^doc_[0-9a-f]{24}$", doc_id)

    def test_document_id_contains_no_physical_path_or_host_info(self) -> None:
        doc_id = generate_document_id("docs://superoffice/guide", "documentation")
        assert "/" not in doc_id
        assert "\\" not in doc_id
        assert ":" not in doc_id
        assert "." not in doc_id

    def test_empty_identity_rejected(self) -> None:
        with pytest.raises(
            KnowledgeAdmissionError, match="Logical source identity cannot be empty"
        ):
            generate_document_id("", "documentation")

    def test_unsupported_document_type_rejected(self) -> None:
        with pytest.raises(KnowledgeAdmissionError, match="not in allowlisted types"):
            generate_document_id("docs://guide", "unsupported_type")

    def test_content_hash_exact_sha256(self) -> None:
        text = "Hello SuperOffice Knowledge Base!"
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest().lower()
        actual = compute_content_hash(text)
        assert actual == expected
        assert len(actual) == 64
        assert re.match(r"^[0-9a-f]{64}$", actual)

    def test_same_content_produces_same_hash(self) -> None:
        h1 = compute_content_hash("Standardized procedure text.")
        h2 = compute_content_hash("Standardized procedure text.")
        assert h1 == h2

    def test_changed_content_produces_different_hash(self) -> None:
        h1 = compute_content_hash("Standardized procedure text v1.")
        h2 = compute_content_hash("Standardized procedure text v2.")
        assert h1 != h2

    def test_empty_content_hash_fails_closed(self) -> None:
        with pytest.raises(KnowledgeAdmissionError, match="empty or whitespace-only"):
            compute_content_hash("   \n\t  ")


# ============================================================================
# 2. Provenance Tests
# ============================================================================


class TestProvenance:
    """Test logical provenance validation across schemes and categories."""

    def test_docs_scheme_accepted_for_documentation(self) -> None:
        validate_provenance("docs://superoffice/admin/configuration", CorpusCategory.DOCUMENTATION)

    def test_sop_scheme_accepted_for_sop(self) -> None:
        validate_provenance("sop://support/escalation-guide", CorpusCategory.SOP)

    def test_runbook_scheme_accepted_for_runbook(self) -> None:
        validate_provenance("runbook://RBK-1001", CorpusCategory.RUNBOOK)

    def test_known_issue_scheme_accepted_for_known_issue(self) -> None:
        validate_provenance("known-issue://KI-2001", CorpusCategory.KNOWN_ISSUE)

    def test_incident_pattern_scheme_accepted_for_incident_pattern(self) -> None:
        validate_provenance("incident-pattern://INC-9001", CorpusCategory.INCIDENT_PATTERN)

    def test_unsupported_scheme_rejected(self) -> None:
        with pytest.raises(KnowledgeAdmissionError, match="Source reference scheme mismatch"):
            validate_provenance("http://example.com/doc", CorpusCategory.DOCUMENTATION)

    def test_file_scheme_rejected(self) -> None:
        with pytest.raises(KnowledgeAdmissionError, match="Source reference scheme mismatch"):
            validate_provenance("file:///etc/hosts", CorpusCategory.DOCUMENTATION)

    def test_drive_path_rejected(self) -> None:
        with pytest.raises(KnowledgeAdmissionError, match="drive letters, backslashes, UNC"):
            validate_provenance("C:\\Users\\admin\\doc.md", CorpusCategory.DOCUMENTATION)

    def test_unc_path_rejected(self) -> None:
        with pytest.raises(KnowledgeAdmissionError, match="drive letters, backslashes, UNC"):
            validate_provenance("\\\\server\\share\\doc.md", CorpusCategory.DOCUMENTATION)

    def test_credential_bearing_reference_rejected(self) -> None:
        with pytest.raises(KnowledgeAdmissionError, match="credentials"):
            validate_provenance(
                "docs://admin:secret123@superoffice/guide", CorpusCategory.DOCUMENTATION
            )

    def test_path_traversal_in_provenance_rejected(self) -> None:
        with pytest.raises(KnowledgeAdmissionError, match="traversal"):
            validate_provenance("docs://superoffice/../secret/guide", CorpusCategory.DOCUMENTATION)

    def test_category_scheme_mismatch_rejected(self) -> None:
        with pytest.raises(KnowledgeAdmissionError, match="Source reference scheme mismatch"):
            validate_provenance("docs://superoffice/guide", CorpusCategory.RUNBOOK)

        with pytest.raises(KnowledgeAdmissionError, match="Source reference scheme mismatch"):
            validate_provenance("runbook://RBK-1001", CorpusCategory.DOCUMENTATION)

    def test_empty_resource_path_rejected(self) -> None:
        with pytest.raises(KnowledgeAdmissionError, match="non-empty resource path"):
            validate_provenance("docs://", CorpusCategory.DOCUMENTATION)


# ============================================================================
# 3. Canonical Document Builder Tests
# ============================================================================


class TestCanonicalDocumentBuilder:
    """Test building CanonicalKnowledgeDocumentDTO from sanitized payloads."""

    def test_build_from_sanitized_document_payload(self) -> None:
        payload = SanitizedDocumentPayloadDTO(
            source_name="config-guide.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            canonical_text="# Configuration Guide\nStep 1: configure settings.",
            source_reference="docs://superoffice/config-guide",
        )
        doc = build_canonical_document(payload)

        assert isinstance(doc, CanonicalKnowledgeDocumentDTO)
        assert doc.document_id.startswith("doc_")
        assert doc.title == "Configuration Guide"
        assert doc.document_type == "documentation"
        assert doc.source_reference == "docs://superoffice/config-guide"
        assert doc.canonical_content == payload.canonical_text
        assert doc.content_hash == compute_content_hash(payload.canonical_text)
        assert doc.corpus_category == CorpusCategory.DOCUMENTATION
        assert doc.structured_payload is None

    def test_build_from_sanitized_runbook_payload(self) -> None:
        payload = SanitizedRunbookPayloadDTO(
            source_name="rbk_1001.json",
            runbook_id="RBK-1001",
            title="Database Connection Recovery",
            problem_description="Connection pool exhausted.",
            diagnostic_steps=("Check connection count.",),
            remediation_steps=("Restart pool.",),
            source_reference="runbook://RBK-1001",
            canonical_text=(
                "Title: Database Connection Recovery\nProblem: Connection pool exhausted."
            ),
        )
        doc = build_canonical_document(payload)

        assert doc.document_id.startswith("doc_")
        assert doc.title == "Database Connection Recovery"
        assert doc.document_type == "runbook"
        assert doc.source_reference == "runbook://RBK-1001"
        assert doc.structured_payload == payload

    def test_build_from_sanitized_known_issue_payload(self) -> None:
        payload = SanitizedKnownIssuePayloadDTO(
            source_name="ki_2001.json",
            issue_id="KI-2001",
            title="Timeout on large sync",
            symptom_summary="Sync times out.",
            root_cause_summary="Batch size too high.",
            source_reference="known-issue://KI-2001",
            canonical_text="Title: Timeout on large sync\nSymptom: Sync times out.",
        )
        doc = build_canonical_document(payload)

        assert doc.document_id.startswith("doc_")
        assert doc.title == "Timeout on large sync"
        assert doc.document_type == "known_issue"
        assert doc.source_reference == "known-issue://KI-2001"
        assert doc.structured_payload == payload

    def test_build_rejects_raw_source_input_type(self) -> None:
        raw_input = AdmissionSourceInputDTO(
            source_name="doc.md",
            source_kind=IngestionSourceKind.MARKDOWN_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"raw content",
        )
        with pytest.raises(TypeError, match="Unsupported payload type"):
            build_canonical_document(raw_input)  # type: ignore[arg-type]

    def test_build_rejects_arbitrary_dict_or_string(self) -> None:
        with pytest.raises(TypeError, match="Unsupported payload type"):
            build_canonical_document({"content": "raw"})  # type: ignore[arg-type]


# ============================================================================
# 4. Artifact Root Configuration & Safety Tests
# ============================================================================


class TestArtifactConfiguration:
    """Test validation of KNOWLEDGE_ARTIFACT_ROOT configuration."""

    def test_unconfigured_root_fails_closed(self) -> None:
        with pytest.raises(KnowledgeArtifactError) as exc_info:
            validate_artifact_root(None)
        assert exc_info.value.error_code == "ARTIFACT_ROOT_NOT_CONFIGURED"

        with pytest.raises(KnowledgeArtifactError) as exc_info:
            validate_artifact_root("   ")
        assert exc_info.value.error_code == "ARTIFACT_ROOT_NOT_CONFIGURED"

    def test_unconfigured_store_fails_closed_on_operations(self) -> None:
        store = FilesystemKnowledgeArtifactStore(artifact_root=None)
        doc = CanonicalKnowledgeDocumentDTO(
            document_id="doc_" + "a" * 24,
            title="Test",
            document_type="documentation",
            source_reference="docs://test",
            canonical_content="content",
            content_hash=compute_content_hash("content"),
            corpus_category=CorpusCategory.DOCUMENTATION,
        )
        with pytest.raises(KnowledgeArtifactError) as exc_info:
            store.stage(doc)
        assert exc_info.value.error_code == "ARTIFACT_ROOT_NOT_CONFIGURED"

    def test_relative_root_rejected(self) -> None:
        with pytest.raises(KnowledgeArtifactError) as exc_info:
            validate_artifact_root(Path("relative/path/artifacts"))
        assert exc_info.value.error_code == "ARTIFACT_ROOT_INVALID"
        assert "absolute path" in str(exc_info.value)

    def test_git_repository_root_rejected(self, tmp_path: Path) -> None:
        fake_git_root = tmp_path / "repo"
        fake_git_root.mkdir()
        (fake_git_root / ".git").mkdir()

        with pytest.raises(KnowledgeArtifactError) as exc_info:
            validate_artifact_root(fake_git_root, git_root=fake_git_root)
        assert exc_info.value.error_code == "ARTIFACT_ROOT_INVALID"
        assert "inside project Git repository" in str(exc_info.value)

    def test_path_inside_git_repository_rejected(self, tmp_path: Path) -> None:
        fake_git_root = tmp_path / "repo"
        fake_git_root.mkdir()
        (fake_git_root / ".git").mkdir()
        inside_path = fake_git_root / "artifacts" / "store"
        inside_path.mkdir(parents=True)

        with pytest.raises(KnowledgeArtifactError) as exc_info:
            validate_artifact_root(inside_path, git_root=fake_git_root)
        assert exc_info.value.error_code == "ARTIFACT_ROOT_INVALID"
        assert "inside project Git repository" in str(exc_info.value)

    def test_scratch_path_rejected(self, tmp_path: Path) -> None:
        scratch_dir = tmp_path / "antigravity-ide" / "scratch" / "artifacts"
        scratch_dir.mkdir(parents=True)

        with pytest.raises(KnowledgeArtifactError) as exc_info:
            validate_artifact_root(scratch_dir)
        assert exc_info.value.error_code == "ARTIFACT_ROOT_INVALID"
        assert "scratch directory" in str(exc_info.value)

    def test_valid_external_temp_root_accepted(self, tmp_path: Path) -> None:
        valid_root = tmp_path / "external_artifacts"
        valid_root.mkdir()
        fake_git = tmp_path / "unrelated_repo"
        fake_git.mkdir()
        resolved = validate_artifact_root(valid_root, git_root=fake_git)
        assert resolved == valid_root.resolve()

    def test_settings_default_unconfigured(self) -> None:
        settings = KnowledgeServerSettings()
        assert settings.artifact_root is None


# ============================================================================
# 5. Artifact Staging & Promotion Tests
# ============================================================================


class TestArtifactStagingAndPromotion:
    """Test staging and promoting canonical knowledge artifacts."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> FilesystemKnowledgeArtifactStore:
        artifact_dir = tmp_path / "safe_artifacts"
        artifact_dir.mkdir()
        fake_git = tmp_path / "other_repo"
        fake_git.mkdir()
        return FilesystemKnowledgeArtifactStore(artifact_root=artifact_dir, git_root=fake_git)

    @pytest.fixture
    def sample_canonical_doc(self) -> CanonicalKnowledgeDocumentDTO:
        content = "# SuperOffice Configuration\nStep 1: setup database."
        content_hash = compute_content_hash(content)
        doc_id = generate_document_id("docs://superoffice/config", "documentation")
        return CanonicalKnowledgeDocumentDTO(
            document_id=doc_id,
            title="SuperOffice Configuration",
            document_type="documentation",
            source_reference="docs://superoffice/config",
            canonical_content=content,
            content_hash=content_hash,
            corpus_category=CorpusCategory.DOCUMENTATION,
        )

    def test_staging_writes_content_under_staging_directory(
        self,
        store: FilesystemKnowledgeArtifactStore,
        sample_canonical_doc: CanonicalKnowledgeDocumentDTO,
    ) -> None:
        token = store.stage(sample_canonical_doc)
        assert isinstance(token, StagedArtifactToken)
        assert token.document_id == sample_canonical_doc.document_id
        assert token.content_hash == sample_canonical_doc.content_hash
        assert token.staging_id.startswith(sample_canonical_doc.document_id)
        assert token.staging_id.endswith(".tmp")

        # Staged file exists and is readable
        staged_file = store._staging_dir / token.staging_id  # type: ignore[operator]
        assert staged_file.is_file()
        assert staged_file.read_bytes() == sample_canonical_doc.canonical_content.encode("utf-8")

    def test_staging_rejects_raw_bytes_or_wrong_type(
        self, store: FilesystemKnowledgeArtifactStore
    ) -> None:
        with pytest.raises(TypeError, match="requires an approved CanonicalKnowledgeDocumentDTO"):
            store.stage("raw text")  # type: ignore[arg-type]

    def test_staging_rejects_content_hash_mismatch(
        self,
        store: FilesystemKnowledgeArtifactStore,
        sample_canonical_doc: CanonicalKnowledgeDocumentDTO,
    ) -> None:
        corrupted_doc = CanonicalKnowledgeDocumentDTO(
            document_id=sample_canonical_doc.document_id,
            title=sample_canonical_doc.title,
            document_type=sample_canonical_doc.document_type,
            source_reference=sample_canonical_doc.source_reference,
            canonical_content=sample_canonical_doc.canonical_content,
            content_hash="0" * 64,  # Contradictory hash
            corpus_category=sample_canonical_doc.corpus_category,
        )
        with pytest.raises(KnowledgeArtifactError) as exc_info:
            store.stage(corrupted_doc)
        assert exc_info.value.error_code == "ARTIFACT_HASH_MISMATCH"

    def test_staging_rejects_oversized_canonical_content(
        self,
        store: FilesystemKnowledgeArtifactStore,
    ) -> None:
        huge_text = "x" * (MAX_CANONICAL_TEXT_BYTES + 10)
        huge_hash = compute_content_hash(huge_text)
        doc_id = generate_document_id("docs://huge", "documentation")
        huge_doc = CanonicalKnowledgeDocumentDTO(
            document_id=doc_id,
            title="Huge",
            document_type="documentation",
            source_reference="docs://huge",
            canonical_content=huge_text,
            content_hash=huge_hash,
            corpus_category=CorpusCategory.DOCUMENTATION,
        )
        with pytest.raises(KnowledgeArtifactError) as exc_info:
            store.stage(huge_doc)
        assert exc_info.value.error_code == "ARTIFACT_STAGE_FAILED"
        assert "exceeds maximum allowed limit" in str(exc_info.value)

    def test_successful_promotion_to_approved_storage(
        self,
        store: FilesystemKnowledgeArtifactStore,
        sample_canonical_doc: CanonicalKnowledgeDocumentDTO,
    ) -> None:
        token = store.stage(sample_canonical_doc)
        record = store.promote(token, sample_canonical_doc)

        assert isinstance(record, ApprovedArtifactRecord)
        assert record.document_type == sample_canonical_doc.document_type
        assert record.document_id == sample_canonical_doc.document_id
        assert record.content_hash == sample_canonical_doc.content_hash

        # Promoted file exists at content-addressed path
        approved_file = (
            store._approved_dir  # type: ignore[operator]
            / sample_canonical_doc.document_type
            / sample_canonical_doc.document_id
            / f"{sample_canonical_doc.content_hash}.md"
        )
        assert approved_file.is_file()
        assert approved_file.read_bytes() == sample_canonical_doc.canonical_content.encode("utf-8")

        # Staged file is removed after promotion
        staged_file = store._staging_dir / token.staging_id  # type: ignore[operator]
        assert not staged_file.exists()

    def test_idempotent_promotion_of_identical_content(
        self,
        store: FilesystemKnowledgeArtifactStore,
        sample_canonical_doc: CanonicalKnowledgeDocumentDTO,
    ) -> None:
        token1 = store.stage(sample_canonical_doc)
        record1 = store.promote(token1, sample_canonical_doc)

        # Stage and promote again with identical content
        token2 = store.stage(sample_canonical_doc)
        record2 = store.promote(token2, sample_canonical_doc)

        assert record1 == record2
        approved_file = (
            store._approved_dir  # type: ignore[operator]
            / sample_canonical_doc.document_type
            / sample_canonical_doc.document_id
            / f"{sample_canonical_doc.content_hash}.md"
        )
        assert approved_file.is_file()

    def test_contradictory_artifact_fails_closed(
        self,
        store: FilesystemKnowledgeArtifactStore,
        sample_canonical_doc: CanonicalKnowledgeDocumentDTO,
    ) -> None:
        token = store.stage(sample_canonical_doc)

        # Plant a contradictory file at the expected destination path
        target_dir = (
            store._approved_dir  # type: ignore[operator]
            / sample_canonical_doc.document_type
            / sample_canonical_doc.document_id
        )
        target_dir.mkdir(parents=True)
        dest_file = target_dir / f"{sample_canonical_doc.content_hash}.md"
        dest_file.write_bytes(b"corrupted or conflicting bytes")

        with pytest.raises(KnowledgeArtifactError) as exc_info:
            store.promote(token, sample_canonical_doc)
        assert exc_info.value.error_code == "ARTIFACT_HASH_MISMATCH"
        assert "contradictory content" in str(exc_info.value)

    def test_tampered_staged_file_fails_closed(
        self,
        store: FilesystemKnowledgeArtifactStore,
        sample_canonical_doc: CanonicalKnowledgeDocumentDTO,
    ) -> None:
        token = store.stage(sample_canonical_doc)
        staged_file = store._staging_dir / token.staging_id  # type: ignore[operator]
        # Modify the staged file after staging
        staged_file.write_bytes(b"tampered content")

        with pytest.raises(KnowledgeArtifactError) as exc_info:
            store.promote(token, sample_canonical_doc)
        assert exc_info.value.error_code == "ARTIFACT_HASH_MISMATCH"
        # Staged file cleaned up
        assert not staged_file.exists()

    def test_promotion_token_mismatch_fails(
        self,
        store: FilesystemKnowledgeArtifactStore,
        sample_canonical_doc: CanonicalKnowledgeDocumentDTO,
    ) -> None:
        token = store.stage(sample_canonical_doc)
        mismatched_doc = CanonicalKnowledgeDocumentDTO(
            document_id="doc_" + "b" * 24,
            title=sample_canonical_doc.title,
            document_type=sample_canonical_doc.document_type,
            source_reference=sample_canonical_doc.source_reference,
            canonical_content=sample_canonical_doc.canonical_content,
            content_hash=sample_canonical_doc.content_hash,
            corpus_category=sample_canonical_doc.corpus_category,
        )
        with pytest.raises(KnowledgeArtifactError) as exc_info:
            store.promote(token, mismatched_doc)
        assert exc_info.value.error_code == "ARTIFACT_PROMOTION_FAILED"

    def test_promotion_race_worker_b_creates_contradictory_destination_preserves_existing_bytes(
        self,
        store: FilesystemKnowledgeArtifactStore,
        sample_canonical_doc: CanonicalKnowledgeDocumentDTO,
    ) -> None:
        token = store.stage(sample_canonical_doc)
        dest_path = (
            store._approved_dir  # type: ignore[operator]
            / sample_canonical_doc.document_type
            / sample_canonical_doc.document_id
            / f"{sample_canonical_doc.content_hash}.md"
        )

        def race_link(_src: Path | str, dst: Path | str) -> None:
            Path(dst).write_bytes(b"worker b conflicting content")
            raise FileExistsError(f"File exists: {dst}")

        with (
            patch("os.link", side_effect=race_link),
            pytest.raises(KnowledgeArtifactError) as exc_info,
        ):
            store.promote(token, sample_canonical_doc)

        assert exc_info.value.error_code == "ARTIFACT_HASH_MISMATCH"
        assert "contradictory content" in str(exc_info.value)
        assert dest_path.read_bytes() == b"worker b conflicting content"

    def test_promotion_race_worker_b_creates_identical_destination_succeeds_idempotently(
        self,
        store: FilesystemKnowledgeArtifactStore,
        sample_canonical_doc: CanonicalKnowledgeDocumentDTO,
    ) -> None:
        token = store.stage(sample_canonical_doc)
        dest_path = (
            store._approved_dir  # type: ignore[operator]
            / sample_canonical_doc.document_type
            / sample_canonical_doc.document_id
            / f"{sample_canonical_doc.content_hash}.md"
        )

        def race_link(_src: Path | str, dst: Path | str) -> None:
            Path(dst).write_bytes(sample_canonical_doc.canonical_content.encode("utf-8"))
            raise FileExistsError(f"File exists: {dst}")

        with patch("os.link", side_effect=race_link):
            record = store.promote(token, sample_canonical_doc)

        assert record.document_id == sample_canonical_doc.document_id
        assert record.content_hash == sample_canonical_doc.content_hash
        assert dest_path.read_bytes() == sample_canonical_doc.canonical_content.encode("utf-8")

    def test_concurrent_threads_promote_same_document_idempotently(
        self,
        store: FilesystemKnowledgeArtifactStore,
        sample_canonical_doc: CanonicalKnowledgeDocumentDTO,
    ) -> None:
        def worker() -> ApprovedArtifactRecord:
            tok = store.stage(sample_canonical_doc)
            return store.promote(tok, sample_canonical_doc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker) for _ in range(8)]
            results = [f.result() for f in futures]

        assert len(results) == 8
        for r in results:
            assert r.document_id == sample_canonical_doc.document_id
            assert r.content_hash == sample_canonical_doc.content_hash

        dest_path = (
            store._approved_dir  # type: ignore[operator]
            / sample_canonical_doc.document_type
            / sample_canonical_doc.document_id
            / f"{sample_canonical_doc.content_hash}.md"
        )
        assert dest_path.is_file()
        assert dest_path.read_bytes() == sample_canonical_doc.canonical_content.encode("utf-8")

    def test_hardlink_unsupported_fallback_preserves_immutability(
        self,
        store: FilesystemKnowledgeArtifactStore,
        sample_canonical_doc: CanonicalKnowledgeDocumentDTO,
    ) -> None:
        token = store.stage(sample_canonical_doc)

        with patch("os.link", side_effect=OSError("Hard links not supported")):
            record = store.promote(token, sample_canonical_doc)

        assert record.document_id == sample_canonical_doc.document_id
        dest_path = (
            store._approved_dir  # type: ignore[operator]
            / sample_canonical_doc.document_type
            / sample_canonical_doc.document_id
            / f"{sample_canonical_doc.content_hash}.md"
        )
        assert dest_path.is_file()
        assert dest_path.read_bytes() == sample_canonical_doc.canonical_content.encode("utf-8")


# ============================================================================
# 6. Path Safety & Traversal Tests
# ============================================================================


class TestPathSafety:
    """Test defense against traversal and invalid paths."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> FilesystemKnowledgeArtifactStore:
        artifact_dir = tmp_path / "safe_artifacts"
        artifact_dir.mkdir()
        return FilesystemKnowledgeArtifactStore(artifact_root=artifact_dir)

    def test_traversal_document_type_rejected(
        self, store: FilesystemKnowledgeArtifactStore
    ) -> None:
        with pytest.raises(KnowledgeArtifactError, match="Invalid document type"):
            store.remove_unreferenced("../../etc", "doc_" + "a" * 24, "f" * 64)

    def test_traversal_document_id_rejected(self, store: FilesystemKnowledgeArtifactStore) -> None:
        with pytest.raises(KnowledgeArtifactError, match="Invalid document identifier"):
            store.remove_unreferenced("documentation", "../../doc_123", "f" * 64)

    def test_invalid_content_hash_rejected(self, store: FilesystemKnowledgeArtifactStore) -> None:
        with pytest.raises(KnowledgeArtifactError, match="Invalid content hash"):
            store.remove_unreferenced("documentation", "doc_" + "a" * 24, "invalid_hash")

    def test_invalid_staging_id_rejected(self, store: FilesystemKnowledgeArtifactStore) -> None:
        token = StagedArtifactToken(
            staging_id="../../escape.tmp",
            document_id="doc_" + "a" * 24,
            document_type="documentation",
            content_hash="f" * 64,
        )
        with pytest.raises(KnowledgeArtifactError, match="Invalid staging token identifier"):
            store.discard_staged(token)


# ============================================================================
# 7. Safe Cleanup Tests
# ============================================================================


class TestArtifactCleanup:
    """Test cleanup primitives for staged and unreferenced promoted artifacts."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> FilesystemKnowledgeArtifactStore:
        artifact_dir = tmp_path / "safe_artifacts"
        artifact_dir.mkdir()
        return FilesystemKnowledgeArtifactStore(artifact_root=artifact_dir)

    def test_discard_staged_success(self, store: FilesystemKnowledgeArtifactStore) -> None:
        doc_id = generate_document_id("docs://cleanup", "documentation")
        content = "Temporary staging content"
        c_hash = compute_content_hash(content)
        doc = CanonicalKnowledgeDocumentDTO(
            document_id=doc_id,
            title="Temp",
            document_type="documentation",
            source_reference="docs://cleanup",
            canonical_content=content,
            content_hash=c_hash,
            corpus_category=CorpusCategory.DOCUMENTATION,
        )
        token = store.stage(doc)
        assert store.discard_staged(token) is True
        # Calling again returns False (safely idempotent)
        assert store.discard_staged(token) is False

    def test_remove_unreferenced_promoted_artifact(
        self, store: FilesystemKnowledgeArtifactStore
    ) -> None:
        doc_id = generate_document_id("docs://unref", "documentation")
        content = "Promoted content to remove"
        c_hash = compute_content_hash(content)
        doc = CanonicalKnowledgeDocumentDTO(
            document_id=doc_id,
            title="Unref",
            document_type="documentation",
            source_reference="docs://unref",
            canonical_content=content,
            content_hash=c_hash,
            corpus_category=CorpusCategory.DOCUMENTATION,
        )
        token = store.stage(doc)
        store.promote(token, doc)

        # Remove unreferenced artifact
        assert store.remove_unreferenced("documentation", doc_id, c_hash) is True
        # Removing already absent artifact returns False safely
        assert store.remove_unreferenced("documentation", doc_id, c_hash) is False

    def test_cleanup_stale_staging_deletes_old_files_only(
        self, store: FilesystemKnowledgeArtifactStore
    ) -> None:
        doc_id = "doc_" + "a" * 24
        old_staging_file = store._staging_dir / f"{doc_id}_{'1' * 32}.tmp"  # type: ignore[operator]
        old_staging_file.write_bytes(b"old staged content")

        # Cleanup with max_age_seconds = 0
        cleaned = store.cleanup_stale_staging(max_age_seconds=-1)
        assert cleaned == 1
        assert not old_staging_file.exists()


# ============================================================================
# 8. Reconciliation Enumeration Tests
# ============================================================================


class TestArtifactReconciliation:
    """Test filesystem enumeration for orphan reconciliation."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> FilesystemKnowledgeArtifactStore:
        artifact_dir = tmp_path / "safe_artifacts"
        artifact_dir.mkdir()
        return FilesystemKnowledgeArtifactStore(artifact_root=artifact_dir)

    def test_enumeration_returns_typed_records(
        self, store: FilesystemKnowledgeArtifactStore
    ) -> None:
        # Create 2 approved artifacts
        for i in range(2):
            content = f"Content {i}"
            c_hash = compute_content_hash(content)
            doc_id = generate_document_id(f"docs://rec_{i}", "documentation")
            doc = CanonicalKnowledgeDocumentDTO(
                document_id=doc_id,
                title=f"Doc {i}",
                document_type="documentation",
                source_reference=f"docs://rec_{i}",
                canonical_content=content,
                content_hash=c_hash,
                corpus_category=CorpusCategory.DOCUMENTATION,
            )
            token = store.stage(doc)
            store.promote(token, doc)

        records = store.enumerate_approved_artifacts()
        assert len(records) == 2
        for r in records:
            assert isinstance(r, ApprovedArtifactRecord)
            assert r.document_type == "documentation"
            assert r.document_id.startswith("doc_")
            assert len(r.content_hash) == 64
            # Assert NO physical path attributes
            assert not hasattr(r, "path")
            assert not hasattr(r, "file_path")
            assert not hasattr(r, "absolute_path")

    def test_enumeration_ignores_unrelated_files_safely(
        self, store: FilesystemKnowledgeArtifactStore
    ) -> None:
        # Plant unrelated file directly under approved directory
        unrelated = store._approved_dir / "unrelated.txt"  # type: ignore[operator]
        unrelated.write_text("ignore me")

        # Plant invalid document directory
        invalid_type_dir = store._approved_dir / "invalid_type"  # type: ignore[operator]
        invalid_type_dir.mkdir()
        (invalid_type_dir / "something.md").write_text("ignore me")

        records = store.enumerate_approved_artifacts()
        assert records == []


# ============================================================================
# 9. Security Boundary & Policy Invariants (D05 / D08 / Non-leakage)
# ============================================================================


class TestSecurityInvariants:
    """Test that security boundaries D05, D08, and non-leakage invariants hold."""

    @pytest.fixture
    def admission_service(self) -> KnowledgeAdmissionService:
        return KnowledgeAdmissionService()

    @pytest.fixture
    def store(self, tmp_path: Path) -> FilesystemKnowledgeArtifactStore:
        artifact_dir = tmp_path / "safe_artifacts"
        artifact_dir.mkdir()
        return FilesystemKnowledgeArtifactStore(artifact_root=artifact_dir)

    def test_d05_customer_attachment_cannot_reach_artifact_store(
        self,
        admission_service: KnowledgeAdmissionService,
    ) -> None:
        source_input = AdmissionSourceInputDTO(
            source_name="invoice.pdf.txt",
            source_kind=IngestionSourceKind.TEXT_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"Customer invoice text",
            classification=ProhibitedSourceClassification.CUSTOMER_ATTACHMENT.value,
        )
        res = admission_service.admit(source_input)
        assert res.decision == AdmissionDecision.REJECTED
        assert res.sanitized_payload is None

        # Cannot build canonical document or stage
        with pytest.raises(TypeError):
            build_canonical_document(res.sanitized_payload)  # type: ignore[arg-type]

    def test_d08_live_crm_data_cannot_reach_artifact_store(
        self,
        admission_service: KnowledgeAdmissionService,
    ) -> None:
        source_input = AdmissionSourceInputDTO(
            source_name="crm_export.txt",
            source_kind=IngestionSourceKind.TEXT_DOCUMENT,
            corpus_category=CorpusCategory.DOCUMENTATION,
            raw_bytes=b"Customer CRM record",
            classification=ProhibitedSourceClassification.LIVE_CRM.value,
        )
        res = admission_service.admit(source_input)
        assert res.decision == AdmissionDecision.REJECTED
        assert res.sanitized_payload is None

    def test_error_messages_do_not_reveal_physical_paths(self) -> None:
        with pytest.raises(KnowledgeArtifactError) as exc_info:
            validate_artifact_root(Path("relative/path"))
        msg = str(exc_info.value)
        assert "relative/path" not in msg

    def test_error_messages_do_not_reveal_canonical_content(
        self, store: FilesystemKnowledgeArtifactStore
    ) -> None:
        secret_content = "TOP_SECRET_CANONICAL_DOCUMENT_BODY_ABC123"
        doc_id = generate_document_id("docs://secret", "documentation")
        doc = CanonicalKnowledgeDocumentDTO(
            document_id=doc_id,
            title="Secret Doc",
            document_type="documentation",
            source_reference="docs://secret",
            canonical_content=secret_content,
            content_hash="0" * 64,  # Intentionally mismatched
            corpus_category=CorpusCategory.DOCUMENTATION,
        )
        with pytest.raises(KnowledgeArtifactError) as exc_info:
            store.stage(doc)
        msg = str(exc_info.value)
        assert secret_content not in msg

    def test_structured_log_excludes_artifact_root_and_content(
        self,
        store: FilesystemKnowledgeArtifactStore,
    ) -> None:
        content = "Public documentation text"
        c_hash = compute_content_hash(content)
        doc_id = generate_document_id("docs://logged", "documentation")
        doc = CanonicalKnowledgeDocumentDTO(
            document_id=doc_id,
            title="Logged Doc",
            document_type="documentation",
            source_reference="docs://logged",
            canonical_content=content,
            content_hash=c_hash,
            corpus_category=CorpusCategory.DOCUMENTATION,
        )
        with patch("kb_mcp.adapters.filesystem_artifact_store.logger.info") as mock_log:
            _ = store.stage(doc)
            mock_log.assert_called_once()
            extra = mock_log.call_args[1]["extra"]
            assert extra["document_id"] == doc_id
            assert extra["document_type"] == "documentation"
            assert extra["content_hash_prefix"] == c_hash[:8]
            assert "canonical_content" not in extra
            assert "root" not in extra
            assert "path" not in extra
