"""
GrowMate – Flask Hauptanwendung
REST API für Sensordaten, Gerätesteuerung und Pflanzentagebuch.
"""

import os
import sys
import logging
import threading
import time
import json
from datetime import datetime, timezone, timedelta
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
    add_sensor_reading, add_analysis_record, get_analysis_history
)
from sensors.tapo_devices import (
    turn_on, turn_off, toggle_device,
    get_device_info, get_energy_usage
)
from scheduler import start_scheduler, stop_scheduler, poll_all_sensors, get_scheduler_status
import analyzer

# ─── Rate-Limiting (Problem 5) ────────────────────────────────────────────────
# Schützt nur destruktive/teure Endpunkte gegen unbeabsichtigtes Flooding.
# Read-Endpunkte bleiben unbeschränkt. Greift nur im lokalen Netz – bewusst
# großzügig dimensioniert (kein öffentlicher Server).
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    _limiter_available = True
except ImportError:
    _limiter_available = False
    logger = logging.getLogger("growmate")
    logger.warning("flask-limiter nicht installiert – Rate-Limiting deaktiviert.")

class MockLimiter:
    """Fallback-Klasse, falls flask-limiter nicht installiert ist."""
    def limit(self, *args, **kwargs):
        def decorator(f):
            return f
        return decorator

# ─── App Setup ──────────────────────────────────────────────────────

VERSION = "1.2"
app = Flask(__name__,
            static_folder="static",
            template_folder="templates")

# Rate-Limiter an App binden (oder Mock nutzen)
if _limiter_available:
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[],          # keine globale Beschränkung auf Read-Endpoints
        storage_uri="memory://"
    )
    # kein Redis nötig, läuft in-process
else:
    limiter = MockLimiter()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("growmate")


# ─── API: Advisor History ───────────────────────────────────────────

@app.route("/api/analysis/history")
def api_analysis_history():
    """Gibt die Historie der automatischen 60-Sekunden-Checks zurück."""
    limit = request.args.get("limit", 20, type=int)
    history = get_analysis_history(limit=limit)
    
    # JSON-Strings in der Datenbank wieder in Listen umwandeln
    for item in history:
        try:
            item["results"] = json.loads(item["results_json"])
            del item["results_json"]
        except:
            item["results"] = []
            
    return jsonify({"success": True, "data": history})

# ─── Hintergrund-Advisor-Thread ─────────────────────────────────────

def run_advisor_loop():
    """Thread-Loop für die automatische 60-Sekunden-Analyse."""
    import analyzer
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "advisor_debug.log")
    
    with open(log_path, "a") as f:
        f.write(f"\n[{datetime.now()}] Advisor-Loop Thread gestartet\n")
        f.write(f"[{datetime.now()}] Analyzer-Pfad: {analyzer.__file__}\n")
    
    while True:
        try:
            with open(log_path, "a") as f:
                f.write(f"[{datetime.now()}] Starte Analyse-Zyklus...\n")
            
            # Analyse triggern
            tips = analyzer.analyze_plant_needs()
            
            with open(log_path, "a") as f:
                f.write(f"[{datetime.now()}] Analyse abgeschlossen: {len(tips)} Tipps gefunden\n")
            
            # In Datenbank speichern
            add_analysis_record(json.dumps(tips))
            
            with open(log_path, "a") as f:
                f.write(f"[{datetime.now()}] Ergebnisse gespeichert.\n")
                
        except Exception as e:
            with open(log_path, "a") as f:
                f.write(f"[{datetime.now()}] KRITISCHER FEHLER im Advisor-Loop: {str(e)}\n")
            logger.error(f"Fehler im Advisor-Loop: {e}")
        
        time.sleep(60)

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
    try:
        hours = int(request.args.get("hours", 24))
    except (ValueError, TypeError):
        hours = 24
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
    try:
        hours = int(request.args.get("hours", 24))
    except (ValueError, TypeError):
        hours = 24
    data = get_energy_history(device_name=device_name, hours=hours)
    return jsonify({"success": True, "data": data})


# ─── API: Geräte-Steuerung ──────────────────────────────────────────

