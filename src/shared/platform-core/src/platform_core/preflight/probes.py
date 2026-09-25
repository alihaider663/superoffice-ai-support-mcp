"""Diagnostic probes for evaluating platform services and external backends."""

from __future__ import annotations

import asyncio
import os
import socket
import time
import urllib.parse
from pathlib import Path

import httpx

from platform_core.preflight.models import ProbeCategory, ProbeResult, ProbeStatus


def _load_env_file() -> None:
    """Ensure .env file is populated into os.environ if present."""
    env_path = Path(".env")
    if not env_path.is_file():
        return
    try:
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            k, v = stripped.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k not in os.environ:
                os.environ[k] = v
    except OSError:
        pass


async def _tcp_ping(host: str, port: int, timeout: float = 3.0) -> tuple[bool, float, str]:
    """Test TCP socket reachability and measure round-trip latency in ms."""
    start = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        latency = (time.perf_counter() - start) * 1000.0
        writer.close()
        await writer.wait_closed()
        return True, latency, f"TCP connection established to {host}:{port}"
    except TimeoutError:
        latency = (time.perf_counter() - start) * 1000.0
        return False, latency, f"TCP connection to {host}:{port} timed out after {timeout}s"
    except Exception as exc:
        latency = (time.perf_counter() - start) * 1000.0
        return False, latency, f"TCP connection failed to {host}:{port} ({exc})"


async def probe_superoffice_cluster() -> list[ProbeResult]:
    """Probe all configured SuperOffice IIS application server nodes."""
    _load_env_file()
    results: list[ProbeResult] = []

    servers_raw = os.getenv("SUPEROFFICE_APP_SERVERS", "").strip()
    if not servers_raw:
        single_url = os.getenv("SUPEROFFICE_API_URL", "").strip()
        nodes = [single_url] if single_url else []
    else:
        nodes = [s.strip() for s in servers_raw.split(",") if s.strip()]

    if not nodes:
        results.append(
            ProbeResult(
                name="SuperOffice Cluster Nodes",
                category=ProbeCategory.APP_SERVERS,
                status=ProbeStatus.WARNING,
                latency_ms=0.0,
                message=(
                    "No SuperOffice application server nodes configured in SUPEROFFICE_APP_SERVERS"
                ),
            )
        )
        return results

    allow_self_signed = os.getenv("SUPEROFFICE_ALLOW_SELF_SIGNED_CERT", "false").lower() in (
        "true",
        "1",
    )

    for node_url in nodes:
        parsed = urllib.parse.urlparse(node_url)
        host = parsed.hostname or "unknown"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        node_name = f"App Server Node ({host})"

        # Check tenant isolation rule: osl-so-iis1 must NOT be engaged
        if "osl-so-iis1" in host.lower():
            results.append(
                ProbeResult(
                    name=node_name,
                    category=ProbeCategory.APP_SERVERS,
                    status=ProbeStatus.FAILURE,
                    latency_ms=0.0,
                    message=(
                        f"Tenant Isolation Violation: {host} is configured to an alternate "
                        "database on 10.6.20.32. Must be removed from SUPEROFFICE_APP_SERVERS "
                        "for this tenant!"
                    ),
                    details={"url": node_url, "host": host, "tenant_violation": True},
                )
            )
            continue

        start_time = time.perf_counter()
        try:
            # 1. Test TCP socket reachability
            tcp_ok, tcp_lat, tcp_msg = await _tcp_ping(host, port, timeout=3.0)
            if not tcp_ok:
                results.append(
                    ProbeResult(
                        name=node_name,
                        category=ProbeCategory.APP_SERVERS,
                        status=ProbeStatus.FAILURE,
                        latency_ms=round(tcp_lat, 2),
                        message=f"TCP unreachable: {tcp_msg}",
                        details={"url": node_url, "host": host, "port": port},
                    )
                )
                continue

            # 2. Test HTTP reachability
            async with httpx.AsyncClient(
                verify=not allow_self_signed,
                timeout=httpx.Timeout(5.0, connect=3.0),
            ) as client:
                resp = await client.get(node_url, follow_redirects=True)
                latency = (time.perf_counter() - start_time) * 1000.0
                iis_server = resp.headers.get("server", "unknown")

                if resp.status_code < 500:
                    results.append(
                        ProbeResult(
                            name=node_name,
                            category=ProbeCategory.APP_SERVERS,
                            status=ProbeStatus.SUCCESS,
                            latency_ms=round(latency, 2),
                            message=(
                                f"HTTP {resp.status_code} ({iis_server}) | "
                                f"TCP {round(tcp_lat, 1)}ms, HTTP round-trip {round(latency, 1)}ms"
                            ),
                            details={
                                "url": node_url,
                                "status_code": resp.status_code,
                                "server_header": iis_server,
                                "tcp_latency_ms": round(tcp_lat, 2),
                                "total_latency_ms": round(latency, 2),
                            },
                        )
                    )
                else:
                    results.append(
                        ProbeResult(
                            name=node_name,
                            category=ProbeCategory.APP_SERVERS,
                            status=ProbeStatus.FAILURE,
                            latency_ms=round(latency, 2),
                            message=f"HTTP Error {resp.status_code} from IIS node",
                            details={"url": node_url, "status_code": resp.status_code},
                        )
                    )
        except Exception as exc:
            latency = (time.perf_counter() - start_time) * 1000.0
            results.append(
                ProbeResult(
                    name=node_name,
                    category=ProbeCategory.APP_SERVERS,
                    status=ProbeStatus.FAILURE,
                    latency_ms=round(latency, 2),
                    message=f"HTTP probe failed: {exc}",
                    details={"url": node_url, "error": str(exc)},
                )
            )

    return results


