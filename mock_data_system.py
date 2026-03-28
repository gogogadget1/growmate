"""
GrowMate – Mock Data System
Baut das bestehende Test-Daten-System aus, erzeugt historische Daten 
und deckt alle Gerätekategorien ab.
"""

import random
import logging
from datetime import datetime, timedelta, timezone
import json
import os
import database
import config

logger = logging.getLogger("growmate.mock")

def is_demo_active():
    """Prüft ob der Demo-Modus aktiv ist (via .env oder config.json)."""
    env_active = os.environ.get("GROW_DEMO_MODE", "false").lower() == "true"
    if env_active:
        return True
        
    try:
        from config import load_config
        cfg = load_config()
        return cfg.get("demo_mode", False)
    except:
        return False

MOCK_DEVICES = [
    # ⚡ Strom (Power)
    {"name": "Smart Plug (Virtual)", "type": "tapo_plug", "category": "power", "ip": "192.168.1.101", "enabled": True, "virtual": True},
    {"name": "Timer-Dose (Virtual)", "type": "tapo_plug", "category": "power", "ip": "192.168.1.102", "enabled": True, "virtual": True},
    {"name": "Steckdosenleiste (Virtual)", "type": "shelly_device", "category": "power", "ip": "192.168.1.103", "enabled": True, "virtual": True},
    
    # 🌡️ Sensoren (Sensors)
    {"name": "Zelt Klima (Virtual)", "type": "govee_ble", "category": "sensor", "mac": "DE:AD:BE:EF:00:01", "enabled": True, "virtual": True},
    {"name": "CO2 Sensor (Virtual)", "type": "mqtt_device", "category": "sensor", "ip": "192.168.1.104", "enabled": True, "virtual": True},
    {"name": "Bodenfeuchte (Virtual)", "type": "tapo_sensor", "category": "sensor", "enabled": True, "virtual": True},
    {"name": "Bodentemp (Virtual)", "type": "tapo_sensor", "category": "sensor", "enabled": True, "virtual": True},
    {"name": "Wassertemp (Virtual)", "type": "mqtt_device", "category": "sensor", "enabled": True, "virtual": True},
    {"name": "pH Meter (Virtual)", "type": "mqtt_device", "category": "sensor", "enabled": True, "virtual": True},
    {"name": "EC/TDS Meter (Virtual)", "type": "mqtt_device", "category": "sensor", "enabled": True, "virtual": True},
    {"name": "Wasserleck (Virtual)", "type": "tapo_sensor", "category": "sensor", "enabled": True, "virtual": True},
    
    # 💡 Licht (Light)
    {"name": "Full Spectrum LED (Virtual)", "type": "tapo_plug", "category": "light", "ip": "192.168.1.106", "enabled": True, "virtual": True},
    {"name": "HPS Blüte (Virtual)", "type": "tapo_plug", "category": "light", "ip": "192.168.1.107", "enabled": True, "virtual": True},
    {"name": "LED Controller (Virtual)", "type": "mqtt_device", "category": "light", "enabled": True, "virtual": True},
    
    # 💨 Lüftung (Ventilation)
    {"name": "Abluft-Inline (Virtual)", "type": "tapo_plug", "category": "ventilation", "ip": "192.168.1.108", "enabled": True, "virtual": True},
    {"name": "Umluft Fan (Virtual)", "type": "tapo_plug", "category": "ventilation", "ip": "192.168.1.109", "enabled": True, "virtual": True},
    {"name": "Fan Controller (Virtual)", "type": "mqtt_device", "category": "ventilation", "enabled": True, "virtual": True},
    
    # 💧 Wasser (Water)
    {"name": "Hauptpumpe (Virtual)", "type": "tapo_plug", "category": "irrigation", "ip": "192.168.1.110", "enabled": True, "virtual": True},
    {"name": "Dosierpumpe (Virtual)", "type": "mqtt_device", "category": "irrigation", "enabled": True, "virtual": True},
    {"name": "Drain-Pumpe (Virtual)", "type": "tapo_plug", "category": "irrigation", "ip": "192.168.1.111", "enabled": True, "virtual": True},
    
    # 🌬️ Klima (Climate)
    {"name": "Entfeuchter (Virtual)", "type": "tapo_plug", "category": "climate", "ip": "192.168.1.112", "enabled": True, "virtual": True},
    {"name": "Befeuchter (Virtual)", "type": "tapo_plug", "category": "climate", "ip": "192.168.1.113", "enabled": True, "virtual": True},
    {"name": "Klimaanlage (Virtual)", "type": "tapo_plug", "category": "climate", "ip": "192.168.1.114", "enabled": True, "virtual": True},
    {"name": "Heizmatte (Virtual)", "type": "tapo_plug", "category": "climate", "ip": "192.168.1.115", "enabled": True, "virtual": True},
    {"name": "CO2 Generator (Virtual)", "type": "tapo_plug", "category": "climate", "ip": "192.168.1.116", "enabled": True, "virtual": True},
    
    # 🔗 Hubs (Hubs)
    {"name": "Tapo H100 (Virtual)", "type": "hub", "category": "hub", "ip": "192.168.1.200", "enabled": True, "virtual": True},
    {"name": "Zigbee Hub (Virtual)", "type": "hub", "category": "hub", "ip": "192.168.1.201", "enabled": True, "virtual": True}
]

