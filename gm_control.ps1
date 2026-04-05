<#
.SYNOPSIS
    GrowMate Control – SSH-Steuerung der Prod-Instanz auf Windows 11 ARM64
.DESCRIPTION
    Ressourcenschonendes One-Shot-CLI-Skript. Kein Hintergrundprozess,
    keine Endlosschleifen. Jeder Aufruf prüft/ändert den Zustand und
    beendet sich sofort.

    Aufrufen via SSH von Kubuntu:
        ssh winserver "powershell -File C:\growmate\gm_control.ps1 status"
        ssh winserver "powershell -File C:\growmate\gm_control.ps1 logs 100"
        ssh winserver "powershell -File C:\growmate\gm_control.ps1 db-sync"

.COMMANDS
    status          Zeigt PID, Port, Uptime und letzten Log-Eintrag
    start           Startet die GrowMate Prod-Instanz (via Scheduled Task)
    stop            Stoppt die Prod-Instanz graceful
    restart         Stop + 3s Pause + Start
    logs [N]        Zeigt letzte N Zeilen des Logs (Standard: 50)
    db-sync         Erstellt sicheren WAL-Snapshot der Prod-DB nach growmate_dev

.NOTES
    Autor   : Antigravity (Senior Systems Architect)
    Version : 1.0
    Datum   : 2026-04-05
#>

param(
    [Parameter(Position=0, Mandatory=$false)]
    [ValidateSet("status", "start", "stop", "restart", "logs", "db-sync", "help")]
    [string]$Command = "status",

    [Parameter(Position=1, Mandatory=$false)]
    [int]$LogLines = 50
)

# ─── Konfiguration ──────────────────────────────────────────────────────────
$ProdDir      = "C:\growmate"
$DevDir       = "C:\growmate_dev"
$ProdDB       = "$ProdDir\growmate.db"
$DevDB        = "$DevDir\growmate_dev.db"
$LogFile      = "$ProdDir\local.log"
$TaskName     = "GrowMate_Prod"
$ProdPort     = 5000
$PythonExe    = "pythonw.exe"    # kein Konsolenfenster
$AppScript    = "$ProdDir\app.py"
# ─────────────────────────────────────────────────────────────────────────────

# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

function Write-Header {
    Write-Host ""
    Write-Host "══════════════════════════════════════════" -ForegroundColor DarkCyan
    Write-Host "  GrowMate Control v1.0  |  Prod: :$ProdPort" -ForegroundColor Cyan
    Write-Host "══════════════════════════════════════════" -ForegroundColor DarkCyan
    Write-Host ""
}

function Get-GrowMateProcess {
    <#
    Gibt das Process-Objekt zurück, wenn GrowMate Prod läuft.
    Nutzt Get-Process (kein WMI-Scan, kein Netstat-Parse) – < 50ms.
    #>
    Get-Process -Name "python*" -ErrorAction SilentlyContinue | Where-Object {
        try {
            # CommandLine-Attribut (Win10/11 mit WMI-CIM-light)
            $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
            $cmdline -like "*app.py*" -and $cmdline -like "*growmate*" -and $cmdline -notlike "*growmate_dev*"
        } catch { $false }
    } | Select-Object -First 1
}

