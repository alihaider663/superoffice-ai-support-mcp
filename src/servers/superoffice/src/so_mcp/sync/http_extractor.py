"""HTTP Extractor for SuperOffice codebase sync via CRMScript handler."""

import base64
import json
import logging
from typing import Any
from urllib.parse import urljoin

import httpx

from so_mcp.sync.contracts import (
    ExtraTableSchemaDTO,
    HierarchyNodeDTO,
    ScreenRecordDTO,
    ScriptRecordDTO,
)

logger = logging.getLogger(__name__)


class HttpExtractorError(Exception):
    """Raised when HTTP extraction from SuperOffice fails."""


class SuperOfficeHttpExtractor:
    """Extracts scripts, screens, and schema configurations via SuperOffice HTTP endpoint."""

    def __init__(
        self,
        base_url: str,
        endpoint_path: str,
        username: str,
        password: str,
        *,
        allow_self_signed_cert: bool = False,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._endpoint_path = endpoint_path.lstrip("/")
        self._target_url = urljoin(self._base_url, self._endpoint_path)
        self._username = username
        self._password = password
        self._allow_self_signed_cert = allow_self_signed_cert
        self._timeout_seconds = timeout_seconds
        self._client = client

    def _get_auth_header(self) -> str:
        credentials = f"{self._username}:{self._password}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        return f"Basic {encoded}"

    async def _execute_get(self, params: dict[str, str]) -> list[dict[str, Any]]:
        """Execute a GET request against the CRMScript sync handler."""
        headers = {
            "Authorization": self._get_auth_header(),
            "Accept": "application/json",
        }

        async def _do_request(http_client: httpx.AsyncClient) -> httpx.Response:
            return await http_client.get(
                self._target_url,
                params=params,
                headers=headers,
                timeout=self._timeout_seconds,
            )

        if self._client:
            resp = await _do_request(self._client)
        else:
            async with httpx.AsyncClient(verify=not self._allow_self_signed_cert) as client:
                resp = await _do_request(client)

        if resp.status_code != 200:
            msg = (
                f"HTTP request to {self._target_url} failed with status "
                f"{resp.status_code}: {resp.text[:300]}"
            )
            raise HttpExtractorError(msg)

        text = resp.text.strip()
        if not text:
            return []

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            msg = f"Failed to parse JSON response from {self._target_url}: {text[:200]}"
            raise HttpExtractorError(msg) from exc

        return self._normalize_rows(data, params.get("table", ""))

    def _extract_raw_items(self, data: Any, table_name: str) -> list[Any]:
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        for key in (table_name, "", "value", "rows"):
            if key in data and isinstance(data[key], list):
                return data[key]
        for val in data.values():
            if isinstance(val, list):
                return val
        return [data] if data else []

    def _normalize_rows(self, data: Any, table_name: str) -> list[dict[str, Any]]:
        """Normalize JSONBuilder output variations into a flat list of dictionaries."""
        raw_items = self._extract_raw_items(data, table_name)
        normalized: list[dict[str, Any]] = []
        prefix = f"{table_name}." if table_name else ""

        for item in raw_items:
            if not isinstance(item, dict):
                continue
            cleaned: dict[str, Any] = {}
            for k, v in item.items():
                clean_key = k[len(prefix) :] if prefix and k.startswith(prefix) else k
                cleaned[clean_key] = v
            normalized.append(cleaned)

        return normalized

    async def fetch_hierarchy_tree(self) -> dict[int, str]:
        """Attempt to fetch the folder hierarchy tree.

        Returns a dictionary mapping hierarchy_id to full folder path (e.g. 'Scripts/Tickets').
        Gracefully returns an empty dictionary if the table is unsupported.
        """
        try:
            rows = await self._execute_get({"table": "hierarchy", "fields": "id,parent_id,name"})
        except HttpExtractorError as exc:
            logger.info(
                "Hierarchy table not accessible over HTTP handler (%s); fallback to ID paths",
                exc,
            )
            return {}

        nodes: dict[int, HierarchyNodeDTO] = {}
        for r in rows:
            raw_id = r.get("id") or r.get("hierarchy_id")
            if raw_id is not None:
                try:
                    nid = int(raw_id)
                    p_raw = r.get("parent_id")
                    pid = int(p_raw) if p_raw is not None and str(p_raw).isdigit() else None
                    name = str(r.get("name") or f"folder_{nid}").strip()
                    nodes[nid] = HierarchyNodeDTO(id=nid, parent_id=pid, name=name)
                except (ValueError, TypeError):
                    continue

        # Reconstruct recursive full paths
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
        """Fetch all CRMScripts from ejscript table."""
        h_map = hierarchy_map or {}
        fields = "id,name,description,body,updated,hierarchy_id,include_id"
        rows = await self._execute_get({"table": "ejscript", "fields": fields})

        scripts: list[ScriptRecordDTO] = []
        for r in rows:
            raw_id = r.get("id") or r.get("ejscript_id")
            if raw_id is None:
                continue
            try:
                sid = int(raw_id)
            except (ValueError, TypeError):
                continue

            name = str(r.get("name") or f"script_{sid}").strip()
            desc = str(r.get("description") or "").strip()
            body = str(r.get("body") or "")
            updated = str(r.get("updated") or "")
            include_id = str(r.get("include_id") or "").strip() or None

            hid_raw = r.get("hierarchy_id")
            hid = int(hid_raw) if hid_raw is not None and str(hid_raw).isdigit() else None

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

        return scripts

    async def fetch_screens(self) -> list[ScreenRecordDTO]:
        """Fetch screen configurations across definition and element tables."""
        tables = [
            "screen_definition",
            "screen_definition_element",
            "screen_definition_action",
            "screen_definition_hidden",
            "screen_definition_language",
        ]
        results: list[ScreenRecordDTO] = []
        for tbl in tables:
            try:
                rows = await self._execute_get({"table": tbl, "fields": "id,name"})
                for r in rows:
                    raw_id = r.get("id")
                    if raw_id is not None:
                        try:
                            sid = int(raw_id)
                            sname = str(r.get("name") or f"{tbl}_{sid}")
                            results.append(
                                ScreenRecordDTO(id=sid, name=sname, table_name=tbl, data=r)
                            )
                        except (ValueError, TypeError):
                            continue
            except HttpExtractorError as exc:
                logger.warning("Failed to extract screen table %s: %s", tbl, exc)

        return results

    async def fetch_extra_tables(self) -> list[ExtraTableSchemaDTO]:
        """Fetch custom extra tables (extra_tables) and custom fields (extra_fields)."""
        table_rows = await self._execute_get({"table": "extra_tables", "fields": "id,table_name"})
        try:
            field_rows = await self._execute_get(
                {"table": "extra_fields", "fields": "id,extra_table_id,field_name,type"}
            )
        except HttpExtractorError:
            field_rows = []

        fields_by_table: dict[int, list[dict[str, Any]]] = {}
        for f in field_rows:
            t_id_raw = f.get("extra_table_id")
            if t_id_raw is not None:
                try:
                    t_id = int(t_id_raw)
                    fields_by_table.setdefault(t_id, []).append(f)
                except (ValueError, TypeError):
                    continue

        schemas: list[ExtraTableSchemaDTO] = []
        for t in table_rows:
            raw_id = t.get("id")
            if raw_id is None:
                continue
            try:
                tid = int(raw_id)
                tname = str(t.get("table_name") or f"y_table_{tid}")
                schemas.append(
                    ExtraTableSchemaDTO(
                        id=tid,
                        table_name=tname,
                        fields=fields_by_table.get(tid, []),
                    )
                )
            except (ValueError, TypeError):
                continue

        return schemas

    async def fetch_configs(self) -> dict[str, list[dict[str, Any]]]:
        """Fetch configuration items like item_config and screen_chooser."""
        configs: dict[str, list[dict[str, Any]]] = {}
        for tbl in ["item_config", "screen_chooser"]:
            try:
                rows = await self._execute_get({"table": tbl, "fields": "id,name"})
                configs[tbl] = rows
            except HttpExtractorError as exc:
                logger.warning("Config table %s not retrieved: %s", tbl, exc)
                configs[tbl] = []
        return configs
