"""Gateway application entrypoint and runtime bootstrap."""

import asyncio
import sys

import uvicorn

from platform_gateway.server.app import create_gateway_app
from platform_gateway.settings import GatewayAppSettings
from platform_observability.logging import configure_logging, get_logger


async def run_gateway() -> None:
    """Bootstrap and initialize the Gateway Streamable HTTP server runtime."""
    settings = GatewayAppSettings()
    configure_logging(settings.logging)
    logger = get_logger("platform_gateway")

    logger.info(
        "gateway_bootstrap_initialized",
        host=settings.host,
        port=settings.port,
        environment=settings.environment,
        transport="Streamable HTTP (ADR 007)",
    )

    app = create_gateway_app(settings)

    config = uvicorn.Config(
        app=app,
        host=settings.host,
        port=settings.port,
        log_config=None,  # Use platform_observability structured logging
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info("gateway_ready_for_connections", port=settings.port)
    await server.serve()


def main() -> None:
    """Main process entrypoint."""
    try:
        asyncio.run(run_gateway())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
