/**
 * SuperOffice CRM Onsite — Model Context Protocol (MCP) Server
 *
 * Exposes tools to interact with SuperOffice CRM Onsite REST WebAPI (v1)
 * over stdio for MCP clients (Claude Desktop, Cursor, Antigravity IDE, etc.).
 *
 * Supported Tools:
 *   - get_contact_by_id      : Fetch company/contact details by ID
 *   - search_persons         : Search contacts/persons by name or email
 *   - get_recent_appointments: Fetch upcoming or past calendar appointments
 *   - get_ticket_by_id       : Fetch support ticket details by ID
 *   - get_latest_tickets     : Fetch recent tickets with filtering
 *   - list_extra_tables      : List custom extra tables (y_* tables)
 *   - list_log_tables        : List logging and audit tables
 *   - query_extra_table      : Query rows from any custom extra table
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

// ─── Environment & Configuration ────────────────────────────────────────────

const API_URL = process.env.SUPEROFFICE_API_URL;
const USERNAME = process.env.SUPEROFFICE_USERNAME;
const PASSWORD = process.env.SUPEROFFICE_PASSWORD;

if (!API_URL || !USERNAME || !PASSWORD) {
  console.error(
    "[superoffice-mcp] Fatal: Missing required environment variables:\n" +
      "  - SUPEROFFICE_API_URL\n" +
      "  - SUPEROFFICE_USERNAME\n" +
      "  - SUPEROFFICE_PASSWORD"
  );
  process.exit(1);
}

// Normalize base URL (strip trailing slashes)
const BASE_URL = API_URL.replace(/\/+$/, "");

/** Global timeout (ms) for HTTP requests to SuperOffice WebAPI */
const REQUEST_TIMEOUT_MS = Number(process.env.SUPEROFFICE_TIMEOUT_MS) || 30_000;

// ─── HTTP Utilities ─────────────────────────────────────────────────────────

function authHeader(): string {
  const encoded = Buffer.from(`${USERNAME}:${PASSWORD}`).toString("base64");
  return `Basic ${encoded}`;
}

async function apiFetch<T = unknown>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    params?: Record<string, string>;
  } = {}
): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
  const { method = "GET", body, params } = options;

  let url = `${BASE_URL}${path}`;
  if (params) {
    const qs = new URLSearchParams(params).toString();
    if (qs) url += `?${qs}`;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const res = await fetch(url, {
      method,
      headers: {
        Authorization: authHeader(),
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return {
        ok: false,
        error: `SuperOffice API error (HTTP ${res.status} ${res.statusText}): ${text}`.trim(),
      };
    }

    const data = (await res.json()) as T;
    return { ok: true, data };
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") {
      return {
        ok: false,
        error: `Request timed out after ${REQUEST_TIMEOUT_MS / 1000}s. Server at ${BASE_URL} may be unreachable or slow.`,
      };
    }
    const message = err instanceof Error ? err.message : "Unknown network error";
    return {
      ok: false,
      error: `Network error contacting SuperOffice API (${BASE_URL}): ${message}`,
    };
  } finally {
    clearTimeout(timeout);
  }
}

// ─── Interfaces ─────────────────────────────────────────────────────────────

interface SOContact {
  ContactId: number;
  Name: string;
  Department: string;
  OrgNr: string;
  Number1: string;
  Number2: string;
  URL: string;
  City: string;
  Country: string;
  Emails?: { Value: string; Description: string }[];
  Phones?: { Value: string; Description: string }[];
  Description: string;
  Category?: { Value: string } | null;
  Business?: { Value: string } | null;
  CreatedDate: string;
  UpdatedDate: string;
}

interface SOPerson {
  PersonId: number;
  Firstname: string;
  Lastname: string;
  FullName: string;
  Title: string;
  Position: string;
  Email: string;
  DirectPhone: string;
  MobilePhone: string;
  ContactName: string;
  ContactId: number;
  Description: string;
}

interface SOAppointment {
  AppointmentId: number;
  StartDate: string;
  EndDate: string;
  Type: string;
  Task: string;
  Description: string;
  Location: string;
  ContactName: string;
  PersonFullName: string;
  Priority: string;
  Status: string;
  IsCompleted: boolean;
}

interface SOTicketSimple {
  TicketId: number;
  Title: string;
  CreatedAt: string;
  LastChanged: string;
  CreatedByName: string;
  Author: string;
  OwnedByName: string;
  Category: number;
  CategoryName: string;
  CategoryFullname: string;
  TicketStatusDisplayValue: string;
  PriorityName: string;
  Origin: string;
  ContactName: string;
  PersonFullname: string;
}