@app.route("/api/devices")
def api_devices():
    """Alle konfigurierten Geräte mit aktuellem Status (non-blocking)."""
    import mock_data_system
    config_data = load_config()
    devices = config_data.get("devices", [])
    
    # Füge virtuelle Geräte hinzu, falls Demo aktiv (De-dupliziert)
    real_devices = config_data.get("devices", [])
    real_names = {d.get("name") for d in real_devices}
    virtual_devices = [d for d in mock_data_system.get_virtual_devices() if d.get("name") not in real_names]
    devices = real_devices + virtual_devices
    
    # Holen der aktuellsten Werte aus der DB (Cache-Ersatz)
    latest_sensors = {r["sensor_name"]: r for r in get_latest_sensor_readings()}
    latest_energy = {r["device_name"]: r for r in get_latest_energy_readings()}

    result = []
    for device in devices:
        name = device.get("name", "")
        dtype = device.get("type", "")
        
        # Bestimme Kategorie (Priorität: Gerät-Attribut > Type-Mapping)
        category = device.get("category")
        if not category:
            if dtype == "tapo_plug": category = "power"
            elif dtype == "hub": category = "hub"
            else: category = "sensor"

        dev_info = {
            "name": name,
            "type": dtype,
            "category": category,
            "ip": device.get("ip", ""),
            "mac": device.get("mac", ""),
            "enabled": device.get("enabled", True),
            "tent_id": device.get("tent_id"),
            "online": False,
            "virtual": device.get("virtual", False),
            "timestamp": None
        }

        # Daten-Mapping aus DB-Readings
        if dtype == "tapo_plug" or category in ["power", "light", "ventilation", "irrigation", "climate"]:
            reading = latest_energy.get(name)
            if reading:
                dev_info["online"] = True
                dev_info["device_on"] = True 
                dev_info["power_w"] = reading.get("power_w", 0)
                dev_info["timestamp"] = reading.get("timestamp")
            
            # Falls es ein Plug ist aber keine Energie-Daten hat, schau bei Sensoren (z.B. Heizmatte als Sensor geloggt)
            if not reading:
                reading = latest_sensors.get(name)
                if reading:
                    dev_info["online"] = True
                    dev_info["temperature"] = reading.get("temperature")
                    dev_info["humidity"] = reading.get("humidity")
                    dev_info["timestamp"] = reading.get("timestamp")

        elif dtype in ["govee_ble", "tapo_sensor", "shelly_device", "mqtt_device"] or category == "sensor":
            reading = latest_sensors.get(name)
            if reading:
                dev_info["online"] = True
                dev_info["temperature"] = reading.get("temperature")
                dev_info["humidity"] = reading.get("humidity")
                dev_info["battery"] = reading.get("battery")
                dev_info["timestamp"] = reading.get("timestamp")
        
        elif category == "hub":
            dev_info["online"] = True # Hubs im Demo Mode immer online

        result.append(dev_info)

    return jsonify({"success": True, "data": result})


@app.route("/api/devices/toggle", methods=["POST"])
@limiter.limit("30 per minute")   # max. 30 Schaltvorgänge/Min – verhindert Flooding
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


@app.route("/api/devices/config")
def api_devices_config():
    """Gibt alle Geräte-Konfigurationen aus der Datenbank zurück."""
    from database import get_all_device_configs
    configs = get_all_device_configs()
    return jsonify({"success": True, "data": configs})


# ─── API: Tagebuch ──────────────────────────────────────────────────

@app.route("/api/diary", methods=["GET"])
def api_diary_list():
    """Tagebucheinträge auflisten mit Filter für archivierte Pflanzen."""
    entry_type = request.args.get("type")
    plant_name = request.args.get("plant")
    try:
        limit = int(request.args.get("limit", 50))
    except (ValueError, TypeError):
        limit = 50
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
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
@limiter.limit("6 per minute")    # max. 1 manueller Poll/10s
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
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=threshold)

    latest_sensors = {r["sensor_name"]: r for r in get_latest_sensor_readings()}
    latest_energy = {r["device_name"]: r for r in get_latest_energy_readings()}

    issues = []

    for d in devices:
        if not d.get("enabled", True):
            continue

        name = d.get("name")
        dtype = d.get("type")
        is_virtual = d.get("virtual", False)

        # Finde letztes Update
        last_ts_str = None
        if dtype in ["govee_ble", "tapo_sensor", "tapo_hub", "shelly_device", "mqtt_device"]:
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
            # Problem-Fix: Mock-Daten haben oft andere Timezones oder Drifts
            # Wenn virtual, sind wir großzügiger
            current_cutoff = cutoff if not is_virtual else (datetime.now(timezone.utc) - timedelta(hours=24))
            
            if last_ts < current_cutoff:
                delta_mins = int((datetime.now(timezone.utc) - last_ts).total_seconds() / 60)
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
                    if not cred_res.get('success'):
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

