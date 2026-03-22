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
    Gibt eine Liste von Tipp-Objekt-Dictionaries zurück.
    """
    tips: list[dict[str, str]] = []
    latest_sensors = get_latest_sensor_readings()
    conn = get_knowledge_connection()
    
    # ─── Schimmelgefahr-Analyse (Botrytis cinerea) ────────────────────
    mold_threshold_rh = 70.0  # Konservativer Schwellenwert
    
    if conn:
        try:
            cursor = conn.cursor()
            # Suche nach maximaler Luftfeuchtigkeit in der Blütephase (Beispielhaft für Cannabis)
            cursor.execute("SELECT max_humidity FROM climate_needs WHERE phase='Blüte' LIMIT 1")
            row = cursor.fetchone()
            if row:
                mold_threshold_rh = row[0]
        except Exception as e:
            print(f"Knowledge DB Lookup Error: {e}")
        finally:
            conn.close()

    for s in latest_sensors:
        temp = s.get("temperature")
        hum = s.get("humidity")
        name = s.get("sensor_name", "Haupt-Sensor")
        
        if hum and hum > mold_threshold_rh:
            tips.append({
                "type": "warning",
                "title": f"Schimmelgefahr bei {name}",
                "message": f"Die Luftfeuchtigkeit liegt bei {hum:.1f}%. Ab {mold_threshold_rh}% steigt das Risiko für Botrytis cinerea (Grauschimmel) massiv.",
                "scientific_ref": "Ref: Elad, Y. (1997). Effect of environmental factors on Botrytis cinerea."
            })
            
            # Lüftungs-Blueprint Logic (Placeholder für Tipps)
            pass
            
        if temp and temp > 30:
            tips.append({
                "type": "warning",
                "title": "Hitzestress",
                "message": f"Die Temperatur ({temp:.1f}°C) beeinträchtigt die Photosynthese-Effizienz.",
                "scientific_ref": "Ref: Larcher, W. (2003). Physiological Plant Ecology."
            })

    # ─── Bewässerungs-Status ──────────────────────────────────────────
    diary = get_diary_entries(limit=1, entry_type="Bewässerung")
    if not diary:
        tips.append({
            "type": "info",
            "title": "Bewässerung fällig?",
            "message": "Es wurden noch keine Gieß-Aktivitäten dokumentiert.",
            "scientific_ref": ""
        })
    else:
        last_date_str = diary[0].get("entry_date")
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