interface SOArchiveResult {
  RowCount: number;
  Rows?: Array<{
    PrimaryKey: number | string;
    EntityName: string;
    ColumnData: Record<string, { DisplayValue: string; RawValue: string }>;
  }>;
  value?: Array<Record<string, unknown>>;
}

function col(row: NonNullable<SOArchiveResult["Rows"]>[number], name: string): string {
  return row.ColumnData?.[name]?.DisplayValue ?? "";
}

// ─── Initialize MCP Server ──────────────────────────────────────────────────

const server = new McpServer({
  name: "superoffice-onsite-mcp",
  version: "1.1.0",
});

// ── Tool 1: get_contact_by_id ───────────────────────────────────────────────

server.tool(
  "get_contact_by_id",
  "Fetch contact (company/organization) details from SuperOffice CRM by Contact ID.",
  {
    contactId: z.number().int().positive().describe("Numeric Contact / Company ID"),
  },
  async ({ contactId }) => {
    const result = await apiFetch<SOContact>(`/api/v1/Contact/${contactId}`);
    if (!result.ok) {
      return { isError: true, content: [{ type: "text", text: `Error: ${result.error}` }] };
    }

    const c = result.data;
    const summary = [
      `# 🏢 Contact: ${c.Name}`,
      "",
      `| Field | Value |`,
      `|-------|-------|`,
      `| **Contact ID** | ${c.ContactId} |`,
      `| **Department** | ${c.Department || "—"} |`,
      `| **Org. Nr.** | ${c.OrgNr || "—"} |`,
      `| **City** | ${c.City || "—"} |`,
      `| **Country** | ${c.Country || "—"} |`,
      `| **Website** | ${c.URL || "—"} |`,
      `| **Category** | ${c.Category?.Value ?? "—"} |`,
      `| **Business** | ${c.Business?.Value ?? "—"} |`,
      `| **Created** | ${c.CreatedDate || "—"} |`,
      `| **Updated** | ${c.UpdatedDate || "—"} |`,
      "",
      c.Emails?.length ? `📧 **Emails:** ${c.Emails.map((e) => e.Value).join(", ")}` : "",
      c.Phones?.length ? `📞 **Phones:** ${c.Phones.map((p) => `${p.Value} (${p.Description})`).join(", ")}` : "",
      c.Description ? `\n📝 **Description:**\n${c.Description}` : "",
    ]
      .filter(Boolean)
      .join("\n");

    return { content: [{ type: "text", text: summary }] };
  }
);

// ── Tool 2: search_persons ──────────────────────────────────────────────────

server.tool(
  "search_persons",
  "Search for people / contact persons in SuperOffice CRM by name or email.",
  {
    query: z.string().min(1).describe("Search string (name, email, or partial match)"),
    limit: z.number().int().min(1).max(100).default(25).describe("Max results (1-100)"),
  },
  async ({ query, limit }) => {
    const archiveResult = await apiFetch<SOArchiveResult>(`/api/v1/Archive/FindPerson`, {
      params: {
        $select: "fullName,title,contactName,emailAddress,phone/formattedNumber,mobilePhone/formattedNumber",
        $filter: `fullName contains '${query}' or emailAddress contains '${query}'`,
        $top: String(limit),
      },
    });

    if (archiveResult.ok && archiveResult.data.Rows?.length) {
      const rows = archiveResult.data.Rows;
      const lines = [
        `Found **${rows.length}** person(s) for "${query}":`,
        "",
        "| ID | Name | Title | Company | Email | Phone | Mobile |",
        "|----|------|-------|---------|-------|-------|--------|",
        ...rows.map(
          (r) =>
            `| ${r.PrimaryKey} | ${col(r, "fullName")} | ${col(r, "title") || "—"} | ${col(r, "contactName") || "—"} | ${col(r, "emailAddress") || "—"} | ${col(r, "phone/formattedNumber") || "—"} | ${col(r, "mobilePhone/formattedNumber") || "—"} |`
        ),
      ];
      return { content: [{ type: "text", text: lines.join("\n") }] };
    }

    // Fallback to Person list endpoint
    const fallback = await apiFetch<SOPerson[]>(`/api/v1/Person`, {
      params: {
        $select: "personId,firstname,lastname,fullName,title,email,directPhone,mobilePhone,contactName,contactId",
        $filter: `fullName sw '${query}' or email sw '${query}'`,
        $top: String(limit),
      },
    });

    if (!fallback.ok) {
      return {
        isError: true,
        content: [{ type: "text", text: `Search failed: ${fallback.error}` }],
      };
    }

    const persons = fallback.data ?? [];
    if (!persons.length) {
      return { content: [{ type: "text", text: `No persons found matching "${query}".` }] };
    }

    const lines = [
      `Found **${persons.length}** person(s) for "${query}":`,
      "",
      "| ID | Name | Title | Company | Email | Phone | Mobile |",
      "|----|------|-------|---------|-------|-------|--------|",
      ...persons.map(
        (p) =>
          `| ${p.PersonId} | ${p.FullName || `${p.Firstname} ${p.Lastname}`} | ${p.Title || "—"} | ${p.ContactName || "—"} | ${p.Email || "—"} | ${p.DirectPhone || "—"} | ${p.MobilePhone || "—"} |`
      ),
    ];
    return { content: [{ type: "text", text: lines.join("\n") }] };
  }
);

