# PP1 demo runner for C4. The main ranking is made in the app (Pipeline: Detect, then Score);
# this script prepares the supporting runs: the fixture shop with the decision check on/off,
# Online Boutique with hand-made events and real history, and (if C3 ran its CLI) the CLI
# detection run out/<run>/events.json as demo-c3. -Warm fills the git history cache, also for
# the latest detection run started from the Pipeline page. Each step prints its time.
# Script: docs/pp1/demo-script.md
#   cd backend
#   powershell -ExecutionPolicy Bypass -File scripts/c4_demo.ps1 -Warm    # once, after C3's run
#   powershell -ExecutionPolicy Bypass -File scripts/c4_demo.ps1 -Ui      # the demo
#   ... -NoOpen  (do not open anything)   -SkipDb  (no Postgres)
#   ... -Ui      (open http://localhost:5173/priorities?run=<id> instead of the HTML files)
#   ... -C3Run <id>        detection's run to score (default RUN-demo)
#   ... -C3Packages <dir>  where its release packages are (default: searched under data/)
#   ... -C3Provenance <p>  banner label (default: live for Online Boutique, else fixture)

param([switch]$Warm, [switch]$NoOpen, [switch]$SkipDb, [switch]$Ui,
      [string]$C3Run = "RUN-demo", [string]$C3Packages = "data", [string]$C3Provenance = "")

$ErrorActionPreference = "Continue"
$backend = Split-Path -Parent $PSScriptRoot
Set-Location $backend
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

$F = "tests/fixtures/degradation_scoring"
$out = "artifacts/scoring"
$repo = "C:\repos\add-repositories\c4-history\microservices-demo"
$history = @("--repo", $repo, "--db-cache",
             "--source-paths", "$F/mappings/online_boutique.source_paths.v1.json")
$fixture = @("--events", "$F/events/fixture_events.v1.json",
             "--graph", "$F/graphs/fixture_release_package.v1.5.0.json")
$boutique = @("--events", "$F/events/online_boutique_events.v1.json",
              "--graph", "$F/graphs/online_boutique_graph.v0.10.7.json") + $history +
            @("--data-provenance", "fixture-events+live-history")
$failed = @()

function Step([string]$name, [scriptblock]$action) {
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    & $action | Out-Null
    $ok = $LASTEXITCODE -eq 0
    $clock.Stop()
    $state = if ($ok) { "ok" } else { "FAILED (exit $LASTEXITCODE)" }
    Write-Output ("{0,-48} {1,6:N1} s  {2}" -f $name, $clock.Elapsed.TotalSeconds, $state)
    if (-not $ok) { $script:failed += $name }
}

# detection's run: its events, the package of the release it ended at, and whether it is
# Online Boutique (then the real history of the clone is used). $null when it has not run here.
function DetectionRun {
    $events = "out/$C3Run/events.json"
    if (-not (Test-Path $events)) { return $null }
    $first = (Get-Content $events -Raw | ConvertFrom-Json) | Select-Object -First 1
    $name = "$($first.system_id)__$($first.window.end_release).json"
    $package = Get-ChildItem $C3Packages -Recurse -Filter $name -ErrorAction SilentlyContinue |
               Select-Object -First 1
    $isBoutique = $first.system_id -match "^(online-boutique|microservices-demo)"
    $provenance = if ($C3Provenance) { $C3Provenance } elseif ($isBoutique) { "live" } else { "fixture" }
    $arguments = @("--events", $events, "--data-provenance", $provenance)
    if ($package) { $arguments += @("--graph", $package.FullName) }
    if ($isBoutique) { $arguments += $history }
    return @{ System = $first.system_id; Package = $name; Found = [bool]$package;
              Args = $arguments }
}

$detection = DetectionRun
if ($detection -and -not $detection.Found) {
    Write-Output "detection run $C3Run found, but no release package $($detection.Package) under $C3Packages (use -C3Packages <dir>)"
    $detection = $null
}

