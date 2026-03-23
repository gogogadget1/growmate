"""
GrowMate – Flask Hauptanwendung
REST API für Sensordaten, Gerätesteuerung und Pflanzentagebuch.
"""

import os
import sys
import logging
from datetime import datetime
from flask import Flask, jsonify, request, render_template, send_from_directory, send_file

# Projektverzeichnis zum Path hinzufügen
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config, save_config, get_tapo_credentials
from dotenv import load_dotenv

# Load env vars early
load_dotenv()
from database import (
    init_db,
    get_latest_sensor_readings, get_sensor_history,
    get_latest_energy_readings, get_energy_history,
    add_diary_entry, get_diary_entries, get_diary_entry,
    update_diary_entry, delete_diary_entry, get_plant_height_history,
    add_sensor_reading
)
from sensors.tapo_devices import (
    turn_on, turn_off, toggle_device,
    get_device_info, get_energy_usage
)
from scheduler import start_scheduler, stop_scheduler, poll_all_sensors, get_scheduler_status
import analyzer

# ─── App Setup ──────────────────────────────────────────────────────

app = Flask(__name__,
            static_folder="static",
            template_folder="templates")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("growmate")


# ─── Frontend ───────────────────────────────────────────────────────

@app.route("/")
def index():
    demo_active = os.environ.get("GROW_DEMO_MODE", "false").lower() == "true"
    return render_template("index.html", demo_active=demo_active)


# ─── API: Sensor-Daten ──────────────────────────────────────────────

@app.route("/api/sensors/current")
def api_sensors_current():
    """Aktuelle Sensorwerte aller Sensoren."""
    readings = get_latest_sensor_readings()
    return jsonify({"success": True, "data": readings})


@app.route("/api/sensors/history")
def api_sensors_history():
    """Historische Sensordaten mit optionalem Filter."""
    sensor_name = request.args.get("sensor")
    hours = int(request.args.get("hours", 24))
    data = get_sensor_history(sensor_name=sensor_name, hours=hours)
    return jsonify({"success": True, "data": data})


# ─── API: Energie-Daten ─────────────────────────────────────────────

@app.route("/api/energy/current")
def api_energy_current():
    """Aktuelle Energiewerte aller Steckdosen."""
    readings = get_latest_energy_readings()
    return jsonify({"success": True, "data": readings})


@app.route("/api/energy/history")
def api_energy_history():
    """Historische Energiedaten."""
    device_name = request.args.get("device")
    hours = int(request.args.get("hours", 24))
    data = get_energy_history(device_name=device_name, hours=hours)
    return jsonify({"success": True, "data": data})


# ─── API: Geräte-Steuerung ──────────────────────────────────────────

@app.route("/api/devices")
def api_devices():
    """Alle konfigurierten Geräte mit aktuellem Status."""
    config = load_config()
    devices = config.get("devices", [])
    email, password = get_tapo_credentials()

    result = []
    for device in devices:
        dev_info = {
            "name": device.get("name", ""),
            "type": device.get("type", ""),
            "ip": device.get("ip", ""),
            "mac": device.get("mac", ""),
            "enabled": device.get("enabled", True),
        }

        # Live-Status für Tapo-Steckdosen abrufen
        if device.get("type") == "tapo_plug" and email and password and device.get("ip"):
            try:
                info = get_device_info(device["ip"], email, password)
                if info.get("success"):
                    dev_info["online"] = True
                    dev_info["device_on"] = info.get("device_on", False)
                    dev_info["signal_level"] = info.get("signal_level", 0)
                else:
                    dev_info["online"] = False
            except Exception:
                dev_info["online"] = False
        elif device.get("type") == "govee_ble":
            dev_info["online"] = True  # BLE Sensoren sind "online" wenn sie beim letzten Scan gefunden wurden

        result.append(dev_info)

    return jsonify({"success": True, "data": result})


