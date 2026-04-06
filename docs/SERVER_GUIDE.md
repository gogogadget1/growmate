# GrowMate Server Management Guide

This guide provides everything you need to manage the GrowMate production and development environments on your Windows 11 ARM64 Server.

---

## 🚀 Connectivity

The server is hosted at **192.168.178.97** and is accessible via SSH.

---

## ⚡️ Quick Start: How to start the Server

To start the GrowMate production environment, follow these three steps:

1. **Login via SSH:**
   ```bash
   ssh homes@192.168.178.97
   ```
2. **Navigate & Execute Control Script:**
   ```powershell
   cd C:\Users\homes\Documents\growmate
   .\gm_control.ps1 start
   ```
3. **Verify:**
   ```powershell
   .\gm_control.ps1 status
   ```

> [!TIP]
> The server is configured to start **automatically on boot** via a Windows Scheduled Task. Use the `start` command only if the service was manually stopped or failed to initialize.

---

## 🛠 Central Control: `gm_control.ps1`

The `gm_control.ps1` script is the central management tool for both environments. It handles process management, port-checking, and database synchronization.

### Location
- **Prod:** `C:\Users\homes\Documents\growmate\gm_control.ps1`
- **Dev:** `C:\Users\homes\Documents\growmate_dev\gm_control.ps1`

### Available Commands

| Command | Usage | Description |
| :--- | :--- | :--- |
| **Status** | `.\gm_control.ps1 status` | Shows if the PID file exists and identifies the running process. |
| **Start** | `.\gm_control.ps1 start` | Performs a "Pre-Flight" port check and starts the Scheduled Task. |
| **Stop** | `.\gm_control.ps1 stop` | Stops the Scheduled Task and kills all associated Python processes. |
| **Restart** | `.\gm_control.ps1 restart` | Short for Stop + Start. |
| **Logs** | `.\gm_control.ps1 logs 50` | Displays the last N lines of the `local.log` file. |
| **DB-Sync** | `.\gm_control.ps1 db-sync` | Performs a WAL checkpoint and copies the Prod DB to the Dev DB. |

---

## 📂 Environment Isolation

| Aspect | Produktion (Prod) | Entwicklung (Dev) |
| :--- | :--- | :--- |
| **Path** | `C:\...\Documents\growmate` | `C:\...\Documents\growmate_dev` |
| **Port** | 5000 | 5001 |
| **Hardware** | Vollzugriff (Polls Hub/Sensors) | **READONLY** (No hardware access) |
| **Autostart** | Scheduled Task: `GrowMate_Prod` | Manual Start only |

---

## 🔍 Troubleshooting & QA

### Port Blocking
If the service fails to start because a port is blocked, `gm_control.ps1 start` will automatically try to find and terminate the blocking process.

### Log Analysis
The production instance logs all output to `C:\Users\homes\Documents\growmate\local.log`. 
To see live polling data:
```powershell
powershell -Command "Get-Content C:\Users\homes\Documents\growmate\local.log -Wait"
```

### Database Health
The system uses SQLite in WAL (Write-Ahead Logging) mode. Before manually copying the database, always use `db-sync` to ensure all data is flushed from the `-wal` file into the main `.db` file.

---

## 📦 Manual Data Migration (Local to Server)

If you need to restore your local `growmate.db` (diary data) to the Production server, follow this **Safe Protocol** to avoid file-lock errors:

1. **Stop Production**: 
   ```powershell
   cd C:\Users\homes\Documents\growmate
   .\gm_control.ps1 stop
   ```
2. **Verify Stop**: 
   ```powershell
   .\gm_control.ps1 status
   ```
   *Ensure it says "No process found".*
3. **Execute SCP** (from your Linux terminal):
   ```bash
   scp growmate.db homes@192.168.178.97:C:/Users/homes/Documents/growmate/growmate.db
   ```
4. **Restart**: 
   ```powershell
   .\gm_control.ps1 start
   ```
