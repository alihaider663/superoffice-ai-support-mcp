"""Direct MSSQL Extractor for SuperOffice codebase sync under SNAPSHOT isolation."""

import logging
import urllib.parse
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

try:
    import pyodbc  # type: ignore[import-not-found]
except ImportError:
    pyodbc = None  # type: ignore[assignment]

from so_mcp.sync.contracts import (
    ExtraTableSchemaDTO,
    HierarchyNodeDTO,
    ScreenRecordDTO,
    ScriptRecordDTO,
)

logger = logging.getLogger(__name__)


def create_mssql_sync_engine(  # noqa: PLR0917
    host: str = "localhost",
    port: int = 1433,
    database: str = "SuperOffice",
    user: str = "so_readonly_user",
    password: str = "insecure-dev-placeholder",
    trust_cert: bool = True,
    isolation_level: str = "READ COMMITTED",
    login_timeout_seconds: int = 5,
    query_timeout_seconds: int = 5,
) -> AsyncEngine:
    """Create a SQLAlchemy AsyncEngine configured for SuperOffice database extraction."""
    if pyodbc is not None:
        pyodbc.pooling = False

    trust_str = "yes" if trust_cert else "no"
    odbc_params = [
        "Driver={ODBC Driver 18 for SQL Server}",
        f"Server=tcp:{host},{port}",
        f"Database={database}",
        f"UID={user}",
        f"PWD={password}",
        "Encrypt=yes",
        f"TrustServerCertificate={trust_str}",
        f"LoginTimeout={login_timeout_seconds}",
    ]
    odbc_str = ";".join(odbc_params)
    quoted_odbc_str = urllib.parse.quote_plus(odbc_str)
    connection_url = f"mssql+aioodbc:///?odbc_connect={quoted_odbc_str}"

    async def _configure_pyodbc_connection(pyodbc_conn: Any) -> None:
        if hasattr(pyodbc_conn, "timeout"):
            pyodbc_conn.timeout = query_timeout_seconds

    return create_async_engine(
        connection_url,
        poolclass=AsyncAdaptedQueuePool,
        isolation_level=isolation_level,
        connect_args={
            "after_created": _configure_pyodbc_connection,
            "timeout": login_timeout_seconds,
        },
    )


class MssqlExtractorError(Exception):
    """Raised when database extraction fails."""


