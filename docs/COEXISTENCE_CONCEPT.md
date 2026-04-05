# GrowMate – Coexistence & Remote-Control Concept

> **Status:** Entwurf – wartet auf explizite Freigabe vor Implementierung  
> **Erstellt:** 2026-04-05  
> **Scope:** Windows 11 ARM64 Server (Prod/Dev-Isolation) + SSH-Steuerung via Kubuntu  

---

## Inhaltsverzeichnis

1. [Ressourcenarme SSH-Steuerung (`gm_control.ps1`)](#1-ressourcenarme-ssh-steuerung)
2. [Isolations-Konzept Prod vs. Dev](#2-isolations-konzept-prod-vs-dev)
   - 2.1 [Netzwerk – Port-Isolierung](#21-netzwerk--port-isolierung)
   - 2.2 [Datenbank – SQLite-Koexistenz](#22-datenbank--sqlite-koexistenz)
   - 2.3 [Hardware-Exklusivität – Tapo & Govee BLE](#23-hardware-exklusivit%C3%A4t--tapo--govee-ble)
3. [Umgebungs-Variablen-Strategie (`.env`)](#3-umgebungs-variablen-strategie)
4. [Deployment-Übersicht](#4-deployment-%C3%BCbersicht)
5. [Freigabe-Checkliste](#5-freigabe-checkliste)

---

## 1. Ressourcenarme SSH-Steuerung

### 1.1 Konzept-Überblick

Das Skript `gm_control.ps1` liegt im Prod-Verzeichnis auf dem Windows-Server und wird **ausschließlich on-demand** aufgerufen – kein dauerhafter Hintergrundprozess, kein Polling.

Die bestehende **WMI-basierte Startlogik** (Scheduled Task / WMI-Event-Consumer) bleibt unangetastet und sorgt weiterhin für SSH-Disconnect-Stabilität. `gm_control.ps1` ist ein reines **Inspect & Command Tool** – kein Ersatz für den Startmechanismus.

```
Kubuntu-Terminal
    │  SSH-Verbindung
    ▼
Windows 11 ARM64
    └── gm_control.ps1 <command>
            │
            ├── status  → prozess-Query (Get-Process, net.exe TCP-stati)
            ├── start   → WMI-Startmethode oder Task Trigger (1× call)
            ├── stop    → Stop-Process (graceful SIGTERM-äquivalent)
            └── logs    → Get-Content -Tail (letzte N Zeilen)
```

### 1.2 Skript-Architektur `gm_control.ps1`

#### Befehlsübersicht

| Kommando | Beschreibung | Methode |
|---|---|---|
| `status` | Zeigt PID, Port, Uptime, letzten Log-Eintrag | `Get-Process`, `netstat`/`Get-NetTCPConnection` |
| `start` | Startet die Prod-Instanz (WMI / Schtask) | `Start-ScheduledTask` oder `pythonw.exe` detach |
| `stop` | Stoppt die Prod-Instanz graceful | `Stop-Process -Id $pid -Force` nach SIGTERM-Versuch |
| `restart` | Stop + kurzes Sleep + Start | Sequenz aus stop/start |
| `logs [N]` | Zeigt letzte N Zeilen des Logs | `Get-Content -Tail $N -Path $LogPath` |

#### Keine Dauer-Schleife

Das Skript verwendet **kein `while($true)` oder Event-Loop**. Jeder Aufruf ist ein **One-Shot**: er prüft/ändert den Zustand und beendet sich. Dies kostet unter 100ms CPU pro Aufruf.

#### Status-Abfrage ohne WMI-Overhead

```powershell
# Effiziente Prozess-Prüfung (kein Full-WMI-Scan)
$proc = Get-Process -Name "python*" | Where-Object {
    $_.MainWindowTitle -eq "" -and $_.CommandLine -like "*growmate*app.py*"
} 2>$null

# PORT-Check – direkt aus TCP-Tabelle (kein netstat-Parse)
$port = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
```

#### Start-Methode (WMI-stabil / SSH-disconnect-sicher)

```powershell
# Methode A: Scheduled Task (bevorzugt – WMI-registriert, überlebt SSH-Disconnect)
Start-ScheduledTask -TaskName "GrowMate_Prod"

# Methode B: Fallback via cmd /c start (neues konsolenloses Fenster, kein SIGHUP)
cmd /c "start /min pythonw.exe C:\growmate\app.py"
```

> **Wichtig:** Die eigentliche WMI-Task-Registrierung (einmalig) muss beim initialen Setup erfolgen. `gm_control.ps1` *ruft* den Task nur auf.

#### Log-Tail (ressourcenschonend)

```powershell
# Nur letzte 50 Zeilen – keine vollständige Datei in Memory laden
Get-Content -Tail 50 -Path "C:\growmate\local.log" -Encoding UTF8
```

### 1.3 SSH-Aufruf von Kubuntu

```bash
# Alias in ~/.bashrc auf dem Kubuntu-Rechner
alias gm='ssh winserver "powershell -File C:/growmate/gm_control.ps1"'

# Beispiele
gm status
gm start
gm stop
gm "logs 100"
```

Der SSH-Aufruf ist verbindungslos (kein persistenter SSH-Multiplex notwendig, aber empfohlen via `ControlMaster=auto` für Latenzvermeidung).

---

## 2. Isolations-Konzept Prod vs. Dev

### Architektur-Übersicht

```
Windows 11 ARM64
├── C:\growmate\           ← PROD (Port 5000, growmate.db WAL)
│   ├── app.py
│   ├── config.json        (TAPO_EMAIL/PW via .env.prod)
│   ├── growmate.db        ← Master-Datenbank (WAL-Modus aktiv)
│   └── .env               ← Prod-Credentials
│
└── C:\growmate_dev\       ← DEV (Port 5001, Sandbox-DB)
    ├── app.py
    ├── config.json        (eigene Geräteliste, MOCK-Mode)
    ├── growmate_dev.db    ← Sandbox-Kopie (periodisch aktualisiert)
    └── .env               ← Dev-Credentials (andere oder leer)
```

---

### 2.1 Netzwerk – Port-Isolierung

#### Problem

Flask lauscht standardmäßig auf Port 5000. Laufen beide Instanzen parallel, crasht die zweite mit `Address already in use`.

#### Lösung: Expliziter Port in `config.json`

**Prod** (`C:\growmate\config.json`):
```json
{
  "server_port": 5000,
  "server_host": "0.0.0.0"
}
```

**Dev** (`C:\growmate_dev\config.json`):
```json
{
  "server_port": 5001,
  "server_host": "127.0.0.1"
}
```

> **Dev lauscht nur auf Loopback (`127.0.0.1`)!** Damit ist die Dev-Instanz von außen (LAN) komplett unsichtbar. Zugriff nur via SSH-Tunnel oder lokal am Server. Dies verhindert unbeabsichtigte Netzwerkzugriffe auf Dev-APIs.

Der Startup-Code in `app.py` liest den Port bereits aus `DEFAULT_CONFIG` mit `server_port: 5000`. Die Dev-Instanz überschreibt diesen Wert via `config.json` – **kein Code muss geändert werden.**

#### App-Start-Befehle

```powershell
# Prod
cd C:\growmate
python app.py          # liest config.json → Port 5000

# Dev (explizit Loopback + Port 5001)
cd C:\growmate_dev
python app.py          # liest config.json → Port 5001, Host 127.0.0.1
```

---

### 2.2 Datenbank – SQLite-Koexistenz

#### Risiko

SQLite im WAL-Modus erlaubt multiple **Leser**, aber nur **einen aktiven Writer**. Zwei schreibende Prozesse auf derselben `.db`-Datei führen zu:
- `SQLITE_LOCKED` / `database is locked` Fehlern
- Datenkorruption im Extremfall (erzwungener Kill während Write-Transaction)

#### Strategie: Strikte Trennung in drei Modi

```
┌─────────────────────────────────────────────────────────────────┐
│  MODUS A: Vollständige DB-Trennung (Standard & empfohlen)       │
│                                                                  │
│  Prod   → C:\growmate\growmate.db        (Master, WAL-Modus)   │
│  Dev    → C:\growmate_dev\growmate_dev.db (Sandbox-Kopie)       │
│                                                                  │
│  Dev schreibt NIEMALS in die Prod-DB.                           │
│  Dev-DB ist eine periodisch aktualisierte Kopie (Snapshot).     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  MODUS B: Read-Only-Attach (für Sensor-Inspektion)              │
│                                                                  │
│  Öffne Prod-DB als ATTACH DATABASE ... AS prod READ ONLY        │
│  Nur für analytische Queries (Charts, Advisor-Dev).             │
│  Kein WAL-Lock-Risiko bei reinem Read-Only-Attach.             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  MODUS C: Pure Mock-Mode (empfohlen für Feature-Dev)            │
│                                                                  │
│  GROW_DEMO_MODE=true → mock_data_system.py liefert alle Daten  │
│  Keine DB-Zugriffe auf Prod überhaupt.                         │
│  Dev arbeitet komplett isoliert und stört nichts.               │
└─────────────────────────────────────────────────────────────────┘
```

#### Empfohlene Implementierung für Modus A: DB-Snapshot-Skript

Ein einmaliges PowerShell-Skript (nicht automatisch, sondern **on-demand** via `gm_control.ps1 db-sync`):

```powershell
# db_sync_to_dev.ps1 – kopiert Prod-DB nach Dev (on-demand, nicht automatisch)
$ProdDB  = "C:\growmate\growmate.db"
$DevDB   = "C:\growmate_dev\growmate_dev.db"
$WalFile = "$ProdDB-wal"
$ShmFile = "$ProdDB-shm"

# Warte auf WAL-Checkpoint (SQLite schreibt WAL zurück in Hauptdatei)
sqlite3.exe $ProdDB "PRAGMA wal_checkpoint(FULL);"

# Kopiere nur die .db Datei (WAL wurde gecheckpointed)
Copy-Item $ProdDB $DevDB -Force
Write-Host "DB-Snapshot erstellt: $DevDB"
```

**Warum nicht automatisch?** Ein automatischer Cron-Copy könnte mitten in eine Prod-Write-Transaction treffen und eine korrupte Kopie erstellen. On-demand ist sicherer.

#### Dev-Config: DB-Pfad explizit überschreiben

In `config.py` ist `DB_PATH` aktuell hardcoded auf `BASE_DIR/growmate.db`. Für Dev wird die Umgebungsvariable `GROWMATE_DB` eingeführt (keine Code-Änderung am Prod-Code erforderlich):

**Konzept-Erweiterung in `config.py` (nur Dev-Instanz):**
```python
# In config.py – liest DB-Pfad aus Env-Variable (falls gesetzt)
DB_PATH = os.environ.get("GROWMATE_DB", os.path.join(BASE_DIR, "growmate.db"))
```

**Dev `.env`:**
```
GROWMATE_DB=C:/growmate_dev/growmate_dev.db
```

Damit zeigt die Dev-Instanz automatisch auf ihre eigene Sandbox-DB.

---

### 2.3 Hardware-Exklusivität – Tapo & Govee BLE

#### Problem

Zwei Instanzen, die gleichzeitig:
- **Tapo-Geräte** via TCP (Port 80) pollen → Rate-Limit der TP-Link Firmware (ca. 1 Req/Sek pro Gerät). Zwei simultane Polls = 50% Timeout-Risiko.
- **Govee BLE** scannen → Bluetooth-Adapter ist **physisch exklusiv**. Zwei `BleakScanner.discover()` parallel = Chaos/Absturz des BT-Stacks.

#### Strategie: Hardware-Ownership durch Prod – Dev liest passiv

```
┌────────────────────────────────────────────────────────────────┐
│  REGEL: NUR PROD berührt echte Hardware                        │
│                                                                 │
│  Prod-Scheduler:                                               │
│    → BLE-Scan (Govee) alle 5 Min → schreibt in growmate.db    │
│    → Tapo-Poll alle 5 Min        → schreibt in growmate.db    │
│                                                                 │
│  Dev-Instanz:                                                  │
│    → GROW_DEMO_MODE=true  → mock_data_system (bevorzugt)      │
│    → ODER: liest nur aus growmate_dev.db (Snapshot)            │
│    → NIEMALS eigene BLE-Scans                                  │
│    → NIEMALS eigene Tapo-Polls                                 │
└────────────────────────────────────────────────────────────────┘
```

#### Technische Umsetzung: Dev-Instanz Hardware-Lock

**Methode 1: Demo-Mode (einfachste Lösung)**

```
# Dev .env
GROW_DEMO_MODE=true
```

`mock_data_system.py` existiert bereits im Projekt und liefert realistische Sensor-Werte inkl. Temperatur, Humidity, VPD. Der Scheduler pollt nur Mock-Daten, berührt keine echte Hardware.

**Methode 2: Hardware-Lock-Flag (für semi-live Dev-Betrieb)**

Neues Flag `GROWMATE_HARDWARE_READONLY=true` in der Dev `.env`:

```python
# Konzept-Erweiterung in scheduler.py (nur wenn Flag gesetzt)
HARDWARE_READONLY = os.environ.get("GROWMATE_HARDWARE_READONLY", "false").lower() == "true"

def poll_all_sensors():
    if HARDWARE_READONLY:
        logger.info("HARDWARE_READONLY: Polling aus DB-Snapshot statt Hardware.")
        # Lese nur aus lokaler Dev-DB, kein BLE/Tapo-Call
        return
    # ... bestehender Code ...
```

Mit diesem Flag kann Dev-Code im vollen Flask-Kontext getestet werden (echte DB-Queries, echter Analyzer), aber ohne Hardware-Touch.

**Methode 3: Bluetooth-Mutex (für spezielle Tests)**

Falls ein Dev-Entwickler ausnahmsweise einen echten BLE-Scan braucht und Prod gerade nicht läuft:

```powershell
# Mutex via Named Pipe / Lockfile
$LockFile = "$env:TEMP\growmate_ble.lock"
if (Test-Path $LockFile) {
    $owner = Get-Content $LockFile
    Write-Error "BLE-Adapter gesperrt von: $owner"
    exit 1
}
"growmate_dev:$PID" | Set-Content $LockFile
# ... BLE-Scan ...
Remove-Item $LockFile
```

Dies ist ein **Fallback**, nicht der Standard. Standard ist Methode 1 (Demo-Mode).

---

## 3. Umgebungs-Variablen-Strategie

Beide Instanzen nutzen separate `.env`-Dateien in ihrem jeweiligen Verzeichnis. Die dotenv-Bibliothek lädt immer `BASE_DIR/.env` (relativ zur `app.py`), also sind sie automatisch getrennt.

| Variable | Prod (`.env`) | Dev (`.env`) |
|---|---|---|
| `TAPO_EMAIL` | `user@example.com` | leer oder Test-Account |
| `TAPO_PASSWORD` | `prod_password` | leer oder Test-Passwort |
| `GROW_DEMO_MODE` | `false` | `true` (empfohlen) |
| `GROWMATE_DB` | nicht gesetzt (Default) | `C:/growmate_dev/growmate_dev.db` |
| `GROWMATE_HARDWARE_READONLY` | nicht gesetzt | `true` (wenn nicht Demo-Mode) |
| `FLASK_ENV` | `production` | `development` |
| `FLASK_DEBUG` | `0` | `1` |

---

## 4. Deployment-Übersicht

```
Windows 11 ARM64 Server
│
├── WMI Scheduled Task "GrowMate_Prod"
│       └── Startet: pythonw.exe C:\growmate\app.py
│               Port: 5000 (LAN-accessible)
│               BLE:  AKTIV
│               Tapo: AKTIV
│               DB:   C:\growmate\growmate.db (Master, WAL)
│
├── WMI Scheduled Task "GrowMate_Dev" (optional, on-demand)
│       └── Startet: python.exe C:\growmate_dev\app.py
│               Port: 5001 (nur 127.0.0.1)
│               BLE:  DEAKTIVIERT (GROW_DEMO_MODE=true)
│               Tapo: DEAKTIVIERT (GROW_DEMO_MODE=true)
│               DB:   C:\growmate_dev\growmate_dev.db (Sandbox)
│
└── gm_control.ps1 (SSH-Steuerung)
        Commands: status | start | stop | restart | logs [N]
        Keine Dauerschleife, kein Hintergrundprozess
        Aufruf: ssh winserver "powershell -File C:/growmate/gm_control.ps1 status"
```

### Ressourcen-Fußabdruck (Schätzung)

| Instanz | RAM | CPU (Idle) | CPU (Poll) |
|---|---|---|---|
| Prod (Flask + Scheduler) | ~80–120 MB | < 1% | 5–15% für 2–3s |
| Dev (Flask + Mock) | ~60–80 MB | < 0.5% | < 1% |
| `gm_control.ps1` (One-Shot) | ~20 MB | ~3% für < 200ms | — |

---

## 5. Freigabe-Checkliste

> **Nichts hiervon wird implementiert bis zur expliziten Benutzer-Freigabe.**

- [ ] **Freigabe:** Konzept grundsätzlich genehmigt
- [ ] **Freigabe:** `gm_control.ps1` auf dem Server anlegen und Scheduled Task registrieren
- [ ] **Freigabe:** Dev-Instanz mit separaten Ports und `.env` konfigurieren
- [ ] **Freigabe:** DB-Snapshot-Skript `db_sync_to_dev.ps1` anlegen
- [ ] **Freigabe:** `config.py` um `GROWMATE_DB`-Env-Variable erweitern
- [ ] **Freigabe:** `scheduler.py` um `GROWMATE_HARDWARE_READONLY`-Flag erweitern
- [ ] **Freigabe:** SSH-Alias auf Kubuntu einrichten

---

*Dokument erstellt von Antigravity – Senior Systems Architect Mode*  
*Letztes Update: 2026-04-05 | Version: 1.0-DRAFT*
