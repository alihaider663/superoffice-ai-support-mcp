"""Synthetic local sample Knowledge corpus definitions for development and E2E testing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class SampleDocument:
    """Synthetic sample document definition."""

    document_id: str
    title: str
    document_type: str
    source_reference: str
    canonical_content: str
    content_hash: str
    version: int = 1


@dataclass(frozen=True)
class SampleChunk:
    """Synthetic sample chunk definition."""

    chunk_id: str
    document_id: str
    chunk_index: int
    content: str


@dataclass(frozen=True)
class SampleRunbook:
    """Synthetic sample runbook definition."""

    runbook_id: str
    title: str
    problem_description: str
    diagnostic_steps: tuple[str, ...]
    remediation_steps: tuple[str, ...]
    product: str | None
    verified_version: str | None
    source_reference: str


@dataclass(frozen=True)
class SampleKnownIssue:
    """Synthetic sample known issue definition."""

    issue_id: str
    title: str
    symptom_summary: str
    root_cause_summary: str
    workaround: str | None
    permanent_fix_reference: str | None
    affected_products: tuple[str, ...]
    affected_versions: tuple[str, ...]
    category: str
    source_reference: str


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 lowercase hexadecimal hash of canonical content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest().lower()


# ============================================================================
# Document 1: PostgreSQL Connection Timeout Troubleshooting
# ============================================================================
DOC_1_CHUNK_0 = (
    "Applications encounter PostgreSQL connection timeouts when unable to establish a "
    "database session within the configured connection timeout period. Key symptoms "
    "include connection attempt timeouts, pool exhaustion errors, and latency spikes "
    "during connection checkout. Diagnostic steps include verifying database host "
    "reachability and network latency, confirming the PostgreSQL service is active and "
    "accepting connections on port 5432, checking current connection counts against the "
    "max_connections setting in pg_stat_activity, and evaluating whether idle or orphaned "
    "client sessions are consuming available connection slots."
)
DOC_1_CHUNK_1 = (
    "To remediate and prevent PostgreSQL connection timeouts, correct misconfigured "
    "database host, port, or pool endpoint parameters. If the PostgreSQL service is "
    "unresponsive, restore service availability and verify listener configuration. When "
    "application connection pools are exhausted, safely recycle the affected pool and "
    "resolve underlying connection leaks before considering limit increases. Terminate "
    "idle-in-transaction sessions that hold locks. Ensure application connection pools "
    "configure appropriate checkout timeouts, idle connection pruning, and connection "
    "validation to maintain pool health."
)
DOC_1_CANONICAL = f"{DOC_1_CHUNK_0}\n\n{DOC_1_CHUNK_1}"

SAMPLE_DOC_1 = SampleDocument(
    document_id="sample-doc-postgres-timeout",
    title="PostgreSQL Connection Timeout Troubleshooting",
    document_type="troubleshooting",
    source_reference="sample://knowledge/postgresql-connection-timeout",
    canonical_content=DOC_1_CANONICAL,
    content_hash=compute_content_hash(DOC_1_CANONICAL),
    version=1,
)

SAMPLE_CHUNKS_DOC_1 = (
    SampleChunk(
        chunk_id="sample-chunk-postgres-timeout-01",
        document_id="sample-doc-postgres-timeout",
        chunk_index=0,
        content=DOC_1_CHUNK_0,
    ),
    SampleChunk(
        chunk_id="sample-chunk-postgres-timeout-02",
        document_id="sample-doc-postgres-timeout",
        chunk_index=1,
        content=DOC_1_CHUNK_1,
    ),
)


# ============================================================================
# Document 2: API JWT Authentication Failure Troubleshooting
# ============================================================================
DOC_2_CHUNK_0 = (
    "REST API requests fail with HTTP 401 Unauthorized when JSON Web Token (JWT) "
    "authentication cannot be verified. Common symptoms include rejected API calls, token "
    "invalidation responses, and missing authorization credentials. Diagnostic checks "
    "involve inspecting the request for a valid Authorization Bearer header, checking "
    "token expiration timestamps (exp claim) against current system time, verifying that "
    "the issuer (iss) and audience (aud) claims match expected API configurations, "
    "confirming that the token signing algorithm and public key match the issuing "
    "authority, and verifying system clock synchronization (NTP) to prevent clock-skew "
    "errors."
)
DOC_2_CHUNK_1 = (
    "Remediation of API JWT authentication failures requires obtaining a fresh access "
    "token from the authentication service using valid refresh credentials or client "
    "credentials flow. Ensure API service configuration contains the correct token issuer, "
    "audience, and trusted signing certificates. Synchronize server system clocks if clock "
    "skew causes premature token rejection. Implement client-side proactive token refresh "
    "before expiration. Diagnostic logging must never record raw token contents, "
    "signatures, or secret keys to prevent credential leakage."
)
DOC_2_CANONICAL = f"{DOC_2_CHUNK_0}\n\n{DOC_2_CHUNK_1}"

SAMPLE_DOC_2 = SampleDocument(
    document_id="sample-doc-api-auth-failure",
    title="API JWT Authentication Failure Troubleshooting",
    document_type="troubleshooting",
    source_reference="sample://knowledge/api-authentication-failure",
    canonical_content=DOC_2_CANONICAL,
    content_hash=compute_content_hash(DOC_2_CANONICAL),
    version=1,
)

SAMPLE_CHUNKS_DOC_2 = (
    SampleChunk(
        chunk_id="sample-chunk-api-auth-01",
        document_id="sample-doc-api-auth-failure",
        chunk_index=0,
        content=DOC_2_CHUNK_0,
    ),
    SampleChunk(
        chunk_id="sample-chunk-api-auth-02",
        document_id="sample-doc-api-auth-failure",
        chunk_index=1,
        content=DOC_2_CHUNK_1,
    ),
)


# ============================================================================
# Document 3: IIS Application Pool Unavailable Troubleshooting
# ============================================================================
DOC_3_CHUNK_0 = (
    "An IIS application becomes unavailable and returns HTTP 503 Service Unavailable when "
    "its IIS application pool is stopped or its worker process crashes repeatedly. "
    "Diagnostic checks require inspecting the IIS Manager to check the state of the "
    "application pool, reviewing Windows Application and System event logs for worker "
    "process (w3wp.exe) termination errors, verifying whether Rapid-Fail Protection has "
    "disabled the pool due to multiple crashes within the failure interval, checking "
    "application pool identity permissions, and inspecting web.config for malformed XML or "
    "invalid module configurations."
)
DOC_3_CHUNK_1 = (
    "To recover an unavailable IIS application pool, resolve the underlying worker process "
    "crash or configuration failure identified in the event logs. Reset Rapid-Fail "
    "Protection status if the pool was automatically stopped, then safely restart the "
    "application pool. Confirm that the application pool identity has adequate access "
    "rights to application directories and temporary folders. Verify application startup "
    "by issuing a test HTTP request. Monitor worker process stability and memory "
    "utilization to ensure the recycle loop is resolved before resuming normal operations."
)
DOC_3_CANONICAL = f"{DOC_3_CHUNK_0}\n\n{DOC_3_CHUNK_1}"

SAMPLE_DOC_3 = SampleDocument(
    document_id="sample-doc-iis-app-pool",
    title="IIS Application Pool Unavailable Troubleshooting",
    document_type="troubleshooting",
    source_reference="sample://knowledge/iis-application-pool-unavailable",
    canonical_content=DOC_3_CANONICAL,
    content_hash=compute_content_hash(DOC_3_CANONICAL),
    version=1,
)

SAMPLE_CHUNKS_DOC_3 = (
    SampleChunk(
        chunk_id="sample-chunk-iis-pool-01",
        document_id="sample-doc-iis-app-pool",
        chunk_index=0,
        content=DOC_3_CHUNK_0,
    ),
    SampleChunk(
        chunk_id="sample-chunk-iis-pool-02",
        document_id="sample-doc-iis-app-pool",
        chunk_index=1,
        content=DOC_3_CHUNK_1,
    ),
)


# ============================================================================
# Runbooks
# ============================================================================
SAMPLE_RUNBOOK_1 = SampleRunbook(
    runbook_id="sample-rb-postgres-timeout",
    title="Resolve PostgreSQL Connection Timeouts",
    problem_description=(
        "Synthetic technical description of an application being unable to obtain a "
        "PostgreSQL connection within the configured timeout."
    ),
    diagnostic_steps=(
        "1. Verify PostgreSQL service availability on the database host.",
        "2. Verify network reachability for the configured host and port.",
        "3. Validate the configured database connection endpoint parameters.",
        "4. Review active PostgreSQL connection count against the max_connections limit.",
        "5. Review application connection-pool utilization and waiting request queues.",
        "6. Check for long-running transactions, blocked queries, or leaked idle sessions.",
    ),
    remediation_steps=(
        "1. Correct any invalid database host, port, or pool endpoint configuration.",
        "2. Restore PostgreSQL service availability if the service is stopped or restarting.",
        "3. Release or recycle an exhausted application connection pool safely.",
        "4. Terminate orphaned or leaked backend sessions before considering limit increases.",
        "5. Re-test application connectivity using a dedicated health probe.",
        "6. Monitor connection usage and pool metrics post-recovery.",
    ),
    product="PostgreSQL",
    verified_version="16",
    source_reference="sample://knowledge/postgresql-connection-timeout",
)

SAMPLE_RUNBOOK_2 = SampleRunbook(
    runbook_id="sample-rb-api-auth-failure",
    title="Resolve API JWT Authentication Failures",
    problem_description=(
        "Synthetic description of REST API requests failing with HTTP 401 Unauthorized "
        "because JWT validation cannot be completed successfully."
    ),
    diagnostic_steps=(
        "1. Verify the presence and format of the Authorization Bearer header in "
        "incoming requests.",
        "2. Verify token expiration timestamp (exp claim) to confirm token validity.",
        "3. Validate the token issuer (iss) and audience (aud) claims against expected values.",
        "4. Verify the signing key configuration on both the authentication issuer "
        "and API validator.",
        "5. Inspect authentication service diagnostic logs without logging sensitive "
        "token signatures.",
        "6. Check system clock synchronization (NTP) to eliminate clock-skew issues.",
    ),
    remediation_steps=(
        "1. Direct the client application to obtain a new token using valid refresh credentials.",
        "2. Correct mismatching issuer or audience configuration in API service settings.",
        "3. Update or re-synchronize trusted JWT signing keys across verifying services.",
        "4. Synchronize server system clocks if clock skew exceeds the acceptable tolerance.",
        "5. Re-test API authentication with a newly minted, valid JWT.",
        "6. Ensure sensitive raw token values and signing secrets are never logged.",
    ),
    product="REST API",
    verified_version="generic",
    source_reference="sample://knowledge/api-authentication-failure",
)

SAMPLE_RUNBOOK_3 = SampleRunbook(
    runbook_id="sample-rb-iis-app-pool",
    title="Recover an Unavailable IIS Application Pool",
    problem_description=(
        "Synthetic description of an application becoming unavailable because its "
        "IIS application pool is stopped or its worker process repeatedly fails."
    ),
    diagnostic_steps=(
        "1. Verify the current operational state of the IIS application pool in IIS Manager.",
        "2. Inspect Windows Application event logs for worker process (w3wp.exe) crash events.",
        "3. Check whether Rapid-Fail Protection has automatically stopped the application pool.",
        "4. Confirm worker process identity credentials and required filesystem permissions.",
        "5. Validate web.config syntax and application initialization modules.",
        "6. Identify recurring crash or recycling patterns from recent service events.",
    ),
    remediation_steps=(
        "1. Resolve the underlying configuration error or missing dependency identified in logs.",
        "2. Reset Rapid-Fail Protection state and safely start the affected application pool.",
        "3. Send a test HTTP request to verify application initialization and HTTP 200 response.",
        "4. Monitor the newly spawned worker process for stability and memory growth.",
        "5. Investigate root causes of repeated recycling before applying further manual restarts.",
    ),
    product="IIS",
    verified_version="generic",
    source_reference="sample://knowledge/iis-application-pool-unavailable",
)


# ============================================================================
# Known Issues
# ============================================================================
SAMPLE_KNOWN_ISSUE_1 = SampleKnownIssue(
    issue_id="sample-ki-db-pool-exhaustion",
    title="Database Connection Pool Exhaustion Causes Request Timeouts",
    symptom_summary=(
        "Synthetic description of application requests timing out because all pooled "
        "database connections are in use."
    ),
    root_cause_summary=(
        "Connection leak, long-held database sessions, or pool sizing inconsistent with workload."
    ),
    workaround=(
        "Safely recycle the affected application connection pool only after capturing "
        "diagnostic evidence and verifying database health."
    ),
    permanent_fix_reference="sample://knowledge/postgresql-connection-timeout",
    affected_products=("PostgreSQL", "Application Runtime"),
    affected_versions=("generic",),
    category="database",
    source_reference="sample://knowledge/postgresql-connection-timeout",
)

SAMPLE_KNOWN_ISSUE_2 = SampleKnownIssue(
    issue_id="sample-ki-jwt-expiration",
    title="JWT Token Expiration Causes API 401 Responses",
    symptom_summary=(
        "Synthetic description of API requests receiving HTTP 401 after an access token "
        "has expired."
    ),
    root_cause_summary=(
        "The caller continues using an expired JWT or token refresh is not occurring correctly."
    ),
    workaround="Obtain a newly issued valid token and retry the request.",
    permanent_fix_reference="sample://knowledge/api-authentication-failure",
    affected_products=("REST API", "Authentication"),
    affected_versions=("generic",),
    category="authentication",
    source_reference="sample://knowledge/api-authentication-failure",
)

SAMPLE_KNOWN_ISSUE_3 = SampleKnownIssue(
    issue_id="sample-ki-iis-recycle-loop",
    title="IIS Worker Process Recycle Loop Causes Application Unavailability",
    symptom_summary=(
        "Synthetic description of intermittent or sustained HTTP unavailability while an "
        "IIS worker process repeatedly terminates and restarts."
    ),
    root_cause_summary=(
        "Application startup failure, configuration problem, resource pressure, or "
        "rapid-fail protection condition."
    ),
    workaround=(
        "Capture diagnostic evidence, resolve the immediate startup condition, then "
        "safely restart the affected application pool."
    ),
    permanent_fix_reference="sample://knowledge/iis-application-pool-unavailable",
    affected_products=("IIS",),
    affected_versions=("generic",),
    category="application",
    source_reference="sample://knowledge/iis-application-pool-unavailable",
)


# ============================================================================
# Corpus Accessors
# ============================================================================
def get_sample_documents() -> tuple[SampleDocument, ...]:
    """Return all approved synthetic sample documents."""
    return (SAMPLE_DOC_1, SAMPLE_DOC_2, SAMPLE_DOC_3)


def get_sample_chunks() -> tuple[SampleChunk, ...]:
    """Return all approved synthetic sample chunks (exactly 6)."""
    return (
        *SAMPLE_CHUNKS_DOC_1,
        *SAMPLE_CHUNKS_DOC_2,
        *SAMPLE_CHUNKS_DOC_3,
    )


def get_sample_runbooks() -> tuple[SampleRunbook, ...]:
    """Return all approved synthetic sample runbooks."""
    return (SAMPLE_RUNBOOK_1, SAMPLE_RUNBOOK_2, SAMPLE_RUNBOOK_3)


def get_sample_known_issues() -> tuple[SampleKnownIssue, ...]:
    """Return all approved synthetic sample known issues."""
    return (SAMPLE_KNOWN_ISSUE_1, SAMPLE_KNOWN_ISSUE_2, SAMPLE_KNOWN_ISSUE_3)
