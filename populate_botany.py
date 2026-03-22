import sqlite3
import os

DB_NAME = "botany_knowledge.db"

def populate():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Clean tables for fresh data
    cursor.execute("DELETE FROM climate_needs")
    cursor.execute("DELETE FROM diseases")
    cursor.execute("DELETE FROM pests")
    
    # 1. Climate Needs (Cannabis example as requested/common)
    climate_data = [
        # Species, Phase, MinTemp, MaxTemp, MinHum, MaxHum, OptTemp, OptHum
        ('Cannabis', 'Keimung', 20.0, 25.0, 70.0, 85.0, 23.0, 75.0),
        ('Cannabis', 'Sämling', 20.0, 28.0, 60.0, 75.0, 24.0, 65.0),
        ('Cannabis', 'Vegetativ', 18.0, 30.0, 50.0, 70.0, 25.0, 55.0),
        ('Cannabis', 'Blüte', 18.0, 28.0, 35.0, 50.0, 24.0, 45.0),
        
        ('Tomate', 'Vegetativ', 18.0, 27.0, 50.0, 70.0, 22.0, 60.0),
        ('Tomate', 'Blüte', 18.0, 26.0, 55.0, 65.0, 23.0, 60.0),
        
        ('Chili', 'Vegetativ', 20.0, 32.0, 50.0, 75.0, 26.0, 60.0),
        ('Chili', 'Blüte', 20.0, 30.0, 50.0, 65.0, 26.0, 55.0),
    ]
    cursor.executemany("""
        INSERT INTO climate_needs (species, phase, min_temp, max_temp, min_humidity, max_humidity, optimal_temp, optimal_humidity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, climate_data)
    
    # 2. Diseases
    disease_data = [
        ('Botrytis (Grauschimmel)', 'Braune Flecken, grauer pelziger Belag auf Blüten/Blättern.', 'Hohe Luftfeuchtigkeit (>60%) und stehende Luft.', 'Luftfeuchtigkeit senken, Umluft erhöhen, befallene Stellen großzügig entfernen.'),
        ('Mehltau (Echter/Falscher)', 'Weißer Staubbelag auf den Blattoberseiten.', 'Feucht-warme Bedingungen, schlechte Belüftung.', 'Umluft verbessern, pH-Wert der Blattoberfläche erhöhen (Backpulver-Lösung).'),
    ]
    cursor.executemany("INSERT INTO diseases (name, symptoms, cause, prevention) VALUES (?, ?, ?, ?)", disease_data)
    
    # 3. Pests
    pest_data = [
        ('Spinnmilben', 'Winzige helle Punkte auf Blättern, feine Gespinste unter den Blättern.', 'Raubmilben einsetzen, Neemöl-Spritzen, Luftfeuchtigkeit kurzzeitig erhöhen.'),
        ('Trauermücken', 'Kleine schwarze Mücken fliegen über der Erde, Larven fressen Wurzeln.', 'Nematoden (SF) gießen, Gelbtafeln aufstellen, Erde oberflächlich antrocknen lassen.'),
        ('Thripse', 'Silbrige glänzende Flecken auf Blättern, schwarze Kotpunkte.', 'Blaufallen, Neemöl, Raubwanzen.'),
    ]
    cursor.executemany("INSERT INTO pests (name, symptoms, treatment) VALUES (?, ?, ?)", pest_data)
    
    conn.commit()
    print("Botany Knowledge Database erfolgreich mit wissenschaftlichen Daten befüllt.")
    conn.close()

if __name__ == "__main__":
    populate()