async def probe_mssql_database() -> ProbeResult:
    """Probe Microsoft SQL Server diagnostic database connectivity."""
    _load_env_file()
    host = os.getenv("DIAGNOSTICS_MSSQL_HOST", "127.0.0.1")
    try:
        port = int(os.getenv("DIAGNOSTICS_MSSQL_PORT", "1433"))
    except ValueError:
        port = 1433
    database = os.getenv("DIAGNOSTICS_MSSQL_DATABASE", "Superoffice")
    user = os.getenv("DIAGNOSTICS_MSSQL_USER", "")
    password = os.getenv("DIAGNOSTICS_MSSQL_PASSWORD", "")
    trust_cert = (
        "yes"
        if os.getenv("DIAGNOSTICS_MSSQL_TRUST_SERVER_CERTIFICATE", "true").lower() in ("true", "1")
        else "no"
    )

    tcp_ok, tcp_lat, tcp_msg = await _tcp_ping(host, port, timeout=3.0)
    if not tcp_ok:
        return ProbeResult(
            name=f"MSSQL Database ({host}:{port}/{database})",
            category=ProbeCategory.MSSQL,
            status=ProbeStatus.FAILURE,
            latency_ms=round(tcp_lat, 2),
            message=f"TCP unreachable: {tcp_msg}",
            details={"host": host, "port": port, "database": database},
        )

    # Attempt direct SQLAlchemy connection test if driver exists
    start_time = time.perf_counter()
    try:
        from sqlalchemy import text  # noqa: PLC0415
        from sqlalchemy.ext.asyncio import create_async_engine  # noqa: PLC0415

        odbc_params = [
            "Driver={ODBC Driver 18 for SQL Server}",
            f"Server=tcp:{host},{port}",
            f"Database={database}",
            f"UID={user}",
            f"PWD={password}",
            "Encrypt=yes",
            f"TrustServerCertificate={trust_cert}",
            "LoginTimeout=3",
        ]
        odbc_str = ";".join(odbc_params)
        quoted_odbc_str = urllib.parse.quote_plus(odbc_str)
        connection_url = f"mssql+aioodbc:///?odbc_connect={quoted_odbc_str}"

        engine = create_async_engine(connection_url)
        async with engine.connect() as conn:
            stmt = text("SELECT DB_NAME() AS db, @@SERVERNAME AS srv")
            row = (await conn.execute(stmt)).fetchone()
            latency = (time.perf_counter() - start_time) * 1000.0
            connected_db = row[0] if row else "unknown"
            server_name = row[1] if row else "unknown"

        await engine.dispose()

        # Verify database name matches tenant expectations
        if connected_db.lower() != database.lower():
            return ProbeResult(
                name=f"MSSQL Database ({host}:{port})",
                category=ProbeCategory.MSSQL,
                status=ProbeStatus.FAILURE,
                latency_ms=round(latency, 2),
                message=(
                    f"Tenant Database Mismatch: Connected to '{connected_db}', "
                    f"expected '{database}'"
                ),
                details={"expected_database": database, "actual_database": connected_db},
            )

        return ProbeResult(
            name=f"MSSQL Database ({host}:{port}/{database})",
            category=ProbeCategory.MSSQL,
            status=ProbeStatus.SUCCESS,
            latency_ms=round(latency, 2),
            message=f"Connected successfully to {connected_db} on {server_name} (Read-Only)",
            details={
                "host": host,
                "port": port,
                "database": connected_db,
                "server_name": server_name,
                "user": user,
            },
        )
    except Exception as exc:
        latency = (time.perf_counter() - start_time) * 1000.0
        err_msg = str(exc)
        # If pyodbc driver is not present on dev workstation, provide informative warning
        is_odbc_err = (
            "IM002" in err_msg
            or "Data source name not found" in err_msg
            or "ODBC Driver" in err_msg
        )
        if is_odbc_err:
            return ProbeResult(
                name=f"MSSQL Database ({host}:{port}/{database})",
                category=ProbeCategory.MSSQL,
                status=ProbeStatus.WARNING,
                latency_ms=round(tcp_lat, 2),
                message=(
                    f"TCP port 1433 reachable ({round(tcp_lat, 1)}ms). ODBC Driver not found on "
                    "local machine to complete authenticated SQL query test."
                ),
                details={"host": host, "port": port, "database": database, "tcp_connected": True},
            )

        return ProbeResult(
            name=f"MSSQL Database ({host}:{port}/{database})",
            category=ProbeCategory.MSSQL,
            status=ProbeStatus.FAILURE,
            latency_ms=round(latency, 2),
            message=f"Database query failed: {exc}",
            details={"host": host, "port": port, "database": database, "error": str(exc)},
        )


