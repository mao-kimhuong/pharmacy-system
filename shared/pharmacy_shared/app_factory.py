import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel

from . import clock
from .auth import CurrentUser, current_user
from .config import BaseServiceSettings
from .db import Database
from .errors import register_error_handlers
from .idempotency import IdempotencyMiddleware
from .logging import setup_logging
from .openapi_errors import add_error_responses
from .outbox_relay import RabbitPublisher, run_relay
from .rate_limit import RateLimitMiddleware
from .redis import RedisProvider
from .replay import replay_router

log = logging.getLogger(__name__)

INTERNAL_PREFIX = "/internal/v1"


class WhoAmI(BaseModel):
    service: str
    user_id: str
    role: str
    branch_ids: list[str]
    is_pharmacist: bool
    permissions: list[str]


def create_service_app(
    settings: BaseServiceSettings,
    db: Database,
    router: APIRouter,
    title: str,
    *,
    outbox_model: type | None = None,
    redis: RedisProvider | None = None,
    rate_limit_exempt: tuple[str, ...] = (),
    on_startup: Sequence[Callable[[], Awaitable[None]]] = (),
    background: Sequence[Callable[[asyncio.Event], Awaitable[None]]] = (),
    internal_router: APIRouter | None = None,
    public_paths: Sequence[str] = (),
) -> FastAPI:
    """Builds a service app with the same health/whoami routes, error format,
    middlewares (per-user rate limit, Idempotency-Key) and outbox relay.

    on_startup: coroutines run once at start (e.g. sync permission catalog).
    background: long-running tasks, e.g. an EventConsumer.run; they get a stop event.
    internal_router: service-to-service endpoints, mounted at /internal/v1 (outside
    /api, so Traefik never routes them; guarded by pharmacy_shared.internal).
    public_paths: routes Traefik serves without a token (e.g. auth's login): no shared
    401/403 in their documentation.
    """
    setup_logging()
    if settings.is_production:
        settings.check_service_token()
    prefix = settings.api_prefix
    redis = redis or RedisProvider(settings.redis_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        for hook in on_startup:
            await hook()
        stop = asyncio.Event()
        tasks = [asyncio.create_task(task(stop)) for task in background]
        relay_task: asyncio.Task[None] | None = None
        publisher: RabbitPublisher | None = None
        if settings.outbox_relay_enabled and outbox_model is not None:
            publisher = RabbitPublisher(settings.rabbitmq_url, settings.service_name)
            relay_task = asyncio.create_task(
                run_relay(
                    lambda: db.sessionmaker,
                    outbox_model,
                    publisher,
                    poll_seconds=settings.outbox_poll_seconds,
                    batch_size=settings.outbox_batch_size,
                    stop=stop,
                )
            )
        yield
        stop.set()
        for task in [*tasks, relay_task]:
            if task is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(task, timeout=5)
        if publisher is not None:
            await publisher.close()
        await redis.close()
        await db.dispose()

    show_docs = not settings.is_production
    app = FastAPI(
        title=title,
        lifespan=lifespan,
        docs_url=f"{prefix}/docs" if show_docs else None,
        redoc_url=None,
        openapi_url=f"{prefix}/openapi.json" if show_docs else None,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.redis = redis
    register_error_handlers(app)

    # Order: the last added runs first. Rate limit runs before idempotency; the dev clock (development only,
    # pharmacy_shared.clock) wraps everything, so idempotency replays and the rate limit see the same time.
    app.add_middleware(
        IdempotencyMiddleware,
        redis=redis,
        service=settings.service_name,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    app.add_middleware(
        RateLimitMiddleware,
        redis=redis,
        service=settings.service_name,
        reads_per_minute=settings.rate_limit_reads_per_minute,
        writes_per_minute=settings.rate_limit_writes_per_minute,
        exempt_paths=(f"{prefix}/health", f"{prefix}/docs", f"{prefix}/openapi.json", *rate_limit_exempt),
        # The calling service already rate-limits the real user.
        exempt_prefixes=(f"{INTERNAL_PREFIX}/",),
    )
    if clock.dev_clock_allowed(settings):
        app.add_middleware(clock.DevClockMiddleware, service_token=settings.service_token)

    @app.get(f"{prefix}/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.service_name}

    @app.get(f"{prefix}/whoami", tags=["system"], response_model=WhoAmI)
    async def whoami(user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
        """Protected test endpoint: shows the user Traefik passed to this service."""
        return {
            "service": settings.service_name,
            "user_id": str(user.id),
            "role": user.role,
            "branch_ids": sorted(str(b) for b in user.branch_ids),
            "is_pharmacist": user.is_pharmacist,
            "permissions": sorted(user.permissions),
        }

    app.include_router(router, prefix=prefix)
    if internal_router is not None:
        app.include_router(internal_router, prefix=INTERNAL_PREFIX, include_in_schema=False)
    if outbox_model is not None:
        app.include_router(replay_router(outbox_model), prefix=INTERNAL_PREFIX, include_in_schema=False)
    public = {f"{prefix}/health", f"{prefix}/docs", f"{prefix}/openapi.json", *(public_paths or ())}
    _add_bearer_auth_to_docs(app, title, public)
    return app


def _add_bearer_auth_to_docs(app: FastAPI, title: str, public: set[str]) -> None:
    """Adds an "Authorize" button to the API docs (paste the access token) and the
    error responses of every operation (pharmacy_shared.openapi_errors)."""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=title, version="1.0.0", routes=app.routes)
        schema.setdefault("components", {})["securitySchemes"] = {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
        }
        schema["security"] = [{"bearerAuth": []}]
        add_error_responses(schema, app.routes, public)
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
