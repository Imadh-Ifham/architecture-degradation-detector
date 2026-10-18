# C3 quality gate: ruff, mypy --strict and pytest for the degradation detection component.
# Run from anywhere:  backend/scripts/check.ps1        (C3 tests only, no Docker needed)
#                     backend/scripts/check.ps1 -All   (whole backend suite, needs the containers up)
param([switch]$All)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# Paths C3 owns. Extend as C3 adds files to app/core, app/domain, app/shared and scripts.
# Shared folders are listed file by file: other components add their own modules there.
$c3Shared = @(
    "app/domain/analysis_run.py", "app/domain/audit_entry.py", "app/domain/boundary.py",
    "app/domain/canonical_release.py",
    "app/domain/degradation_event.py", "app/domain/release_package.py",
    "app/infrastructure/postgres/models/c3_analysis_run.py",
    "app/infrastructure/postgres/models/c3_release.py",
    "app/infrastructure/postgres/repositories/c3_analysis_run_repository.py",
    "app/infrastructure/postgres/repositories/c3_release_repository.py",
    "alembic/versions/0001_c3_ingestion.py", "alembic/versions/0002_c3_analysis_run.py"
)
$c3Source = @(
    "app/components/degradation_detection", "app/core/logging.py", "app/shared", "scripts/c3.py"
) + $c3Shared
# Integration tests (PostgreSQL) are linted here but run only with -All.
$c3Tests = @(
    "tests/components/degradation_detection", "tests/core/test_logging.py", "tests/domain",
    "tests/scripts", "tests/shared"
)
$c3IntegrationTests = @(
    "tests/infrastructure/postgres/test_c3_analysis_run_repository.py",
    "tests/infrastructure/postgres/test_c3_release_repository.py"
)
$c3Lint = $c3Source + $c3Tests + $c3IntegrationTests + @("tests/conftest.py")

function Invoke-Step([string]$Name, [scriptblock]$Step) {
    Write-Host "== $Name" -ForegroundColor Cyan
    & $Step
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Name" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Invoke-Step "ruff check" { uv run ruff check @c3Lint }
Invoke-Step "ruff format --check" { uv run ruff format --check @c3Lint }
Invoke-Step "mypy --strict" { uv run mypy }
# Coverage targets: >= 85% on the component, >= 95% on trends/ (M4, the statistics everything
# else is judged by). One pytest run records the data; `coverage report` gates trends/ from it.
$c3Cov = @(
    "--cov=app/components/degradation_detection", "--cov-report=term", "--cov-fail-under=85"
)
if ($All) {
    Invoke-Step "pytest (all)" { uv run pytest @c3Cov }
} else {
    Invoke-Step "pytest (C3)" { uv run pytest @c3Tests -m "not integration and not llm" @c3Cov }
}
Invoke-Step "coverage trends/ >= 95%" {
    uv run coverage report --include="app/components/degradation_detection/trends/*" --fail-under=95
}

Write-Host "All checks passed." -ForegroundColor Green
