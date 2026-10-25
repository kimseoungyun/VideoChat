# Replays the original implementation (commit c8d7002) under the same load tool.
# Each run gets a fresh server process and an empty Room table, so runs never inherit
# ghost rooms or request threads still spinning in the original room-number loop.
# Usage: .\loadtest\legacy.ps1 -App <extracted VideoChat_venv\myproj> (Redis on 6379 required)
param([Parameter(Mandatory)][string]$App, [string]$Out = 'docs/benchmarks/results.jsonl', [int]$Repeat = 3)
$root = Split-Path $PSScriptRoot -Parent
$python = "$root\.venv\Scripts\python.exe"
& $python "$App\manage.py" migrate -v 0
$matrix = @(@{ Clients = 2; Ramp = 6 }, @{ Clients = 20; Ramp = 5 }, @{ Clients = 200; Ramp = 5 }, @{ Clients = 200; Ramp = 0 })
foreach ($case in $matrix) {
    foreach ($i in 1..$Repeat) {
        & $python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('delete from main_room'); c.commit()" "$App\db.sqlite3"
        # The original asgi.py imports models before configuring Django, so only runserver can start it.
        $server = Start-Process -FilePath $python -ArgumentList 'manage.py runserver 127.0.0.1:8030 --noreload' `
            -WorkingDirectory $App -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput "$root\.runtime\legacy.out" -RedirectStandardError "$root\.runtime\legacy.log"
        Start-Sleep 4
        $line = & $python "$PSScriptRoot\matching.py" --mode legacy --base http://127.0.0.1:8030 `
            --clients $case.Clients --ramp $case.Ramp --timeout 20
        Start-Sleep 3  # let the server finish every disconnect handler before counting
        $ghosts = & $python -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('select count(*) from main_room where user_count>0').fetchone()[0])" "$App\db.sqlite3"
        Stop-Process -Id $server.Id -Confirm:$false -ErrorAction SilentlyContinue
        $record = $line | ConvertFrom-Json
        # Rooms still counted as occupied after every client disconnected.
        $record | Add-Member ghost_rooms_after_disconnect ([int]$ghosts)
        $record | Add-Member label 'legacy-c8d7002'
        $record | Add-Member date (Get-Date -Format 'yyyy-MM-dd')
        $json = $record | ConvertTo-Json -Compress -Depth 5
        Add-Content -Path (Join-Path $root $Out) -Value $json -Encoding utf8
        $json
    }
}
