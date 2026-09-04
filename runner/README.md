# Taskman Agent Runner (Windows)

Локальный runner получает только подписанные поручения из очереди Taskman и
соединяется с сервером только исходящими HTTPS-запросами. Токен runner хранится
в Windows Credential Manager; в `runner.json` остаются только URL, ID устройства
и путь к рабочему репозиторию.

```powershell
cd C:\projects\Taskmanager\runner
py -m pip install -e .
taskman-agent-runner register --api-url https://api.taskman.example --name "Owner PC" --workspace C:\projects\Taskmanager
taskman-agent-runner run
```

Create a dedicated API token with `agent_operations:read` and `agent_operations:write` before pairing. Do not use an MCP Bridge token for the runner.

Для pairing CLI запросит короткоживущий API-token владельца через скрытый ввод.
В production API URL должен использовать HTTPS. Разработчик получает отдельную
Git worktree и не работает в `main`; worktree с изменениями сохраняется для
проверки владельцем, пустая временная worktree очищается автоматически.
