"""Canonical schema definitions for Gateway-exposed platform tools."""

# ruff: noqa: E501
from mcp.types import Tool

INVESTIGATE_INCIDENT_INPUT_SCHEMA = {
    "$defs": {
        "DeadlockInvestigationInputDTO": {
            "additionalProperties": False,
            "description": "Public criteria for database deadlock analysis.",
            "properties": {
                "start_time": {
                    "anyOf": [{"format": "date-time", "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Start of observation time window with explicit offset (e.g. '...Z')",
                    "title": "Start Time",
                },
                "end_time": {
                    "anyOf": [{"format": "date-time", "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "End of observation time window with explicit offset (e.g. '...Z')",
                    "title": "End Time",
                },
                "limit": {
                    "anyOf": [{"maximum": 50, "minimum": 1, "type": "integer"}, {"type": "null"}],
                    "default": 10,
                    "description": "Maximum deadlock events to return (1..50, default 10)",
                    "title": "Limit",
                },
            },
            "title": "DeadlockInvestigationInputDTO",
            "type": "object",
        },
        "InvestigationDiagnosticsInputDTO": {
            "additionalProperties": False,
            "description": "Public opt-in selection for database diagnostic checks.",
            "properties": {
                "include_database_health": {
                    "default": False,
                    "description": "Explicit opt-in to execute database health check",
                    "title": "Include Database Health",
                    "type": "boolean",
                },
                "deadlocks": {
                    "anyOf": [{"$ref": "#/$defs/DeadlockInvestigationInputDTO"}, {"type": "null"}],
                    "default": None,
                    "description": "Explicit opt-in criteria to search recent database deadlocks",
                },
                "slow_queries": {
                    "anyOf": [{"$ref": "#/$defs/SlowQueryInvestigationInputDTO"}, {"type": "null"}],
                    "default": None,
                    "description": "Explicit opt-in criteria to search slow executing database queries",
                },
                "include_ticket_diagnostic": {
                    "default": False,
                    "description": "Explicit opt-in to inspect ticket database diagnostic record (y_logticket)",
                    "title": "Include Ticket Diagnostic",
                    "type": "boolean",
                },
                "include_blocking_sessions": {
                    "default": False,
                    "description": "Explicit opt-in to inspect active blocking sessions snapshot",
                    "title": "Include Blocking Sessions",
                    "type": "boolean",
                },
            },
            "title": "InvestigationDiagnosticsInputDTO",
            "type": "object",
        },
        "InvestigationKnowledgeInputDTO": {
            "additionalProperties": False,
            "description": "Public criteria for Knowledge Base search.",
            "properties": {
                "include_knowledge_search": {
                    "default": True,
                    "description": "Whether to search knowledge base for matching known issues and runbooks",
                    "title": "Include Knowledge Search",
                    "type": "boolean",
                },
                "query_override": {
                    "anyOf": [{"maxLength": 256, "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Optional custom query for knowledge search (defaults to hypothesis/ticket)",
                    "title": "Query Override",
                },
                "limit": {
                    "default": 5,
                    "description": "Maximum knowledge items to retrieve",
                    "maximum": 20,
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            "title": "InvestigationKnowledgeInputDTO",
            "type": "object",
        },
        "InvestigationLogsInputDTO": {
            "additionalProperties": False,
            "description": "Public criteria for Application Logs search.",
            "properties": {
                "include_logs": {
                    "default": False,
                    "description": "Explicit opt-in to search application logs",
                    "title": "Include Logs",
                    "type": "boolean",
                },
                "query": {
                    "anyOf": [{"maxLength": 256, "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Query text for log search",
                    "title": "Query",
                },
                "limit": {
                    "default": 20,
                    "description": "Maximum log excerpts to retrieve",
                    "maximum": 50,
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            "title": "InvestigationLogsInputDTO",
            "type": "object",
        },
        "InvestigationSuperOfficeInputDTO": {
            "additionalProperties": False,
            "description": "Public criteria for SuperOffice CRM evidence collection.",
            "properties": {
                "include_audit_trail": {
                    "default": False,
                    "description": "Explicit opt-in to retrieve ticket change history and audit trail",
                    "title": "Include Audit Trail",
                    "type": "boolean",
                },
                "audit_trail_limit": {
                    "default": 20,
                    "description": "Maximum audit trail events to retrieve",
                    "maximum": 100,
                    "minimum": 1,
                    "title": "Audit Trail Limit",
                    "type": "integer",
                },
            },
            "title": "InvestigationSuperOfficeInputDTO",
            "type": "object",
        },
        "SlowQueryInvestigationInputDTO": {
            "additionalProperties": False,
            "description": "Public criteria for database slow query analysis.",
            "properties": {
                "start_time": {
                    "anyOf": [{"format": "date-time", "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Start of observation time window with explicit offset (e.g. '...Z')",
                    "title": "Start Time",
                },
                "end_time": {
                    "anyOf": [{"format": "date-time", "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "End of observation time window with explicit offset (e.g. '...Z')",
                    "title": "End Time",
                },
                "min_duration_ms": {
                    "default": 1000,
                    "description": "Minimum execution duration threshold in milliseconds (default 1000ms)",
                    "minimum": 1,
                    "title": "Min Duration Ms",
                    "type": "integer",
                },
                "limit": {
                    "anyOf": [{"maximum": 50, "minimum": 1, "type": "integer"}, {"type": "null"}],
                    "default": 10,
                    "description": "Maximum slow queries to return (1..50, default 10)",
                    "title": "Limit",
                },
            },
            "title": "SlowQueryInvestigationInputDTO",
            "type": "object",
        },
    },
    "additionalProperties": False,
    "description": "Public MCP input contract for cross-domain incident investigation.",
    "properties": {
        "initial_hypothesis": {
            "description": "Explicit incident hypothesis to investigate",
            "maxLength": 256,
            "minLength": 1,
            "title": "Initial Hypothesis",
            "type": "string",
        },
        "ticket_id": {
            "anyOf": [{"minimum": 1, "type": "integer"}, {"type": "null"}],
            "default": None,
            "description": "Optional SuperOffice ticket ID to collect CRM ticket context",
            "title": "Ticket Id",
        },
        "superoffice": {
            "anyOf": [{"$ref": "#/$defs/InvestigationSuperOfficeInputDTO"}, {"type": "null"}],
            "default": None,
            "description": "Optional SuperOffice CRM collection criteria (e.g. audit trail)",
        },
        "diagnostics": {
            "anyOf": [{"$ref": "#/$defs/InvestigationDiagnosticsInputDTO"}, {"type": "null"}],
            "default": None,
            "description": "Optional database diagnostic checks to execute",
        },
        "knowledge": {
            "anyOf": [{"$ref": "#/$defs/InvestigationKnowledgeInputDTO"}, {"type": "null"}],
            "default": None,
            "description": "Optional knowledge base search options",
        },
        "logs": {
            "anyOf": [{"$ref": "#/$defs/InvestigationLogsInputDTO"}, {"type": "null"}],
            "default": None,
            "description": "Optional application logs search options",
        },
    },
    "required": ["initial_hypothesis"],
    "title": "InvestigateIncidentRequestDTO",
    "type": "object",
}

INVESTIGATE_INCIDENT_OUTPUT_SCHEMA = {
    "$defs": {
        "BlockingSessionObservationDTO": {
            "additionalProperties": False,
            "description": "MSSQL active blocking session observation.",
            "properties": {
                "observation_type": {
                    "const": "blocking_session",
                    "default": "blocking_session",
                    "title": "Observation Type",
                    "type": "string",
                },
                "blocking_session_id": {
                    "description": "Head blocking session ID",
                    "title": "Blocking Session Id",
                    "type": "integer",
                },
                "blocked_session_id": {
                    "description": "Blocked session ID",
                    "title": "Blocked Session Id",
                    "type": "integer",
                },
                "wait_duration_ms": {
                    "description": "Wait duration in milliseconds",
                    "title": "Wait Duration Ms",
                    "type": "integer",
                },
                "wait_type": {
                    "default": "",
                    "description": "MSSQL wait resource/type",
                    "title": "Wait Type",
                    "type": "string",
                },
            },
            "required": ["blocking_session_id", "blocked_session_id", "wait_duration_ms"],
            "title": "BlockingSessionObservationDTO",
            "type": "object",
        },
        "DatabaseHealthObservationDTO": {
            "additionalProperties": False,
            "description": "MSSQL database cluster health observation.",
            "properties": {
                "observation_type": {
                    "const": "database_health",
                    "default": "database_health",
                    "title": "Observation Type",
                    "type": "string",
                },
                "is_healthy": {
                    "description": "Whether database is responsive and healthy",
                    "title": "Is Healthy",
                    "type": "boolean",
                },
                "active_connections": {
                    "description": "Current active connection count",
                    "title": "Active Connections",
                    "type": "integer",
                },
                "latency_ms": {
                    "description": "Database probe latency in milliseconds",
                    "title": "Latency Ms",
                    "type": "number",
                },
            },
            "required": ["is_healthy", "active_connections", "latency_ms"],
            "title": "DatabaseHealthObservationDTO",
            "type": "object",
        },
        "DeadlockObservationDTO": {
            "additionalProperties": False,
            "description": "MSSQL database deadlock observation.",
            "properties": {
                "observation_type": {
                    "const": "deadlock",
                    "default": "deadlock",
                    "title": "Observation Type",
                    "type": "string",
                },
                "deadlock_id": {
                    "description": "Deterministic deadlock event identifier",
                    "title": "Deadlock Id",
                    "type": "string",
                },
                "victim_session_id": {
                    "description": "Session ID chosen as deadlock victim",
                    "title": "Victim Session Id",
                    "type": "integer",
                },
                "participating_session_count": {
                    "description": "Number of sessions participating in deadlock",
                    "title": "Participating Session Count",
                    "type": "integer",
                },
            },
            "required": ["deadlock_id", "victim_session_id", "participating_session_count"],
            "title": "DeadlockObservationDTO",
            "type": "object",
        },
        "DiagnosticEvidenceWireDTO": {
            "additionalProperties": False,
            "description": "Public representation of an observed diagnostic finding.",
            "properties": {
                "source": {
                    "description": "Originating domain source",
                    "enum": [
                        "superoffice_crm",
                        "mssql_diagnostics",
                        "application_logs",
                        "knowledge_base",
                    ],
                    "title": "Source",
                    "type": "string",
                },
                "timestamp": {
                    "description": "Observation timestamp in UTC (ISO 8601)",
                    "format": "date-time",
                    "title": "Timestamp",
                    "type": "string",
                },
                "data": {
                    "description": "Structured observation payload conforming to observation_type",
                    "discriminator": {
                        "mapping": {
                            "blocking_session": "#/$defs/BlockingSessionObservationDTO",
                            "database_health": "#/$defs/DatabaseHealthObservationDTO",
                            "deadlock": "#/$defs/DeadlockObservationDTO",
                            "knowledge_article": "#/$defs/KnowledgeArticleObservationDTO",
                            "known_issue": "#/$defs/KnownIssueObservationDTO",
                            "log_excerpt": "#/$defs/LogExcerptObservationDTO",
                            "slow_query": "#/$defs/SlowQueryObservationDTO",
                            "ticket": "#/$defs/TicketObservationDTO",
                            "ticket_audit": "#/$defs/TicketAuditObservationDTO",
                            "ticket_diagnostic": "#/$defs/TicketDiagnosticObservationDTO",
                        },
                        "propertyName": "observation_type",
                    },
                    "oneOf": [
                        {"$ref": "#/$defs/TicketObservationDTO"},
                        {"$ref": "#/$defs/TicketAuditObservationDTO"},
                        {"$ref": "#/$defs/DatabaseHealthObservationDTO"},
                        {"$ref": "#/$defs/DeadlockObservationDTO"},
                        {"$ref": "#/$defs/SlowQueryObservationDTO"},
                        {"$ref": "#/$defs/TicketDiagnosticObservationDTO"},
                        {"$ref": "#/$defs/BlockingSessionObservationDTO"},
                        {"$ref": "#/$defs/LogExcerptObservationDTO"},
                        {"$ref": "#/$defs/KnownIssueObservationDTO"},
                        {"$ref": "#/$defs/KnowledgeArticleObservationDTO"},
                    ],
                    "title": "Data",
                },
            },
            "required": ["source", "timestamp", "data"],
            "title": "DiagnosticEvidenceWireDTO",
            "type": "object",
        },
        "HypothesisEvaluationWireDTO": {
            "additionalProperties": False,
            "description": "Grounded evaluation outcome for an incident hypothesis.",
            "properties": {
                "hypothesis_id": {
                    "description": "Target hypothesis identifier",
                    "title": "Hypothesis Id",
                    "type": "string",
                },
                "outcome": {
                    "description": "Deterministic evaluation outcome",
                    "enum": ["SUPPORTED", "REFUTED", "INCONCLUSIVE", "UNEVALUATED"],
                    "title": "Outcome",
                    "type": "string",
                },
            },
            "required": ["hypothesis_id", "outcome"],
            "title": "HypothesisEvaluationWireDTO",
            "type": "object",
        },
        "InvestigationSourceOutcomeWireDTO": {
            "additionalProperties": False,
            "description": "Sanitized diagnostic source status report.",
            "properties": {
                "source": {
                    "description": "Domain source identifier",
                    "enum": [
                        "superoffice_crm",
                        "mssql_diagnostics",
                        "application_logs",
                        "knowledge_base",
                    ],
                    "title": "Source",
                    "type": "string",
                },
                "status": {
                    "description": "Collection status across the domain source",
                    "enum": ["SUCCESS", "NOT_CONFIGURED", "BLOCKED", "UNAVAILABLE", "FAILED"],
                    "title": "Status",
                    "type": "string",
                },
                "error_code": {
                    "anyOf": [
                        {
                            "enum": [
                                "DIAGNOSTIC_LOGS_BLOCKED",
                                "KNOWLEDGE_BASE_NOT_CONFIGURED",
                                "SUPEROFFICE_UNAVAILABLE",
                                "SUPEROFFICE_RETRIEVAL_FAILED",
                                "DIAGNOSTICS_UNAVAILABLE",
                                "DIAGNOSTICS_RETRIEVAL_FAILED",
                                "SOURCE_EXECUTION_FAILED",
                            ],
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "default": None,
                    "description": "Standardized error code if collection was not successful",
                    "title": "Error Code",
                },
                "error_message": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Safe, sanitized explanation if collection was not successful",
                    "title": "Error Message",
                },
            },
            "required": ["source", "status"],
            "title": "InvestigationSourceOutcomeWireDTO",
            "type": "object",
        },
        "KnowledgeArticleObservationDTO": {
            "additionalProperties": False,
            "description": "Knowledge base article or runbook documentation observation.",
            "properties": {
                "observation_type": {
                    "const": "knowledge_article",
                    "default": "knowledge_article",
                    "title": "Observation Type",
                    "type": "string",
                },
                "document_id": {
                    "description": "Document identifier",
                    "title": "Document Id",
                    "type": "string",
                },
                "title": {"description": "Article title", "title": "Title", "type": "string"},
                "content_excerpt": {
                    "description": "Excerpt content",
                    "title": "Content Excerpt",
                    "type": "string",
                },
                "category": {
                    "description": "Article category",
                    "title": "Category",
                    "type": "string",
                },
                "relevance_score": {
                    "description": "Relevance score",
                    "title": "Relevance Score",
                    "type": "number",
                },
                "source_reference": {
                    "description": "Source reference",
                    "title": "Source Reference",
                    "type": "string",
                },
            },
            "required": [
                "document_id",
                "title",
                "content_excerpt",
                "category",
                "relevance_score",
                "source_reference",
            ],
            "title": "KnowledgeArticleObservationDTO",
            "type": "object",
        },
        "KnownIssueObservationDTO": {
            "additionalProperties": False,
            "description": "Knowledge base verified known issue observation.",
            "properties": {
                "observation_type": {
                    "const": "known_issue",
                    "default": "known_issue",
                    "title": "Observation Type",
                    "type": "string",
                },
                "issue_id": {
                    "description": "Known issue identifier",
                    "title": "Issue Id",
                    "type": "string",
                },
                "title": {
                    "description": "Known issue summary title",
                    "title": "Title",
                    "type": "string",
                },
                "symptom_summary": {
                    "description": "Observable symptoms",
                    "title": "Symptom Summary",
                    "type": "string",
                },
                "root_cause_summary": {
                    "description": "Root cause explanation",
                    "title": "Root Cause Summary",
                    "type": "string",
                },
                "workaround": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Recommended workaround",
                    "title": "Workaround",
                },
                "permanent_fix_reference": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Fix reference or hotfix ID",
                    "title": "Permanent Fix Reference",
                },
                "affected_products": {
                    "description": "Affected products",
                    "items": {"type": "string"},
                    "title": "Affected Products",
                    "type": "array",
                },
            },
            "required": ["issue_id", "title", "symptom_summary", "root_cause_summary"],
            "title": "KnownIssueObservationDTO",
            "type": "object",
        },
        "LogExcerptObservationDTO": {
            "additionalProperties": False,
            "description": "Sanitized application or API log excerpt observation.",
            "properties": {
                "observation_type": {
                    "const": "log_excerpt",
                    "default": "log_excerpt",
                    "title": "Observation Type",
                    "type": "string",
                },
                "excerpt_id": {
                    "description": "Unique log excerpt identifier",
                    "title": "Excerpt Id",
                    "type": "string",
                },
                "service_name": {
                    "description": "Originating service name",
                    "title": "Service Name",
                    "type": "string",
                },
                "severity": {"description": "Log severity", "title": "Severity", "type": "string"},
                "sanitized_message": {
                    "description": "Sanitized log message",
                    "title": "Sanitized Message",
                    "type": "string",
                },
                "correlation_id": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Request correlation identifier",
                    "title": "Correlation Id",
                },
            },
            "required": ["excerpt_id", "service_name", "severity", "sanitized_message"],
            "title": "LogExcerptObservationDTO",
            "type": "object",
        },
        "SlowQueryObservationDTO": {
            "additionalProperties": False,
            "description": "MSSQL slow-running query observation.",
            "properties": {
                "observation_type": {
                    "const": "slow_query",
                    "default": "slow_query",
                    "title": "Observation Type",
                    "type": "string",
                },
                "query_hash": {
                    "description": "Stable query plan hash identifier",
                    "title": "Query Hash",
                    "type": "string",
                },
                "duration_ms": {
                    "description": "Total execution duration in milliseconds",
                    "title": "Duration Ms",
                    "type": "integer",
                },
                "cpu_time_ms": {
                    "description": "CPU processing time in milliseconds",
                    "title": "Cpu Time Ms",
                    "type": "integer",
                },
                "logical_reads": {
                    "description": "Number of logical page reads",
                    "title": "Logical Reads",
                    "type": "integer",
                },
                "execution_count": {
                    "description": "Number of executions recorded",
                    "title": "Execution Count",
                    "type": "integer",
                },
            },
            "required": [
                "query_hash",
                "duration_ms",
                "cpu_time_ms",
                "logical_reads",
                "execution_count",
            ],
            "title": "SlowQueryObservationDTO",
            "type": "object",
        },
        "TicketAuditObservationDTO": {
            "additionalProperties": False,
            "description": "SuperOffice CRM ticket audit trail action observation.",
            "properties": {
                "observation_type": {
                    "const": "ticket_audit",
                    "default": "ticket_audit",
                    "title": "Observation Type",
                    "type": "string",
                },
                "action_id": {
                    "description": "Unique action identifier",
                    "title": "Action Id",
                    "type": "integer",
                },
                "ticket_id": {
                    "description": "SuperOffice ticket identifier",
                    "title": "Ticket Id",
                    "type": "integer",
                },
                "action_code": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "default": None,
                    "description": "SuperOffice action code",
                    "title": "Action Code",
                },
                "action_name": {
                    "description": "Descriptive action title",
                    "title": "Action Name",
                    "type": "string",
                },
                "description": {
                    "default": "",
                    "description": "Action description",
                    "title": "Description",
                    "type": "string",
                },
                "actor": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Actor login name or user ID representation",
                    "title": "Actor",
                },
                "field_changes": {
                    "description": "Granular field mutations associated with this action",
                    "items": {"additionalProperties": True, "type": "object"},
                    "title": "Field Changes",
                    "type": "array",
                },
            },
            "required": ["action_id", "ticket_id", "action_name"],
            "title": "TicketAuditObservationDTO",
            "type": "object",
        },
        "TicketDiagnosticObservationDTO": {
            "additionalProperties": False,
            "description": "MSSQL ticket database diagnostic activity observation.",
            "properties": {
                "observation_type": {
                    "const": "ticket_diagnostic",
                    "default": "ticket_diagnostic",
                    "title": "Observation Type",
                    "type": "string",
                },
                "ticket_id": {
                    "description": "SuperOffice ticket identifier",
                    "title": "Ticket Id",
                    "type": "integer",
                },
                "has_db_activity": {
                    "description": "Whether ticket has DB diagnostic activity",
                    "title": "Has Db Activity",
                    "type": "boolean",
                },
                "recent_error_count": {
                    "description": "Count of recent errors matching ticket",
                    "title": "Recent Error Count",
                    "type": "integer",
                },
                "last_activity_time": {
                    "anyOf": [{"format": "date-time", "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Timestamp of latest DB activity",
                    "title": "Last Activity Time",
                },
                "diagnostic_summary": {
                    "description": "Database diagnostic summary",
                    "title": "Diagnostic Summary",
                    "type": "string",
                },
            },
            "required": [
                "ticket_id",
                "has_db_activity",
                "recent_error_count",
                "diagnostic_summary",
            ],
            "title": "TicketDiagnosticObservationDTO",
            "type": "object",
        },
        "TicketObservationDTO": {
            "additionalProperties": False,
            "description": "SuperOffice CRM ticket observation.",
            "properties": {
                "observation_type": {
                    "const": "ticket",
                    "default": "ticket",
                    "title": "Observation Type",
                    "type": "string",
                },
                "ticket_id": {
                    "description": "SuperOffice ticket identifier",
                    "title": "Ticket Id",
                    "type": "integer",
                },
                "title": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Sanitized ticket subject or title",
                    "title": "Title",
                },
                "status": {"description": "Ticket status", "title": "Status", "type": "string"},
                "category": {
                    "description": "Ticket category",
                    "title": "Category",
                    "type": "string",
                },
                "priority": {
                    "description": "Ticket priority level",
                    "title": "Priority",
                    "type": "string",
                },
                "sanitized_description": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Sanitized ticket problem description or symptom text",
                    "title": "Sanitized Description",
                },
                "sanitized_customer_reference": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Sanitized customer reference identifier",
                    "title": "Sanitized Customer Reference",
                },
            },
            "required": ["ticket_id", "status", "category", "priority"],
            "title": "TicketObservationDTO",
            "type": "object",
        },
    },
    "additionalProperties": False,
    "description": "Immutable public wire contract for incident investigation results.",
    "properties": {
        "source_outcomes": {
            "description": "Diagnostic coverage and collection status across each domain source",
            "items": {"$ref": "#/$defs/InvestigationSourceOutcomeWireDTO"},
            "title": "Source Outcomes",
            "type": "array",
        },
        "evidence": {
            "default": [],
            "description": "Chronologically ordered diagnostic evidence items observed across sources",
            "items": {"$ref": "#/$defs/DiagnosticEvidenceWireDTO"},
            "title": "Evidence",
            "type": "array",
        },
        "hypothesis_evaluation": {
            "anyOf": [{"$ref": "#/$defs/HypothesisEvaluationWireDTO"}, {"type": "null"}],
            "default": None,
            "description": "Deterministic evaluation outcome of the incident hypothesis",
        },
    },
    "required": ["source_outcomes"],
    "title": "InvestigateIncidentResponseDTO",
    "type": "object",
}


def get_platform_tool_schemas() -> list[Tool]:
    """Return official MCP Tool definitions with complete JSON schemas for approved platform tools.

    Inventory (23 Approved Platform Tools):
    - Knowledge (3 tools): search_knowledge, get_runbook, find_known_issues
    - SuperOffice (13 tools): get_ticket, search_tickets, get_ticket_messages, list_attachments,
                             get_company, find_companies, get_person, find_persons, sync_codebase,
                             list_extra_tables, get_extra_table_schema, query_extra_table,
                             get_ticket_audit_trail
    - Diagnostics (6 tools): get_database_health, find_slow_queries, get_ticket_diagnostic_record,
                             search_logs, find_deadlocks, find_blocking_sessions
    - Infrastructure (0 tools): Deferred per Decision 2A-D07
    - Investigation (1 tool): investigate_incident (L3 Composite Investigation)
    """
    return [
        # Knowledge Base MCP Tools (L1)
        Tool(
            name="search_knowledge",
            description="Search sanitized knowledge base and runbooks",
            inputSchema={
                "type": "object",
                "properties": {
                    "query_text": {
                        "type": "string",
                        "description": "Semantic or keyword search query text",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of chunks to return (default: 5, max: 20)",
                        "default": 5,
                    },
                },
                "required": ["query_text"],
            },
        ),
        Tool(
            name="get_runbook",
            description="Retrieve specific runbook by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "runbook_id": {
                        "type": "string",
                        "description": "Unique identifier of the runbook article",
                    },
                },
                "required": ["runbook_id"],
            },
        ),
        Tool(
            name="find_known_issues",
            description="Find matching known issue articles",
            inputSchema={
                "type": "object",
                "properties": {
                    "query_text": {
                        "type": "string",
                        "description": "Search string for known issues and resolutions",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of known issues to return",
                        "default": 5,
                    },
                },
                "required": ["query_text"],
            },
        ),
        # SuperOffice CRM MCP Tools (L1 Read-Only Operations)
        Tool(
            name="get_ticket",
            description="Get basic ticket summary and status",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "Unique identifier of the SuperOffice ticket",
                    },
                },
                "required": ["ticket_id"],
            },
        ),
        Tool(
            name="search_tickets",
            description="Search tickets by title, category, or status",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Filter by ticket title text"},
                    "category": {
                        "type": "string",
                        "description": "Filter by ticket category name",
                    },
                    "status": {"type": "string", "description": "Filter by ticket status string"},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return (max 50)",
                        "default": 10,
                    },
                },
            },
        ),
        Tool(
            name="get_ticket_messages",
            description="Get ticket message history",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "Ticket ID to retrieve messages for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum messages to return",
                        "default": 20,
                    },
                },
                "required": ["ticket_id"],
            },
        ),
        Tool(
            name="list_attachments",
            description="List attachment metadata without raw content",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "Ticket ID to list attachments for",
                    },
                },
                "required": ["ticket_id"],
            },
        ),
        Tool(
            name="get_company",
            description="Retrieve customer company details",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {
                        "type": "integer",
                        "description": "Unique identifier of the company/contact",
                    },
                },
                "required": ["contact_id"],
            },
        ),
        Tool(
            name="find_companies",
            description="Find companies matching criteria",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Company name search substring"},
                    "category": {"type": "string", "description": "Company category filter"},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 10,
                    },
                },
            },
        ),
        Tool(
            name="get_person",
            description="Retrieve customer contact person details",
            inputSchema={
                "type": "object",
                "properties": {
                    "person_id": {
                        "type": "integer",
                        "description": "Unique identifier of the person",
                    },
                },
                "required": ["person_id"],
            },
        ),
        Tool(
            name="find_persons",
            description="Find contact persons matching criteria",
            inputSchema={
                "type": "object",
                "properties": {
                    "first_name": {
                        "type": "string",
                        "description": "First name search substring",
                    },
                    "last_name": {"type": "string", "description": "Last name search substring"},
                    "email": {"type": "string", "description": "Email address search substring"},
                    "contact_id": {
                        "type": "integer",
                        "description": "Filter by company contact ID",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 10,
                    },
                },
            },
        ),
        Tool(
            name="sync_codebase",
            description=(
                "Sync SuperOffice CRMScripts, screens, and custom tables to local mirror directory"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["http", "mssql"],
                        "description": (
                            "Extraction mode: 'http' via CRMScript handler, "
                            "or 'mssql' via direct database connection"
                        ),
                    },
                    "tables": {
                        "type": "string",
                        "description": (
                            "Comma-separated entities to sync (e.g. 'ejscript,screens,schema' "
                            "or 'all')"
                        ),
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, scans and evaluates without writing files to disk",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="list_extra_tables",
            description=(
                "List registered SuperOffice custom extra tables (y_*) "
                "with metadata and field counts"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": (
                            "Optional substring filter to match against table name, "
                            "display name, or description"
                        ),
                    },
                },
            },
        ),
        Tool(
            name="get_extra_table_schema",
            description=(
                "Retrieve column definitions, labels, data types, and defaults "
                "for a specific y_* table"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Target extra table name (e.g. 'y_subscription')",
                    },
                },
                "required": ["table_name"],
            },
        ),
        Tool(
            name="query_extra_table",
            description=(
                "Query records from a specific SuperOffice custom extra table with "
                "column-level filtering, projection, ordering, and pagination"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Target extra table name (e.g. 'y_subscription')",
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Specific columns to select. If omitted, selects id and all "
                            "custom x_* fields."
                        ),
                    },
                    "filters": {
                        "type": "object",
                        "description": (
                            "Key-value filter mapping matching column names to desired values"
                        ),
                    },
                    "order_by": {
                        "type": "string",
                        "description": "Column to sort by (defaults to id)",
                        "default": "id",
                    },
                    "order_direction": {
                        "type": "string",
                        "enum": ["asc", "desc"],
                        "description": "Sort direction ('asc' or 'desc')",
                        "default": "asc",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Maximum rows to return (1..50, default 20)",
                        "default": 20,
                    },
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Number of rows to skip for pagination (default 0)",
                        "default": 0,
                    },
                },
                "required": ["table_name"],
            },
        ),
        Tool(
            name="get_ticket_audit_trail",
            description=(
                "Retrieve the complete, chronological audit trail and change history for a "
                "SuperOffice ticket, including high-level lifecycle events, user actions, and "
                "granular before/after field mutations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Ticket ID to retrieve audit trail for",
                    },
                    "include_field_changes": {
                        "type": "boolean",
                        "description": (
                            "Whether to include granular field transitions (default: True)"
                        ),
                        "default": True,
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Maximum action records to return (1..100, default 50)",
                        "default": 50,
                    },
                },
                "required": ["ticket_id"],
            },
        ),
        Tool(
            name="search_codebase",
            description=(
                "Search across all mirrored SuperOffice CRMScripts, screen definitions, button "
                "actions, and element creation scripts by keyword, path, or regex pattern."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword, path segment, or regex pattern to search for",
                    },
                    "target_type": {
                        "type": "string",
                        "enum": ["all", "crmscript", "screen", "action", "element"],
                        "description": "Filter by target artifact type (default: all)",
                        "default": "all",
                    },
                    "screen_name": {
                        "type": "string",
                        "description": "Optional screen name to scope search within",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Maximum number of search items to return (default: 20)",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_codebase_file",
            description=(
                "Safely retrieve the content of a mirrored CRMScript or screen definition file "
                "with bounded line windowing and path traversal protection."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "relative_path": {
                        "type": "string",
                        "description": "Relative path of file inside codebase mirror",
                    },
                    "start_line": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "1-indexed starting line number (default: 1)",
                        "default": 1,
                    },
                    "end_line": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "1-indexed ending line number (default: 100)",
                        "default": 100,
                    },
                },
                "required": ["relative_path"],
            },
        ),
        Tool(
            name="get_screen_details",
            description=(
                "Inspect the structural layout, constituent elements, button actions, and "
                "associated lifecycle scripts of a SuperOffice screen by name or ID."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "screen_name_or_id": {
                        "type": "string",
                        "description": "Screen name (e.g. 'Create case') or numeric screen ID",
                    },
                },
                "required": ["screen_name_or_id"],
            },
        ),
        Tool(
            name="get_associate_details",
            description=(
                "Retrieve details for an internal SuperOffice consultant, support engineer, "
                "or technician by associate ID or username."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "associate_id": {
                        "type": "integer",
                        "description": "SuperOffice associate ID or ejuser ID",
                    },
                    "username": {
                        "type": "string",
                        "description": "Username or login name to search for",
                    },
                },
            },
        ),
        Tool(
            name="get_ticket_metadata_lists",
            description=(
                "Retrieve system reference lists including ticket categories, priorities, "
                "statuses, and user groups."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "list_type": {
                        "type": "string",
                        "enum": ["all", "category", "priority", "status", "group", "user_group"],
                        "description": "Type of list to retrieve (default: all)",
                        "default": "all",
                    },
                },
            },
        ),
        Tool(
            name="list_system_events_and_triggers",
            description=(
                "Inspect scheduled background tasks, cron execution statuses, and CRMScript "
                "bindings across the SuperOffice system."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "include_disabled": {
                        "type": "boolean",
                        "description": "Include disabled scheduled tasks (default: True)",
                        "default": True,
                    },
                    "only_errors": {
                        "type": "boolean",
                        "description": "Filter only to tasks with errors or error messages",
                        "default": False,
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional search keyword to match task or script names",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Maximum number of tasks to return (default: 50)",
                        "default": 50,
                    },
                },
            },
        ),
        # Diagnostics MCP Tools (L2 & L3)
        Tool(
            name="get_database_health",
            description=(
                "Current point-in-time observation of database cluster health, active "
                "connections, backup history, and connectivity boundary. A CONNECTED state "
                "proves database reachability at collection time only; it does NOT "
                "invalidate or disprove previously observed failures. Historical root cause "
                "remains UNKNOWN unless separate historical evidence proves it. latency_ms "
                "is an observational diagnostic measurement for this specific query and does "
                "NOT by itself prove client timeout, SQL saturation, VPN/firewall failure, "
                "connection pool exhaustion, or outage cause. Do not recommend changing "
                "connection timeouts, firewall, VPN, or database network configurations "
                "without concrete supporting evidence. Note: Included automatically in "
                "investigate_incident if include_database_health=true."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="find_slow_queries",
            description=(
                "Inspect slow query execution records from the SQL Server plan cache "
                "(sys.dm_exec_query_stats). Metrics represent cached and aggregated historical "
                "averages per execution, not proof of query execution at the exact current moment. "
                "Note: Included automatically in investigate_incident."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "min_duration_ms": {
                        "type": "number",
                        "description": "Minimum execution duration in milliseconds (default: 1000)",
                        "default": 1000.0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of records to return (max 50)",
                        "default": 10,
                    },
                },
            },
        ),
        Tool(
            name="get_ticket_diagnostic_record",
            description=(
                "Inspect database-level diagnostic activity and update telemetry for a ticket, "
                "verifying database recording state, activity counts, and recent mutations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Ticket ID to query database records for",
                    },
                },
                "required": ["ticket_id"],
            },
        ),
        Tool(
            name="search_logs",
            description=(
                "Search application and API log entries (BLOCKED: Log backend is unconfigured "
                "in this environment. Do not call or retry calling this tool; rely on database "
                "and ticket diagnostics instead)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query pattern",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum log entries to return",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="find_deadlocks",
            description=(
                "Query deadlock events captured in the SQL Server system_health ring buffer within "
                "the queried time window (hours_back, default 24). Zero returned deadlocks means "
                "only that none were captured within that specific window; it does NOT prove "
                "historical absence outside that window or absence of other contention. Note: "
                "Included automatically in investigate_incident."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "hours_back": {
                        "type": "integer",
                        "description": "Hours back to search for deadlock events (default: 24)",
                        "default": 24,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of deadlocks to return (max 50)",
                        "default": 10,
                    },
                },
            },
        ),
        Tool(
            name="find_blocking_sessions",
            description=(
                "Real-time snapshot of active SQL Server blocking transactions. Zero current "
                "blocking sessions means no blocking sessions were observed at the exact moment "
                "of this snapshot; it does NOT prove absence of blocking prior to the snapshot."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        # Investigation MCP Tool (L3 Composite Investigation)
        Tool(
            name="investigate_incident",
            description=(
                "Orchestrate structured, cross-domain diagnostic investigation of a platform "
                "incident. Preferred primary tool for incident investigation. Aggregates ticket "
                "context, database health, deadlocks, and slow queries in a single roundtrip, "
                "avoiding redundant separate diagnostic tool calls."
            ),
            inputSchema=INVESTIGATE_INCIDENT_INPUT_SCHEMA,
            outputSchema=INVESTIGATE_INCIDENT_OUTPUT_SCHEMA,
        ),
    ]


def get_tool_schema_map() -> dict[str, Tool]:
    """Return dictionary of official MCP Tool definitions keyed by tool name."""
    return {tool.name: tool for tool in get_platform_tool_schemas()}
