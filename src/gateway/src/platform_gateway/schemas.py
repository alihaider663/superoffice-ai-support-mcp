"""Canonical MCP Tool Definitions and Input Schemas for approved platform tools."""

from mcp.types import Tool

INVESTIGATE_INCIDENT_INPUT_SCHEMA = {
    "$defs": {
        "DeadlockInvestigationInputDTO": {
            "additionalProperties": False,
            "description": "Public criteria for database deadlock analysis.",
            "properties": {
                "end_time": {
                    "anyOf": [{"format": "date-time", "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "End "
                    "of "
                    "observation "
                    "time "
                    "window "
                    "with "
                    "explicit "
                    "offset "
                    "(e.g. "
                    "'...Z')",
                    "title": "End Time",
                },
                "limit": {
                    "anyOf": [{"maximum": 50, "minimum": 1, "type": "integer"}, {"type": "null"}],
                    "default": 10,
                    "description": "Maximum "
                    "deadlock "
                    "events "
                    "to "
                    "return "
                    "(1..50, "
                    "default "
                    "10, "
                    "capped "
                    "by "
                    "D02)",
                    "title": "Limit",
                },
                "start_time": {
                    "anyOf": [{"format": "date-time", "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Start "
                    "of "
                    "observation "
                    "time "
                    "window "
                    "with "
                    "explicit "
                    "offset "
                    "(e.g. "
                    "'...Z')",
                    "title": "Start Time",
                },
            },
            "title": "DeadlockInvestigationInputDTO",
            "type": "object",
        },
        "InvestigationDiagnosticsInputDTO": {
            "additionalProperties": False,
            "description": "Public opt-in selection for database diagnostic checks.",
            "properties": {
                "deadlocks": {
                    "anyOf": [{"$ref": "#/$defs/DeadlockInvestigationInputDTO"}, {"type": "null"}],
                    "default": None,
                    "description": "Explicit opt-in criteria to search recent database deadlocks",
                },
                "include_database_health": {
                    "default": False,
                    "description": "Explicit opt-in to execute database health check",
                    "title": "Include Database Health",
                    "type": "boolean",
                },
                "slow_queries": {
                    "anyOf": [{"$ref": "#/$defs/SlowQueryInvestigationInputDTO"}, {"type": "null"}],
                    "default": None,
                    "description": "Explicit "
                    "opt-in "
                    "criteria "
                    "to "
                    "search "
                    "slow "
                    "executing "
                    "database "
                    "queries",
                },
            },
            "title": "InvestigationDiagnosticsInputDTO",
            "type": "object",
        },
        "SlowQueryInvestigationInputDTO": {
            "additionalProperties": False,
            "description": "Public criteria for database slow query analysis.",
            "properties": {
                "end_time": {
                    "anyOf": [{"format": "date-time", "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "End "
                    "of "
                    "observation "
                    "time "
                    "window "
                    "with "
                    "explicit "
                    "offset "
                    "(e.g. "
                    "'...Z')",
                    "title": "End Time",
                },
                "limit": {
                    "anyOf": [{"maximum": 50, "minimum": 1, "type": "integer"}, {"type": "null"}],
                    "default": 10,
                    "description": "Maximum "
                    "slow "
                    "queries "
                    "to "
                    "return "
                    "(1..50, "
                    "default "
                    "10, "
                    "capped "
                    "by "
                    "D02)",
                    "title": "Limit",
                },
                "min_duration_ms": {
                    "default": 1000,
                    "description": "Minimum "
                    "execution "
                    "duration "
                    "threshold "
                    "in "
                    "milliseconds "
                    "(default "
                    "1000ms)",
                    "minimum": 1,
                    "title": "Min Duration Ms",
                    "type": "integer",
                },
                "start_time": {
                    "anyOf": [{"format": "date-time", "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Start "
                    "of "
                    "observation "
                    "time "
                    "window "
                    "with "
                    "explicit "
                    "offset "
                    "(e.g. "
                    "'...Z')",
                    "title": "Start Time",
                },
            },
            "title": "SlowQueryInvestigationInputDTO",
            "type": "object",
        },
    },
    "additionalProperties": False,
    "description": "Public MCP input contract for cross-domain incident investigation.",
    "properties": {
        "diagnostics": {
            "anyOf": [{"$ref": "#/$defs/InvestigationDiagnosticsInputDTO"}, {"type": "null"}],
            "default": None,
            "description": "Optional database diagnostic checks to execute",
        },
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
    },
    "required": ["initial_hypothesis"],
    "title": "InvestigateIncidentRequestDTO",
    "type": "object",
}

INVESTIGATE_INCIDENT_OUTPUT_SCHEMA = {
    "$defs": {
        "DatabaseHealthObservationDTO": {
            "additionalProperties": False,
            "description": "MSSQL database cluster health observation.",
            "properties": {
                "active_connections": {
                    "description": "Current active connection count",
                    "title": "Active Connections",
                    "type": "integer",
                },
                "is_healthy": {
                    "description": "Whether database is responsive and healthy",
                    "title": "Is Healthy",
                    "type": "boolean",
                },
                "latency_ms": {
                    "description": "Database probe latency in milliseconds",
                    "title": "Latency Ms",
                    "type": "number",
                },
                "observation_type": {
                    "const": "database_health",
                    "default": "database_health",
                    "title": "Observation Type",
                    "type": "string",
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
                "deadlock_id": {
                    "description": "Deterministic deadlock event identifier",
                    "title": "Deadlock Id",
                    "type": "string",
                },
                "observation_type": {
                    "const": "deadlock",
                    "default": "deadlock",
                    "title": "Observation Type",
                    "type": "string",
                },
                "participating_session_count": {
                    "description": "Number of sessions participating in deadlock",
                    "title": "Participating Session Count",
                    "type": "integer",
                },
                "victim_session_id": {
                    "description": "Session ID chosen as deadlock victim",
                    "title": "Victim Session Id",
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
                "data": {
                    "description": "Structured observation payload conforming to observation_type",
                    "discriminator": {
                        "mapping": {
                            "database_health": "#/$defs/DatabaseHealthObservationDTO",
                            "deadlock": "#/$defs/DeadlockObservationDTO",
                            "slow_query": "#/$defs/SlowQueryObservationDTO",
                            "ticket": "#/$defs/TicketObservationDTO",
                        },
                        "propertyName": "observation_type",
                    },
                    "oneOf": [
                        {"$ref": "#/$defs/TicketObservationDTO"},
                        {"$ref": "#/$defs/DatabaseHealthObservationDTO"},
                        {"$ref": "#/$defs/DeadlockObservationDTO"},
                        {"$ref": "#/$defs/SlowQueryObservationDTO"},
                    ],
                    "title": "Data",
                },
                "source": {
                    "description": "Originating domain source",
                    "enum": ["superoffice_crm", "mssql_diagnostics"],
                    "title": "Source",
                    "type": "string",
                },
                "timestamp": {
                    "description": "Observation timestamp in UTC (ISO 8601)",
                    "format": "date-time",
                    "title": "Timestamp",
                    "type": "string",
                },
            },
            "required": ["source", "timestamp", "data"],
            "title": "DiagnosticEvidenceWireDTO",
            "type": "object",
        },
        "InvestigationSourceOutcomeWireDTO": {
            "additionalProperties": False,
            "description": "Sanitized diagnostic source status report.",
            "properties": {
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
            },
            "required": ["source", "status"],
            "title": "InvestigationSourceOutcomeWireDTO",
            "type": "object",
        },
        "SlowQueryObservationDTO": {
            "additionalProperties": False,
            "description": "MSSQL slow-running query observation.",
            "properties": {
                "cpu_time_ms": {
                    "description": "CPU processing time in milliseconds",
                    "title": "Cpu Time Ms",
                    "type": "integer",
                },
                "duration_ms": {
                    "description": "Total execution duration in milliseconds",
                    "title": "Duration Ms",
                    "type": "integer",
                },
                "execution_count": {
                    "description": "Number of executions recorded",
                    "title": "Execution Count",
                    "type": "integer",
                },
                "logical_reads": {
                    "description": "Number of logical page reads",
                    "title": "Logical Reads",
                    "type": "integer",
                },
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
        "TicketObservationDTO": {
            "additionalProperties": False,
            "description": "SuperOffice CRM ticket observation.",
            "properties": {
                "category": {
                    "description": "Ticket category",
                    "title": "Category",
                    "type": "string",
                },
                "observation_type": {
                    "const": "ticket",
                    "default": "ticket",
                    "title": "Observation Type",
                    "type": "string",
                },
                "priority": {
                    "description": "Ticket priority level",
                    "title": "Priority",
                    "type": "string",
                },
                "status": {"description": "Ticket status", "title": "Status", "type": "string"},
                "ticket_id": {
                    "description": "SuperOffice ticket identifier",
                    "title": "Ticket Id",
                    "type": "integer",
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
        "evidence": {
            "default": [],
            "description": "Chronologically ordered "
            "diagnostic evidence items "
            "observed across sources",
            "items": {"$ref": "#/$defs/DiagnosticEvidenceWireDTO"},
            "title": "Evidence",
            "type": "array",
        },
        "source_outcomes": {
            "description": "Diagnostic coverage and collection status across each domain source",
            "items": {"$ref": "#/$defs/InvestigationSourceOutcomeWireDTO"},
            "title": "Source Outcomes",
            "type": "array",
        },
    },
    "required": ["source_outcomes"],
    "title": "InvestigateIncidentResponseDTO",
    "type": "object",
}


def get_platform_tool_schemas() -> list[Tool]:
    """Return official MCP Tool definitions with complete JSON schemas for approved platform tools.

    Inventory (18 Approved & Blocked Platform Tools):
    - Knowledge (3 tools): search_knowledge, get_runbook, find_known_issues
    - SuperOffice (8 tools): get_ticket, search_tickets, get_ticket_messages, list_attachments,
                             get_company, find_companies, get_person, find_persons
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
                "without concrete supporting evidence."
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
                "averages per execution, not proof of query execution at the exact current moment."
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
            description="Get diagnostic database records for a ticket (BLOCKED: awaiting schema)",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "Ticket ID to query database records for",
                    },
                },
                "required": ["ticket_id"],
            },
        ),
        Tool(
            name="search_logs",
            description="Search application and API log entries (BLOCKED: awaiting log backend)",
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
                "historical absence outside that window or absence of other contention."
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
                "Orchestrate structured, cross-domain diagnostic "
                "investigation of a platform incident"
            ),
            inputSchema=INVESTIGATE_INCIDENT_INPUT_SCHEMA,
            outputSchema=INVESTIGATE_INCIDENT_OUTPUT_SCHEMA,
        ),
    ]


def get_tool_schema_map() -> dict[str, Tool]:
    """Return dictionary of official MCP Tool definitions keyed by tool name."""
    return {tool.name: tool for tool in get_platform_tool_schemas()}