MOCK_PLANTS = [
    {"name": "Lemon Haze #1", "species": "Lemon Haze (Sativa)", "start_date": (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")},
    {"name": "Northern Lights #2", "species": "Northern Lights (Indica)", "start_date": (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")}
]

def clean_mock_config():
    """Entfernt Mock-Geräte aus der echten config.json."""
    cfg = config.load_config()
    devices = cfg.get("devices", [])
    mock_names = [d["name"] for d in MOCK_DEVICES]
    cfg["devices"] = [d for d in devices if d.get("name") not in mock_names]
    config.save_config(cfg)
    logger.info("Echte Konfiguration von Mock-Geräten bereinigt.")

def get_virtual_devices():
    """Gibt die Liste der virtuellen Geräte zurück, wenn Demo aktiv ist."""
    return MOCK_DEVICES if is_demo_active() else []

def generate_historical_data(days=7):
    """Erzeugt historische Sensordaten und Tagebucheinträge."""
    logger.info(f"Generiere historische Testdaten für die letzten {days} Tage...")
    
    # 1. Pflanzen anlegen
    existing_plants = [p["name"] for p in database.get_plants()]
    for plant in MOCK_PLANTS:
        if plant["name"] not in existing_plants:
            try:
                conn = database.get_db()
                conn.execute("INSERT INTO plants (name, species, start_date) VALUES (?, ?, ?)", 
                             (plant["name"], plant["species"], plant["start_date"]))
                conn.commit()
                conn.close()
            except:
                pass

    # 2. Sensordaten und Energiedaten
    start_time = datetime.now(timezone.utc) - timedelta(days=days)
    curr_time = start_time
    
    conn = database.get_db()
    sensor_records = []
    energy_records = []
    
    while curr_time < datetime.now(timezone.utc):
        ts_str = curr_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        hour = curr_time.hour
        is_day = 6 <= hour <= 22
        
        # Sensors
        sensor_records.append(("Zelt Klima (Virtual)", "govee_ble", round(22.0 + random.random()*4, 1), round(50.0 + random.random()*15, 1), 95, ts_str))
        sensor_records.append(("CO2 Sensor (Virtual)", "mqtt_device", round(400 + random.random()*200, 0), None, None, ts_str))
        sensor_records.append(("Bodenfeuchte (Virtual)", "tapo_sensor", None, round(60.0 + random.random()*10, 1), 88, ts_str))
        sensor_records.append(("Bodentemp (Virtual)", "tapo_sensor", round(19.0 + random.random()*3, 1), None, 92, ts_str))
        sensor_records.append(("Wassertemp (Virtual)", "mqtt_device", round(18.0 + random.random()*2, 1), None, None, ts_str))
        sensor_records.append(("pH Meter (Virtual)", "mqtt_device", round(5.8 + random.random()*0.4, 2), None, None, ts_str))
        sensor_records.append(("EC/TDS Meter (Virtual)", "mqtt_device", round(1.2 + random.random()*0.3, 2), None, None, ts_str))
        
        # Energy
        energy_records.append(("Smart Plug (Virtual)", 15.5 if is_day else 0.5, 500, 12000, 230, 0.1, ts_str))
        energy_records.append(("Full Spectrum LED (Virtual)", 240.0 if is_day else 0.0, 5000, 150000, 230, 1.1, ts_str))
        energy_records.append(("Abluft-Inline (Virtual)", 35.0, 840, 25000, 230, 0.2, ts_str))
        energy_records.append(("Entfeuchter (Virtual)", 200.0 if not is_day else 0.0, 2000, 60000, 230, 0.9, ts_str))

        curr_time += timedelta(hours=1)

    # Batch Insert
    conn.executemany("INSERT INTO sensor_readings (sensor_name, sensor_type, temperature, humidity, battery, timestamp) VALUES (?, ?, ?, ?, ?, ?)", sensor_records)
    conn.executemany("INSERT INTO energy_readings (device_name, power_w, energy_today_wh, energy_month_wh, voltage_v, current_a, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)", energy_records)
    conn.commit()
    conn.close()

    # 3. Tagebucheinträge
    diary_entries = [
        {"day": -20, "type": "System", "title": "Pflanze Lemon Haze angelegt", "plant": "Lemon Haze #1"},
        {"day": -15, "type": "Gießen", "title": "Erstes Mal Wasser", "content": "100ml ohne Dünger", "plant": "Lemon Haze #1"},
        {"day": -1, "type": "Düngen", "title": "Nährstoffe zugegeben", "content": "2ml/L BioGrow", "plant": "Lemon Haze #1"},
    ]
    
    for entry in diary_entries:
        date = (datetime.now() + timedelta(days=entry["day"])).strftime("%Y-%m-%d")
        database.add_diary_entry(entry_date=date, entry_type=entry["type"], title=entry["title"], 
                                 content=entry.get("content", ""), plant_height_cm=entry.get("height"), 
                                 plant_name=entry.get("plant", "Allgemein"))

    logger.info("Historische Testdaten erfolgreich generiert.")

def get_live_mock_data():
    """Erzeugt aktuelle Mock-Werte für alle Kategorien."""
    # Sensors
    database.add_sensor_reading("Zelt Klima (Virtual)", "govee_ble", round(24.5, 1), 58.0, 98)
    database.add_sensor_reading("CO2 Sensor (Virtual)", "mqtt_device", 450.0, None, None)
    database.add_sensor_reading("Bodenfeuchte (Virtual)", "tapo_sensor", None, 65.0, 92)
    database.add_sensor_reading("pH Meter (Virtual)", "mqtt_device", 6.2, None, None)
    
    # Plugs
    database.add_energy_reading("Full Spectrum LED (Virtual)", 242.5, 4800, 145000, 231, 1.05)
    database.add_energy_reading("Abluft-Inline (Virtual)", 34.8, 800, 24000, 231, 0.16)
    database.add_energy_reading("Smart Plug (Virtual)", 12.0, 300, 10000, 231, 0.05)
    
    logger.debug("Live-Mockdaten in DB geschrieben.")

if __name__ == "__main__":
    generate_historical_data(days=1)
