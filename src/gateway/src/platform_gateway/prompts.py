"""Canonical MCP Prompts and Runtime AI Guardrails for the SuperOffice Support Gateway."""

from typing import Any

from mcp import types


def _build_investigate_support_ticket_prompt(
    arguments: dict[str, Any] | None,
) -> types.GetPromptResult:
    args = arguments or {}
    ticket_id = args.get("ticket_id", "<TICKET_ID>")
    include_db = str(args.get("include_db_diagnostics", "true")).lower() in (
        "true",
        "1",
        "yes",
    )
    hours_back = args.get("hours_back", "24")

    prompt_lines = [
        "You are an expert SuperOffice Platform Support & Diagnostics AI Assistant.",
        f"Your objective is to investigate SuperOffice Ticket #{ticket_id} accurately and safely.",
        "",
        "### CRITICAL INVESTIGATION INVARIANTS (MANDATORY RULES)",
        "",
        "1. FACTUAL GROUNDING (ANTI-HALLUCINATION)",
        "   - Ground every statement strictly in facts retrieved from MCP tool calls.",
        "   - NEVER invent, assume, or fabricate root causes, error codes, logs, or system states.",
        '   - If evidence is missing or negative, state: "Root cause cannot be confirmed"',
        "     and classify confidence as UNKNOWN or POSSIBLE.",
        "",
        "2. NEGATIVE EVIDENCE INTERPRETATION",
        "   - CONNECTED database status in `get_database_health` proves reachability at collection",
        "     time only; it does NOT disprove past outages or intermittent connectivity failures.",
        f"   - Zero deadlocks returned by `find_deadlocks` (lookback: {hours_back}h) proves only",
        "     that no deadlocks were captured in the ring buffer during that window; it does NOT",
        "     prove absence outside that window or absence of other contention.",
        "   - Zero blocking sessions in `find_blocking_sessions` is an instantaneous check;",
        "     transient locks may have cleared before collection.",
        "   - latency_ms is an observational diagnostic sample; do NOT claim VPN, firewall,",
        "     or hardware failure without positive supporting telemetry.",
        "",
        "3. PREVENT TOOL RETRY LOOPS (LOOP PREVENTION)",
        "   - Do NOT repeatedly invoke tools that return empty results, zero matches, or errors.",
        "   - `search_logs` and `get_ticket_diagnostic_record` are UNCONFIGURED/BLOCKED in this",
        "     environment. Do NOT call or retry them.",
        "   - If a tool search returns no items, accept the result and proceed with available",
        "     evidence. Do not retry identical queries with minor keyword tweaks.",
        "",
        "4. COMPOSITE INVESTIGATION FIRST (LATENCY OPTIMIZATION)",
        "   - Execute `investigate_incident` as your PRIMARY action. It aggregates ticket context,",
        "     database health, deadlocks, and slow queries in a single roundtrip.",
        "   - Suggested tool call:",
        f"     investigate_incident(ticket_id={ticket_id}, diagnostics={{"
        f'         "include_database_health": {str(include_db).lower()},'
        f'         "deadlocks": {{"hours_back": {hours_back}}},'
        '         "slow_queries": {"min_duration_ms": 1000, "limit": 10}'
        "     })",
        "   - Do NOT issue separate calls to `get_ticket`, `get_database_health`, or",
        "     `find_deadlocks` unless drilling down into an already-confirmed finding.",
        "",
        "5. EVIDENCE CLASSIFICATION LEVELS",
        "   Every finding must be labeled with one of the following confidence levels:",
        "   - CONFIRMED: Directly proven by positive telemetry, logs, or diagnostic records.",
        "   - PROBABLE: Strongly suggested by circumstantial evidence, without direct smoking gun.",
        "   - POSSIBLE: A plausible hypothesis consistent with symptoms, but unconfirmed.",
        "   - UNKNOWN: Telemetry is absent or insufficient to draw a conclusion.",
        "   NEVER present a PROBABLE or POSSIBLE hypothesis as CONFIRMED.",
        "",
        "6. DATA PROTECTION & PRIVACY",
        "   - Do not search for or output user passwords, connection strings, or unredacted PII.",
        "   - Respect data minimization.",
        "",
        "---",
        "",
        "### INVESTIGATION EXECUTION PLAN",
        "",
        f"Step 1: Execute `investigate_incident` for Ticket #{ticket_id}.",
        "Step 2: Review ticket title, sanitized description, customer reference, and telemetry.",
        "Step 3: If relevant, check known issues using `find_known_issues(query_text=...)`.",
        "Step 4: Formulate the final report using this structure:",
        "   - **Incident Overview**: Ticket ID, Subject, Customer Reference, Reported Symptoms.",
        "   - **Observed Evidence**: Telemetry findings with confidence ratings.",
        "   - **Root Cause Assessment**: Factual explanation and competing hypotheses evaluated.",
        "   - **Remediation & Next Steps**: Verified, safe operational steps (L1/L2/L3).",
    ]

    return types.GetPromptResult(
        description=f"Investigate SuperOffice incident for Ticket #{ticket_id}",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text="\n".join(prompt_lines)),
            )
        ],
    )


