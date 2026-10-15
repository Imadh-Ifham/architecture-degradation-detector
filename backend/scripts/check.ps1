# C3 quality gate: ruff, mypy --strict and pytest for the degradation detection component.
# Run from anywhere:  backend/scripts/check.ps1        (C3 tests only, no Docker needed)
#                     backend/scripts/check.ps1 -All   (whole backend suite, needs the containers up)
param([switch]$All)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# Paths C3 owns. Extend as C3 adds files to app/core, app/domain, app/shared and scripts.
$c3Source = @(
    "app/components/degradation_detection", "app/domain", "app/shared", "scripts/c3.py"
)
$c3Tests = @(
    "tests/components/degradation_detection", "tests/domain", "tests/scripts", "tests/shared"
)
$c3Lint = $c3Source + $c3Tests

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
if ($All) {
    Invoke-Step "pytest (all)" { uv run pytest }
} else {
    Invoke-Step "pytest (C3)" { uv run pytest @c3Tests -m "not integration and not llm" }
}

Write-Host "All checks passed." -ForegroundColor Green
