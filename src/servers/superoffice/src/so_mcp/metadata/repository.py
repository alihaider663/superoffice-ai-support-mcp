"""Repository layer for fetching SuperOffice metadata, associates, lists, and scheduled tasks."""

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as SaTimeoutError
from sqlalchemy.ext.asyncio import AsyncEngine

from so_mcp.metadata.contracts import (
    AssociateDetailCriteriaDTO,
    AssociateDetailDTO,
    ScheduledTaskItemDTO,
    SuperOfficeMetadataError,
    SystemEventsCriteriaDTO,
    SystemEventsResultDTO,
    TicketCategoryItemDTO,
    TicketMetadataListsCriteriaDTO,
    TicketMetadataListsDTO,
    TicketPriorityItemDTO,
    TicketStatusItemDTO,
    UserGroupItemDTO,
)

logger = logging.getLogger(__name__)


def _serialize_text(val: Any) -> str:
    """Format database cell value into safe string representation."""
    if val is None:
        return ""
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return str(val)


def _get_val(row: Any, key: str, index: int, default: Any = None) -> Any:
    """Extract column value by name or positional index across SQLAlchemy Row, dict, or tuple."""
    if hasattr(row, "_mapping"):
        return row._mapping.get(key, default)
    if isinstance(row, dict):
        return row.get(key, default)
    if isinstance(row, (tuple, list)) and len(row) > index:
        return row[index]
    return default


class MetadataRepositoryProtocol(Protocol):
    """Protocol defining metadata, user, list, and scheduled task query operations."""

    async def get_associate_details(
        self, criteria: AssociateDetailCriteriaDTO
    ) -> AssociateDetailDTO | None:
        """Fetch details for an internal consultant/support agent by ID or username."""
        ...

    async def get_ticket_metadata_lists(
        self, criteria: TicketMetadataListsCriteriaDTO
    ) -> TicketMetadataListsDTO:
        """Fetch reference lists for categories, priorities, statuses, and groups."""
        ...

    async def list_system_events_and_triggers(
        self, criteria: SystemEventsCriteriaDTO
    ) -> SystemEventsResultDTO:
        """Fetch scheduled background tasks and system event executions."""
        ...


