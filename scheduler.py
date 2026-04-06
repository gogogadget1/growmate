"""
GrowMate – Scheduler
Automatisches Polling aller Sensoren und Steckdosen in konfigurierbaren Intervallen.
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import load_config, get_tapo_credentials, get_devices_by_type
from database import add_sensor_reading, add_energy_reading
from sensors import govee_ble, tapo_devices
import database
import config
import metrics
import alerts
import os
from datetime import datetime
import threading
import time
import random
import mock_data_system

logger = logging.getLogger("growmate.scheduler")

# ─── Hardware-Lock (Multi-Environment-Schutz) ──────────────────────────────
# Wenn GROWMATE_HARDWARE_READONLY=true gesetzt ist (z.B. in der Dev .env),
# werden ALLE Hardware-Zugriffe (BLE-Scan, Tapo-Polling) vollständig
# übersprungen. Die Instanz darf nur aus ihrer eigenen DB lesen.
# Prod-Instanz: Variable nicht gesetzt → Hardware-Zugriff aktiv.
HARDWARE_READONLY = os.environ.get("GROWMATE_HARDWARE_READONLY", "false").lower() == "true"

if HARDWARE_READONLY:
    logger.warning(
        "HARDWARE_READONLY-Modus aktiv: Alle BLE-Scans und Tapo-Netzwerkaufrufe "
        "sind deaktiviert. Diese Instanz liest ausschließlich aus der lokalen DB."
    )

# Globale Variable für den APScheduler
scheduler = BackgroundScheduler(daemon=True)
_automation_state = {}  # Tracks previous state to only trigger actions once per state change

_watchdog_thread = None

def _watchdog_loop():
    """Hintergrund-Watchdog: Startet den Scheduler automatisch bei Abstürzen neu (Self-Repair)."""
    while True:
        try:
            time.sleep(60) # Alle 60 Sekunden prüfen
            if not scheduler.running:
                logger.error("WATCHDOG: Scheduler ist abgestürzt oder inaktiv! Self-Repair triggert Restart...")
                start_scheduler()
        except Exception as e:
            logger.error(f"WATCHDOG Fehler: {e}")


def poll_all_sensors():
    """Pollt alle Sensoren und speichert die Ergebnisse in der Datenbank."""
    logger.info("Starte Sensor-Polling...")
    cfg = load_config()
    devices = cfg.get("devices", [])
    t_email, t_password = get_tapo_credentials()

    # ─── Hardware-Lock (Dev-Schutz) ─────────────────────────────────
    # Wenn GROWMATE_HARDWARE_READONLY=true: Kein BLE-Scan, kein Tapo-Call.
    # Die Instanz arbeitet ausschließlich mit ihrer lokalen DB (Snapshot
    # oder Mock-Daten). Prod-DB und Hardware bleiben vollständig unberührt.
    if HARDWARE_READONLY:
        logger.info(
            "HARDWARE_READONLY: Hardware-Polling übersprungen. "
            "Nur DB-Lesezugriff und Alert-Check werden ausgeführt."
        )
        # Alert-Check läuft weiterhin – liest nur aus lokaler DB, kein Hardware-Touch
        try:
            current_readings = database.get_latest_sensor_readings()
            alert_messages = alerts.check_thresholds(current_readings, cfg)
            for msg in alert_messages:
                alerts.send_webhook_alert(msg, webhook_url=cfg.get("alert_webhook_url"))
        except Exception as e:
            logger.error(f"HARDWARE_READONLY: Fehler beim Alert-Check: {e}")
        return

    # ─── Demo Mode ──────────────────────────────────────────────────
    if os.environ.get("GROW_DEMO_MODE", "false").lower() == "true":
        mock_data_system.get_live_mock_data()
        logger.info("Demo-Modus: Comprehensive Mock-Daten generiert.")

    try:
        # ─── Govee BLE Sensoren ─────────────────────────────────────────
        try:
            govee_devices = [d for d in devices if d.get("type") == "govee_ble"]
            if govee_devices:
                ble_duration = cfg.get("ble_scan_duration_seconds", 10)
                govee_results = govee_ble.scan_govee_sync(duration=ble_duration)

                for sensor in govee_results:
                    add_sensor_reading(
                        sensor_name=sensor.get("name", "Unbekannt"),
                        sensor_type="govee_ble",
                        temperature=sensor.get("temperature"),
                        humidity=sensor.get("humidity"),
                        battery=sensor.get("battery")
                    )
                    logger.info(
                        f"Govee-Daten gespeichert: {sensor['name']} – "
                        f"{sensor['temperature']}°C, {sensor['humidity']}%"
                    )
                    
                    # ─── NEU: VPD Berechnung ───────────────────────────
                    vpd = metrics.calculate_vpd(sensor['temperature'], sensor['humidity'])
                    if vpd is not None:
                        database.add_growth_metric(sensor['name'], vpd=vpd)
                        logger.debug(f"VPD berechnet für {sensor['name']}: {vpd} kPa")
            else:
                logger.debug("Keine Govee BLE-Geräte konfiguriert, überspringe Scan.")
        except Exception as e:
            logger.error(f"Fehler beim Govee BLE Polling: {e}")

        # ─── Tapo Steckdosen ────────────────────────────────────────────
        try:
            if t_email and t_password:
                tapo_plugs = get_devices_by_type("tapo_plug")
                if tapo_plugs:
                    plug_results = tapo_devices.scan_tapo_plugs(tapo_plugs, t_email, t_password)

                    for plug in plug_results:
                        if plug.get("success") and plug.get("power_w") is not None:
                            name = plug.get("configured_name", plug.get("ip", "Unbekannt"))
                            add_energy_reading(
                                device_name=name,
                                power_w=plug.get("power_w", 0),
                                energy_today_wh=plug.get("energy_today_wh"),
                                energy_month_wh=plug.get("energy_month_wh"),
                                voltage_v=plug.get("voltage_v"),
                                current_a=plug.get("current_a")
                            )
                            
                            # ─── NEU: DLI Berechnung ───────────────────────────
                            dev_cfg = database.get_device_config(name)
                            if dev_cfg and dev_cfg.get("is_growth_light") and dev_cfg.get("ppfd_value"):
                                interval_mins = cfg.get("polling_interval_minutes", 5)
                                hours_on = database.get_daily_light_hours(name, interval_minutes=interval_mins)
                                dli = metrics.calculate_dli(dev_cfg["ppfd_value"], hours_on)
                                if dli is not None:
                                    database.add_growth_metric(name, dli=dli)
                                    logger.info(f"DLI berechnet für {name}: {dli} mol/m²/d")

                            logger.info(
                                f"Tapo-Energiedaten gespeichert: "
                                f"{name} – "
                                f"{plug.get('power_w', 0):.1f}W"
                            )
            else:
                logger.debug("Tapo-Zugangsdaten nicht konfiguriert, überspringe Tapo-Polling.")
        except Exception as e:
            logger.error(f"Fehler beim Tapo Polling: {e}")

        # ─── Tapo Hubs (und deren Child-Sensoren) ─────────────────────────
        hubs = [d for d in devices if d.get("type") == "tapo_hub"]
        logger.info(f"Hub-Polling: {len(hubs)} Hubs gefunden.")
        if hubs and t_email and t_password:
            try:
                logger.debug(f"Starte Bulk-Scan fuer Hubs: {[h.get('ip') for h in hubs]}")
                hub_sensors = tapo_devices.scan_tapo_hubs_sync(t_email, t_password, hubs)
                
                for s in hub_sensors:
                    # ID-Mapping: Name aus config.json bevorzugen
                    device_id = s.get("raw_data", {}).get("device_id")
                    sensor_name = s["sensor_name"]
                    
                    # Falls eine explizite Config existiert, wird diese hier NICHT doppelt gepollt,
                    # sondern nur der Name übernommen falls er passt.
                    # HINWEIS: Wir priorisieren jetzt aber das dedizierte Polling unten.
                    pass 
            except Exception as e:
                logger.error(f"Fehler beim Tapo Hub Bulk-Polling: {e}")

        # ─── Tapo Einzelsensoren (dediziertes Polling) ────────────────────
        tapo_sensors = [d for d in devices if d.get("type") == "tapo_sensor" and d.get("enabled", True)]
        if tapo_sensors and t_email and t_password:
            for ts in tapo_sensors:
                hub_ip = ts.get("parent_hub_ip")
                device_id = ts.get("device_id")
                if not hub_ip or not device_id:
                    continue
                
                try:
                    s_data = tapo_devices.get_hub_sensor_data(hub_ip, t_email, t_password, device_id)
                    if s_data.get("success"):
                        database.add_sensor_reading(
                            sensor_name=ts.get("name"),
                            sensor_type="tapo_sensor",
                            temperature=s_data.get("temperature"),
                            humidity=s_data.get("humidity"),
                            battery=s_data.get("battery")
                        )
                        logger.info(f"Tapo-Sensor-Daten gespeichert: {ts.get('name')} ({s_data.get('temperature')}°C, {s_data.get('humidity')}%)")
                        
                        # Automatisierung prüfen
                        # Wir simulieren hier das sensor_data Format für check_automations
                        check_automations({
                            "sensor_name": ts.get("name"),
                            "is_leak": s_data.get("is_leak", False),
                            "temperature": s_data.get("temperature"),
                            "humidity": s_data.get("humidity")
                        }, cfg)
                    else:
                        logger.warning(f"Tapo-Sensor {ts.get('name')} lieferte keine Daten: {s_data.get('error')}")
                except Exception as e:
                    logger.error(f"Konnte Tapo-Sensor {ts.get('name')} nicht pollen: {e}")

        # ─── NEU: Webhook Alerts ────────────────────────────────────────
        try:
            current_readings = database.get_latest_sensor_readings()
            alert_messages = alerts.check_thresholds(current_readings, cfg)
            
            for msg in alert_messages:
                alerts.send_webhook_alert(msg, webhook_url=cfg.get("alert_webhook_url"))
        except Exception as e:
            logger.error(f"Fehler beim Alert-Check: {e}")

        logger.info("Polling-Job abgeschlossen.")

    except Exception as e:
        logger.error(f"Fehler im Polling-Job: {e}")

def check_automations(sensor_data, cfg):
    automations = cfg.get("automations", [])
    if not automations:
        return
        
    s_name = sensor_data["sensor_name"]
    is_leak = sensor_data.get("is_leak", False)
    
    # Track state change per sensor
    prev_state = _automation_state.get(s_name, False)
    _automation_state[s_name] = is_leak
    
    # State changed?
    if is_leak != prev_state:
        state_str: str = "leak" if is_leak else "dry"
        logger.info(f"Automation trigger: {s_name} changed to {state_str}")
        
        for rule in automations:
            if not rule.get("enabled", True):
                continue
            
            trigger = rule.get("trigger", {})
            if trigger.get("device_name") == s_name and trigger.get("state") == state_str:
                # Execute actions
                upper_state = str(state_str).upper()
                execute_automation_actions(rule.get("actions", []), cfg, f"{s_name} meldet {upper_state}")

def execute_automation_actions(actions, cfg, reason):
    """Führt Automatisierungsaktionen protokoll-agnostisch aus."""
    action_log = []
    
    for action in actions:
        target_name = action.get("device_name")
        cmd = action.get("action")
        
        success, message = execute_device_command(target_name, cmd, cfg)
        if success:
            action_log.append(f"{target_name} ➔ {cmd.upper()}")
            logger.info(f"Aktion erfolgreich: {target_name} -> {cmd.upper()}")
        else:
            logger.warning(f"Aktion fehlgeschlagen: {target_name} ({message})")
            
    # Tagebucheintrag für Transparenz
    if action_log:
        today = datetime.now().strftime("%Y-%m-%d")
        title = "⚠️ Automatisierung ausgelöst"
        content = f"Grund: {reason}\nAktionen:\n" + "\n".join(action_log)
        database.add_diary_entry(today, "System", title, content, None)


def execute_device_command(device_name, command, cfg):
    """
    Zentrale, protokoll-agnostische Funktion zur Gerätesteuerung.
    Unterstützt aktuell: Tapo
    Vorbereitet für: MQTT, Shelly
    """
    devices = cfg.get("devices", [])
    device = next((d for d in devices if d.get("name") == device_name), None)
    
    if not device:
        return False, "Gerät nicht in Konfiguration gefunden"
    
    d_type = device.get("type")
    d_ip = device.get("ip")
    
    # ─── Prototyp: Protokoll-Weiche ────────────────────────────────────
    
    if d_type in ["tapo_plug", "tapo_hub"]:
        t_email, t_password = config.get_tapo_credentials()
        if command == "on":
            return tapo_devices.turn_on(d_ip, t_email, t_password).get("success"), "Tapo ON"
        elif command == "off":
            return tapo_devices.turn_off(d_ip, t_email, t_password).get("success"), "Tapo OFF"
            
    elif d_type == "mqtt_device":
        # PLATZHALTER für MQTT (Tasmota / Zigbee2MQTT)
        logger.info(f"[PLATZHALTER] MQTT Publish: {device_name} -> {command}")
        return True, "MQTT Placeholder"
        
    elif d_type == "shelly_device":
        # PLATZHALTER für Shelly REST API
        logger.info(f"[PLATZHALTER] Shelly API Call: {d_ip} -> {command}")
        return True, "Shelly Placeholder"
        
    return False, f"Protokoll {d_type} nicht unterstützt"


# DEPRECATED: This exists for backward compatibility, use mock_data_system instead.
def _generate_mock_data():
    mock_data_system.get_live_mock_data()

def start_scheduler():
    """Startet den Scheduler mit dem konfigurierten Intervall."""
    config = load_config()
    interval = config.get("polling_interval_minutes", 5)

    # Entferne alten Job falls vorhanden
    if scheduler.get_job("poll_sensors"):
        scheduler.remove_job("poll_sensors")

    scheduler.add_job(
        poll_all_sensors,
        trigger=IntervalTrigger(minutes=interval),
        id="poll_sensors",
        name="Sensor Polling",
        replace_existing=True,
        max_instances=1
    )

    if not scheduler.running:
        # ─── Demo Initialization ───
        if os.environ.get("GROW_DEMO_MODE", "false").lower() == "true":
            logger.info("Demo-Modus aktiv: Vorbereite Testumgebung...")
            # Mock-Geräte werden nun dynamisch über die API eingebunden (clean_mock_config call in app.py)
            # Generiere 7 Tage Historie falls noch nicht geschehen (Prüfung vereinfacht: nur bei leerer Tabelle)
            latest_readings = database.get_latest_sensor_readings()
            if not latest_readings:
                 mock_data_system.generate_historical_data(days=7)
        
        scheduler.start()
        logger.info(f"Scheduler gestartet – Polling alle {interval} Minuten.")
        
    global _watchdog_thread
    if _watchdog_thread is None or not _watchdog_thread.is_alive():
        _watchdog_thread = threading.Thread(target=_watchdog_loop, daemon=True, name="SchedulerWatchdog")
        _watchdog_thread.start()
        logger.info("Scheduler Watchdog gestartet.")


def stop_scheduler():
    """Stoppt den Scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler gestoppt.")


def update_interval(minutes):
    """Aktualisiert das Polling-Intervall."""
    if scheduler.running:
        scheduler.reschedule_job(
            "poll_sensors",
            trigger=IntervalTrigger(minutes=minutes)
        )
        logger.info(f"Polling-Intervall auf {minutes} Minuten geändert.")


def get_scheduler_status():
    """Gibt den aktuellen Scheduler-Status zurück."""
    job = scheduler.get_job("poll_sensors") if scheduler.running else None
    return {
        "running": scheduler.running,
        "next_run": str(job.next_run_time) if job else None,
        "interval_minutes": load_config().get("polling_interval_minutes", 5),
    }
