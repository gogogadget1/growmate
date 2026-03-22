# 🌿 GrowMate – Start Guide

## 1. Erstmalige Einrichtung (Setup)

Bevor du die App zum ersten Mal startest, stelle sicher, dass alle Abhängigkeiten installiert sind:

```bash
pip install -r requirements.txt
```

### Datenbanken initialisieren
Initialisiere die wissenschaftliche Wissensdatenbank:

```bash
python3 setup_knowledge_db.py
```

## 2. Umgebungsvariablen (.env)

Erstelle eine `.env` Datei im Hauptverzeichnis (falls nicht vorhanden) und trage deine Zugangsdaten ein:

```env
TAPO_EMAIL=deine@email.de
TAPO_PASSWORD=dein_passwort
PLANT_EDIT_PASSWORD=growmate  # Passwort für Archivierung/Änderungen
```

## 3. Anwendung starten

Du kannst die App direkt mit Python starten:

```bash
python3 app.py
```

Oder nutze das bereitgestellte Start-Skript:

```bash
./start.sh
```

Die App ist anschließend unter **http://localhost:5000** erreichbar.

---
*Viel Erfolg bei deinem Grow!*
