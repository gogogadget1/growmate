"""
GrowMate – Setup Knowledge Database
Initialisiert botany_knowledge.db mit wissenschaftlichen Daten zu Pflanzenkrankheiten, Schädlingen und Klimabedürfnissen.
"""

import sqlite3
import os

DB_PATH = "botany_knowledge.db"

def setup():
    if os.path.exists(DB_PATH):
        print(f"Datenbank {DB_PATH} existiert bereits. Überspringe Initialisierung.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Effiziente Indizierung für große Datenmengen (bis 8GB konzipiert)
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS diseases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            symptoms TEXT,
            causes TEXT,
            prevention TEXT,
            scientific_refs TEXT
        );

        CREATE TABLE IF NOT EXISTS climate_needs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            species TEXT NOT NULL,
            phase TEXT NOT NULL,
            min_temp REAL,
            max_temp REAL,
            min_humidity REAL,
            max_humidity REAL,
            scientific_refs TEXT,
            UNIQUE(species, phase)
        );

        CREATE TABLE IF NOT EXISTS pests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            treatment TEXT,
            scientific_refs TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_climate_species ON climate_needs(species);
        CREATE INDEX IF NOT EXISTS idx_disease_name ON diseases(name);
    """)

    # Wissenschaftliche Referenzdaten (Simulation fundierter Quellen)
    # Beispiel Botrytis (Grauschimmel)
    cursor.execute("""
        INSERT OR IGNORE INTO diseases (name, symptoms, causes, prevention, scientific_refs)
        VALUES (
            'Botrytis cinerea (Grauschimmel)',
            'Graue, pelzige Beläge auf Blüten und Blättern, weiche Stellen.',
            'Hohe Luftfeuchtigkeit (>60%), mangelnde Luftzirkulation, stehende Nässe.',
            'Luftfeuchtigkeit senken, Umluft erhöhen, befallene Stellen großflächig entfernen.',
            'Referenz: Elad, Y., et al. (2016). Botrytis - the Fungus, the Pathogen and its Management in Agricultural Systems.'
        )
    """)

    # Klimabedürfnisse (Blütephase)
    cursor.execute("""
        INSERT OR IGNORE INTO climate_needs (species, phase, min_temp, max_temp, min_humidity, max_humidity, scientific_refs)
        VALUES (
            'Cannabis sativa', 
            'Blüte', 
            18.0, 26.0, 40.0, 55.0,
            'Referenz: Chandra, S., et al. (2017). Cannabis sativa L. - Botany and Biotechnology.'
        )
    """)

    # Klimabedürfnisse (Wachstumsphase / Vegetation)
    cursor.execute("""
        INSERT OR IGNORE INTO climate_needs (species, phase, min_temp, max_temp, min_humidity, max_humidity, scientific_refs)
        VALUES (
            'Cannabis sativa', 
            'Vegetation', 
            20.0, 28.0, 50.0, 70.0,
            'Referenz: Chandra, S., et al. (2017).'
        )
    """)

    # Klimabedürfnisse (Sämling / Seedling)
    cursor.execute("""
        INSERT OR IGNORE INTO climate_needs (species, phase, min_temp, max_temp, min_humidity, max_humidity, scientific_refs)
        VALUES (
            'Cannabis sativa', 
            'Sämling', 
            22.0, 26.0, 65.0, 80.0,
            'Referenz: Chandra, S., et al. (2017).'
        )
    """)

    conn.commit()
    conn.close()
    print(f"Datenbank {DB_PATH} wurde erfolgreich initialisiert.")

if __name__ == "__main__":
    setup()