class MssqlMetadataRepository:
    """Production MSSQL repository querying ASSOCIATE, EJUSER, EJ_CATEGORY, SCHEDULE, etc."""

    def __init__(self, engine: AsyncEngine, query_timeout_seconds: float = 5.0) -> None:
        self._engine = engine
        self._query_timeout_seconds = query_timeout_seconds

    def _handle_exception(self, exc: Exception, operation: str) -> None:
        """Translate driver, DBAPI, and asyncio exceptions into SuperOfficeMetadataError."""
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError, SaTimeoutError)):
            raise SuperOfficeMetadataError(
                f"Database query timed out during {operation}.",
                error_code="DATABASE_TIMEOUT",
                details={"operation": operation, "timeout_seconds": self._query_timeout_seconds},
            ) from exc

        if isinstance(exc, DBAPIError):
            orig = getattr(exc, "orig", None)
            sqlstate = getattr(orig, "sqlstate", None) or (
                orig.args[0] if orig and orig.args else None
            )
            raise SuperOfficeMetadataError(
                f"Database driver error during {operation}: {exc}",
                error_code="DBAPI_ERROR",
                details={"operation": operation, "sqlstate": str(sqlstate)},
            ) from exc

        raise SuperOfficeMetadataError(
            f"Unexpected database error during {operation}: {exc}",
            error_code="INTERNAL_DATABASE_ERROR",
            details={"operation": operation},
        ) from exc

    async def get_associate_details(
        self, criteria: AssociateDetailCriteriaDTO
    ) -> AssociateDetailDTO | None:
        """Fetch details for an internal consultant or support engineer."""
        if criteria.associate_id is None and not criteria.username:
            raise SuperOfficeMetadataError(
                "Either associate_id or username must be provided.",
                error_code="INVALID_ARGUMENTS",
            )

        clean_user = criteria.username.strip() if criteria.username else None
        # Check if username is integer-like (could be an ID)
        int_id = criteria.associate_id
        if int_id is None and clean_user and clean_user.isdigit():
            int_id = int(clean_user)

        sql = text(
            """
            SELECT TOP 1
                a.associate_id,
                a.name AS associate_name,
                a.person_id,
                a.type AS associate_type,
                u.id AS ejuser_id,
                u.username,
                u.loginname,
                u.email,
                u.status AS user_status,
                u.default_category,
                p.firstname,
                p.lastname,
                p.title,
                g.UserGroup_id AS group_id,
                g.name AS group_name
            FROM ASSOCIATE a
            LEFT JOIN EJUSER u ON a.ejuserId = u.id
            LEFT JOIN PERSON p ON a.person_id = p.person_id
            LEFT JOIN USERGROUP g ON a.group_idx = g.UserGroup_id
            WHERE (:int_id IS NOT NULL AND (a.associate_id = :int_id OR u.id = :int_id))
               OR (:clean_user IS NOT NULL AND (
                   LOWER(u.username) = LOWER(:clean_user)
                   OR LOWER(u.loginname) = LOWER(:clean_user)
                   OR LOWER(a.name) = LOWER(:clean_user)
               ))
            """
        )

        try:
            async with self._engine.connect() as conn:
                res = await asyncio.wait_for(
                    conn.execute(sql, {"int_id": int_id, "clean_user": clean_user}),
                    timeout=self._query_timeout_seconds,
                )
                row = res.first()
                if not row:
                    return None

                assoc_id = int(_get_val(row, "associate_id", 0))
                ej_val = _get_val(row, "ejuser_id", 1)
                ej_id = int(ej_val) if ej_val is not None else None
                name_val = _get_val(row, "associate_name", 2)
                user_val = _get_val(row, "username", 3)
                login_val = _get_val(row, "loginname", 4)
                fn_val = _get_val(row, "firstname", 5)
                ln_val = _get_val(row, "lastname", 6)
                title_val = _get_val(row, "title", 7)
                email_val = _get_val(row, "email", 8)
                gid_val = _get_val(row, "group_id", 9)
                user_status = _get_val(row, "user_status", 10)
                def_cat_val = _get_val(row, "default_category", 11)
                gname_val = _get_val(row, "group_name", 12)

                name = str(name_val or user_val or f"Associate #{assoc_id}")
                username = str(user_val or login_val or name)
                fn = str(fn_val).strip() if fn_val else None
                ln = str(ln_val).strip() if ln_val else None
                title = str(title_val).strip() if title_val else None
                email = str(email_val or "").strip()
                gid = int(gid_val) if gid_val is not None else None
                gname = str(gname_val).strip() if gname_val else None
                # status: 1 = Active, 2 = Deleted, 3 = Former/Inactive
                is_active = user_status == 1 or user_status is None
                def_cat = int(def_cat_val) if def_cat_val is not None else None

                return AssociateDetailDTO(
                    associate_id=assoc_id,
                    ejuser_id=ej_id,
                    name=name,
                    username=username,
                    first_name=fn,
                    last_name=ln,
                    title=title,
                    email=email,
                    group_id=gid,
                    group_name=gname,
                    is_active=is_active,
                    default_category_id=def_cat,
                )
        except Exception as exc:
            self._handle_exception(exc, "get_associate_details")
            return None

    async def get_ticket_metadata_lists(
        self, criteria: TicketMetadataListsCriteriaDTO
    ) -> TicketMetadataListsDTO:
        """Fetch categories, priorities, statuses, and user groups."""
        list_type = criteria.list_type.lower()
        fetch_all = list_type in ("all", "")

        categories: list[TicketCategoryItemDTO] = []
        priorities: list[TicketPriorityItemDTO] = []
        statuses: list[TicketStatusItemDTO] = []
        user_groups: list[UserGroupItemDTO] = []

        try:
            async with self._engine.connect() as conn:
                if fetch_all or list_type == "category":
                    cat_sql = text(
                        """
                        SELECT id, name, fullname, parent_id, delegate_method,
                               notification_email, closing_status
                        FROM EJ_CATEGORY
                        ORDER BY fullname ASC
                        """
                    )
                    cat_res = await asyncio.wait_for(
                        conn.execute(cat_sql), timeout=self._query_timeout_seconds
                    )
                    for r in cat_res.fetchall():
                        fn_name = _get_val(r, "fullname", 2) or _get_val(r, "name", 1) or ""
                        notif_email = _get_val(r, "notification_email", 5)
                        categories.append(
                            TicketCategoryItemDTO(
                                category_id=int(_get_val(r, "id", 0)),
                                name=str(_get_val(r, "name", 1) or ""),
                                fullname=str(fn_name),
                                parent_id=int(_get_val(r, "parent_id", 3) or 0),
                                delegate_method=int(_get_val(r, "delegate_method", 4) or 0),
                                notification_email=(
                                    str(notif_email).strip() if notif_email else None
                                ),
                                closing_status=int(_get_val(r, "closing_status", 6) or 0),
                            )
                        )

                if fetch_all or list_type == "priority":
                    prio_sql = text(
                        """
                        SELECT id, name, status, sort_order, flags
                        FROM TICKET_PRIORITY
                        ORDER BY sort_order ASC
                        """
                    )
                    prio_res = await asyncio.wait_for(
                        conn.execute(prio_sql), timeout=self._query_timeout_seconds
                    )
                    for r in prio_res.fetchall():
                        priorities.append(
                            TicketPriorityItemDTO(
                                priority_id=int(_get_val(r, "id", 0)),
                                name=str(_get_val(r, "name", 1) or ""),
                                status=int(_get_val(r, "status", 2) or 0),
                                sort_order=int(_get_val(r, "sort_order", 3) or 0),
                                flags=int(_get_val(r, "flags", 4) or 0),
                            )
                        )

                if fetch_all or list_type == "status":
                    stat_sql = text(
                        """
                        SELECT id, name, status, ts_rank, time_counter, deleted
                        FROM TICKET_STATUS
                        ORDER BY ts_rank ASC
                        """
                    )
                    stat_res = await asyncio.wait_for(
                        conn.execute(stat_sql), timeout=self._query_timeout_seconds
                    )
                    for r in stat_res.fetchall():
                        statuses.append(
                            TicketStatusItemDTO(
                                status_id=int(_get_val(r, "id", 0)),
                                name=str(_get_val(r, "name", 1) or ""),
                                status_type=int(_get_val(r, "status", 2) or 0),
                                ts_rank=int(_get_val(r, "ts_rank", 3) or 0),
                                time_counter=int(_get_val(r, "time_counter", 4) or 0),
                                is_deleted=bool(_get_val(r, "deleted", 5) != 0),
                            )
                        )

                if fetch_all or list_type in ("group", "user_group"):
                    grp_sql = text(
                        """
                        SELECT UserGroup_id, name, rank
                        FROM USERGROUP
                        WHERE deleted = 0
                        ORDER BY rank ASC
                        """
                    )
                    grp_res = await asyncio.wait_for(
                        conn.execute(grp_sql), timeout=self._query_timeout_seconds
                    )
                    for r in grp_res.fetchall():
                        user_groups.append(
                            UserGroupItemDTO(
                                group_id=int(_get_val(r, "UserGroup_id", 0)),
                                name=str(_get_val(r, "name", 1) or ""),
                                rank=int(_get_val(r, "rank", 2) or 0),
                            )
                        )

            return TicketMetadataListsDTO(
                categories=tuple(categories),
                priorities=tuple(priorities),
                statuses=tuple(statuses),
                user_groups=tuple(user_groups),
                total_categories=len(categories),
                total_priorities=len(priorities),
                total_statuses=len(statuses),
                total_user_groups=len(user_groups),
            )
        except Exception as exc:
            self._handle_exception(exc, "get_ticket_metadata_lists")
            return TicketMetadataListsDTO((), (), (), (), 0, 0, 0, 0)

    async def list_system_events_and_triggers(
        self, criteria: SystemEventsCriteriaDTO
    ) -> SystemEventsResultDTO:
        """Fetch scheduled background tasks and system event executions."""
        query_param = criteria.query.strip() if criteria.query else None
        like_query = f"%{query_param}%" if query_param else None

        sql = text(
            """
            SELECT TOP (:limit)
                t.id AS task_id,
                sch.id AS schedule_id,
                sch.name AS task_name,
                s.id AS script_id,
                s.unique_identifier AS script_identifier,
                s.include_id AS script_include_id,
                sch.disabled,
                sch.status AS execution_status,
                sch.minute_interval,
                sch.last_execution,
                sch.next_execution,
                sch.execution_time AS execution_time_ms,
                sch.error_message,
                sch.last_error,
                sch.retries
            FROM SCHEDULED_TASK t
            JOIN SCHEDULE sch ON t.schedule_id = sch.id
            LEFT JOIN EJSCRIPT s ON t.script_id = s.id
            WHERE (:inc_disabled = 1 OR sch.disabled = 0)
              AND (:only_errors = 0 OR (sch.status != 0 OR sch.error_message IS NOT NULL))
              AND (:like_query IS NULL OR (
                  sch.name LIKE :like_query
                  OR s.unique_identifier LIKE :like_query
                  OR s.include_id LIKE :like_query
              ))
            ORDER BY sch.name ASC
            """
        )

        try:
            async with self._engine.connect() as conn:
                res = await asyncio.wait_for(
                    conn.execute(
                        sql,
                        {
                            "limit": max(1, min(criteria.limit, 100)),
                            "inc_disabled": 1 if criteria.include_disabled else 0,
                            "only_errors": 1 if criteria.only_errors else 0,
                            "like_query": like_query,
                        },
                    ),
                    timeout=self._query_timeout_seconds,
                )
                rows = res.fetchall()
                tasks: list[ScheduledTaskItemDTO] = []
                for r in rows:
                    inc_id = _get_val(r, "script_include_id", 5)
                    ident = _get_val(r, "script_identifier", 4)
                    s_name = (
                        str(inc_id).strip() if inc_id else (str(ident).strip() if ident else None)
                    )
                    sid = _get_val(r, "script_id", 3)
                    min_interval = _get_val(r, "minute_interval", 8)
                    exec_time = _get_val(r, "execution_time_ms", 11)
                    err_msg = _get_val(r, "error_message", 12)
                    tasks.append(
                        ScheduledTaskItemDTO(
                            task_id=int(_get_val(r, "task_id", 0)),
                            schedule_id=int(_get_val(r, "schedule_id", 1)),
                            task_name=str(
                                _get_val(r, "task_name", 2) or f"Task #{_get_val(r, 'task_id', 0)}"
                            ),
                            script_id=int(sid) if sid is not None else None,
                            script_identifier=str(ident) if ident else None,
                            script_include_id=s_name,
                            is_disabled=bool(_get_val(r, "disabled", 6) != 0),
                            execution_status=int(_get_val(r, "execution_status", 7) or 0),
                            minute_interval=int(min_interval) if min_interval is not None else None,
                            last_execution=_serialize_text(_get_val(r, "last_execution", 9))
                            or None,
                            next_execution=_serialize_text(_get_val(r, "next_execution", 10))
                            or None,
                            execution_time_ms=int(exec_time) if exec_time is not None else None,
                            error_message=str(err_msg).strip() if err_msg else None,
                            last_error=_serialize_text(_get_val(r, "last_error", 13)) or None,
                            retries=int(_get_val(r, "retries", 14) or 0),
                        )
                    )

            return SystemEventsResultDTO(
                total_tasks=len(tasks),
                returned_tasks=len(tasks),
                tasks=tuple(tasks),
            )
        except Exception as exc:
            self._handle_exception(exc, "list_system_events_and_triggers")
            return SystemEventsResultDTO(0, 0, ())