async def probe_postgres_knowledge() -> ProbeResult:
    """Probe PostgreSQL Knowledge Base database and pgvector extension."""
    _load_env_file()
    host = os.getenv("KNOWLEDGE_DATABASE_HOST", "127.0.0.1")
    try:
        port = int(os.getenv("KNOWLEDGE_DATABASE_PORT", "5432"))
    except ValueError:
        port = 5432
    db_name = os.getenv("KNOWLEDGE_DATABASE_NAME", "superoffice_ai_knowledge")
    user = os.getenv("KNOWLEDGE_DATABASE_USER", "postgres")
    password = os.getenv("KNOWLEDGE_DATABASE_PASSWORD", "")
    schema = os.getenv("KNOWLEDGE_DATABASE_SCHEMA", "knowledge")

    tcp_ok, tcp_lat, tcp_msg = await _tcp_ping(host, port, timeout=3.0)
    if not tcp_ok:
        return ProbeResult(
            name=f"PostgreSQL Knowledge ({host}:{port}/{db_name})",
            category=ProbeCategory.POSTGRES,
            status=ProbeStatus.FAILURE,
            latency_ms=round(tcp_lat, 2),
            message=f"TCP unreachable: {tcp_msg}",
            details={"host": host, "port": port, "database": db_name},
        )

    start_time = time.perf_counter()
    try:
        from sqlalchemy import text  # noqa: PLC0415
        from sqlalchemy.ext.asyncio import create_async_engine  # noqa: PLC0415

        quoted_pass = urllib.parse.quote_plus(password)
        async_url = f"postgresql+asyncpg://{user}:{quoted_pass}@{host}:{port}/{db_name}"
        engine = create_async_engine(async_url, connect_args={"timeout": 5.0})

        async with engine.connect() as conn:
            # Check pgvector extension
            ext_stmt = text("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector'")
            ext_row = (await conn.execute(ext_stmt)).fetchone()
            has_vector = ext_row is not None
            vector_version = ext_row[1] if ext_row else "missing"

            # Check schema tables
            tables_stmt = text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"
            )
            tables_res = await conn.execute(tables_stmt, {"schema": schema})
            tables = [row[0] for row in tables_res.fetchall()]

        await engine.dispose()

        if not has_vector:
            return ProbeResult(
                name=f"PostgreSQL Knowledge ({host}:{port}/{db_name})",
                category=ProbeCategory.POSTGRES,
                status=ProbeStatus.FAILURE,
                latency_ms=round((time.perf_counter() - start_time) * 1000.0, 2),
                message="pgvector extension is NOT installed in superoffice_ai_knowledge!",
                details={"has_pgvector": False, "tables": tables},
            )

        latency = (time.perf_counter() - start_time) * 1000.0
        return ProbeResult(
            name=f"PostgreSQL Knowledge ({host}:{port}/{db_name})",
            category=ProbeCategory.POSTGRES,
            status=ProbeStatus.SUCCESS,
            latency_ms=round(latency, 2),
            message=(
                f"Connected with pgvector v{vector_version}. Schema '{schema}' "
                f"contains {len(tables)} tables."
            ),
            details={
                "host": host,
                "port": port,
                "database": db_name,
                "pgvector_version": vector_version,
                "schema": schema,
                "tables": tables,
            },
        )
    except Exception as exc:
        latency = (time.perf_counter() - start_time) * 1000.0
        return ProbeResult(
            name=f"PostgreSQL Knowledge ({host}:{port}/{db_name})",
            category=ProbeCategory.POSTGRES,
            status=ProbeStatus.FAILURE,
            latency_ms=round(latency, 2),
            message=f"PostgreSQL probe failed: {exc}",
            details={"host": host, "port": port, "database": db_name, "error": str(exc)},
        )