class SuperOfficeMssqlExtractor:
    """Extracts scripts, screens, and schema directly from Microsoft SQL Server."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def fetch_hierarchy_tree(self) -> dict[int, str]:
        """Fetch hierarchy table and build recursive path map."""
        sql = text("SELECT id, parent_id, name FROM dbo.hierarchy ORDER BY id ASC;")

        nodes: dict[int, HierarchyNodeDTO] = {}
        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(sql)
                rows = result.fetchall()
                for r in rows:
                    hid = int(r[0])
                    pid = int(r[1]) if r[1] is not None else None
                    name = str(r[2] or f"folder_{hid}").strip()
                    nodes[hid] = HierarchyNodeDTO(id=hid, parent_id=pid, name=name)
        except Exception as exc:
            logger.warning("Failed to fetch hierarchy tree from database: %s", exc)
            return {}

        path_map: dict[int, str] = {}

        def _get_path(node_id: int, visited: set[int]) -> str:
            if node_id in visited or node_id not in nodes:
                return ""
            visited.add(node_id)
            node = nodes[node_id]
            if node.parent_id and node.parent_id in nodes:
                parent_path = _get_path(node.parent_id, visited)
                return f"{parent_path}/{node.name}".strip("/")
            return node.name

        for nid in nodes:
            path_map[nid] = _get_path(nid, set())

        return path_map

    async def fetch_scripts(
        self, hierarchy_map: dict[int, str] | None = None
    ) -> list[ScriptRecordDTO]:
        """Fetch all CRMScripts from dbo.ejscript."""
        h_map = hierarchy_map or {}
        sql = text(
            "SELECT id, "
            "COALESCE(NULLIF(include_id, ''), NULLIF(unique_identifier, ''), "
            "description, CONCAT('script_', id)) AS script_name, "
            "description, body, updated, hierarchy_id, include_id "
            "FROM dbo.ejscript "
            "ORDER BY id ASC;"
        )

        scripts: list[ScriptRecordDTO] = []
        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(sql)
                rows = result.fetchall()
                for r in rows:
                    sid = int(r[0])
                    name = str(r[1] or f"script_{sid}").strip()
                    desc = str(r[2] or "").strip()
                    body = str(r[3] or "")
                    updated = str(r[4] or "")
                    hid = int(r[5]) if r[5] is not None else None
                    include_id = str(r[6] or "").strip() or None

                    if hid and hid in h_map:
                        h_path = h_map[hid]
                    elif hid:
                        h_path = f"folder_{hid}"
                    else:
                        h_path = "Scripts"

                    scripts.append(
                        ScriptRecordDTO(
                            id=sid,
                            name=name,
                            description=desc,
                            body=body,
                            updated=updated,
                            hierarchy_id=hid,
                            hierarchy_path=h_path,
                            include_id=include_id,
                        )
                    )
        except Exception as exc:
            raise MssqlExtractorError(f"Database query on dbo.ejscript failed: {exc}") from exc

        return scripts

    async def _fetch_actions_by_screen(self, conn: Any) -> dict[int, list[dict[str, Any]]]:
        a_sql = text(
            "SELECT id, screen_definition, button, ejscript, ejscript_body, do_check "
            "FROM dbo.screen_definition_action ORDER BY id ASC;"
        )
        actions_by_screen: dict[int, list[dict[str, Any]]] = {}
        try:
            a_res = await conn.execute(a_sql)
            for ar in a_res.fetchall():
                aid = int(ar[0])
                screen_id = int(ar[1]) if ar[1] is not None else 0
                actions_by_screen.setdefault(screen_id, []).append(
                    {
                        "id": aid,
                        "screen_definition": screen_id,
                        "button": str(ar[2] or "").strip(),
                        "ejscript": int(ar[3]) if ar[3] is not None else None,
                        "ejscript_body": str(ar[4] or ""),
                        "do_check": ar[5],
                    }
                )
        except Exception as a_exc:
            logger.warning("Failed to fetch screen_definition_action: %s", a_exc)
        return actions_by_screen

    async def _fetch_elements_by_screen(self, conn: Any) -> dict[int, list[dict[str, Any]]]:
        e_sql = text(
            "SELECT id, screen_definition, name, element_type, description, "
            "creation_script, order_pos, base_table, hide "
            "FROM dbo.screen_definition_element ORDER BY screen_definition ASC, order_pos ASC;"
        )
        elements_by_screen: dict[int, list[dict[str, Any]]] = {}
        try:
            e_res = await conn.execute(e_sql)
            for er in e_res.fetchall():
                eid = int(er[0])
                screen_id = int(er[1]) if er[1] is not None else 0
                elements_by_screen.setdefault(screen_id, []).append(
                    {
                        "id": eid,
                        "screen_definition": screen_id,
                        "name": str(er[2] or "").strip(),
                        "element_type": er[3],
                        "description": str(er[4] or ""),
                        "creation_script": str(er[5] or ""),
                        "order_pos": er[6],
                        "base_table": str(er[7] or ""),
                        "hide": er[8],
                    }
                )
        except Exception as e_exc:
            logger.warning("Failed to fetch screen_definition_element: %s", e_exc)
        return elements_by_screen

    async def fetch_screens(self) -> list[ScreenRecordDTO]:
        """Fetch screen definitions including scripts, button actions, and elements."""
        s_sql = text(
            "SELECT id, name, description, id_string, screen_key, layout_model, "
            "load_script_body, load_post_cgi_script_body, load_final_script_body, "
            "creation_script, hierarchy_id, warn_on_navigate, autosave "
            "FROM dbo.screen_definition ORDER BY id ASC;"
        )

        try:
            async with self._engine.connect() as conn:
                s_res = await conn.execute(s_sql)
                s_rows = s_res.fetchall()
                actions_by_screen = await self._fetch_actions_by_screen(conn)
                elements_by_screen = await self._fetch_elements_by_screen(conn)
        except Exception as exc:
            logger.warning("Failed to fetch screen_definition from database: %s", exc)
            return []

        results: list[ScreenRecordDTO] = []
        for r in s_rows:
            sid = int(r[0])
            sname = str(r[1] or f"screen_{sid}").strip()
            sdesc = str(r[2] or "").strip()
            id_str = str(r[3] or "").strip()
            skey = str(r[4] or "").strip()
            screen_actions = actions_by_screen.get(sid, [])
            screen_elements = elements_by_screen.get(sid, [])

            results.append(
                ScreenRecordDTO(
                    id=sid,
                    name=sname,
                    table_name="screen_definition",
                    description=sdesc,
                    id_string=id_str,
                    screen_key=skey,
                    load_script_body=str(r[6] or ""),
                    load_post_cgi_script_body=str(r[7] or ""),
                    load_final_script_body=str(r[8] or ""),
                    creation_script=str(r[9] or ""),
                    actions=screen_actions,
                    elements=screen_elements,
                    data={
                        "id": sid,
                        "name": sname,
                        "description": sdesc,
                        "id_string": id_str,
                        "screen_key": skey,
                        "layout_model": r[5],
                        "hierarchy_id": int(r[10]) if r[10] is not None else None,
                        "warn_on_navigate": r[11],
                        "autosave": r[12],
                        "actions": screen_actions,
                        "elements": screen_elements,
                    },
                )
            )

        return results

    async def fetch_extra_tables(self) -> list[ExtraTableSchemaDTO]:
        """Fetch custom extra tables and extra fields."""
        t_sql = text(
            "SELECT id, table_name, name, description FROM dbo.extra_tables ORDER BY id ASC;"
        )
        f_sql = text(
            "SELECT id, extra_table, field_name, name, type, default_value, description "
            "FROM dbo.extra_fields "
            "ORDER BY id ASC;"
        )

        try:
            async with self._engine.connect() as conn:
                t_result = await conn.execute(t_sql)
                t_rows = t_result.fetchall()

                f_result = await conn.execute(f_sql)
                f_rows = f_result.fetchall()
        except Exception as exc:
            logger.warning("Failed to fetch extra_tables/extra_fields: %s", exc)
            return []

        fields_by_table: dict[int, list[dict[str, Any]]] = {}
        for f in f_rows:
            fid = int(f[0])
            tid = int(f[1]) if f[1] is not None else 0
            fname = str(f[2] or "")
            flabel = str(f[3] or "")
            ftype = int(f[4]) if f[4] is not None else 0
            fdefault = str(f[5] or "")
            fdesc = str(f[6] or "")
            fields_by_table.setdefault(tid, []).append(
                {
                    "id": fid,
                    "extra_table_id": tid,
                    "field_name": fname,
                    "name": flabel,
                    "type": ftype,
                    "default_value": fdefault,
                    "description": fdesc,
                }
            )

        schemas: list[ExtraTableSchemaDTO] = []
        for t in t_rows:
            tid = int(t[0])
            tname = str(t[1] or f"y_table_{tid}")
            schemas.append(
                ExtraTableSchemaDTO(
                    id=tid,
                    table_name=tname,
                    fields=fields_by_table.get(tid, []),
                )
            )

        return schemas