if ($Warm) {
    # first mine of the history windows into the Postgres cache (minutes, once per machine)
    Remove-Item -Recurse -Force "$out/*/demo-warm*" -ErrorAction SilentlyContinue
    Step "warm: Online Boutique fixture windows" {
        uv run python -m scripts.c4_rank @boutique --no-adr --run-id demo-warm 2>$null
    }
    if ($detection) {
        Step "warm: detection run $C3Run windows" {
            uv run python -m scripts.c4_rank @($detection.Args) --no-adr --run-id demo-warm-c3 2>$null
        }
    }
    # the latest run started from the Pipeline page (what its Score button will read)
    foreach ($latest in Get-ChildItem "artifacts/degradation/*/latest" -Directory -ErrorAction SilentlyContinue) {
        if ((Get-Content "$($latest.FullName)/events.json" -Raw | ConvertFrom-Json).Count -eq 0) { continue }
        Step "warm: pipeline detection run of $($latest.Parent.Name)" {
            uv run python -m scripts.c4_rank --events "$($latest.FullName)/events.json" `
                --graph "$($latest.FullName)/release_package.json" @history --no-adr `
                --run-id demo-warm-pipeline --outputs-root "$env:TEMP/c4-warm" 2>$null
        }
        Remove-Item -Recurse -Force "$env:TEMP/c4-warm" -ErrorAction SilentlyContinue
    }
    Remove-Item -Recurse -Force "$out/*/demo-warm*" -ErrorAction SilentlyContinue
    exit $failed.Count
}

# 1. reset: demo report folders and the demo rows in Postgres (rows cascade from the run)
foreach ($folder in @("$out/*/demo-c3", "$out/c4-fixture-shop/demo-adr-on",
                      "$out/c4-fixture-shop/demo-adr-off", "$out/online-boutique/demo-ob")) {
    Remove-Item -Recurse -Force $folder -ErrorAction SilentlyContinue
}
$reset = @"
from sqlalchemy import text
from app.infrastructure.postgres.database import engine
with engine.begin() as db:
    db.execute(text("DELETE FROM c4_scoring_run WHERE run_id IN ('demo-c3', 'fixture-demo-adr-on', 'fixture-demo-adr-off')"))
"@
if (-not $SkipDb) { Step "reset demo rows in Postgres" { $reset | uv run python - 2>$null } }
$save = @()
if (-not $SkipDb) { $save = @("--save-db") }

# 2. the hand-over: detection's run scored unchanged (report files + Postgres rows)
$opened = @()
if ($detection) {
    Step "detection run $C3Run scored (demo-c3)" {
        uv run python -m scripts.c4_rank @($detection.Args) --no-adr @save --run-id demo-c3 2>$null
    }
    $opened += "$($detection.System)/demo-c3"
} elseif (-not (Test-Path "out/$C3Run/events.json")) {
    Write-Output "detection run $C3Run not found (out/$C3Run/events.json): run C3's pipeline first; demo-ob is the fallback"
}

# 3. fixture shop, decision check on and off: the one system where all four parts can be shown
Step "fixture shop, decision check on  (demo-adr-on)" {
    uv run python -m scripts.c4_rank @fixture --adr-index "$F/adr" --run-id demo-adr-on 2>$null
}
Step "fixture shop, decision check off (demo-adr-off)" {
    uv run python -m scripts.c4_rank @fixture --no-adr --run-id demo-adr-off 2>$null
}
if (-not $SkipDb) {
    Step "Postgres run, decision check on  (fixture-demo-adr-on)" {
        uv run python -m scripts.c4_run_features --run-id fixture-demo-adr-on 2>$null
    }
    Step "Postgres run, decision check off (fixture-demo-adr-off)" {
        uv run python -m scripts.c4_run_features --no-adr --run-id fixture-demo-adr-off 2>$null
    }
}
$opened += @("c4-fixture-shop/demo-adr-on", "c4-fixture-shop/demo-adr-off")

# 4. fallback: Online Boutique with hand-made events and real history from the cache
Step "Online Boutique, hand-made events (demo-ob)" {
    uv run python -m scripts.c4_rank @boutique --no-adr --run-id demo-ob 2>$null
}
$opened += "online-boutique/demo-ob"

if (-not $NoOpen) {
    foreach ($run in $opened) {
        if ($Ui) {
            Start-Process "http://localhost:5173/priorities?run=$(Split-Path -Leaf $run)"
        } else {
            $html = Get-ChildItem "$out/$run/c4_report.html" -ErrorAction SilentlyContinue |
                    Select-Object -First 1
            if ($html) { Start-Process $html.FullName }
        }
    }
}

if ($failed.Count -gt 0) {
    Write-Output "FAILED: $($failed -join ', ')  -> use the fallback in demo-script.md"
}
exit $failed.Count
