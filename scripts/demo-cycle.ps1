param(
    [string]$ApiBase = 'http://localhost:8000'
)

$ErrorActionPreference = 'Stop'
$headers = @{ 'Idempotency-Key' = 'demo-autonomous-cycle-v1' }
$result = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/demo/cycle" -Headers $headers -ContentType 'application/json' -Body '{}'
$result | ConvertTo-Json -Depth 10
