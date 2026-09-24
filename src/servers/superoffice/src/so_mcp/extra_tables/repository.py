"""Repository for SuperOffice extra tables catalog introspection and query execution."""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from so_mcp.extra_tables.contracts import (
    SUPEROFFICE_STANDARD_COLUMNS,
    ExtraFieldDefinitionDTO,
    ExtraTableDetailSchemaDTO,
    ExtraTableQueryCriteriaDTO,
    ExtraTableQueryResultDTO,
    ExtraTableSummaryDTO,
    SuperOfficeExtraTableQueryError,
    get_field_type_name,
)
from so_mcp.extra_tables.validator import ExtraTableSecurityValidator

logger = logging.getLogger(__name__)


def _serialize_cell_value(val: Any) -> Any:
    """Format database cell value into JSON-serializable representation."""
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, bytes):
        return val.hex()
    return val


class ExtraTableRepositoryProtocol(Protocol):
    """Protocol defining extra table catalog discovery and querying interface."""

    async def get_table_catalog(self) -> dict[str, ExtraTableDetailSchemaDTO]:
        """Fetch all registered extra tables mapped by normalized table name."""
        ...

    async def list_tables(self, search: str | None = None) -> list[ExtraTableSummaryDTO]:
        """Return list of extra table summaries with field counts."""
        ...

    async def get_table_schema(self, table_name: str) -> ExtraTableDetailSchemaDTO | None:
        """Return schema details for a specific extra table."""
        ...

    async def query_table(
        self,
        criteria: ExtraTableQueryCriteriaDTO,
        schema: ExtraTableDetailSchemaDTO,
    ) -> ExtraTableQueryResultDTO:
        """Execute a secure, parameterized query against a target extra table."""
        ...


