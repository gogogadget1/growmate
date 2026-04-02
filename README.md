# 🌱 GrowMate v2.1
**Autarkes Botanik-Monitoring & Edge-AI System**

GrowMate ist ein Local-First-System zur iterativen Überwachung und Automation von Pflanzenumgebungen. Es wurde mit einem kompromisslosen Fokus auf **maximale Datensicherheit und Unabhängigkeit** entwickelt. Anstatt Umgebungsdaten an externe Cloud-Anbieter zu senden, verarbeitet GrowMate alle Metriken lokal. Eine integrierte Vektor-Engine (ONNX) vergleicht Sensordaten in Echtzeit mit wissenschaftlichen Botanik-Regeln, um proaktiv vor Stressfaktoren zu warnen.

---

## ✨ Kernfunktionen

*   🧠 **Lokale Edge-AI (RAG):** Nutzt eine leichtgewichtige, token-effiziente ONNX-Vektordatenbank, um anhand pflanzenspezifischer Parameter dynamische Warnungen auszugeben (z. B. Hitzestress, Luftfeuchtigkeit). Vollständig offline – kein OpenAI-Key zur Laufzeit nötig!
*   🔒 **Radikale Autarkie (Local-First):** Verwendet *Bluetooth Low Energy* für passive Govee-Klimasensoren und die lokale Netzwerk-API (`PyP100`) für Tapo-Hubs und -Steckdosen. Null Hersteller-Cloud-Zwang!
*   🔬 **Wissenschaftliches Monitoring:** Berechnet im Hintergrund hochpräzise agrarwissenschaftliche Werte wie das Vapor Pressure Deficit (**VPD**) und die notwendige Beleuchtungsstärke.
*   🛡️ **Sichere Architektur:** Konsequente Trennung von Logic und Credentials via `.env`. Die lokale Telemetrie-Datenbank läuft auf einer gehärteten SQLite-Instanz (WAL-Modus) für Langlebigkeit bei intensivem I/O-Dauerbetrieb (perfekt für SD-Karten & Edge Devices).

---

## 🛠️ Systemanforderungen & Kompatibilität

Dank des strikt modularen Aufbaus in Python und Flask läuft GrowMate plattformunabhängig:
*   **Linux Edge-Devices:** Raspberry Pi, Kubuntu, Debian.
*   **Windows Server:** Kompatibel mit traditionellem x64 sowie modernem **Windows 11 ARM64** (z.B. Snapdragon Galaxy Books).
*   **Hintergrund-Betrieb:** Unterstützt den vollkommen unsichtbaren Headless-Betrieb via `.vbs` oder PowerShell `WMI Win32_Process`-Injektion unter Windows.

---

## 🚀 Installation & Setup

### 1. Repository Klonen
```bash
git clone -b growmate-v2.1 https://github.com/gogogadget1/growmate.git
cd growmate
```

### 2. Virtuelle Umgebung einrichten
Wir empfehlen strikt die Nutzung einer virtuellen Umgebung, um Abhängigkeiten des Systems isoliert zu halten.
```bash
# Unter Linux/macOS:
python3 -m venv venv
source venv/bin/activate

# Unter Windows (PowerShell):
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Abhängigkeiten installieren
```bash
pip install -r requirements.txt
```

### 4. Konfiguration (WICHTIG!)
Die Zugangsdaten für Netzwerkgeräte (wie Tapo) werden **nicht** in die `config.json` geschrieben, sondern durch Umgebungsvariablen gesichert:

1.  Kopieren Sie die Vorlagendatei:
    ```bash
    cp .env.example .env
    ```
2.  Öffnen Sie die `.env` und tragen Sie Ihre Anmeldedaten ein (z.B. Ihre Tapo-E-Mail und das Passwort).
3.  Die `config.json` steuert lediglich die Topologie der Sensoren und das Timer-Intervall.

---

## 🖥 Bedienung

Starten Sie die Applikation einfach über den Haupteinstiegspunkt:
```bash
python app.py
```
Sobald der Server gestartet ist, rufen Sie das Web-Dashboard lokal im Netzwerk auf:
👉 **http://127.0.0.1:5000** oder die Host-IP Ihres Servers.

*(Hinweis für Windows Server: Um GrowMate vor Verbindungsabbrüchen oder falschen SSH-Sessions zu schützen, empfehlen wir, die Applikation über die Windows Aufgabenplanung oder autarke WMI-Skripte als Hintergrunddienst zu persistieren.)*