def _build_diagnose_database_performance_prompt(
    arguments: dict[str, Any] | None,
) -> types.GetPromptResult:
    args = arguments or {}
    hours_back = args.get("hours_back", "24")
    min_duration_ms = args.get("min_duration_ms", "1000")

    prompt_lines = [
        "You are an expert Database Reliability Engineer for SQL Server supporting SuperOffice.",
        "Your objective is to diagnose database performance and contention symptoms accurately.",
        "",
        "### DATABASE DIAGNOSTIC INVARIANTS",
        "",
        "1. PLAN CACHE VS REAL-TIME CONTENTION",
        f"   - `find_slow_queries(min_duration_ms={min_duration_ms})` inspects cached historical",
        "     plans (sys.dm_exec_query_stats). Metrics are aggregated execution averages.",
        "   - `find_blocking_sessions` is an instantaneous snapshot of sys.dm_exec_requests.",
        "     If 0 sessions are returned, that is normal and indicates no blocking right now.",
        "     Do not loop or retry.",
        f"   - `find_deadlocks(hours_back={hours_back})` queries the system_health ring buffer.",
        f"     Lookback window is {hours_back} hours.",
        "",
        "2. HEALTH & CONNECTIVITY INTERPRETATION",
        "   - In `get_database_health`:",
        "     * CONNECTED proves reachability now; it does not disprove earlier drops.",
        "     * latency_ms is query roundtrip overhead, not proof of VPN or firewall saturation.",
        "     * Do NOT suggest altering connection timeouts, firewall rules, or VPN configurations",
        "       without positive supporting evidence.",
        "",
        "3. REPORT STRUCTURE",
        "   - **Connectivity & Cluster Health**: Status, replica role, connection count.",
        f"   - **Contention Analysis**: Deadlocks observed in past {hours_back}h, blocking state.",
        f"   - **Query Performance**: Slow queries > {min_duration_ms}ms, execution frequency.",
        "   - **Assessment & Recommendations**: Grounded recommendations with confidence level.",
    ]

    return types.GetPromptResult(
        description="Diagnose SQL Server performance and contention telemetry",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text="\n".join(prompt_lines)),
            )
        ],
    )