class MssqlExtraTableRepository:
    """Production MSSQL implementation using SQLAlchemy AsyncEngine under READ COMMITTED."""

    def __init__(
        self,
        engine: AsyncEngine,
        fallback_repo: ExtraTableRepositoryProtocol | None = None,
    ) -> None:
        self._engine = engine
        self._fallback_repo = fallback_repo
        self._cached_catalog: dict[str, ExtraTableDetailSchemaDTO] | None = None

    async def get_table_catalog(
        self,
        force_refresh: bool = False,
    ) -> dict[str, ExtraTableDetailSchemaDTO]:
        """Fetch and cache extra_tables and extra_fields catalog from database."""
        if self._cached_catalog is not None and not force_refresh:
            return self._cached_catalog

        t_sql = text(
            "SELECT id, table_name, name, description FROM dbo.extra_tables ORDER BY id ASC;"
        )
        f_sql = text(
            "SELECT id, extra_table, field_name, name, type, default_value, description "
            "FROM dbo.extra_fields ORDER BY id ASC;"
        )

        try:
            async with self._engine.connect() as conn:
                t_result = await conn.execute(t_sql)
                t_rows = t_result.fetchall()

                f_result = await conn.execute(f_sql)
                f_rows = f_result.fetchall()
        except Exception as exc:
            if self._fallback_repo is not None:
                logger.warning(
                    "MSSQL catalog query failed (%s). Falling back to local mirror.",
                    exc,
                )
                fallback_catalog = await self._fallback_repo.get_table_catalog()
                if fallback_catalog:
                    self._cached_catalog = fallback_catalog
                    return fallback_catalog
            logger.error("Failed to fetch extra_tables catalog from database: %s", exc)
            raise SuperOfficeExtraTableQueryError(
                message=f"Failed to query SuperOffice extra table catalog: {exc}",
                table_name="dbo.extra_tables",
            ) from exc

        fields_by_table_id: dict[int, list[ExtraFieldDefinitionDTO]] = {}
        for f in f_rows:
            fid = int(f[0])
            tid = int(f[1]) if f[1] is not None else 0
            fname = str(f[2] or "").strip()
            flabel = str(f[3] or "").strip()
            ftype = int(f[4]) if f[4] is not None else 0
            fdefault = str(f[5] or "").strip()
            fdesc = str(f[6] or "").strip()

            fields_by_table_id.setdefault(tid, []).append(
                ExtraFieldDefinitionDTO(
                    id=fid,
                    extra_table_id=tid,
                    field_name=fname,
                    display_name=flabel,
                    type_code=ftype,
                    type_name=get_field_type_name(ftype),
                    default_value=fdefault,
                    description=fdesc,
                )
            )

        catalog: dict[str, ExtraTableDetailSchemaDTO] = {}
        for t in t_rows:
            tid = int(t[0])
            raw_tname = str(t[1] or "").strip()
            if not raw_tname:
                continue
            normalized_name = ExtraTableSecurityValidator.normalize_table_name(raw_tname)
            dname = str(t[2] or normalized_name).strip()
            desc = str(t[3] or "").strip()

            table_fields = tuple(fields_by_table_id.get(tid, []))
            catalog[normalized_name] = ExtraTableDetailSchemaDTO(
                id=tid,
                table_name=normalized_name,
                display_name=dname,
                description=desc,
                fields=table_fields,
                standard_columns=SUPEROFFICE_STANDARD_COLUMNS,
            )

        self._cached_catalog = catalog
        return catalog

    async def list_tables(self, search: str | None = None) -> list[ExtraTableSummaryDTO]:
        """Return summaries of all registered extra tables."""
        catalog = await self.get_table_catalog()
        summaries: list[ExtraTableSummaryDTO] = []
        search_lower = search.strip().lower() if search else None

        for table in catalog.values():
            if search_lower and (
                search_lower not in table.table_name.lower()
                and search_lower not in table.display_name.lower()
                and search_lower not in table.description.lower()
            ):
                continue
            summaries.append(
                ExtraTableSummaryDTO(
                    id=table.id,
                    table_name=table.table_name,
                    display_name=table.display_name,
                    description=table.description,
                    field_count=len(table.fields),
                )
            )

        summaries.sort(key=lambda s: s.table_name)
        return summaries

    async def get_table_schema(self, table_name: str) -> ExtraTableDetailSchemaDTO | None:
        """Return complete schema for a specific table."""
        catalog = await self.get_table_catalog()
        normalized = ExtraTableSecurityValidator.normalize_table_name(table_name)
        return catalog.get(normalized)

    async def query_table(
        self,
        criteria: ExtraTableQueryCriteriaDTO,
        schema: ExtraTableDetailSchemaDTO,
    ) -> ExtraTableQueryResultDTO:
        """Execute a secure, parameterized query with column whitelisting and pagination."""
        # 1. Determine projected columns
        if criteria.fields:
            selected_cols = ExtraTableSecurityValidator.validate_columns_for_table(
                criteria.table_name, criteria.fields, schema
            )
        else:
            # Default projection: id + all defined extra fields
            field_names = [f.field_name for f in schema.fields]
            cols = ["id"] + [f for f in field_names if f.lower() != "id"]
            selected_cols = ExtraTableSecurityValidator.validate_columns_for_table(
                criteria.table_name, cols, schema
            )

        # 2. Build column selection string with SQL brackets
        col_clause = ", ".join(f"[{col}]" for col in selected_cols)

        # 3. Build WHERE clause with parameterized bindings
        where_clauses: list[str] = []
        bind_params: dict[str, Any] = {}

        if criteria.filters:
            validated_filters = ExtraTableSecurityValidator.validate_filter_keys(
                criteria.table_name, criteria.filters, schema
            )
            for idx, (col_name, col_val) in enumerate(validated_filters.items()):
                param_key = f"p_{idx}"
                if col_val is None:
                    where_clauses.append(f"[{col_name}] IS NULL")
                else:
                    where_clauses.append(f"[{col_name}] = :{param_key}")
                    bind_params[param_key] = col_val

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # 4. Validate order_by and order_direction
        order_col = ExtraTableSecurityValidator.validate_order_by(
            criteria.table_name, criteria.order_by, schema
        )
        direction = "DESC" if criteria.order_direction.lower() == "desc" else "ASC"
        order_sql = f"ORDER BY [{order_col}] {direction}"

        # 5. Pagination bounds
        bind_params["p_offset"] = criteria.offset
        bind_params["p_limit"] = criteria.limit

        table_sql = f"dbo.[{schema.table_name}]"
        sql_query = (
            f"SELECT {col_clause} FROM {table_sql} "
            f"{where_sql} "
            f"{order_sql} "
            f"OFFSET :p_offset ROWS FETCH NEXT :p_limit ROWS ONLY;"
        )

        try:
            async with self._engine.connect() as conn:
                stmt = text(sql_query)
                result = await conn.execute(stmt, bind_params)
                raw_rows = result.fetchall()
        except Exception as exc:
            logger.error("Failed to query extra table %s: %s", schema.table_name, exc)
            raise SuperOfficeExtraTableQueryError(
                message=f"Database execution error querying table '{schema.table_name}': {exc}",
                table_name=schema.table_name,
            ) from exc

        # 6. Map rows to dictionaries
        rows: list[dict[str, Any]] = []
        for r in raw_rows:
            row_dict: dict[str, Any] = {}
            for col_idx, col_name in enumerate(selected_cols):
                row_dict[col_name] = _serialize_cell_value(r[col_idx])
            rows.append(row_dict)

        return ExtraTableQueryResultDTO(
            table_name=schema.table_name,
            total_rows_returned=len(rows),
            limit=criteria.limit,
            offset=criteria.offset,
            columns=tuple(selected_cols),
            rows=tuple(rows),
        )


