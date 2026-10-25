# Fixed benchmark matrix; appends one JSON line per run to -Out with a -Label.
# Requires Redis. Usage: .\loadtest\bench.ps1 -Label after -RedisUrl redis://127.0.0.1:6380/0
param([string]$Label = 'run', [string]$RedisUrl = 'redis://127.0.0.1:6379/0',
      [string]$Out = 'docs/benchmarks/results.jsonl', [int]$Repeat = 3)
$root = Split-Path $PSScriptRoot -Parent
$python = "$root\.venv\Scripts\python.exe"
New-Item -ItemType Directory -Force (Split-Path (Join-Path $root $Out)) | Out-Null
$matrix = @(
    @{ Workers = 1; Clients = 200; Ramp = 0 },
    @{ Workers = 1; Clients = 200; Ramp = 5 },
    @{ Workers = 4; Clients = 800; Ramp = 0 },
    @{ Workers = 4; Clients = 1000; Ramp = 10 }
)
foreach ($workers in ($matrix | ForEach-Object { $_.Workers } | Sort-Object -Unique)) {
    $bases = & "$PSScriptRoot\serve.ps1" -Workers $workers -RedisUrl $RedisUrl | Select-Object -Last 1
    foreach ($case in $matrix | Where-Object { $_.Workers -eq $workers }) {
        foreach ($i in 1..$Repeat) {
            Start-Sleep 5  # let the previous cohort's disconnects drain so runs stay independent
            $line = & $python "$PSScriptRoot\matching.py" --base $bases --clients $case.Clients `
                --ramp $case.Ramp --timeout 30
            $record = $line | ConvertFrom-Json
            $record | Add-Member label $Label
            $record | Add-Member date (Get-Date -Format 'yyyy-MM-dd')
            $json = $record | ConvertTo-Json -Compress -Depth 5
            Add-Content -Path (Join-Path $root $Out) -Value $json -Encoding utf8
            $json
        }
    }
}
& "$PSScriptRoot\serve.ps1" -Stop
