# MCP Server Responsibilities

## 1. SuperOffice MCP

### Purpose

Provide controlled access to SuperOffice business entities and ticket operations.

### Owns

* tickets
* ticket history
* customers
* persons
* companies
* statuses
* notes
* replies
* attachments

### Does Not Own

* infrastructure
* Linux administration
* database diagnostics
* AI reasoning

### Example Tools

```text
get_ticket
search_tickets
get_ticket_history
get_customer
get_person
list_attachments
get_attachment_metadata
get_ticket_status
add_ticket_note
add_ticket_reply
update_ticket
```

---

# 2. Diagnostics MCP

## Purpose

Provide technical evidence for application and integration investigations.

### Owns

* application logs
* API logs
* HTTP errors
* timeout analysis
* correlation analysis
* database diagnostics

### Example Tools

```text
search_application_logs
search_api_logs
find_http_errors
find_timeout_errors
find_slow_queries
find_deadlocks
find_blocking_sessions
correlate_transaction
```

---

# 3. Knowledge MCP

## Purpose

Provide organizational technical knowledge.

### Owns

* documentation
* runbooks
* known issues
* historical incidents
* troubleshooting procedures
* resolution patterns

### Example Tools

```text
search_knowledge
get_runbook
find_known_issue
search_previous_incidents
get_resolution_pattern
```

---

# 4. Infrastructure MCP

## Purpose

Provide controlled infrastructure diagnostics.

### Owns

* server health
* service health
* CPU
* memory
* disk
* endpoint health
* load balancer health
* network connectivity

### Example Tools

```text
get_server_health
get_cpu_usage
get_memory_usage
get_disk_usage
get_service_status
check_endpoint
test_tcp_connection
check_load_balancer
get_node_health
```

---

# 5. Gateway

## Purpose

Security and access-control boundary.

### Owns

* authentication
* authorization
* RBAC
* tool permissions
* rate limiting
* audit correlation
* security policies
* output filtering

The Gateway does not own SuperOffice business logic.

---

# 6. Application Services

## Purpose

Implement cross-system business workflows.

Examples:

```text
Ticket Investigation
Incident Correlation
Attachment Processing
Knowledge Retrieval
Root Cause Analysis Support
```

Application services may orchestrate multiple MCP/integration capabilities but must not contain protocol-specific logic unnecessarily.

---

# 7. Integration Clients

## Purpose

Communicate with external systems.

Examples:

```text
SuperOffice API Client
MSSQL Client
Logging Client
Infrastructure Client
Supabase Client
```

Integration clients must be isolated behind interfaces so they can be mocked during testing.

---

# Ownership Rule

Every capability must have one clear owner.

Do not duplicate the same external-system logic across MCP servers.

If a capability crosses multiple domains, place orchestration in the application/service layer rather than creating cross-domain MCP servers.
