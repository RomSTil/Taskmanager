# Taskman

Taskman — локальный task manager для проектов, задач, заметок и дедлайнов. Desktop-клиент построен на Tauri и React, backend — на FastAPI.

## Возможности

- проекты, рабочие пространства и Markdown-заметки;
- задачи со статусом, приоритетом, исполнителем и диапазоном дедлайна;
- priority-board «Низкий / Обычный / Высокий / Срочный»;
- drag-and-drop для изменения приоритета и порядка задач;
- календарный режим с горизонтальной шкалой дедлайнов;
- фильтр задач по проекту;
- JWT-аутентификация, Telegram-интеграция и MCP bridge для Codex;
- SQLite для разработки и PostgreSQL для production.

## Структура

```text
backend/                 FastAPI API, модели, миграции и тесты
frontend/task manager/   актуальный React + Tauri интерфейс
desktop/                 предыдущий desktop-клиент
mcp-bridge/              MCP bridge для Codex
infra/                   Caddy и backup-скрипты
scripts/                 скрипты разработки
```

## Требования

Python 3.12+, Node.js 20+, Rust stable и WebView2 для сборки Tauri.

## Быстрый запуск

В первом терминале запустите backend:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"
Set-Location backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8765
```

Во втором терминале запустите frontend:

```powershell
Set-Location "frontend\task manager"
npm install
npm run dev
```

Откройте `http://127.0.0.1:1420` и укажите backend `http://127.0.0.1:8765`. Для desktop-режима используйте `npm run tauri dev`.

## Тесты и сборка

```powershell
# backend — из корня
.\.venv\Scripts\python.exe -m pytest -q

# frontend
Set-Location "frontend\task manager"
npm test -- --run
npm run build
```

## Production

Production-конфигурация запускается через PostgreSQL, FastAPI, Telegram worker и Caddy:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

Перед запуском замените домен, пароли базы данных и секреты в `.env`. Состояние сервиса проверяется через `/healthz`, готовность приложения и базы — через `/readyz`.

## MCP bridge для Codex

```powershell
python -m pip install -e .\mcp-bridge
taskman-mcp login --url https://tasks.example.com
```

Конфигурация Codex:

```toml
[mcp_servers.taskman]
command = "taskman-mcp"
args = ["serve"]
default_tools_approval_mode = "writes"
startup_timeout_sec = 15
tool_timeout_sec = 60
```

## Безопасность

Не добавляйте `.env`, токены, пароли, локальную базу и `.venv` в Git. Для production используйте PostgreSQL, HTTPS и резервные копии.

Backend организован как расширяемый модульный монолит. Инструкции по подключению новых модулей
находятся в [`backend/ARCHITECTURE.md`](backend/ARCHITECTURE.md), результаты security review —
в [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md).

Модули Яндекс Директа, событий, уведомлений и MAX-бота описаны в
[`docs/YANDEX_DIRECT_MAX.md`](docs/YANDEX_DIRECT_MAX.md).

## Статус и лицензия

Проект находится в активной разработке. Лицензия пока не выбрана.
