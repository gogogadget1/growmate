"""
GrowMate – Datenbank
SQLite Schema und Helfer-Funktionen für Sensordaten, Energiedaten und Tagebuch.
"""

import os
import sys
import sqlite3
# Pfad-Fix für lokale Module
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

import config
from datetime import datetime, timedelta


import time
import logging
from functools import wraps

def db_retry(max_retries=5, initial_delay=0.1, backoff_factor=2.0):
    """Self-Repair Decorator für Datenbank-Schreibzugriffe bei Locks."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                        logging.getLogger("growmate.db").warning(
                            f"SQLite Lock in {func.__name__} (Versuch {attempt+1}/{max_retries}). "
                            f"Self-Repair: Warte {delay:.2f}s..."
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        raise
        return wrapper
    return decorator


def get_db():
    """Erstellt eine neue Datenbankverbindung."""
    conn = sqlite3.connect(config.DB_PATH, timeout=10.0) # Self-Repair: Native timeout integration
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@db_retry()
def init_db():
    """Erstellt alle Tabellen falls nicht vorhanden."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS sensor_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sensor_name TEXT NOT NULL,
            sensor_type TEXT NOT NULL,
            temperature REAL,
            humidity REAL,
            battery INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS energy_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL,
            power_w REAL,
            energy_today_wh REAL,
            energy_month_wh REAL,
            voltage_v REAL,
            current_a REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS diary_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_date DATE NOT NULL,
            entry_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT,
            plant_height_cm REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_sensor_readings_timestamp
            ON sensor_readings(timestamp);
        CREATE INDEX IF NOT EXISTS idx_sensor_readings_name
            ON sensor_readings(sensor_name);
        CREATE INDEX IF NOT EXISTS idx_energy_readings_timestamp
            ON energy_readings(timestamp);
        CREATE INDEX IF NOT EXISTS idx_diary_entries_date
            ON diary_entries(entry_date);

        CREATE TABLE IF NOT EXISTS plants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            is_archived INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    conn.close()


# ─── Sensor Readings ────────────────────────────────────────────────

@db_retry()
def add_sensor_reading(sensor_name, sensor_type, temperature, humidity, battery=None):
    """Speichert eine Sensor-Messung."""
    conn = get_db()
    conn.execute(
        """INSERT INTO sensor_readings (sensor_name, sensor_type, temperature, humidity, battery)
           VALUES (?, ?, ?, ?, ?)""",
        (sensor_name, sensor_type, temperature, humidity, battery)
    )
    conn.commit()
    conn.close()


