param(
    [string]$OutputPath = "",
    [string]$Database = "taskman",
    [string]$User = "taskman",
    [string]$DbHost = "127.0.0.1",
    [int]$Port = 5432
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$defaultOutputDir = Join-Path $projectRoot "backups"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $defaultOutputDir "taskman-$timestamp.sql"
}

function Resolve-PgDump {
    $candidates = @(
        "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\15\bin\pg_dump.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

function Ensure-ParentDir([string]$Path) {
    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }
}

Ensure-ParentDir -Path $OutputPath

$pgDump = Resolve-PgDump
if (-not $pgDump) {
    throw "pg_dump.exe was not found. Install PostgreSQL client tools or add pg_dump.exe to PATH."
}

Write-Host "Exporting from local PostgreSQL at $DbHost`:$Port to $OutputPath"
& $pgDump -h $DbHost -p $Port -U $User -d $Database -F p -f $OutputPath