async def probe_codebase_mirror() -> ProbeResult:
    """Probe local SuperOffice codebase mirror filesystem directory."""
    _load_env_file()
    local_path = os.getenv("SUPEROFFICE_CODEBASE_LOCAL_PATH", "").strip()
    if not local_path:
        return ProbeResult(
            name="Codebase Local Mirror",
            category=ProbeCategory.CODEBASE,
            status=ProbeStatus.WARNING,
            latency_ms=0.0,
            message="SUPEROFFICE_CODEBASE_LOCAL_PATH is not configured in .env",
            details={"configured": False},
        )

    start = time.perf_counter()
    p = Path(local_path)
    if not p.exists():
        return ProbeResult(
            name=f"Codebase Mirror ({local_path})",
            category=ProbeCategory.CODEBASE,
            status=ProbeStatus.WARNING,
            latency_ms=0.0,
            message=(
                "Directory does not exist. Run scripts/sync-so-codebase.ps1 to mirror "
                "scripts, screens, and database schemas."
            ),
            details={"path": str(p), "exists": False},
        )

    if not p.is_dir():
        return ProbeResult(
            name=f"Codebase Mirror ({local_path})",
            category=ProbeCategory.CODEBASE,
            status=ProbeStatus.FAILURE,
            latency_ms=0.0,
            message=f"Configured path is not a directory: {local_path}",
            details={"path": str(p), "is_dir": False},
        )

    # Check for mirrored components
    subdirs = [d.name for d in p.iterdir() if d.is_dir()]
    manifest_file = p / "manifest.json"
    has_manifest = manifest_file.exists()

    file_count = sum(1 for _ in p.rglob("*") if _.is_file())
    latency = (time.perf_counter() - start) * 1000.0

    return ProbeResult(
        name=f"Codebase Mirror ({p.name})",
        category=ProbeCategory.CODEBASE,
        status=ProbeStatus.SUCCESS,
        latency_ms=round(latency, 2),
        message=(
            f"Mirror verified: {file_count} files across {len(subdirs)} categories "
            f"(manifest: {'present' if has_manifest else 'missing'})"
        ),
        details={
            "path": str(p),
            "file_count": file_count,
            "has_manifest": has_manifest,
            "categories": subdirs,
        },
    )


