#!/bin/bash
# GrowMate Ressourcen-Management und lokales Start-Skript
# Läuft autark ohne Docker! Integriertes OS-Level Self-Repair.

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
LOG_FILE="growmate_run.log"

if [ "$USER" != "gov-k" ] && [ "$LOGNAME" != "gov-k" ]; then
    echo "[FATAL] System abort: GrowMate darf zwingend nur als Benutzer 'gov-k' ausgefuehrt werden!" | tee -a $LOG_FILE
    exit 1
fi

echo "[$(date)] Starte GrowMate Ressource-Management..." | tee -a $LOG_FILE

# Self-Repair: Memory & CPU Check Funktion (Ohne Sudo!)
check_resources_and_repair() {
    # Wenn RAM unter 50MB frei (Hardware Optimierung für RPi)
    FREE_MEM=$(free -m | grep -E "^(Mem|Speicher):" | awk '{print $4}')
    if [[ "$FREE_MEM" =~ ^[0-9]+$ ]] && [ "$FREE_MEM" -lt 50 ]; then
        echo "[$(date)] WARNING: Kritisch wenig RAM ($FREE_MEM MB). Beende unwichtige User-Prozesse..." | tee -a $LOG_FILE
        # Da wir kein Sudo haben (Zero-Root Prinzip), können wir nur User-Prozesse killen.
        pkill -u $USER -f "pip" 2>/dev/null || true
        pkill -u $USER -f "npm" 2>/dev/null || true
    fi
}

# Endlosschleife für Autonomie (OS-Level Watchdog)
while true; do
    check_resources_and_repair
    
    # Self-Repair: Zombie-Prozesse (nur User-Level!)
    echo "[$(date)] Prüfe auf blockierte Ports (Self-Repair)..." | tee -a $LOG_FILE
    fuser -k 5000/tcp 2>/dev/null || true
    pkill -f "python3 app.py" 2>/dev/null || true
    
    echo "[$(date)] Starte Flask App (GrowMate)..." | tee -a $LOG_FILE
    
    # Virtualenv nutzen, falls vorhanden (z. B. uv)
    if [ -d ".venv" ]; then
        source .venv/bin/activate
    fi
    
    # Unbuffered Output verwenden, um Logs in Echtzeit zu prüfen
    PYTHONUNBUFFERED=1 python3 app.py 2>&1 | tee -a $LOG_FILE
    
    EXIT_CODE=${PIPESTATUS[0]}
    echo "[$(date)] App unerwartet beendet. Code $EXIT_CODE. Restart (Backoff) in 10 Sekunden..." | tee -a $LOG_FILE
    sleep 10
done