# ─── API: Tents ─────────────────────────────────────────────────────

@app.route("/api/tents", methods=["GET"])
def api_tents_get():
    """Gibt alle Zelte zurück."""
    config = load_config()
    return jsonify({"success": True, "data": config.get("tents", [])})

@app.route("/api/tents", methods=["POST"])
def api_tents_save():
    """Zelt hinzufügen oder aktualisieren."""
    data = request.get_json()
    if not data or "id" not in data or "name" not in data:
        return jsonify({"success": False, "message": "Zelt-Daten unvollständig"}), 400

    config = load_config()
    tents = config.get("tents", [])
    
    # Check if exists
    found = False
    for i, t in enumerate(tents):
        if t.get("id") == data["id"]:
            tents[i] = data
            found = True
            break
            
    if not found:
        tents.append(data)
        
    config["tents"] = tents
    save_config(config)
    return jsonify({"success": True, "message": "Zelt gespeichert"})

@app.route("/api/tents/<tent_id>", methods=["DELETE"])
def api_tents_delete(tent_id):
    """Zelt löschen und Geräte-Zuweisungen entfernen."""
    config = load_config()
    tents = config.get("tents", [])
    config["tents"] = [t for t in tents if t.get("id") != tent_id]
    
    # Update devices to remove tent_id
    for dev in config.get("devices", []):
        if dev.get("tent_id") == tent_id:
            dev["tent_id"] = None
            
    save_config(config)
    return jsonify({"success": True, "message": "Zelt gelöscht"})

@app.route("/api/devices/update", methods=["POST"])
def api_devices_update():
    """Geräte-Eigenschaften aktualisieren (z.B. tent_id)."""
    data = request.get_json()
    name = data.get("name")
    if not name:
        return jsonify({"success": False, "message": "Name fehlt"}), 400

    config = load_config()
    devices = config.get("devices", [])
    
    # Payload-Abstraktion: Support für {name, edits: {...}} oder flach {name, ...}
    updates = data.get("edits", data)
    
    found = False
    for d in devices:
        if d.get("name") == name:
            for k, v in updates.items():
                if k != "name":
                    d[k] = v
            found = True
            break

    if not found:
        # Check if it was a virtual device and promote it
        import mock_data_system
        virtual_dev = next((d for d in mock_data_system.get_virtual_devices() if d.get("name") == name), None)
        if virtual_dev:
            # Promote to real config
            new_dev = virtual_dev.copy()
            for k, v in updates.items():
                if k != "name":
                    new_dev[k] = v
            devices.append(new_dev)
            config["devices"] = devices
            found = True
        else:
            return jsonify({"success": False, "message": "Gerät nicht gefunden"}), 404

    save_config(config)
    return jsonify({"success": True, "message": "Gerät aktualisiert"})

# ─── App Start ──────────────────────────────────────────────────────