async def probe_network_ports() -> ProbeResult:
    """Probe standard platform microservice TCP ports (8000-8005)."""
    ports = {
        8000: "Platform Gateway",
        8001: "SuperOffice MCP",
        8002: "Diagnostics MCP",
        8003: "Knowledge MCP",
        8005: "Investigation MCP",
    }

    start = time.perf_counter()
    available: list[int] = []
    occupied: dict[int, str] = {}

    for port, service_label in ports.items():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        try:
            sock.bind(("127.0.0.1", port))
            available.append(port)
        except OSError:
            occupied[port] = service_label
        finally:
            sock.close()

    latency = (time.perf_counter() - start) * 1000.0

    if not occupied:
        return ProbeResult(
            name="Platform TCP Ports (8000-8005)",
            category=ProbeCategory.PORTS,
            status=ProbeStatus.SUCCESS,
            latency_ms=round(latency, 2),
            message=(
                "All 5 platform service ports (8000, 8001, 8002, 8003, 8005) "
                "are available for startup"
            ),
            details={"available_ports": available, "occupied_ports": {}},
        )

    # Some or all ports are occupied
    all_occupied = len(occupied) == len(ports)
    status = ProbeStatus.SUCCESS if all_occupied else ProbeStatus.WARNING
    bound_details = ", ".join(f"{p} ({label})" for p, label in occupied.items())
    summary_text = (
        "Platform is already actively running on all 5 ports"
        if all_occupied
        else f"Some ports already bound: {bound_details}"
    )

    return ProbeResult(
        name="Platform TCP Ports (8000-8005)",
        category=ProbeCategory.PORTS,
        status=status,
        latency_ms=round(latency, 2),
        message=summary_text,
        details={
            "available_ports": available,
            "occupied_ports": occupied,
            "running_instance_detected": all_occupied,
        },
    )


async def probe_security_configuration() -> ProbeResult:
    """Probe platform security parameters and JWT settings."""
    _load_env_file()
    jwt_secret = os.getenv("SECURITY_JWT_SECRET_KEY", "").strip()
    enable_auth = os.getenv("SECURITY_ENABLE_AUTH", "true").lower() in ("true", "1")
    enable_pii = os.getenv("SECURITY_ENABLE_PII_REDACTION", "true").lower() in ("true", "1")
    killswitch = os.getenv("SECURITY_ENABLE_ATTACHMENT_DOWNLOAD_KILLSWITCH", "true").lower() in (
        "true",
        "1",
    )
    algorithm = os.getenv("SECURITY_JWT_ALGORITHM", "HS256")

    issues: list[str] = []

    if len(jwt_secret) < 32:
        issues.append(f"JWT secret key too short ({len(jwt_secret)} chars, min 32 required)")

    if "placeholder" in jwt_secret.lower() or "insecure" in jwt_secret.lower():
        issues.append("JWT secret key contains development placeholder text")

    if not enable_pii:
        issues.append("PII redaction is DISABLED (should be enabled for production)")

    if not killswitch:
        issues.append("Attachment download killswitch is DISABLED (unrestricted downloads enabled)")

    if not issues:
        return ProbeResult(
            name="Security & Authorization Perimeter",
            category=ProbeCategory.SECURITY,
            status=ProbeStatus.SUCCESS,
            latency_ms=0.0,
            message=(
                f"Security invariants satisfied: JWT secret is 256-bit+ secure ({algorithm}), "
                "PII redaction active, attachment killswitch enforced."
            ),
            details={
                "auth_enabled": enable_auth,
                "pii_redaction_enabled": enable_pii,
                "killswitch_enabled": killswitch,
                "jwt_algorithm": algorithm,
            },
        )

    return ProbeResult(
        name="Security & Authorization Perimeter",
        category=ProbeCategory.SECURITY,
        status=ProbeStatus.WARNING,
        latency_ms=0.0,
        message=f"Security configuration warnings: {'; '.join(issues)}",
        details={
            "issues": issues,
            "auth_enabled": enable_auth,
            "pii_redaction_enabled": enable_pii,
            "killswitch_enabled": killswitch,
        },
    )
