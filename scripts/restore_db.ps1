param(
    [Parameter(Mandatory = $true)]
    [string]$DumpPath
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $DumpPath)) {
    throw "Dump file not found: $DumpPath"
}

$dumpFileName = Split-Path $DumpPath -Leaf

docker cp $DumpPath "market_risk_db:/tmp/$dumpFileName"
docker exec market_risk_db pg_restore -U market_risk -d market_risk --clean --if-exists "/tmp/$dumpFileName"

Write-Host "Database restored from: $DumpPath"
