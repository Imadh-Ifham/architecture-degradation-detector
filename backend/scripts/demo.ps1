# C3 PP1 demo (plan T-15): clean database -> stub -> ingest -> run -> report -> evaluation.
#
# Run from anywhere:  backend/scripts/demo.ps1             (add -SkipSync to skip `uv sync`)
# Needs uv and Docker Desktop running. Works on a fresh clone without a .env.
#
# The demo has its own database, c3_demo, dropped and recreated every time: the migrations run
# from empty and the development database is never touched. The settings below are set for this
# script only (the environment wins over .env) and the caller's values are restored at the end.
# Outputs: backend/out/RUN-demo/ (events.json, series.csv, report.md, plots/, mvp_eval.md).
# The run id is fixed, so a second demo produces byte-identical events.
param([switch]$SkipSync)

$RunId = "RUN-demo"
$System = "shopfront"

# Every setting the backend requires. PostgreSQL: the dev container from docker-compose.yml, with
# the demo database. C3 never connects to Neo4j, but the settings must exist to load.
$demoEnv = [ordered]@{
    POSTGRES_HOST     = "localhost"
    POSTGRES_PORT     = "5434"
    POSTGRES_DB       = "c3_demo"
    POSTGRES_USER     = "architecture"
    POSTGRES_PASSWORD = "architecture_dev_password"
    NEO4J_URI         = "bolt://localhost:7687"
    NEO4J_USER        = "neo4j"
    NEO4J_PASSWORD    = "neo4j_dev_password"
}

function Invoke-Step([string]$Name, [scriptblock]$Step) {
    Write-Host ""
    Write-Host "== $Name" -ForegroundColor Cyan
    & $Step
    if ($LASTEXITCODE -ne 0) {
        throw "step failed: $Name (exit code $LASTEXITCODE)"
    }
}

function Wait-Postgres {
    # -h 127.0.0.1: during first start-up the image runs a temporary server on the Unix socket
    # only; waiting on TCP skips it and answers once the real server is up.
    for ($i = 0; $i -lt 60; $i++) {
        docker compose exec -T postgres pg_isready -h 127.0.0.1 -U architecture -q
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 1
    }
    throw "PostgreSQL did not become ready within 60 seconds"
}

$saved = @{}
foreach ($name in $demoEnv.Keys) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}
$clock = [Diagnostics.Stopwatch]::StartNew()
Push-Location (Join-Path $PSScriptRoot "..")
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is not installed: https://docs.astral.sh/uv/"
    }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker is not running: start Docker Desktop and run the demo again"
    }
    foreach ($name in $demoEnv.Keys) {
        [Environment]::SetEnvironmentVariable($name, $demoEnv[$name], "Process")
    }

    if (-not $SkipSync) {
        Invoke-Step "install (uv sync)" { uv sync }
    }
    Invoke-Step "start PostgreSQL" { docker compose up -d postgres }
    Invoke-Step "wait for PostgreSQL" { Wait-Postgres }  # returns right after pg_isready said 0
    # Keep the database name in step with POSTGRES_DB above (a test checks it).
    Invoke-Step "recreate the demo database" {
        docker compose exec -T postgres psql -U architecture -d postgres -q -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS c3_demo WITH (FORCE);" -c "CREATE DATABASE c3_demo;"
    }
    Invoke-Step "migrate (alembic upgrade head)" { uv run alembic upgrade head }
    $out = Join-Path "out" $RunId
    if (Test-Path $out) { Remove-Item -Recurse -Force $out }

    Invoke-Step "generate the synthetic system" {
        uv run python -m scripts.c3 --log-level WARNING stub generate
    }
    Invoke-Step "ingest (M1)" {
        uv run python -m scripts.c3 --log-level WARNING ingest data/samples/shopfront
    }
    Invoke-Step "analyse (M2 -> M4, events)" {
        uv run python -m scripts.c3 --log-level WARNING run --system $System --run-id $RunId
    }
    Invoke-Step "report from the stored run" {
        uv run python -m scripts.c3 --log-level WARNING report --run-id $RunId
    }
    Invoke-Step "evaluate against the ground truth" {
        uv run python -m scripts.mvp_eval --run-id $RunId
    }

    $clock.Stop()
    Write-Host ""
    Write-Host ("Demo finished in {0:N0} s. Outputs in backend/{1}/:" -f $clock.Elapsed.TotalSeconds, ($out -replace "\\", "/")) -ForegroundColor Green
    Get-ChildItem $out | ForEach-Object { Write-Host "  $($_.Name)" }
}
catch {
    Write-Host ""
    Write-Host "DEMO FAILED: $_" -ForegroundColor Red
    exit 1
}
finally {
    # Restore the caller's environment, so the demo database does not leak into the next command.
    foreach ($name in $saved.Keys) {
        [Environment]::SetEnvironmentVariable($name, $saved[$name], "Process")
    }
    Pop-Location
}
