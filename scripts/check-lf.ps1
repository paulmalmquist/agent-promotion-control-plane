$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$tracked = @()

if (Test-Path (Join-Path $repoRoot '.git')) {
    $tracked = git -C $repoRoot ls-files '*.sh'
    if ($LASTEXITCODE -ne 0) { throw 'git ls-files failed' }
} else {
    $tracked = Get-ChildItem -LiteralPath $repoRoot -Recurse -File -Filter '*.sh' |
        ForEach-Object { $_.FullName.Substring($repoRoot.Length + 1) }
}

$failures = @()
foreach ($relativePath in $tracked) {
    $path = Join-Path $repoRoot $relativePath
    $bytes = [System.IO.File]::ReadAllBytes($path)
    if ($bytes -contains 13) { $failures += "$relativePath contains a carriage return" }
}

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "LF validation passed for $($tracked.Count) shell script(s)."
