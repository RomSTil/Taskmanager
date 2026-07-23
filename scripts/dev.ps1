$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path "$projectRoot\.venv\Scripts\python.exe")) {
    python -m venv "$projectRoot\.venv"
}

& "$projectRoot\.venv\Scripts\python.exe" -m pip install -e "$projectRoot\backend[dev]"
Start-Process -WindowStyle Hidden -FilePath "$projectRoot\.venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8765", "--reload", "--no-server-header" -WorkingDirectory "$projectRoot\backend"

Push-Location "$projectRoot\frontend\task manager"
try {
    npm.cmd install
    npm.cmd run tauri dev
} finally {
    Pop-Location
}
