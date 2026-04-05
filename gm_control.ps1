<#
.SYNOPSIS
    GrowMate Control - SSH-Steuerung der Prod-Instanz
.DESCRIPTION
    Ressourcenschonendes One-Shot-CLI-Skript. Kompatibel mit PowerShell 5.1.
#>

param(
    [Parameter(Position=0, Mandatory=$false)]
    [ValidateSet("status", "start", "stop", "restart", "logs", "db-sync", "help")]
    [string]$Command = "status",

    [Parameter(Position=1, Mandatory=$false)]
    [int]$LogLines = 50
)

# --- Konfiguration ---
$ProdDir      = "C:\Users\homes\Documents\growmate"
$DevDir       = "C:\Users\homes\Documents\growmate_dev"
$ProdDB       = "$ProdDir\growmate.db"
$DevDB        = "$DevDir\growmate_dev.db"
$LogFile      = "$ProdDir\local.log"
$TaskName     = "GrowMate_Prod"
$ProdPort     = 5000
$PythonExe    = "pythonw.exe"
$AppScript    = "$ProdDir\app.py"

# --- Hilfsfunktionen ---

function Write-Header {
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor DarkCyan
    Write-Host "  GrowMate Control v1.0  |  Port: $ProdPort" -ForegroundColor Cyan
    Write-Host "==========================================" -ForegroundColor DarkCyan
}

function Get-GrowMateProcess {
    $foundProc = $null
    Get-Process -Name "python*" -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
            if ($cmdline -like "*app.py*" -and $cmdline -like "*growmate*" -and $cmdline -notlike "*growmate_dev*") {
                $foundProc = $_
            }
        } catch { }
    }
    return $foundProc
}

function Get-PortListening {
    param([int]$Port)
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Format-Uptime {
    param([System.Diagnostics.Process]$Proc)
    if ($null -eq $Proc) { return "---" }
    $uptime = (Get-Date) - $Proc.StartTime
    $h = [Math]::Floor($uptime.TotalHours)
    $m = $uptime.Minutes
    return "$($h)h $($m)m"
}

function Invoke-Status {
    Write-Header
    $proc = Get-GrowMateProcess
    $port = Get-PortListening -Port $ProdPort
    if ($proc -and $port) {
        Write-Host "  Status  : RUNNING" -ForegroundColor Green
        Write-Host "  PID     : $($proc.Id)"
        Write-Host "  Uptime  : $(Format-Uptime -Proc $proc)"
    } elseif ($proc) {
        Write-Host "  Status  : STARTING" -ForegroundColor Yellow
        Write-Host "  PID     : $($proc.Id)"
    } else {
        Write-Host "  Status  : STOPPED" -ForegroundColor Red
    }
}

function Get-PortBindingProcessId {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { return $conn.OwningProcess }
    return $null
}

function Invoke-Start {
    Write-Header
    
    # 1. Port-Check: Ist der Port besetzt?
    $bindingPid = Get-PortBindingProcessId -Port $ProdPort
    if ($bindingPid) {
        Write-Host "  ! Port $ProdPort belegt von PID $bindingPid. Pruefe Prozess..." -ForegroundColor Yellow
        $bindingProc = Get-Process -Id $bindingPid -ErrorAction SilentlyContinue
        if ($bindingProc.ProcessName -like "*python*") {
            Write-Host "  -> Beende alten Prozess (PID $bindingPid)..." -ForegroundColor Cyan
            Stop-Process -Id $bindingPid -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        } else {
            Write-Host "  X Port $ProdPort belegt von fremdem Prozess ($($bindingProc.ProcessName))!" -ForegroundColor Red
            return
        }
    }

    # 2. Prozess-Check: Läuft die App bereits laut CmdLine?
    if (Get-GrowMateProcess) {
        Write-Host "  ALREADY RUNNING." -ForegroundColor Yellow
        return
    }

    # 3. Start
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "  Starting Task $TaskName..." -ForegroundColor Cyan
        Start-ScheduledTask -TaskName $TaskName
    } else {
        Write-Host "  Starting via pythonw.exe..." -ForegroundColor Cyan
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "start", "/min", $PythonExe, "`"$AppScript`"" -WorkingDirectory $ProdDir -WindowStyle Hidden
    }
    Start-Sleep -Seconds 2
}

function Invoke-Stop {
    Write-Header
    $proc = Get-GrowMateProcess
    if ($proc) {
        Write-Host "  Stopping PID $($proc.Id)..." -ForegroundColor Cyan
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "  NOT RUNNING." -ForegroundColor DarkGray
    }
}

function Invoke-Restart {
    Invoke-Stop
    Start-Sleep -Seconds 2
    Invoke-Start
}

function Invoke-Logs {
    param([int]$N = 50)
    Write-Header
    if (Test-Path $LogFile) {
        Get-Content -Tail $N -Path $LogFile -Encoding UTF8
    } else {
        Write-Host "  Log file not found." -ForegroundColor Red
    }
}

function Invoke-DbSync {
    Write-Header
    Write-Host "  DB-Sync: Prod to Dev" -ForegroundColor Cyan
    if (Test-Path $ProdDB) {
        $sqlite3 = Get-Command "sqlite3.exe" -ErrorAction SilentlyContinue
        if ($sqlite3) { & $sqlite3.Source $ProdDB "PRAGMA wal_checkpoint(FULL);" }
        Copy-Item -Path $ProdDB -Destination $DevDB -Force
        if (Test-Path "$ProdDB-wal") { Copy-Item -Path "$ProdDB-wal" -Destination "$DevDB-wal" -Force }
        if (Test-Path "$ProdDB-shm") { Copy-Item -Path "$ProdDB-shm" -Destination "$DevDB-shm" -Force }
        Write-Host "  Sync completed." -ForegroundColor Green
    }
}

function Invoke-Help {
    Write-Header
    Write-Host "  Commands: status, start, stop, restart, logs, db-sync" -ForegroundColor Cyan
}

switch ($Command) {
    "status"   { Invoke-Status }
    "start"    { Invoke-Start }
    "stop"     { Invoke-Stop }
    "restart"  { Invoke-Restart }
    "logs"     { Invoke-Logs -N $LogLines }
    "db-sync"  { Invoke-DbSync }
    default    { Invoke-Help }
}
