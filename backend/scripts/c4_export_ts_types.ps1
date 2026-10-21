# Regenerates the frontend's TypeScript types for the C4 severity report from the committed
# JSON Schema. Run after the report contract changes (and after scoring_export_schemas).
#   cd backend
#   powershell -ExecutionPolicy Bypass -File scripts/c4_export_ts_types.ps1

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$schema = "backend/app/components/degradation_scoring/docs/schemas/severity_report.schema.json"
$target = "frontend/src/lib/severityReport.ts"
$generator = "json-schema-to-typescript@15.0.4"

Push-Location $repo
try {
    $body = npx --yes $generator -i $schema --additionalProperties=false --bannerComment '""'
    if ($LASTEXITCODE -ne 0) { throw "$generator failed" }
    $header = @(
        "// GENERATED from $schema - do not edit.",
        "// Regenerate: cd backend; powershell -ExecutionPolicy Bypass -File scripts/c4_export_ts_types.ps1",
        ""
    )
    $text = (($header + $body) -join "`n") + "`n"
    [System.IO.File]::WriteAllText((Join-Path $repo $target), $text, (New-Object System.Text.UTF8Encoding $false))
    Write-Output "wrote $target"
}
finally {
    Pop-Location
}