class LocalMirrorExtraTableRepository:
    """Fallback repository introspecting schema from local mirror (schema/extra_tables.json)."""

    def __init__(self, mirror_root: Path) -> None:
        self._mirror_root = mirror_root
        self._cached_catalog: dict[str, ExtraTableDetailSchemaDTO] | None = None

    def _load_schema_file(self) -> dict[str, ExtraTableDetailSchemaDTO]:
        schema_file = self._mirror_root / "schema" / "extra_tables.json"
        if not schema_file.exists():
            return {}

        try:
            with schema_file.open(encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            logger.warning("Failed to read mirrored extra_tables.json: %s", exc)
            return {}

        catalog: dict[str, ExtraTableDetailSchemaDTO] = {}
        for item in data:
            tid = int(item.get("id", 0))
            raw_tname = str(item.get("table_name", "")).strip()
            if not raw_tname:
                continue
            normalized = ExtraTableSecurityValidator.normalize_table_name(raw_tname)
            dname = str(item.get("name") or normalized).strip()
            desc = str(item.get("description") or "").strip()

            fields: list[ExtraFieldDefinitionDTO] = []
            for f in item.get("fields", []):
                fid = int(f.get("id", 0))
                fname = str(f.get("field_name", "")).strip()
                flabel = str(f.get("name", "")).strip()
                ftype = int(f.get("type", 0))
                fdefault = str(f.get("default_value", "")).strip()
                fdesc = str(f.get("description", "")).strip()
                fields.append(
                    ExtraFieldDefinitionDTO(
                        id=fid,
                        extra_table_id=tid,
                        field_name=fname,
                        display_name=flabel,
                        type_code=ftype,
                        type_name=get_field_type_name(ftype),
                        default_value=fdefault,
                        description=fdesc,
                    )
                )

            catalog[normalized] = ExtraTableDetailSchemaDTO(
                id=tid,
                table_name=normalized,
                display_name=dname,
                description=desc,
                fields=tuple(fields),
                standard_columns=SUPEROFFICE_STANDARD_COLUMNS,
            )

        return catalog

    async def get_table_catalog(self) -> dict[str, ExtraTableDetailSchemaDTO]:
        if self._cached_catalog is None:
            self._cached_catalog = self._load_schema_file()
        return self._cached_catalog

    async def list_tables(self, search: str | None = None) -> list[ExtraTableSummaryDTO]:
        catalog = await self.get_table_catalog()
        summaries: list[ExtraTableSummaryDTO] = []
        search_lower = search.strip().lower() if search else None

        for table in catalog.values():
            if search_lower and (
                search_lower not in table.table_name.lower()
                and search_lower not in table.display_name.lower()
            ):
                continue
            summaries.append(
                ExtraTableSummaryDTO(
                    id=table.id,
                    table_name=table.table_name,
                    display_name=table.display_name,
                    description=table.description,
                    field_count=len(table.fields),
                )
            )
        summaries.sort(key=lambda s: s.table_name)
        return summaries

    async def get_table_schema(self, table_name: str) -> ExtraTableDetailSchemaDTO | None:
        catalog = await self.get_table_catalog()
        normalized = ExtraTableSecurityValidator.normalize_table_name(table_name)
        return catalog.get(normalized)

    async def query_table(
        self,
        _criteria: ExtraTableQueryCriteriaDTO,
        schema: ExtraTableDetailSchemaDTO,
    ) -> ExtraTableQueryResultDTO:
        raise SuperOfficeExtraTableQueryError(
            message=(
                f"Cannot query live rows from '{schema.table_name}' using "
                "LocalMirrorExtraTableRepository. Active database connection required."
            ),
            table_name=schema.table_name,
        )


class FakeExtraTableRepository:
    """In-memory test double for unit testing extra tables."""

    def __init__(
        self,
        tables: dict[str, ExtraTableDetailSchemaDTO] | None = None,
        rows_by_table: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.tables = tables or {}
        self.rows_by_table = rows_by_table or {}

    async def get_table_catalog(self) -> dict[str, ExtraTableDetailSchemaDTO]:
        return dict(self.tables)

    async def list_tables(self, search: str | None = None) -> list[ExtraTableSummaryDTO]:
        summaries: list[ExtraTableSummaryDTO] = []
        search_lower = search.strip().lower() if search else None
        for table in self.tables.values():
            if search_lower and (
                search_lower not in table.table_name.lower()
                and search_lower not in table.display_name.lower()
            ):
                continue
            summaries.append(
                ExtraTableSummaryDTO(
                    id=table.id,
                    table_name=table.table_name,
                    display_name=table.display_name,
                    description=table.description,
                    field_count=len(table.fields),
                )
            )
        summaries.sort(key=lambda s: s.table_name)
        return summaries

    async def get_table_schema(self, table_name: str) -> ExtraTableDetailSchemaDTO | None:
        normalized = ExtraTableSecurityValidator.normalize_table_name(table_name)
        return self.tables.get(normalized)

    async def query_table(
        self,
        criteria: ExtraTableQueryCriteriaDTO,
        schema: ExtraTableDetailSchemaDTO,
    ) -> ExtraTableQueryResultDTO:
        all_rows = self.rows_by_table.get(schema.table_name, [])

        # Filter
        filtered: list[dict[str, Any]] = []
        for r in all_rows:
            matches = True
            if criteria.filters:
                for k, v in criteria.filters.items():
                    if r.get(k) != v:
                        matches = False
                        break
            if matches:
                filtered.append(r)

        # Slice
        paged = filtered[criteria.offset : criteria.offset + criteria.limit]

        # Project columns
        cols = criteria.fields or tuple(
            ["id"] + [f.field_name for f in schema.fields if f.field_name != "id"]
        )
        projected_rows: list[dict[str, Any]] = []
        for r in paged:
            projected_rows.append({col: r.get(col) for col in cols})

        return ExtraTableQueryResultDTO(
            table_name=schema.table_name,
            total_rows_returned=len(projected_rows),
            limit=criteria.limit,
            offset=criteria.offset,
            columns=tuple(cols),
            rows=tuple(projected_rows),
        )
