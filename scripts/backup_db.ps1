param(
    [string]$OutputDir = "C:\market_risk_project\backups",
    [string]$DumpFileName = "market_risk.dump"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$dumpPath = Join-Path $OutputDir $DumpFileName

docker exec market_risk_db sh -c "rm -f /tmp/$DumpFileName"
docker exec market_risk_db pg_dump -U market_risk -d market_risk -F c -f "/tmp/$DumpFileName"
docker cp "market_risk_db:/tmp/$DumpFileName" $dumpPath

Write-Host "Database dump created: $dumpPath"
