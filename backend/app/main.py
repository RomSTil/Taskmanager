from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import get_settings
from .database import Base, SessionLocal, engine
from .routers import auth, notes, telegram, work


def create_app(initialize_database: bool | None = None) -> FastAPI:
    settings = get_settings()
    should_initialize = settings.environment == "development" if initialize_database is None else initialize_database

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        settings.vault_path.expanduser().resolve().mkdir(parents=True, exist_ok=True)
        if should_initialize:
            Base.metadata.create_all(bind=engine)
        yield

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Global personal task and Markdown knowledge workspace.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get("/healthz", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz", tags=["system"])
    def ready() -> dict[str, str]:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ready"}

    api_prefix = "/api/v1"
    application.include_router(auth.router, prefix=api_prefix)
    application.include_router(work.router, prefix=api_prefix)
    application.include_router(notes.router, prefix=api_prefix)
    application.include_router(telegram.router, prefix=api_prefix)
    return application


app = create_app()


def run() -> None:
    uvicorn.run("app.main:app", host="0.0.0.0", port=8765, reload=False)


if __name__ == "__main__":
    run()