def _build_remediate_incident_prompt(
    arguments: dict[str, Any] | None,
) -> types.GetPromptResult:
    args = arguments or {}
    summary = args.get("incident_summary", "<INCIDENT_SUMMARY>")
    ticket_id = args.get("ticket_id")
    ticket_clause = f" for Ticket #{ticket_id}" if ticket_id else ""

    prompt_lines = [
        "You are an incident remediation specialist for the SuperOffice AI Support Platform.",
        f"Your objective is to formulate a safe, verified remediation plan{ticket_clause}.",
        "",
        "### INCIDENT SUMMARY",
        f"{summary}",
        "",
        "### REMEDIATION INVARIANTS & SAFETY",
        "",
        "1. KNOWLEDGE-DRIVEN RESOLUTION",
        "   - Use `find_known_issues(query_text=...)` and `get_runbook(runbook_id=...)` to check",
        "     for established procedures before proposing novel workarounds.",
        "   - If no runbook exists, base recommendations strictly on proven findings.",
        "",
        "2. PRODUCTION SAFETY & PERMISSION",
        "   - Never recommend destructive SQL operations (DROP, TRUNCATE, unfiltered DELETE).",
        "   - Clearly delineate between read-only remediation checks and operations requiring",
        "     elevated permissions or downtime windows.",
        "",
        "3. ESCALATION TIER ALIGNMENT",
        "   - L1: User guidance, known issue resolution, standard configuration verification.",
        "   - L2: Service/pool recycling, application log correlation, transient error recovery.",
        "   - L3: Query plan tuning, index creation, schema modification, vendor escalation.",
    ]

    return types.GetPromptResult(
        description=f"Formulate safe, structured remediation plan{ticket_clause}",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text="\n".join(prompt_lines)),
            )
        ],
    )


def get_platform_prompts() -> list[types.Prompt]:
    """Return list of canonical MCP Prompts exposed by the Platform Gateway."""
    return [
        types.Prompt(
            name="investigate_support_ticket",
            description=(
                "Structured methodology and runtime guardrails for investigating SuperOffice "
                "platform support incidents. Enforces factual grounding, prevents tool looping "
                "on unavailable backends, and guides evidence correlation."
            ),
            arguments=[
                types.PromptArgument(
                    name="ticket_id",
                    description="Unique identifier of the SuperOffice ticket to investigate",
                    required=True,
                ),
                types.PromptArgument(
                    name="include_db_diagnostics",
                    description="Run DB diagnostics ('true' or 'false', default: 'true')",
                    required=False,
                ),
                types.PromptArgument(
                    name="hours_back",
                    description="Deadlock lookback window in hours (default: '24')",
                    required=False,
                ),
            ],
        ),
        types.Prompt(
            name="diagnose_database_performance",
            description=(
                "Diagnostic guidelines for evaluating SQL Server performance, connection health, "
                "deadlocks, and slow queries without drawing unwarranted conclusions."
            ),
            arguments=[
                types.PromptArgument(
                    name="hours_back",
                    description="Deadlock lookback window in hours (default: '24')",
                    required=False,
                ),
                types.PromptArgument(
                    name="min_duration_ms",
                    description="Slow query threshold in milliseconds (default: '1000')",
                    required=False,
                ),
            ],
        ),
        types.Prompt(
            name="remediate_incident",
            description=(
                "Structured triage and remediation guidance for platform incidents, "
                "ensuring safety, knowledge article referencing, and escalation."
            ),
            arguments=[
                types.PromptArgument(
                    name="incident_summary",
                    description="Summary of confirmed findings from diagnostic investigation",
                    required=True,
                ),
                types.PromptArgument(
                    name="ticket_id",
                    description="Optional SuperOffice ticket ID associated with the incident",
                    required=False,
                ),
            ],
        ),
    ]


def get_platform_prompt_result(
    name: str,
    arguments: dict[str, Any] | None = None,
) -> types.GetPromptResult:
    """Resolve and build a canonical MCP Prompt result by prompt name.

    Raises:
        ValueError: If prompt name is not recognized.
    """
    if name == "investigate_support_ticket":
        return _build_investigate_support_ticket_prompt(arguments)
    if name == "diagnose_database_performance":
        return _build_diagnose_database_performance_prompt(arguments)
    if name == "remediate_incident":
        return _build_remediate_incident_prompt(arguments)

    valid_names = [p.name for p in get_platform_prompts()]
    raise ValueError(f"Unknown prompt '{name}'. Available prompts: {valid_names}")
