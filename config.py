"""
GrowMate – Konfiguration
Laden und Speichern der Benutzer-Konfiguration.
Sensible Daten werden ausschließlich aus der .env Datei geladen.
"""

import os
import json
import logging
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("GROWMATE_DB", os.path.join(BASE_DIR, "growmate.db"))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")

# Load environment variables from .env
load_dotenv(os.path.join(BASE_DIR, ".env"))

DEFAULT_CONFIG = {
    "polling_interval_minutes": 5,
    "ble_scan_duration_seconds": 10,
    "server_host": "0.0.0.0",
    "server_port": 5000,
    "devices": [],
    "automations": []
}


def load_config():
    """Lädt die Konfiguration aus config.json oder gibt Standardwerte zurück."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            # Bereinigung: Sensible Daten niemals aus config.json laden
            for key in ["tapo_email", "tapo_password"]:
                user_config.pop(key, None)
            
            # Merge mit Standardwerten
            merged = {**DEFAULT_CONFIG, **user_config}
            return merged
        except (json.JSONDecodeError, IOError):
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(config_dict):
    """Speichert die Konfiguration in config.json (ohne sensible Daten)."""
    clean_config = config_dict.copy()
    for key in ["tapo_email", "tapo_password"]:
        clean_config.pop(key, None)
    
    try:
        # Self-Repair: Proaktive Berechtigungen vor dem Schreiben
        if os.path.exists(CONFIG_PATH):
            os.chmod(CONFIG_PATH, 0o600)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(clean_config, f, indent=2, ensure_ascii=False)
        os.chmod(CONFIG_PATH, 0o600)  # Berechtigungen final sichern
    except PermissionError:
        logger = logging.getLogger("growmate")
        logger.warning("Keine Schreibrechte für config.json. Versuche Self-Repair durch os.chmod...")
        try:
            os.chmod(CONFIG_PATH, 0o600)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(clean_config, f, indent=2, ensure_ascii=False)
            os.chmod(CONFIG_PATH, 0o600)
            logger.info("Self-Repair erfolgreich: config.json gespeichert.")
        except Exception as e:
            logger.error(f"Self-Repair fehlgeschlagen: {e}")


def get_tapo_credentials():
    """Gibt Tapo E-Mail und Passwort STRICT aus der .env Datei zurück."""
    email = os.getenv("TAPO_EMAIL")
    password = os.getenv("TAPO_PASSWORD")
    
    if not email or not password:
        logger = logging.getLogger("growmate")
        logger.error("FATAL: TAPO_EMAIL oder TAPO_PASSWORD fehlen in der .env Datei! (Dürfen nicht in config stehen)")
        
    return email or "", password or ""

def update_env_credentials(email, password):
    """Aktualisiert die Tapo E-Mail und das Passwort in der .env Datei."""
    os.environ["TAPO_EMAIL"] = email
    os.environ["TAPO_PASSWORD"] = password
    
    lines = []
    if os.path.exists(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except IOError:
            pass

    new_lines = []
    email_found = False
    pass_found = False

    for line in lines:
        if line.strip().startswith("TAPO_EMAIL="):
            new_lines.append(f"TAPO_EMAIL={email}\n")
            email_found = True
        elif line.strip().startswith("TAPO_PASSWORD="):
            new_lines.append(f"TAPO_PASSWORD={password}\n")
            pass_found = True
        else:
            if not line.endswith("\n") and line.strip() != "":
                line += "\n"
            new_lines.append(line)

    if not email_found:
        new_lines.append(f"TAPO_EMAIL={email}\n")
    if not pass_found:
        new_lines.append(f"TAPO_PASSWORD={password}\n")

    try:
        # Self-Repair: Brutales Neuschreiben für saubere Berechtigungen
        if os.path.exists(ENV_PATH):
            try: os.chmod(ENV_PATH, 0o600)
            except: pass
        
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        os.chmod(ENV_PATH, 0o600)
    except IOError as e:
        import logging
        logger = logging.getLogger("growmate")
        logger.error(f"Konnte .env nicht schreiben: {e}")


def get_devices_by_type(device_type):
    """Gibt alle Geräte eines bestimmten Typs zurück."""
    cfg = load_config()
    devices = cfg.get("devices", [])
    if not isinstance(devices, list):
        return []
    return [d for d in devices if isinstance(d, dict) and d.get("type") == device_type]


def _invalidate_config_cache():
    """
    Invalidiert den Config-Cache nach einem Restore.
    load_config() liest direkt von Disk ohne Cache,
    daher reicht hier ein No-Op als explizite Schnittstelle.
    """
    pass