def main():
    """Startet die GrowMate-Anwendung."""
    import getpass

    # Problem 1 – Fix: Benutzerpflicht konfigurierbar via .env
    # GROWMATE_USER=gov-k  → erzwingt diesen Benutzer
    # (nicht gesetzt)      → läuft unter jedem Benutzer, gibt nur eine Warnung aus
    required_user = os.getenv("GROWMATE_USER", "").strip()
    current_user  = getpass.getuser()
    if required_user and current_user != required_user:
        logger.error(
            f"FATAL: App muss unter Benutzer '{required_user}' laufen "
            f"(aktuell: '{current_user}'). "
            f"Entweder 'sudo -u {required_user} ...' oder GROWMATE_USER aus .env entfernen."
        )
        sys.exit(1)
    elif not required_user:
        logger.warning(
            f"GROWMATE_USER nicht gesetzt – läuft als '{current_user}'. "
            "Für Produktionsbetrieb GROWMATE_USER=<username> in .env setzen."
        )

    # Datenbank initialisieren
    init_db()
    
    # Demo-System initialisieren
    import mock_data_system
    mock_data_system.clean_mock_config()
    
    logger.info("Datenbank initialisiert.")

    # Scheduler starten
    start_scheduler()

    # Initiales Polling ausführen (im Hintergrund, um Startup nicht zu blockieren)
    logger.info("Starte initiales Sensor-Polling (Hintergrund)...")
    import threading
    threading.Thread(target=poll_all_sensors, daemon=True).start()

    # Flask starten
    config_data = load_config()
    host = config_data.get("server_host", "0.0.0.0")
    port = config_data.get("server_port", 5000)

    # Advisor-Thread starten
    advisor_thread = threading.Thread(target=run_advisor_loop, daemon=True)
    advisor_thread.start()

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

@app.route("/api/analyze/text", methods=["POST"])
@limiter.limit("10 per minute")
def api_analyze_text():
    """Analysiert einen beliebigen Text (visuelle Beobachtung) mit dem Modell."""
    data = request.get_json()
    if not data or not data.get("text"):
        return jsonify({"success": False, "message": "Text fehlt"}), 400
        
    text = data.get("text").strip()
    if len(text) < 3:
        return jsonify({"success": False, "message": "Text zu kurz"}), 400
        
    tips = analyzer._search(text, threshold=0.55, top_k=3)
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
    """Erstellt ein ZIP-Backup aller wichtigen Dateien inkl. Vektor-Wissensbasis."""
    import zipfile
    import io

    memory_file = io.BytesIO()
    base_dir    = os.path.dirname(os.path.abspath(__file__))

    try:
        with zipfile.ZipFile(memory_file, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Einzeldateien
            for filename in ["growmate.db", "config.json", "knowledge_vectors.json"]:
                filepath = os.path.join(base_dir, filename)
                if os.path.exists(filepath):
                    zf.write(filepath, arcname=filename)

        memory_file.seek(0)
        return send_file(
            memory_file,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"growmate_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        )
    except Exception as e:
        logger.error(f"Backup Error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/admin/restore", methods=["POST"])
@limiter.limit("5 per hour")
def api_admin_restore():
    """Stellt Daten aus einem ZIP-Backup wieder her."""
    import zipfile

    if "file" not in request.files:
        return jsonify({"success": False, "message": "Keine Datei hochgeladen"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"success": False, "message": "Keine Datei ausgewählt"}), 400

    if not file.filename.endswith(".zip"):
        return jsonify({"success": False, "message": "Ungültiges Dateiformat (nur .zip)"}), 400

    base_dir      = os.path.dirname(os.path.abspath(__file__))
    real_base_dir = os.path.realpath(base_dir) + os.sep

    try:
        with zipfile.ZipFile(file) as zf:
            # Zip-Slip-Schutz: kein Eintrag darf außerhalb base_dir landen
            for name in zf.namelist():
                target = os.path.realpath(os.path.join(base_dir, name))
                if not target.startswith(real_base_dir):
                    return jsonify({
                        "success": False,
                        "message": f"Sicherheitsfehler: Ungültiger Pfad '{name}' im Backup."
                    }), 400

            allowed_files = {"growmate.db", "config.json", "knowledge_vectors.json"}

            for name in zf.namelist():
                if name in allowed_files:
                    target = os.path.join(base_dir, name)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as f_out:
                        f_out.write(zf.read(name))

        # Config-Cache invalidieren damit neue config.json sofort gilt
        from config import _invalidate_config_cache
        _invalidate_config_cache()

        # Analyzer-Cache leeren damit neue Vektordatei sofort genutzt wird
        analyzer.invalidate_analysis_cache()

        return jsonify({"success": True, "message": "Backup erfolgreich wiederhergestellt."})

    except Exception as e:
        logger.error(f"Restore Error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ─── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
