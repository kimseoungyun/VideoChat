# Start N Daphne processes (ports 8020, 8021, ...) sharing one Redis, for loadtest/matching.py.
# Usage: .\loadtest\serve.ps1 -Workers 4 -RedisUrl redis://127.0.0.1:6380/0
#        .\loadtest\serve.ps1 -Stop
param([int]$Workers = 1, [string]$RedisUrl = 'redis://127.0.0.1:6379/0', [switch]$Stop)
$root = Split-Path $PSScriptRoot -Parent
$pidFile = Join-Path $root '.runtime\loadtest-servers.txt'
if (Test-Path $pidFile) {
    # PIDs get reused: only stop processes that are still our Daphne servers.
    Get-Content $pidFile | ForEach-Object {
        Get-Process -Id $_ -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -eq 'daphne' } |
            Stop-Process -Confirm:$false
    }
    Remove-Item $pidFile
}
if ($Stop) { return }
New-Item -ItemType Directory -Force (Join-Path $root '.runtime') | Out-Null
$env:REDIS_URL = $RedisUrl
$env:DJANGO_DEBUG = '1'
$env:DATABASE_PATH = Join-Path $root '.runtime\load.sqlite3'
# Every simulated user shares 127.0.0.1, so lift the per-IP limits for this run only.
$env:WS_MAX_PER_IP = '100000'
$env:WS_CONNECT_RATE = '100000'
# Simulated users never see the consent page; the gate has its own server and e2e tests.
$env:CONSENT_REQUIRED = '0'
& "$root\.venv\Scripts\python.exe" "$root\backend\manage.py" migrate -v 0
$bases = foreach ($i in 0..($Workers - 1)) {
    $port = 8020 + $i
    $log = Join-Path $root ".runtime\daphne-$port"
    $p = Start-Process -FilePath "$root\.venv\Scripts\daphne.exe" -WorkingDirectory "$root\backend" `
        -ArgumentList "-b 127.0.0.1 -p $port myproj.asgi:application" -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput "$log.out" -RedirectStandardError "$log.log"
    Add-Content $pidFile $p.Id
    "http://127.0.0.1:$port"
}
foreach ($base in $bases) {
    foreach ($attempt in 1..30) {
        try { Invoke-WebRequest "$base/health/" -UseBasicParsing -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep 1 }
    }
}
$bases -join ','
