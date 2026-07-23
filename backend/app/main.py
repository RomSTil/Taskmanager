from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import get_settings
from .core.errors import ApplicationError
from .core.modules import ApplicationModule, ModuleContext, ModuleRegistry
from .database import Base, SessionLocal, engine
from .module_catalog import default_modules


def create_app(
    initialize_database: bool | None = None,
    modules: Iterable[ApplicationModule] | None = None,
) -> FastAPI:
    settings = get_settings()
    settings.validate_runtime()
    should_initialize = (
        settings.environment == "development"
        if initialize_database is None
        else initialize_database
    )
    registry = ModuleRegistry(modules if modules is not None else default_modules())
    context = ModuleContext(settings=settings)
    registry.configure(context)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        settings.vault_path.expanduser().resolve().mkdir(parents=True, exist_ok=True)
        if should_initialize:
            Base.metadata.create_all(bind=engine)
        await registry.startup(context)
        try:
            yield
        finally:
            await registry.shutdown(context)

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Global personal task and Markdown knowledge workspace.",
        lifespan=lifespan,
    )
    application.state.module_context = context
    application.state.module_registry = registry
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_host_list,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(ApplicationError)
    async def application_error_handler(
        _: Request, exc: ApplicationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    @application.middleware("http")
    async def security_headers_and_limits(  # type: ignore[no-untyped-def]
        request: Request, call_next
    ):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                body_size = int(content_length)
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
            if body_size < 0:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
            if body_size > settings.max_request_mb * 1024 * 1024:
                return JSONResponse(status_code=413, content={"detail": "Request body is too large"})
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @application.get("/healthz", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz", tags=["system"])
    def ready() -> dict[str, str]:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ready"}

    api_prefix = "/api/v1"
    registry.install_routes(application, prefix=api_prefix)
    return application


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.bind_host,
        port=settings.bind_port,
        reload=False,
        server_header=False,
    )


if __name__ == "__main__":
    run()
