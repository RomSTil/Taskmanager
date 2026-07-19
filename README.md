# Taskman

Личный центр управления проектами: задачи, Markdown-vault, Telegram-тикеты и контекст для Codex через локальный MCP bridge.

## Что уже входит в MVP

- FastAPI API с первоначальной настройкой единственного владельца, JWT/refresh-сессиями и scoped API-токенами.
- Проекты, Kanban, подзадачи, чек-листы, комментарии, приоритеты, сроки, теги, saved views и архив.
- Канонический Markdown-vault с frontmatter, ревизиями, `[[wikilinks]]`, backlinks, поиском, вложениями и конфликтными копиями.
- Tauri + React desktop: visual/raw/split редактор, offline-кэш задач, очередь операций, watcher и синхронизация локального vault.
- Несколько Telegram-ботов с allowlist, командами, inline-кнопками, webhook idempotency и PostgreSQL outbox.
- Локальный stdio MCP bridge для Codex; в нём отсутствует hard-delete.
- Docker Compose: PostgreSQL, API, Telegram worker, Caddy/HTTPS и ежедневные резервные копии.

## Локальная разработка

Требования: Python 3.12, Node.js 20+, Rust stable с Windows MSVC toolchain и WebView2.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.\backend[dev]'
Set-Location backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8765
```

Во втором терминале:

```powershell
Set-Location desktop
npm install
npm run tauri dev
```

В development-режиме backend использует SQLite и создаёт таблицы автоматически. Production всегда использует Alembic и PostgreSQL.

## VPS

1. Настройте DNS домена на VPS и откройте TCP 80/443 и UDP 443.
2. Скопируйте `.env.example` в `.env`, замените домен, пароль БД и все секреты. Секреты можно сгенерировать через `scripts/generate-secrets.ps1`.
3. Запустите `docker compose up -d --build`.
4. Откройте desktop, укажите `https://ваш-домен` и создайте владельца с `TASKMAN_SETUP_TOKEN`.

Проверка: `/healthz` показывает жизнь процесса, `/readyz` дополнительно проверяет БД. Каталог `backups/` содержит дамп PostgreSQL, архив vault и контрольные суммы. Обязательно копируйте его за пределы VPS.

## Telegram

В desktop откройте **Настройки → Telegram-боты**, добавьте токен BotFather, default project и Telegram user/chat ID в allowlist. После сохранения нажмите **Webhook**. Обычный текст создаёт тикет; доступны `/help`, `/new`, `/tasks`, `/search`, `/status`, `/priority`, `/due`, `/project`, `/comment`.

## Codex MCP

Создайте токен в **Настройки → Codex MCP**, затем установите bridge:

```powershell
python -m pip install -e .\mcp-bridge
taskman-mcp login --url https://tasks.example.com
```

Добавьте в пользовательский `~/.codex/config.toml`:

```toml
[mcp_servers.taskman]
command = "taskman-mcp"
args = ["serve"]
default_tools_approval_mode = "writes"
startup_timeout_sec = 15
tool_timeout_sec = 60
```

Bridge хранит токен в системном credential store. Codex автоматически получает read-tools без лишних подтверждений, а операции записи попадают под режим `writes`. После изменения конфигурации перезапустите Codex и проверьте сервер через `/mcp` или `codex mcp list`.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests
.\.venv\Scripts\python.exe -m ruff check backend mcp-bridge
Set-Location desktop
npm test
npm run build
```

Rust/Tauri: `npm run tauri build`. Windows installer появляется в `desktop/src-tauri/target/release/bundle`.
