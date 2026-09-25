"""Async orchestration engine for executing diagnostic pre-flight probes."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from platform_core.preflight.models import (
    PreflightReport,
    ProbeResult,
    ProbeStatus,
)
from platform_core.preflight.probes import (
    probe_codebase_mirror,
    probe_mssql_database,
    probe_network_ports,
    probe_postgres_knowledge,
    probe_security_configuration,
    probe_superoffice_cluster,
)


class PreflightEngine:
    """Orchestrates comprehensive platform dependency and connectivity probes."""

    async def run(self) -> PreflightReport:
        """Execute all configured diagnostic probes concurrently and aggregate results."""
        start_time = time.perf_counter()

        # Run independent probe tasks concurrently
        so_task = asyncio.create_task(probe_superoffice_cluster())
        mssql_task = asyncio.create_task(probe_mssql_database())
        pg_task = asyncio.create_task(probe_postgres_knowledge())
        codebase_task = asyncio.create_task(probe_codebase_mirror())
        ports_task = asyncio.create_task(probe_network_ports())
        sec_task = asyncio.create_task(probe_security_configuration())

        so_results, mssql_res, pg_res, codebase_res, ports_res, sec_res = await asyncio.gather(
            so_task,
            mssql_task,
            pg_task,
            codebase_task,
            ports_task,
            sec_task,
        )

        all_results: list[ProbeResult] = []
        all_results.extend(so_results)
        all_results.append(mssql_res)
        all_results.append(pg_res)
        all_results.append(codebase_res)
        all_results.append(ports_res)
        all_results.append(sec_res)

        total_duration = (time.perf_counter() - start_time) * 1000.0

        passed_count = sum(1 for r in all_results if r.status == ProbeStatus.SUCCESS)
        warning_count = sum(1 for r in all_results if r.status == ProbeStatus.WARNING)
        failure_count = sum(1 for r in all_results if r.status == ProbeStatus.FAILURE)

        if failure_count > 0:
            overall = ProbeStatus.FAILURE
            ready = False
        elif warning_count > 0:
            overall = ProbeStatus.WARNING
            ready = True
        else:
            overall = ProbeStatus.SUCCESS
            ready = True

        return PreflightReport(
            timestamp=datetime.now(UTC).isoformat(),
            overall_status=overall,
            ready_to_launch=ready,
            passed_count=passed_count,
            warning_count=warning_count,
            failure_count=failure_count,
            total_duration_ms=round(total_duration, 2),
            results=all_results,
        )


async def run_preflight_probes() -> PreflightReport:
    """Helper entrypoint to instantiate engine and execute probes."""
    engine = PreflightEngine()
    return await engine.run()