// ── Tool 3: get_recent_appointments ─────────────────────────────────────────

server.tool(
  "get_recent_appointments",
  "Fetch calendar appointments from SuperOffice CRM within a date range.",
  {
    fromDate: z.string().optional().describe("Start date (YYYY-MM-DD), default: 7 days ago"),
    toDate: z.string().optional().describe("End date (YYYY-MM-DD), default: 14 days ahead"),
    associateId: z.number().int().positive().optional().describe("Filter by Associate (user) ID"),
    limit: z.number().int().min(1).max(200).default(50).describe("Max appointments to return"),
  },
  async ({ fromDate, toDate, associateId, limit }) => {
    const now = new Date();
    const defaultFrom = new Date(now);
    defaultFrom.setDate(defaultFrom.getDate() - 7);
    const defaultTo = new Date(now);
    defaultTo.setDate(defaultTo.getDate() + 14);

    const from = fromDate ?? defaultFrom.toISOString().slice(0, 10);
    const to = toDate ?? defaultTo.toISOString().slice(0, 10);

    const filterParts = [`startDate ge '${from}'`, `startDate le '${to}'`];
    if (associateId) filterParts.push(`associateId eq ${associateId}`);

    const res = await apiFetch<SOArchiveResult>(`/api/v1/Archive/Appointment`, {
      params: {
        $select: "appointmentId,startDate,endDate,type,taskName,description,location,contactName,personFullName,status,completed",
        $filter: filterParts.join(" and "),
        $orderby: "startDate asc",
        $top: String(limit),
      },
    });

    if (res.ok && res.data.Rows?.length) {
      const rows = res.data.Rows;
      const lines = [
        `📅 Found **${rows.length}** appointment(s) [${from} → ${to}]:`,
        "",
        "| ID | Start | End | Task | Description | Location | Contact | Person | Status |",
        "|----|-------|-----|------|-------------|----------|---------|--------|--------|",
        ...rows.map((r) => {
          const desc = col(r, "description");
          const shortDesc = desc.length > 50 ? desc.slice(0, 47) + "…" : desc || "—";
          const status = col(r, "completed") === "Yes" ? "Completed" : col(r, "status") || "—";
          return `| ${r.PrimaryKey} | ${col(r, "startDate")} | ${col(r, "endDate")} | ${col(r, "taskName") || "—"} | ${shortDesc} | ${col(r, "location") || "—"} | ${col(r, "contactName") || "—"} | ${col(r, "personFullName") || "—"} | ${status} |`;
        }),
      ];
      return { content: [{ type: "text", text: lines.join("\n") }] };
    }

    // Fallback to Appointment endpoint
    const fallback = await apiFetch<SOAppointment[]>(`/api/v1/Appointment`, {
      params: {
        $filter: filterParts.join(" and "),
        $orderby: "StartDate asc",
        $top: String(limit),
      },
    });

    if (!fallback.ok) {
      return { isError: true, content: [{ type: "text", text: `Error fetching appointments: ${fallback.error}` }] };
    }

    const appts = fallback.data ?? [];
    if (!appts.length) {
      return { content: [{ type: "text", text: `No appointments found between ${from} and ${to}.` }] };
    }

    const lines = [
      `📅 Found **${appts.length}** appointment(s) [${from} → ${to}]:`,
      "",
      "| ID | Start | End | Task | Description | Location | Contact | Person | Status |",
      "|----|-------|-----|------|-------------|----------|---------|--------|--------|",
      ...appts.map((a) => {
        const desc = a.Description ? (a.Description.length > 50 ? a.Description.slice(0, 47) + "…" : a.Description) : "—";
        return `| ${a.AppointmentId} | ${a.StartDate} | ${a.EndDate} | ${a.Task || "—"} | ${desc} | ${a.Location || "—"} | ${a.ContactName || "—"} | ${a.PersonFullName || "—"} | ${a.IsCompleted ? "Completed" : a.Status || "—"} |`;
      }),
    ];
    return { content: [{ type: "text", text: lines.join("\n") }] };
  }
);

