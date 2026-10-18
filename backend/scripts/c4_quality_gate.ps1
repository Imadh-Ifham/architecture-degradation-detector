<#
.SYNOPSIS
    Runs the degradation scoring (C4) quality gates and saves the output as evidence.

.DESCRIPTION
    Author: Dahami
    Date: 2026-10-18

    Runs the four gates from app/components/degradation_scoring/CLAUDE.md §7 on
    the C4 paths only (the component, plus the C4-owned domain contract and
    scripts and their tests): ruff lint, ruff format check, mypy (strict flags from
    pyproject.toml), and pytest with coverage (minimum 80 %). Every gate runs
    even if an earlier one fails, so one report shows all problems.

    The full output is written to
    app/components/degradation_scoring/docs/pp1/evidence/quality-gate-<timestamp>.txt
    together with the git commit and tool versions, so a result can be traced.
    Exit code is 0 only when all four gates pass.

    Stand-in for a CI job until the team adds one (C4-ADR-000, open issue O6).

.EXAMPLE
    cd backend
    powershell -ExecutionPolicy Bypass -File scripts/c4_quality_gate.ps1
#>

$ErrorActionPreference = "Continue"

$backend = Split-Path -Parent $PSScriptRoot
Set-Location $backend

$sourcePath = "app/components/degradation_scoring"
$testPath = "tests/components/degradation_scoring"
# C4-owned files outside the component folder, and their tests (C4-T05, C4-T12 adapters).
$extraSources = @("app/domain/severity_report.py", "scripts/scoring_export_schemas.py",
                  "app/infrastructure/git/history.py",
                  "app/infrastructure/postgres/models/c4_mining_cache.py",
                  "app/infrastructure/postgres/repositories/mining_cache_repository.py",
                  "alembic/versions/0002_c4_mining_cache.py",
                  "scripts/c4_hotspot_profile.py",
                  "app/infrastructure/postgres/models/c4_scoring_run.py",
                  "app/infrastructure/postgres/repositories/scoring_run_repository.py",
                  "alembic/versions/0003_c4_scoring_run.py",
                  "scripts/c4_run_features.py")
$extraTests = @("tests/domain/test_severity_report.py", "tests/scripts/test_scoring_export_schemas.py",
                "tests/infrastructure/git/test_history.py",
                "tests/infrastructure/postgres/test_mining_cache_repository.py",
                "tests/infrastructure/postgres/test_scoring_run_repository.py")
$allPaths = @($sourcePath, $testPath) + $extraSources + $extraTests
# Stricter lint rules for C4 only; pyproject.toml keeps ruff's defaults for
# everyone else. I = import order, UP = modern syntax, B = likely bugs,
# SIM = simplifications, N = naming, RUF = ruff-specific checks.
$extraLintRules = "I,UP,B,SIM,N,RUF"
$minimumCoverage = 80
# Keep coverage's data file out of the working tree (it is not git-ignored).
$env:COVERAGE_FILE = Join-Path ([System.IO.Path]::GetTempPath()) "c4-quality-gate.coverage"

$evidenceDir = Join-Path $backend "$sourcePath/docs/pp1/evidence"
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$report = Join-Path $evidenceDir "quality-gate-$timestamp.txt"

$gates = @(
    @{ Name = "ruff check";        Args = @("run", "ruff", "check", "--extend-select", $extraLintRules) + $allPaths },
    @{ Name = "ruff format";       Args = @("run", "ruff", "format", "--check") + $allPaths },
    @{ Name = "mypy";              Args = @("run", "mypy") + $allPaths },
    @{ Name = "pytest + coverage"; Args = @("run", "pytest", $testPath) + $extraTests + @("-q", "-p", "no:cacheprovider",
                                            "--cov=app.components.degradation_scoring",
                                            "--cov=app.domain.severity_report",
                                            "--cov=scripts.scoring_export_schemas",
                                            "--cov=app.infrastructure.git.history",
                                            "--cov=app.infrastructure.postgres.repositories.mining_cache_repository",
                                            "--cov=app.infrastructure.postgres.repositories.scoring_run_repository",
                                            "--cov-report=term-missing",
                                            "--cov-fail-under=$minimumCoverage") }
)

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("C4 quality gate report")
$lines.Add("Date (UTC): $((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss'))")
$lines.Add("Git commit: $(git rev-parse --short HEAD) on $(git branch --show-current)")
$lines.Add("Uncommitted changes: $(@(git status --porcelain).Count) paths")
$lines.Add("Python: $(uv run python --version 2>&1)")
$lines.Add("uv: $(uv --version)")
$lines.Add("")

$results = @()
foreach ($gate in $gates) {
    $lines.Add("=== $($gate.Name): uv $($gate.Args -join ' ') ===")
    $output = & uv @($gate.Args) 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    foreach ($line in $output) { $lines.Add($line) }
    $status = if ($code -eq 0) { "PASS" } else { "FAIL (exit $code)" }
    $lines.Add("--- $($gate.Name): $status")
    $lines.Add("")
    $results += [pscustomobject]@{ Gate = $gate.Name; Result = $status }
}

$lines.Add("=== Summary ===")
foreach ($r in $results) { $lines.Add(("{0,-20} {1}" -f $r.Gate, $r.Result)) }
$lines | Set-Content -Path $report -Encoding utf8

$results | Format-Table -AutoSize | Out-String | Write-Host
Write-Host "Report saved to $report"

if ($results | Where-Object { $_.Result -ne "PASS" }) { exit 1 }
exit 0