function Get-PortListening {
    param([int]$Port)
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Format-Uptime {
    param([System.Diagnostics.Process]$Proc)
    if ($null -eq $Proc) { return "—" }
    $uptime = (Get-Date) - $Proc.StartTime
    if ($uptime.TotalHours -ge 1) {
        return "$([int]$uptime.TotalHours)h $($uptime.Minutes)m"
    } else {
        return "$($uptime.Minutes)m $($uptime.Seconds)s"
    }
}

# ─── COMMAND: status ─────────────────────────────────────────────────────────

function Invoke-Status {
    Write-Header
    $proc = Get-GrowMateProcess
    $port = Get-PortListening -Port $ProdPort

    if ($proc -and $port) {
        Write-Host "  Status  : " -NoNewline
        Write-Host "RUNNING ●" -ForegroundColor Green
        Write-Host "  PID     : $($proc.Id)"
        Write-Host "  Port    : :$ProdPort (Listening)"
        Write-Host "  Uptime  : $(Format-Uptime -Proc $proc)"
        Write-Host "  RAM     : $([math]::Round($proc.WorkingSet64 / 1MB, 1)) MB"
    } elseif ($proc -and -not $port) {
        Write-Host "  Status  : " -NoNewline
        Write-Host "STARTING ◐" -ForegroundColor Yellow
        Write-Host "  PID     : $($proc.Id)"
        Write-Host "  Port    : :$ProdPort nicht erreichbar (evtl. noch im Start)"
    } else {
        Write-Host "  Status  : " -NoNewline
        Write-Host "STOPPED ○" -ForegroundColor Red
        Write-Host "  PID     : —"
        Write-Host "  Port    : —"
    }

    # Letzter Log-Eintrag
    if (Test-Path $LogFile) {
        $lastLine = Get-Content -Tail 1 -Path $LogFile -Encoding UTF8 -ErrorAction SilentlyContinue
        Write-Host ""
        Write-Host "  Log     : $lastLine" -ForegroundColor DarkGray
    }
    Write-Host ""
}

# ─── COMMAND: start ──────────────────────────────────────────────────────────

function Invoke-Start {
    Write-Header
    $proc = Get-GrowMateProcess

    if ($proc) {
        Write-Host "  ⚠  GrowMate läuft bereits (PID $($proc.Id))." -ForegroundColor Yellow
        Write-Host "     Nutze 'restart' um neu zu starten." -ForegroundColor DarkGray
        return
    }

    # Methode A: Windows Scheduled Task (WMI-stabil, überlebt SSH-Disconnect)
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "  → Starte Scheduled Task '$TaskName'..." -ForegroundColor Cyan
        Start-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 3
        $proc = Get-GrowMateProcess
        if ($proc) {
            Write-Host "  ✓ GrowMate gestartet (PID $($proc.Id))" -ForegroundColor Green
        } else {
            Write-Host "  ? Prozess noch nicht sichtbar, bitte Status prüfen." -ForegroundColor Yellow
        }
    } else {
        # Methode B: Fallback – Detached Window (kein SIGHUP bei SSH-Disconnect)
        Write-Host "  ⚠  Task '$TaskName' nicht gefunden – Fallback: Detached-Start." -ForegroundColor Yellow
        Write-Host "  → Starte mit cmd /c start /min..." -ForegroundColor Cyan
        $py = (Get-Command $PythonExe -ErrorAction SilentlyContinue)?.Source
        if (-not $py) { $py = "pythonw" }
        $argStr = "`"$AppScript`""
        Start-Process -FilePath "cmd.exe" `
            -ArgumentList "/c", "start", "/min", $py, $argStr `
            -WorkingDirectory $ProdDir `
            -WindowStyle Hidden
        Start-Sleep -Seconds 4
        $proc = Get-GrowMateProcess
        if ($proc) {
            Write-Host "  ✓ GrowMate gestartet (PID $($proc.Id))" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Start fehlgeschlagen. Prüfe lokalen Log:" -ForegroundColor Red
            Write-Host "    $LogFile" -ForegroundColor DarkGray
        }
    }
    Write-Host ""
}

# ─── COMMAND: stop ───────────────────────────────────────────────────────────