// ── Tool 4: get_ticket_by_id ────────────────────────────────────────────────

server.tool(
  "get_ticket_by_id",
  "Fetch full details of a SuperOffice support ticket by Ticket ID, including category, status, and owner.",
  {
    ticketId: z.number().int().positive().describe("Numeric SuperOffice Ticket ID"),
  },
  async ({ ticketId }) => {
    const res = await apiFetch<SOTicketSimple>(`/api/v1/Ticket/${ticketId}/Simple`);
    if (!res.ok) {
      return { isError: true, content: [{ type: "text", text: `Error fetching ticket: ${res.error}` }] };
    }

    const t = res.data;
    const summary = [
      `# 🎫 Ticket #${t.TicketId}: ${t.Title}`,
      "",
      `| Property | Value |`,
      `|----------|-------|`,
      `| **Ticket ID** | ${t.TicketId} |`,
      `| **Title** | ${t.Title} |`,
      `| **Category** | ${t.CategoryFullname || t.CategoryName || (t.Category === 0 ? "*(None / ID 0)*" : `ID ${t.Category}`)} |`,
      `| **Status** | ${t.TicketStatusDisplayValue || "—"} |`,
      `| **Priority** | ${t.PriorityName || "—"} |`,
      `| **Created At** | ${t.CreatedAt || "—"} |`,
      `| **Created By** | ${t.CreatedByName || t.Author || "—"} |`,
      `| **Owner** | ${t.OwnedByName || "—"} |`,
      `| **Origin** | ${t.Origin || "—"} |`,
      `| **Contact** | ${t.ContactName || "—"} |`,
      `| **Person** | ${t.PersonFullname || "—"} |`,
    ].join("\n");

    return { content: [{ type: "text", text: summary }] };
  }
);

// ── Tool 5: get_latest_tickets ──────────────────────────────────────────────

server.tool(
  "get_latest_tickets",
  "Fetch recent support tickets from SuperOffice CRM with title, creation date, status, and IDs.",
  {
    limit: z.number().int().min(1).max(50).default(10).describe("Number of tickets to fetch"),
  },
  async ({ limit }) => {
    const res = await apiFetch<{ value: Array<Record<string, unknown>> }>(`/api/v1/Ticket`, {
      params: {
        $top: String(limit),
        $orderby: "ticketId desc",
        $select: "ticketId,title,createdAt,status",
      },
    });

    if (!res.ok) {
      return { isError: true, content: [{ type: "text", text: `Error: ${res.error}` }] };
    }

    const tickets = res.data.value ?? [];
    if (!tickets.length) {
      return { content: [{ type: "text", text: "No tickets found." }] };
    }

    const lines = [
      `🎫 **Latest ${tickets.length} Ticket(s):**`,
      "",
      "| ID | Title | Created At | Status |",
      "|----|-------|------------|--------|",
      ...tickets.map(
        (t) =>
          `| ${t.ticketId || t.PrimaryKey} | ${String(t.title || "—").replace(/\|/g, "/")} | ${t.createdAt || "—"} | ${t.status || "—"} |`
      ),
    ];
    return { content: [{ type: "text", text: lines.join("\n") }] };
  }
);

// ── Tool 6: list_extra_tables ───────────────────────────────────────────────

server.tool(
  "list_extra_tables",
  "List all custom extra tables (y_* tables) defined in the SuperOffice CRM database.",
  {},
  async () => {
    const res = await apiFetch<SOArchiveResult>(`/api/v1/Archive/Dynamic`, {
      params: {
        $select: "extra_tables.id,extra_tables.table_name",
        $top: "200",
      },
    });

    if (!res.ok) {
      return { isError: true, content: [{ type: "text", text: `Error: ${res.error}` }] };
    }

    const items = (res.data.value ?? []) as Array<{ "extra_tables.id"?: number; "extra_tables.table_name"?: string }>;
    if (!items.length) {
      return { content: [{ type: "text", text: "No extra tables found." }] };
    }

    const lines = [
      `📋 **Custom Extra Tables (${items.length} total):**`,
      "",
      "| ID | Table Name |",
      "|----|------------|",
      ...items.map((i) => `| ${i["extra_tables.id"]} | \`${i["extra_tables.table_name"]}\` |`),
    ];
    return { content: [{ type: "text", text: lines.join("\n") }] };
  }
);

