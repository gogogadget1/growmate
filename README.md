Titel & Vision

🌱 GrowMate
Autarkes Botanik-Monitoring & Edge-AI System

GrowMate ist ein Local-First-System zur Überwachung und Steuerung von Pflanzenumgebungen. Es wurde mit einem klaren Fokus auf maximale Datensicherheit und Unabhängigkeit entwickelt. Anstatt Umgebungsdaten an externe Cloud-Anbieter zu senden, verarbeitet GrowMate alle Metriken lokal. Eine integrierte Vektor-Engine (ONNX) vergleicht Sensordaten in Echtzeit mit wissenschaftlichen Botanik-Regeln, um proaktiv vor Stressfaktoren zu warnen.

Kernfunktionen (Features)

Lokale Edge-AI: Nutzt eine leichtgewichtige, token-effiziente ONNX-Vektordatenbank, um anhand von über 150 pflanzenspezifischen Parametern Warnungen auszugeben (z. B. Hitzestress, VPD-Anomalien). Kein OpenAI-Key, keine Internetverbindung zur Laufzeit nötig.

Radikale Autarkie: Bluetooth Low Energy (für Govee-Klimasensoren) und lokale IP-Steuerung (für Tapo-Steckdosen) ersetzen den Zwang zu Hersteller-Clouds.

Wissenschaftliches Monitoring: Berechnet im Hintergrund kritische Werte wie das Vapor Pressure Deficit (VPD) und den Daily Light Integral (DLI).

Sichere Architektur: Strikte Trennung von sensiblem Code und Credentials (via .env). Die Datenbank läuft auf einer gehärteten SQLite-Instanz (WAL-Modus), die auf Langlebigkeit bei Dauerbetrieb (z. B. auf SD-Karten) ausgelegt ist.

Systemanforderungen & Installation

Mache hier klar, dass das System durch seinen modularen Aufbau überall läuft – vom Raspberry Pi bis zum Windows ARM64-Server.
Gib die genauen Befehle für die Einrichtung der virtuellen Umgebung an (python3 -m venv .venv, pip install -r requirements.txt).
Erwähne fett, dass die .env.example in .env umbenannt und mit eigenen Zugangsdaten gefüllt werden muss.