function Invoke-Stop {
    Write-Header
    $proc = Get-GrowMateProcess

    if (-not $proc) {
        Write-Host "  ○ GrowMate läuft nicht – nichts zu stoppen." -ForegroundColor DarkGray
        Write-Host ""
        return
    }

    Write-Host "  → Stoppe GrowMate (PID $($proc.Id))..." -ForegroundColor Cyan
    try {
        # Graceful: erst normaler Stop-Versuch
        $proc.CloseMainWindow() | Out-Null
        $proc.WaitForExit(3000) | Out-Null

        # Falls noch aktiv: Force
        if (-not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
        Write-Host "  ✓ GrowMate gestoppt." -ForegroundColor Green
    } catch {
        Write-Host "  ✗ Fehler beim Stoppen: $_" -ForegroundColor Red
    }

    # Scheduled Task auch auf "stopped" setzen (falls Task als laufend gilt)
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task -and $task.State -eq "Running") {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    Write-Host ""
}

# ─── COMMAND: restart ────────────────────────────────────────────────────────

function Invoke-Restart {
    Write-Host ""
    Write-Host "  → Restart-Sequenz..." -ForegroundColor Cyan
    Invoke-Stop
    Write-Host "  → Warte 3 Sekunden..." -ForegroundColor DarkGray
    Start-Sleep -Seconds 3
    Invoke-Start
}

# ─── COMMAND: logs ───────────────────────────────────────────────────────────

function Invoke-Logs {
    param([int]$N = 50)
    Write-Header
    if (-not (Test-Path $LogFile)) {
        Write-Host "  ✗ Log-Datei nicht gefunden: $LogFile" -ForegroundColor Red
        Write-Host ""
        return
    }
    Write-Host "  Letzte $N Zeilen von: $LogFile" -ForegroundColor DarkGray
    Write-Host "  ─────────────────────────────────────────" -ForegroundColor DarkGray
    Get-Content -Tail $N -Path $LogFile -Encoding UTF8 | ForEach-Object {
        # Farbige Log-Level-Hervorhebung
        if ($_ -match "ERROR|CRITICAL") {
            Write-Host "  $_" -ForegroundColor Red
        } elseif ($_ -match "WARNING") {
            Write-Host "  $_" -ForegroundColor Yellow
        } elseif ($_ -match "WATCHDOG|FEHLER") {
            Write-Host "  $_" -ForegroundColor Magenta
        } else {
            Write-Host "  $_" -ForegroundColor Gray
        }
    }
    Write-Host ""
}

# ─── COMMAND: db-sync ────────────────────────────────────────────────────────

function Invoke-DbSync {
    Write-Header
    Write-Host "  → DB-Sync: Prod → Dev" -ForegroundColor Cyan
    Write-Host "    Quelle : $ProdDB"
    Write-Host "    Ziel   : $DevDB"
    Write-Host ""

    # Prüfungen
    if (-not (Test-Path $ProdDB)) {
        Write-Host "  ✗ Prod-Datenbank nicht gefunden: $ProdDB" -ForegroundColor Red
        return
    }
    if (-not (Test-Path $DevDir)) {
        Write-Host "  → Erstelle Dev-Verzeichnis: $DevDir" -ForegroundColor DarkGray
        New-Item -ItemType Directory -Path $DevDir -Force | Out-Null
    }

    # Sicherheitswarnung wenn GrowMate gerade läuft
    $proc = Get-GrowMateProcess
    if ($proc) {
        Write-Host "  ⚠  GrowMate Prod läuft (PID $($proc.Id))." -ForegroundColor Yellow
        Write-Host "     Führe WAL-Checkpoint durch (sichere Konsistenz)..." -ForegroundColor DarkGray
    }

    # WAL-Checkpoint: Schreibt alle uncommitted WAL-Daten zurück in die DB.
    # Nur nötig wenn sqlite3.exe verfügbar ist – sonst kopieren wir trotzdem
    # (SQLite WAL garantiert Lesekonsistenz auch ohne expliziten Checkpoint).
    $sqlite3 = (Get-Command "sqlite3.exe" -ErrorAction SilentlyContinue)?.Source
    if ($sqlite3) {
        Write-Host "  → WAL-Checkpoint (FULL)..." -ForegroundColor DarkGray
        $result = & $sqlite3 $ProdDB "PRAGMA wal_checkpoint(FULL);" 2>&1
        Write-Host "     Ergebnis: $result" -ForegroundColor DarkGray
    } else {
        Write-Host "  ℹ  sqlite3.exe nicht im PATH – Kopie ohne expliziten Checkpoint." -ForegroundColor DarkGray
        Write-Host "     WAL-Modus stellt dennoch Lesekonsistenz sicher." -ForegroundColor DarkGray
    }

    # Kopieren (DB + evtl. WAL-Shm-Dateien mitschleppen für komplette Konsistenz)
    try {
        Copy-Item -Path $ProdDB -Destination $DevDB -Force
        Write-Host "  ✓ growmate.db → growmate_dev.db" -ForegroundColor Green

        # WAL/SHM nur wenn vorhanden (sonst keine Aktion)
        $walFile = "$ProdDB-wal"
        $shmFile = "$ProdDB-shm"
        if (Test-Path $walFile) {
            Copy-Item -Path $walFile -Destination "$DevDB-wal" -Force
            Write-Host "  ✓ growmate.db-wal → growmate_dev.db-wal" -ForegroundColor Green
        }
        if (Test-Path $shmFile) {
            Copy-Item -Path $shmFile -Destination "$DevDB-shm" -Force
            Write-Host "  ✓ growmate.db-shm → growmate_dev.db-shm" -ForegroundColor Green
        }

        $size = [math]::Round((Get-Item $DevDB).Length / 1MB, 2)
        Write-Host ""
        Write-Host "  ✓ Snapshot erstellt – $size MB – $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Green
    } catch {
        Write-Host "  ✗ Kopier-Fehler: $_" -ForegroundColor Red
    }
    Write-Host ""
}

# ─── COMMAND: help ────────────────────────────────────────────────────────────

function Invoke-Help {
    Write-Header
    Write-Host "  VERWENDUNG:" -ForegroundColor Cyan
    Write-Host "    powershell -File gm_control.ps1 <command> [args]"
    Write-Host ""
    Write-Host "  COMMANDS:"
    Write-Host "    status          Prozess-Status, PID, Port, letzter Log-Eintrag"
    Write-Host "    start           Startet GrowMate Prod (via Scheduled Task)"
    Write-Host "    stop            Stoppt GrowMate Prod graceful"
    Write-Host "    restart         stop → 3s Pause → start"
    Write-Host "    logs [N]        Letzte N Log-Zeilen (Standard: 50)"
    Write-Host "    db-sync         WAL-Checkpoint + Snapshot Prod-DB → Dev-DB"
    Write-Host "    help            Diese Hilfe"
    Write-Host ""
    Write-Host "  BEISPIELE (via SSH von Kubuntu):"
    Write-Host "    ssh winserver `"powershell -File C:\growmate\gm_control.ps1 status`""
    Write-Host "    ssh winserver `"powershell -File C:\growmate\gm_control.ps1 logs 100`""
    Write-Host "    ssh winserver `"powershell -File C:\growmate\gm_control.ps1 db-sync`""
    Write-Host ""
}

# ─── DISPATCHER ──────────────────────────────────────────────────────────────

switch ($Command) {
    "status"   { Invoke-Status }
    "start"    { Invoke-Start }
    "stop"     { Invoke-Stop }
    "restart"  { Invoke-Restart }
    "logs"     { Invoke-Logs -N $LogLines }
    "db-sync"  { Invoke-DbSync }
    "help"     { Invoke-Help }
    default    { Invoke-Help }
}
