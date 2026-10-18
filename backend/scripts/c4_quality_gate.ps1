<#
.SYNOPSIS
    Runs the degradation scoring (C4) quality gates and saves the output as evidence.

.DESCRIPTION
    Author: Dahami
    Date: 2026-10-18

    Runs the four gates from app/components/degradation_scoring/CLAUDE.md §7 on
    the C4 paths only: ruff lint, ruff format check, mypy (strict flags from
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
    @{ Name = "ruff check";        Args = @("run", "ruff", "check", "--extend-select", $extraLintRules, $sourcePath, $testPath) },
    @{ Name = "ruff format";       Args = @("run", "ruff", "format", "--check", $sourcePath, $testPath) },
    @{ Name = "mypy";              Args = @("run", "mypy", $sourcePath, $testPath) },
    @{ Name = "pytest + coverage"; Args = @("run", "pytest", $testPath, "-q", "-p", "no:cacheprovider",
                                            "--cov=app.components.degradation_scoring",
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
