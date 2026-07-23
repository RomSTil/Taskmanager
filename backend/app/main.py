from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from html import escape
import re
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine, get_session
from .routers import auth, notes, telegram, work


def _public_note_description(markdown: str) -> str:
    """Create a compact plain-text Open Graph description from a Markdown note."""
    without_frontmatter = re.sub(r"\A---\s*\r?\n[\s\S]*?\r?\n---\s*\r?\n?", "", markdown)
    plain_text = re.sub(r"!?(?:\[[^\]]*\])?\([^)]*\)|[`*_#>~-]", " ", without_frontmatter)
    plain_text = re.sub(r"\s+", " ", plain_text).strip()
    if not plain_text:
        return "Открытая заметка в Taskman"
    return f"{plain_text[:197].rstrip()}…" if len(plain_text) > 200 else plain_text


def _public_note_html(title: str, description: str, url: str, markdown: str) -> str:
    page_title = f"{title} — Taskman"
    body = re.sub(r"\A---\s*\r?\n[\s\S]*?\r?\n---\s*\r?\n?", "", markdown).strip()
    return f"""<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(page_title)}</title>
    <meta name="description" content="{escape(description)}">
    <meta property="og:type" content="article">
    <meta property="og:site_name" content="Taskman">
    <meta property="og:title" content="{escape(title)}">
    <meta property="og:description" content="{escape(description)}">
    <meta property="og:url" content="{escape(url)}">
    <style>body{{max-width:760px;margin:48px auto;padding:0 20px;color:#302e29;font:16px/1.65 system-ui,sans-serif}}article{{padding:32px;border:1px solid #e5dfd4;border-radius:16px;background:#fcfaf5}}p{{color:#706a60}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}}</style>
  </head>
  <body>
    <article><p>ОТКРЫТАЯ ЗАМЕТКА · TASKMAN</p><h1>{escape(title)}</h1><pre>{escape(body)}</pre></article>
  </body>
</html>"""


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

    @application.get("/public/notes/{token}", response_class=HTMLResponse, include_in_schema=False)
    def public_note_page(token: str, session: Annotated[Session, Depends(get_session)]) -> HTMLResponse:
        note = notes.get_public_note(session, token)
        public_url = settings.public_url.rstrip("/")
        url = f"{public_url}/public/notes/{token}"
        return HTMLResponse(
            _public_note_html(note.title, _public_note_description(note.content_markdown), url, note.content_markdown)
        )

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