@app.route("/api/devices/toggle", methods=["POST"])
def api_device_toggle():
    """Schaltet eine Steckdose um."""
    data = request.get_json()
    ip = data.get("ip")
    action = data.get("action", "toggle")  # "on", "off", or "toggle"

    if not ip:
        return jsonify({"success": False, "message": "IP-Adresse fehlt"}), 400

    email, password = get_tapo_credentials()
    if not email or not password:
        return jsonify({"success": False, "message": "Tapo-Zugangsdaten nicht konfiguriert"}), 400

    if action == "on":
        result = turn_on(ip, email, password)
    elif action == "off":
        result = turn_off(ip, email, password)
    else:
        result = toggle_device(ip, email, password)

    return jsonify(result)


@app.route("/api/devices/energy")
def api_device_energy():
    """Energieverbrauch einer bestimmten Steckdose."""
    ip = request.args.get("ip")
    if not ip:
        return jsonify({"success": False, "message": "IP-Adresse fehlt"}), 400

    email, password = get_tapo_credentials()
    result = get_energy_usage(ip, email, password)
    return jsonify(result)


# ─── API: Tagebuch ──────────────────────────────────────────────────

@app.route("/api/diary", methods=["GET"])
def api_diary_list():
    """Tagebucheinträge auflisten mit Filter für archivierte Pflanzen."""
    entry_type = request.args.get("type")
    plant_name = request.args.get("plant")
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    show_archived = request.args.get("show_archived", "false").lower() == "true"
    
    entries = get_diary_entries(limit=limit, offset=offset, 
                               entry_type=entry_type, plant_name=plant_name,
                               show_archived=show_archived)
    return jsonify({"success": True, "data": entries})


@app.route("/api/diary", methods=["POST"])
def api_diary_create():
    """Neuen Tagebucheintrag erstellen."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Keine Daten"}), 400

    required = ["entry_type", "title"]
    for field in required:
        if field not in data:
            return jsonify({"success": False, "message": f"Feld '{field}' fehlt"}), 400

    entry_id = add_diary_entry(
        entry_date=data.get("entry_date", datetime.now().strftime("%Y-%m-%d")),
        entry_type=data["entry_type"],
        title=data["title"],
        content=data.get("content", ""),
        plant_height_cm=data.get("plant_height_cm"),
        plant_name=data.get("plant_name", "Allgemein"),
        plant_phase=data.get("plant_phase"),
        health_status=data.get("health_status"),
        water_amount_ml=data.get("water_amount_ml"),
        ph_value=data.get("ph_value")
    )

    return jsonify({"success": True, "id": entry_id}), 201


@app.route("/api/diary/<int:entry_id>", methods=["GET"])
def api_diary_get(entry_id):
    """Einzelnen Tagebucheintrag abrufen."""
    entry = get_diary_entry(entry_id)
    if entry:
        return jsonify({"success": True, "data": entry})
    return jsonify({"success": False, "message": "Eintrag nicht gefunden"}), 404


@app.route("/api/diary/<int:entry_id>", methods=["PUT"])
def api_diary_update(entry_id):
    """Tagebucheintrag aktualisieren."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Keine Daten"}), 400

    success = update_diary_entry(entry_id, **data)
    if success:
        return jsonify({"success": True, "message": "Eintrag aktualisiert"})
    return jsonify({"success": False, "message": "Eintrag nicht gefunden"}), 404


@app.route("/api/diary/<int:entry_id>", methods=["DELETE"])
def api_diary_delete(entry_id):
    """Tagebucheintrag löschen."""
    delete_diary_entry(entry_id)
    return jsonify({"success": True, "message": "Eintrag gelöscht"})


@app.route("/api/diary/heights")
def api_diary_heights():
    """Pflanzenhöhen-Historie."""
    data = get_plant_height_history()
    return jsonify({"success": True, "data": data})


# ─── API: Polling & Scheduler ───────────────────────────────────────