def get_latest_sensor_readings():
    """Gibt die letzten Messwerte pro Sensor zurück."""
    conn = get_db()
    rows = conn.execute("""
        SELECT sr.*
        FROM sensor_readings sr
        INNER JOIN (
            SELECT sensor_name, MAX(timestamp) as max_ts
            FROM sensor_readings
            GROUP BY sensor_name
        ) latest ON sr.sensor_name = latest.sensor_name AND sr.timestamp = latest.max_ts
        ORDER BY sr.sensor_name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sensor_history(sensor_name=None, hours=24):
    """Gibt Sensor-Historiedaten zurück."""
    conn = get_db()
    since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    if sensor_name:
        rows = conn.execute(
            """SELECT * FROM sensor_readings
               WHERE sensor_name = ? AND timestamp >= ?
               ORDER BY timestamp ASC""",
            (sensor_name, since)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM sensor_readings
               WHERE timestamp >= ?
               ORDER BY timestamp ASC""",
            (since,)
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


# ─── Energy Readings ────────────────────────────────────────────────

@db_retry()
def add_energy_reading(device_name, power_w, energy_today_wh=None,
                       energy_month_wh=None, voltage_v=None, current_a=None):
    """Speichert eine Energie-Messung."""
    conn = get_db()
    conn.execute(
        """INSERT INTO energy_readings
           (device_name, power_w, energy_today_wh, energy_month_wh, voltage_v, current_a)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (device_name, power_w, energy_today_wh, energy_month_wh, voltage_v, current_a)
    )
    conn.commit()
    conn.close()


def get_latest_energy_readings():
    """Gibt die letzten Energiewerte pro Gerät zurück."""
    conn = get_db()
    rows = conn.execute("""
        SELECT er.*
        FROM energy_readings er
        INNER JOIN (
            SELECT device_name, MAX(timestamp) as max_ts
            FROM energy_readings
            GROUP BY device_name
        ) latest ON er.device_name = latest.device_name AND er.timestamp = latest.max_ts
        ORDER BY er.device_name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_energy_history(device_name=None, hours=24):
    """Gibt Energie-Historiedaten zurück."""
    conn = get_db()
    since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    if device_name:
        rows = conn.execute(
            """SELECT * FROM energy_readings
               WHERE device_name = ? AND timestamp >= ?
               ORDER BY timestamp ASC""",
            (device_name, since)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM energy_readings
               WHERE timestamp >= ?
               ORDER BY timestamp ASC""",
            (since,)
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


# ─── Diary Entries ──────────────────────────────────────────────────

@db_retry()
def add_diary_entry(entry_date, entry_type, title, content="", plant_height_cm=None, plant_name="Allgemein", 
                    plant_phase=None, health_status=None, water_amount_ml=None, ph_value=None):
    """Erstellt einen neuen Tagebucheintrag."""
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO diary_entries (entry_date, entry_type, title, content, plant_height_cm, plant_name, 
                                     plant_phase, health_status, water_amount_ml, ph_value)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (entry_date, entry_type, title, content, plant_height_cm, plant_name, 
         plant_phase, health_status, water_amount_ml, ph_value)
    )
    entry_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return entry_id


def get_diary_entries(limit=50, offset=0, entry_type=None, plant_name=None, show_archived=False):
    """Gibt Tagebucheinträge zurück, optional gefiltert nach Typ und Pflanze."""
    conn = get_db()
    query = "SELECT * FROM diary_entries WHERE 1=1"
    params = []

    if entry_type:
        query += " AND entry_type = ?"
        params.append(entry_type)
    
    if plant_name:
        query += " AND plant_name = ?"
        params.append(plant_name)

    # Filter archived plants out if show_archived is False
    if not show_archived:
        query += " AND plant_name NOT IN (SELECT name FROM plants WHERE is_archived = 1)"

    query += " ORDER BY entry_date DESC, created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_diary_entry(entry_id):
    """Gibt einen einzelnen Tagebucheintrag zurück."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM diary_entries WHERE id = ?", (entry_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


@db_retry()
def update_diary_entry(entry_id, **kwargs):
    """Aktualisiert einen Tagebucheintrag."""
    allowed = {"entry_date", "entry_type", "title", "content", "plant_height_cm", "plant_name", 
               "plant_phase", "health_status", "water_amount_ml", "ph_value"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False

    updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [entry_id]

    conn = get_db()
    conn.execute(f"UPDATE diary_entries SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return True


@db_retry()
def delete_diary_entry(entry_id):
    """Löscht einen Tagebucheintrag."""
    conn = get_db()
    conn.execute("DELETE FROM diary_entries WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()


def get_plant_height_history():
    """Gibt die Pflanzenhöhen-Historie zurück."""
    conn = get_db()
    rows = conn.execute(
        """SELECT entry_date, plant_height_cm, plant_name
           FROM diary_entries
           WHERE plant_height_cm IS NOT NULL
           ORDER BY entry_date ASC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_plants(show_archived=False):
    """Gibt alle Pflanzenprofile zurück."""
    conn = get_db()
    if show_archived:
        rows = conn.execute("SELECT * FROM plants ORDER BY name ASC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM plants WHERE is_archived = 0 ORDER BY name ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@db_retry()
def archive_plant(plant_id, archived=True):
    """Archiviert oder de-archiviert eine Pflanze."""
    conn = get_db()
    conn.execute("UPDATE plants SET is_archived = ? WHERE id = ?", (1 if archived else 0, plant_id))
    conn.commit()
    conn.close()
    return True