// ── Tool 7: list_log_tables ─────────────────────────────────────────────────

server.tool(
  "list_log_tables",
  "List all dedicated logging and audit tables in SuperOffice CRM (e.g. y_logticket, y_logactivity, y_log_team).",
  {},
  async () => {
    const res = await apiFetch<SOArchiveResult>(`/api/v1/Archive/Dynamic`, {
      params: {
        $select: "extra_tables.id,extra_tables.table_name",
        $top: "200",
      },
    });

    if (!res.ok) {
      return { isError: true, content: [{ type: "text", text: `Error: ${res.error}` }] };
    }

    const items = ((res.data.value ?? []) as Array<{ "extra_tables.id"?: number; "extra_tables.table_name"?: string }>).filter(
      (i) => i["extra_tables.table_name"]?.toLowerCase().includes("log")
    );

    const lines = [
      `📝 **Logging & Audit Tables (${items.length} found):**`,
      "",
      "| ID | Table Name | Description |",
      "|----|------------|-------------|",
      ...items.map((i) => {
        const name = i["extra_tables.table_name"] || "";
        let desc = "Custom audit/logging table";
        if (name.includes("msisdn")) desc = "Phone number search audit log";
        if (name.includes("team")) desc = "Team assignment modification log";
        if (name.includes("activity")) desc = "User/system activity log";
        if (name.includes("ticket")) desc = "Ticket change event log";
        return `| ${i["extra_tables.id"]} | \`${name}\` | ${desc} |`;
      }),
      "",
      "### Built-in System Event Providers:",
      "- `ErpSyncLog` — ERP synchronization log",
      "- `SystemEvents` — Core system event log",
      "- `EventHandler` — CRMScript event handler registry",
      "- `SaleHistory` — Sales stage change audit log",
    ];

    return { content: [{ type: "text", text: lines.join("\n") }] };
  }
);

// ── Tool 8: query_extra_table ───────────────────────────────────────────────

server.tool(
  "query_extra_table",
  "Query rows from any custom extra table (y_*) in SuperOffice via the Dynamic archive provider.",
  {
    tableName: z.string().describe("Name of the table (e.g., 'y_interaction', 'y_logticket', 'y_case_categories')"),
    fields: z.string().optional().describe("Comma-separated fields to select (defaults to id)"),
    limit: z.number().int().min(1).max(100).default(25).describe("Max rows to return"),
  },
  async ({ tableName, fields, limit }) => {
    const cleanTable = tableName.trim().toLowerCase();
    const selectField = fields
      ? fields
          .split(",")
          .map((f) => (f.includes(".") ? f.trim() : `${cleanTable}.${f.trim()}`))
          .join(",")
      : `${cleanTable}.id`;

    const res = await apiFetch<SOArchiveResult>(`/api/v1/Archive/Dynamic`, {
      params: {
        $select: selectField,
        $top: String(limit),
      },
    });

    if (!res.ok) {
      return { isError: true, content: [{ type: "text", text: `Error querying ${cleanTable}: ${res.error}` }] };
    }

    const rows = res.data.value ?? [];
    if (!rows.length) {
      return { content: [{ type: "text", text: `No records found in table \`${cleanTable}\`.` }] };
    }

    const keys = Object.keys(rows[0]).filter((k) => !k.startsWith("odata."));
    const header = `| ${keys.join(" | ")} |`;
    const separator = `| ${keys.map(() => "---").join(" | ")} |`;
    const dataLines = rows.map((r) => `| ${keys.map((k) => String(r[k] ?? "—")).join(" | ")} |`);

    const resultText = [
      `📊 **Results from \`${cleanTable}\` (${rows.length} rows):**`,
      "",
      header,
      separator,
      ...dataLines,
    ].join("\n");

    return { content: [{ type: "text", text: resultText }] };
  }
);

// ─── Server Startup ─────────────────────────────────────────────────────────

async function main(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(`[superoffice-mcp] Server v1.1.0 started — connected to ${BASE_URL}`);
}

main().catch((err) => {
  console.error("[superoffice-mcp] Fatal startup error:", err);
  process.exit(1);
});
