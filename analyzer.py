"""
GrowMate – Analyse-Engine (Scientific Advisor)
Logik zur Analyse von Sensordaten und Tagebucheinträgen basierend auf botanischem Wissen.
"""

import sqlite3
import os
import sys
from datetime import datetime

# Pfad-Fix für lokale Module
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
import config
from database import get_latest_sensor_readings, get_diary_entries

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_DB = os.path.join(BASE_DIR, "botany_knowledge.db")

def get_knowledge_connection():
    """Stellt Verbindung zur wissenschaftlichen Datenbank her."""
    if not os.path.exists(KNOWLEDGE_DB):
        return None
    return sqlite3.connect(KNOWLEDGE_DB)

def analyze_plant_needs():
    """
    Analysiert den Zustand der Pflanzen gegen wissenschaftliche Schwellenwerte.
    Berücksichtigt dabei die aktuelle Phase aus den Tagebucheinträgen.
    """
    tips: list[dict[str, str]] = []
    latest_sensors = get_latest_sensor_readings()
    conn = get_knowledge_connection()
    
    # ─── Aktuelle Phase ermitteln ─────────────────────────────────────
    # Wir schauen nach dem aktuellsten Tagebucheintrag, der eine Phase definiert.
    current_phase = "Vegetativ" # Default
    current_species = "Cannabis" # Default (kann später dynamisch pro Pflanze sein)
    
    diary_entries = get_diary_entries(limit=10)
    for entry in diary_entries:
        if entry.get("phase"):
            current_phase = entry["phase"]
            break
    
    # ─── Wissens-Check ────────────────────────────────────────────────
    thresholds = {
        "min_temp": 18.0, "max_temp": 30.0,
        "min_hum": 40.0, "max_hum": 70.0,
        "opt_temp": 24.0, "opt_hum": 55.0
    }
    
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT min_temp, max_temp, min_humidity, max_humidity, optimal_temp, optimal_humidity 
                FROM climate_needs 
                WHERE species = ? AND (phase = ? OR phase IS NULL)
                LIMIT 1
            """, (current_species, current_phase))
            row = cursor.fetchone()
            if row:
                thresholds = {
                    "min_temp": row[0], "max_temp": row[1],
                    "min_hum": row[2], "max_hum": row[3],
                    "opt_temp": row[4], "opt_hum": row[5]
                }
        except Exception as e:
            print(f"Knowledge DB Lookup Error: {e}")
        finally:
            conn.close()

    for s in latest_sensors:
        temp = s.get("temperature")
        hum = s.get("humidity")
        name = s.get("sensor_name", "Haupt-Sensor")
        
        # Temperatur-Check
        if temp:
            if temp > thresholds["max_temp"]:
                tips.append({
                    "type": "warning",
                    "title": f"Hitzestress bei {name}",
                    "message": f"Die Temperatur ({temp:.1f}°C) liegt über dem Maximum für die {current_phase}-Phase ({thresholds['max_temp']}°C).",
                    "scientific_ref": "Ref: Larcher, W. (2003). Physiological Plant Ecology."
                })
            elif temp < thresholds["min_temp"]:
                tips.append({
                    "type": "warning",
                    "title": f"Kältestress bei {name}",
                    "message": f"Die Temperatur ({temp:.1f}°C) ist zu niedrig für optimales Wachstum ({thresholds['min_temp']}°C).",
                    "scientific_ref": "Ref: Larcher, W. (2003)."
                })

        # Feuchtigkeits-Check
        if hum:
            if hum > thresholds["max_hum"]:
                tips.append({
                    "type": "warning",
                    "title": f"Schimmelgefahr ({name})",
                    "message": f"Die Luftfeuchtigkeit ({hum:.1f}%) ist zu hoch für die {current_phase}-Phase. Risiko für Botrytis cinerea!",
                    "scientific_ref": "Ref: Elad, Y. (1997)."
                })
            elif hum < thresholds["min_hum"]:
                tips.append({
                    "type": "info",
                    "title": f"Zu trocken ({name})",
                    "message": f"Die Luftfeuchtigkeit ({hum:.1f}%) liegt unter dem Minimum von {thresholds['min_hum']}%.",
                    "scientific_ref": ""
                })

    # ─── Bewässerungs-Status ──────────────────────────────────────────
    watering_diary = [e for e in diary_entries if e.get("entry_type") == "Bewässerung"]
    if not watering_diary:
        tips.append({
            "type": "info",
            "title": "Bewässerung prüfen",
            "message": "Es wurden noch keine Gieß-Aktivitäten dokumentiert. Prüfe die Erde manuell.",
            "scientific_ref": ""
        })
    else:
        last_date_str = watering_diary[0].get("entry_date")
        if last_date_str:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
            days_ago = (datetime.now() - last_date).days
            if days_ago >= 3:
                tips.append({
                    "type": "info",
                    "title": "Bodenfeuchte prüfen",
                    "message": f"Die letzte Bewässerung liegt {days_ago} Tage zurück.",
                    "scientific_ref": ""
                })

    return tips