class FakeMetadataRepository:
    """In-memory metadata repository for deterministic testing."""

    def __init__(
        self,
        associates: list[AssociateDetailDTO] | None = None,
        lists: TicketMetadataListsDTO | None = None,
        tasks: list[ScheduledTaskItemDTO] | None = None,
    ) -> None:
        self.associates = associates or [
            AssociateDetailDTO(
                associate_id=1607,
                ejuser_id=1606,
                name="junaid.tariq",
                username="junaid.tariq",
                first_name="Junaid",
                last_name="Tariq",
                title="Support Specialist",
                email="junaid.tariq@example.com",
                group_id=4,
                group_name="Services",
                is_active=True,
                default_category_id=415,
            )
        ]
        self.lists = lists or TicketMetadataListsDTO(
            categories=(
                TicketCategoryItemDTO(
                    category_id=415,
                    name="AAQOO",
                    fullname="AAQOO",
                    parent_id=-1,
                    delegate_method=4,
                    notification_email="alerts@example.com",
                    closing_status=0,
                ),
            ),
            priorities=(
                TicketPriorityItemDTO(
                    priority_id=1,
                    name="Medium",
                    status=1,
                    sort_order=20,
                    flags=2,
                ),
                TicketPriorityItemDTO(
                    priority_id=2,
                    name="High",
                    status=1,
                    sort_order=50,
                    flags=4,
                ),
            ),
            statuses=(
                TicketStatusItemDTO(
                    status_id=1,
                    name="Open",
                    status_type=1,
                    ts_rank=7,
                    time_counter=1,
                    is_deleted=False,
                ),
                TicketStatusItemDTO(
                    status_id=2,
                    name="Closed",
                    status_type=2,
                    ts_rank=8,
                    time_counter=0,
                    is_deleted=False,
                ),
            ),
            user_groups=(
                UserGroupItemDTO(group_id=1, name="Administration", rank=5),
                UserGroupItemDTO(group_id=4, name="Services", rank=1),
            ),
            total_categories=1,
            total_priorities=2,
            total_statuses=2,
            total_user_groups=2,
        )
        self.tasks = tasks or [
            ScheduledTaskItemDTO(
                task_id=43,
                schedule_id=43,
                task_name="Calculate Dashboard",
                script_id=148,
                script_identifier="a5e3dba515f147f9a34348aa12720cc6",
                script_include_id="calculateDashboard",
                is_disabled=True,
                execution_status=2,
                minute_interval=10,
                last_execution="2025-01-03T15:40:35",
                next_execution="2025-09-02T15:23:00",
                execution_time_ms=2,
                error_message="EjScript runtime exception: No ExtraTable named: y_dashboard",
                last_error="2025-09-02T15:11:07",
                retries=1,
            )
        ]

    async def get_associate_details(
        self, criteria: AssociateDetailCriteriaDTO
    ) -> AssociateDetailDTO | None:
        for a in self.associates:
            if criteria.associate_id is not None and criteria.associate_id in (
                a.associate_id,
                a.ejuser_id,
            ):
                return a
            if criteria.username and criteria.username.lower() in (
                a.username.lower(),
                a.name.lower(),
            ):
                return a
        return None

    async def get_ticket_metadata_lists(
        self, criteria: TicketMetadataListsCriteriaDTO
    ) -> TicketMetadataListsDTO:
        lt = criteria.list_type.lower()
        if lt in ("all", ""):
            return self.lists
        return TicketMetadataListsDTO(
            categories=self.lists.categories if lt == "category" else (),
            priorities=self.lists.priorities if lt == "priority" else (),
            statuses=self.lists.statuses if lt == "status" else (),
            user_groups=self.lists.user_groups if lt in ("group", "user_group") else (),
            total_categories=len(self.lists.categories) if lt == "category" else 0,
            total_priorities=len(self.lists.priorities) if lt == "priority" else 0,
            total_statuses=len(self.lists.statuses) if lt == "status" else 0,
            total_user_groups=len(self.lists.user_groups) if lt in ("group", "user_group") else 0,
        )

    async def list_system_events_and_triggers(
        self, criteria: SystemEventsCriteriaDTO
    ) -> SystemEventsResultDTO:
        filtered = []
        for t in self.tasks:
            if not criteria.include_disabled and t.is_disabled:
                continue
            if criteria.only_errors and t.execution_status == 0 and not t.error_message:
                continue
            if criteria.query:
                q = criteria.query.lower()
                if q not in t.task_name.lower() and (
                    not t.script_include_id or q not in t.script_include_id.lower()
                ):
                    continue
            filtered.append(t)
            if len(filtered) >= criteria.limit:
                break
        return SystemEventsResultDTO(
            total_tasks=len(filtered),
            returned_tasks=len(filtered),
            tasks=tuple(filtered),
        )