@app.route("/api/poll", methods=["POST"])
def api_poll():
    """Manuelles Polling aller Sensoren triggern."""
    try:
        poll_all_sensors()
        return jsonify({"success": True, "message": "Polling abgeschlossen"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/scheduler/status")
def api_scheduler_status():
    """Scheduler-Status abrufen."""
    return jsonify({"success": True, "data": get_scheduler_status()})


@app.route("/api/status")
def api_status():
    """Schneller Status-Check, ob alle Sensoren aktuelle Daten liefern."""
    from datetime import datetime, timedelta
    config = load_config()
    devices = config.get("devices", [])
    if not devices:
        return jsonify({"success": True, "status": "ok", "issues": []})

    interval_mins = config.get("polling_interval_minutes", 5)
    # Toleranz: 3 Intervalle fehlgeschlagen (mindestens 15 min)
    threshold = max(15, interval_mins * 3)
    cutoff = datetime.utcnow() - timedelta(minutes=threshold)

    latest_sensors = {r["sensor_name"]: r for r in get_latest_sensor_readings()}
    latest_energy = {r["device_name"]: r for r in get_latest_energy_readings()}

    issues = []

    for d in devices:
        if not d.get("enabled", True):
            continue

        name = d.get("name")
        dtype = d.get("type")

        # Finde letztes Update
        last_ts_str = None
        if dtype in ["govee_ble", "tapo_sensor", "tapo_hub"]:
            if name in latest_sensors:
                last_ts_str = latest_sensors[name]["timestamp"]
        elif dtype == "tapo_plug":
            if name in latest_energy:
                last_ts_str = latest_energy[name]["timestamp"]
            # Fallback falls es beim Sensor-Log dabei ist?
            elif name in latest_sensors:
                last_ts_str = latest_sensors[name]["timestamp"]

        if not last_ts_str:
            issues.append({"device": name, "message": "Noch keine Daten empfangen."})
            continue

        try:
            # SQLite datetime format: "2024-03-18 15:10:00"
            last_ts = datetime.strptime(last_ts_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
            if last_ts < cutoff:
                delta_mins = int((datetime.utcnow() - last_ts).total_seconds() / 60)
                issues.append({"device": name, "message": f"Keine Daten seit {delta_mins} Minuten."})
        except Exception:
            pass

    overall_status = "error" if issues else "ok"
    return jsonify({"success": True, "status": overall_status, "issues": issues})



# ─── API: Konfiguration ─────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
def api_config_get():
    """Konfiguration abrufen."""
    config = load_config()
    
    # Tapo credentials from .env in config einfügen (maskiert)
    email, password = get_tapo_credentials()
    if email and password:
        config["tapo_email"] = email
        config["tapo_password"] = ""
        
    # Passwort maskieren (für den Fall, dass es fälschlicherweise in config.json war)
    if config.get("tapo_password"):
        config["tapo_password"] = ""
    return jsonify({"success": True, "data": config})


@app.route("/api/config", methods=["PUT"])
def api_config_update():
    """Konfiguration aktualisieren."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Keine Daten"}), 400

    cfg = load_config() # Assuming load_config is available
    if 'polling_interval_minutes' in data:
        minutes = int(data['polling_interval_minutes'])
        cfg['polling_interval_minutes'] = minutes
        from scheduler import update_interval # Import here to avoid circular dependency if scheduler imports app
        update_interval(minutes)
    if 'ble_scan_duration_seconds' in data:
        cfg['ble_scan_duration_seconds'] = int(data['ble_scan_duration_seconds'])
        
    if 'tapo_email' in data:
        t_email = data['tapo_email']
        t_pass = data.get('tapo_password', "••••••••")
        
        # Hole aktuelles Passwort, falls das Feld maskiert oder leer belassen wurde
        from config import get_tapo_credentials
        curr_email, curr_pass = get_tapo_credentials()
        
        if t_pass == "••••••••" or t_pass == "":
            t_pass = curr_pass
            
        from config import update_env_credentials
        update_env_credentials(t_email, t_pass)
            
    if 'automations' in data:
        cfg['automations'] = data['automations']
        
    save_config(cfg) # Assuming save_config is available
    return jsonify({"success": True, "message": "Konfiguration aktualisiert"})


@app.route('/api/config/test-tapo', methods=['POST'])
def test_tapo():
    data = request.get_json()
    email = data.get('tapo_email')
    password = data.get('tapo_password')
    if not email or not password:
        return jsonify({"success": False, "message": "E-Mail oder Passwort fehlen"})
        
    from sensors.tapo_devices import test_tapo_credentials # Import here
    res = test_tapo_credentials(email, password)
    return jsonify(res)


@app.route('/api/diagnostics', methods=['GET'])
def run_diagnostics():
    import asyncio
    from bleak import BleakScanner
    import socket
    import config
    
    cfg = config.load_config()
    
    bt_status = "ok"
    bt_message = ""
    bt_devices_found = 0
    tapo_results = []
    
    # 1. Test Bluetooth
    try:
        def _run_scan():
            import asyncio
            return asyncio.run(BleakScanner.discover(timeout=5.0))
            
        import concurrent.futures
        from typing import List, Any
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run_scan)
            dev_list: List[Any] = future.result() # type: ignore

        govee_count = sum(1 for d in dev_list if hasattr(d, "name") and d.name and "Govee" in d.name)
        
        if len(dev_list) == 0:
            bt_status = "error"
            bt_message = "Der Bluetooth-Adapter hat 0 Geräte gefunden. Mögliche Ursachen: Bluetooth ist deaktiviert, der Laptop hat kein Bluetooth, oder das Programm benötigt root-Rechte (sudo start.sh)."
        else:
            bt_devices_found = len(dev_list)
            if govee_count == 0:
                bt_status = "warning"
                bt_message = f"Bluetooth funktioniert (fand {len(dev_list)} fremde Geräte), aber kein Govee-Gerät ist in Reichweite oder eingeschaltet."
            else:
                bt_status = "ok"
                bt_message = f"Bluetooth ist aktiv. {govee_count} Govee-Geräte in Reichweite gefunden!"
    except Exception as e:
        bt_status = "error"
        bt_message = f"Systemfehler beim Zugriff auf Bluetooth: {str(e)}. (Fehlen sudo-Rechte?)"

    # 2. Test Tapo Devices
    for dev in cfg.get("devices", []):
        if dev.get("type") in ["tapo_plug", "tapo_hub"]:
            ip = dev.get("ip")
            name = dev.get("name")
            if not ip:
                tapo_results.append({"name": name, "ip": "Keine IP", "status": "error", "message": "Es wurde keine IP-Adresse konfiguriert."})
                continue
                
            # Quick Ping via Socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            try:
                # Port 80 is used by Tapo
                result = sock.connect_ex((ip, 80))
                if result == 0:
                    status_info = {"name": name, "ip": ip, "status": "ok", "message": "Gerät ist im Netzwerk erreichbar (Port 80 offen)."}
                    # Also test credentials if possible
                    from sensors.tapo_devices import test_tapo_credentials
                    cred_res = test_tapo_credentials(cfg.get('tapo_email',''), cfg.get('tapo_password',''), ip=ip)
                    if not cred_res['success']:
                         status_info["status"] = "warning"
                         status_info["message"] += f" Aber der Login schlägt fehl: {cred_res['message']} (Falsches Passwort?)"
                    tapo_results.append(status_info)
                else:
                    tapo_results.append({"name": name, "ip": ip, "status": "error", "message": "Gerät ist im Netzwerk NICHT erreichbar. Bitte prüfe die IP-Adresse im Router."})
            except Exception as e:
                tapo_results.append({"name": name, "ip": ip, "status": "error", "message": f"Netzwerkfehler: {str(e)}"})
            finally:
                sock.close()

    results = {
        "bluetooth": {"status": bt_status, "message": bt_message, "devices_found": bt_devices_found},
        "tapo": tapo_results
    }
    return jsonify({"success": True, "diagnostics": results})


@app.route("/api/devices/add", methods=["POST"])
def api_device_add():
    """Neues Gerät zur Konfiguration hinzufügen."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Keine Daten"}), 400

    required = ["name", "type"]
    for field in required:
        if field not in data:
            return jsonify({"success": False, "message": f"Feld '{field}' fehlt"}), 400

    config = load_config()
    device = {
        "name": data["name"],
        "type": data["type"],
        "ip": data.get("ip", ""),
        "mac": data.get("mac", ""),
        "enabled": data.get("enabled", True),
    }
    config.setdefault("devices", []).append(device)
    save_config(config)

    return jsonify({"success": True, "message": "Gerät hinzugefügt"}), 201


@app.route("/api/devices/remove", methods=["POST"])
def api_device_remove():
    """Gerät aus der Konfiguration entfernen."""
    data = request.get_json()
    name = data.get("name")
    if not name:
        return jsonify({"success": False, "message": "Name fehlt"}), 400

    config = load_config()
    config["devices"] = [d for d in config.get("devices", []) if d.get("name") != name]
    save_config(config)

    return jsonify({"success": True, "message": "Gerät entfernt"})

@app.route("/api/devices/rename", methods=["POST"])
def api_device_rename():
    """Gerät umbenennen."""
    data = request.get_json()
    old_name = data.get("old_name")
    new_name = data.get("new_name")
    
    if not old_name or not new_name:
        return jsonify({"success": False, "message": "Ein Name fehlt"}), 400

    config = load_config()
    found = False
    for d in config.get("devices", []):
        if d.get("name") == old_name:
            d["name"] = new_name
            found = True
            break
            
    if not found:
        return jsonify({"success": False, "message": "Gerät nicht in Konfiguration gefunden"}), 404

    save_config(config)

    # Update history in database to preserve charts
    try:
        from database import get_db
        conn = get_db()
        conn.execute("UPDATE energy_readings SET device_name = ? WHERE device_name = ?", (new_name, old_name))
        conn.execute("UPDATE sensor_readings SET sensor_name = ? WHERE sensor_name = ?", (new_name, old_name))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Fehler beim Umbenennen in DB: {e}")

    return jsonify({"success": True, "message": "Gerät erfolgreich umbenannt"})

# ─── App Start ──────────────────────────────────────────────────────

def main():
    """Startet die GrowMate-Anwendung."""
    import getpass
    if getpass.getuser() != "gov-k":
        logger.error("FATAL ERROR: Das System darf zwingend nur unter dem Benutzer 'gov-k' ausgeführt werden.")
        sys.exit(1)

    # Datenbank initialisieren
    init_db()
    logger.info("Datenbank initialisiert.")

    # Scheduler starten
    start_scheduler()

    # Initiales Polling ausführen (im Hintergrund, um Startup nicht zu blockieren)
    logger.info("Starte initiales Sensor-Polling (Hintergrund)...")
    import threading
    threading.Thread(target=poll_all_sensors, daemon=True).start()

    # Flask starten
    config = load_config()
    host = config.get("server_host", "0.0.0.0")
    port = config.get("server_port", 5000)

    logger.info(f"GrowMate startet auf http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)


# ─── API: Pflanzen-Profile ─────────────────────────────────────────

@app.route("/api/plants", methods=["GET"])
def api_plants_list():
    """Gibt alle Pflanzenprofile zurück."""
    show_archived = request.args.get("show_archived", "false").lower() == "true"
    from database import get_plants
    plants = get_plants(show_archived=show_archived)
    return jsonify({"success": True, "data": plants})

@app.route("/api/plants", methods=["POST"])
def api_plants_create():
    """Erstellt ein neues Pflanzenprofil."""
    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"success": False, "message": "Name erforderlich"}), 400
        
    from database import get_db
    conn = get_db()
    try:
        conn.execute("INSERT INTO plants (name, description) VALUES (?, ?)", 
                     (data["name"], data.get("description", "")))
        conn.commit()
        return jsonify({"success": True}), 201
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        conn.close()

