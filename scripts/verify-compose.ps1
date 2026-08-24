$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repoRoot
try {
    $composeVersion = docker compose version --short
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is unavailable.' }
    $normalized = $composeVersion.TrimStart('v').Split('-')[0]
    if ([version]$normalized -lt [version]'2.20.0') {
        throw "Docker Compose 2.20 or newer is required; found $composeVersion."
    }

    1..2 | ForEach-Object {
        Write-Host "Compose startup pass $_ of 2"
        docker compose up --build --wait --wait-timeout 180
        if ($LASTEXITCODE -ne 0) { throw "Compose startup pass $_ failed." }

        $expectedServices = @('api', 'db', 'web', 'worker')
        $runningServices = @(docker compose ps --services --status running | Sort-Object)
        if ($LASTEXITCODE -ne 0) { throw 'Unable to list running Compose services.' }
        if (Compare-Object $expectedServices $runningServices) {
            throw "Expected api, db, web, and worker to be running; found $($runningServices -join ', ')."
        }
        foreach ($service in $expectedServices) {
            $containerId = (docker compose ps -q $service).Trim()
            if (-not $containerId) { throw "No container exists for $service." }
            $status = (docker inspect --format '{{.State.Health.Status}}' $containerId).Trim()
            if ($LASTEXITCODE -ne 0 -or $status -ne 'healthy') {
                throw "$service health was '$status' on pass $_."
            }
        }

        $health = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/health'
        if ($health.status -ne 'ok') { throw "API was not healthy on pass $_." }

        $web = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:3001/api/health'
        if ($web.StatusCode -ne 200) { throw "Web was not healthy on pass $_." }

        if ($_ -eq 1) {
            $candidates = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/candidates'
            if ($candidates.total -lt 8) { throw "Expected at least eight seeded candidates; found $($candidates.total)." }
            $schedules = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/schedules'
            if ($schedules.total -ne 6) { throw "Expected six seeded schedules; found $($schedules.total)." }
        }
    }

    Write-Host 'Compose started twice; bootstrap remained idempotent.'
} finally {
    Pop-Location
}