@app.route("/api/plants/<int:plant_id>", methods=["PUT"])
def api_plants_update(plant_id):
    """Aktualisiert ein Pflanzenprofil mit Passwortschutz."""
    data = request.get_json()
    password = request.headers.get("X-Plant-Password")
    env_password = os.getenv("PLANT_EDIT_PASSWORD", "growmate")
    
    if password != env_password:
        return jsonify({"success": False, "message": "Ungültiges Passwort"}), 403
        
    if not data or "description" not in data:
        return jsonify({"success": False, "message": "Beschreibung erforderlich"}), 400
        
    from database import get_db
    conn = get_db()
    cursor = conn.execute("UPDATE plants SET description = ? WHERE id = ?", 
                          (data["description"], plant_id))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    
    if success:
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Pflanze nicht gefunden"}), 404

@app.route("/api/plants/<int:plant_id>/archive", methods=["PUT"])
def api_plants_archive(plant_id):
    """Archiviert eine Pflanze mit Passwortschutz."""
    data = request.get_json() or {}
    password = request.headers.get("X-Plant-Password")
    env_password = os.getenv("PLANT_EDIT_PASSWORD", "growmate")
    
    if password != env_password:
        return jsonify({"success": False, "message": "Ungültiges Passwort"}), 403
        
    archived = data.get("is_archived", True)
    from database import archive_plant
    archive_plant(plant_id, archived=archived)
    return jsonify({"success": True})

# ─── API: Analyse ──────────────────────────────────────────────────

@app.route("/api/analysis")
def api_analysis():
    """Liefert automatisierte Analysen und Tipps."""
    tips = analyzer.analyze_plant_needs()
    return jsonify({"success": True, "data": tips})


# ─── API: Admin & System ───────────────────────────────────────────

@app.route("/api/admin/config", methods=["GET", "POST"])
def api_admin_config():
    """Liest oder aktualisiert die System-Konfiguration."""
    if request.method == "POST":
        new_config = request.get_json()
        if not new_config:
            return jsonify({"success": False, "message": "Keine Daten empfangen"}), 400
        
        # Bestehende Config laden und nur erlaubte Felder aktualisieren
        current_cfg = load_config()
        # Nur unkritische Felder erlauben (Credentials sind in .env!)
        for key in ["polling_interval_minutes", "ble_scan_duration_seconds", "server_host", "server_port"]:
            if key in new_config:
                current_cfg[key] = new_config[key]
        
        save_config(current_cfg)
        return jsonify({"success": True, "message": "Konfiguration aktualisiert"})
    
    # GET: Aktuelle Config zurückgeben (sensible Daten werden in config gefiltert)
    return jsonify({"success": True, "data": load_config()})


@app.route("/api/admin/backup", methods=["GET"])
def api_admin_backup():
    """Erstellt ein ZIP-Backup der wichtigsten Dateien."""
    import zipfile
    import io
    
    memory_file = io.BytesIO()
    files_to_backup = ["growmate.db", "botany_knowledge.db", "config.json"]
    
    try:
        with zipfile.ZipFile(memory_file, 'w') as zf:
            for filename in files_to_backup:
                if os.path.exists(filename):
                    zf.write(filename)
        
        memory_file.seek(0)
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"growmate_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        )
    except Exception as e:
        logger.error(f"Backup Error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/admin/restore", methods=["POST"])
def api_admin_restore():
    """Stellt Daten aus einem ZIP-Backup wieder her (nur growmate.db, botany_knowledge.db, config.json)."""
    import zipfile
    
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "Keine Datei hochgeladen"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "message": "Keine Datei ausgewählt"}), 400
        
    if file and file.filename.endswith('.zip'):
        try:
            with zipfile.ZipFile(file) as zf:
                # Sicherheitscheck: Nur erlaubte Dateien extrahieren + Pfad-Validierung (Zip-Slip)
                allowed_files = ["growmate.db", "botany_knowledge.db", "config.json"]
                base_dir = os.path.dirname(os.path.abspath(__file__))
                for name in zf.namelist():
                    if name in allowed_files:
                        target = os.path.join(base_dir, name)
                        with open(target, "wb") as f_out:
                            f_out.write(zf.read(name))
            return jsonify({"success": True, "message": "Backup erfolgreich wiederhergestellt."})
        except Exception as e:
            logger.error(f"Restore Error: {e}")
            return jsonify({"success": False, "message": str(e)}), 500
        
    return jsonify({"success": False, "message": "Ungültiges Dateiformat (nur .zip)"}), 400

# ─── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
