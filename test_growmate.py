#!/usr/bin/env python3
"""
GrowMate Automated Health Check
Testet alle wesentlichen API-Endpoints der GrowMate-Anwendung.
"""

import urllib.request
import urllib.error
import urllib.parse
import json
import sys

BASE_URL = "http://localhost:5002"

ENDPOINTS = [
    ("/api/status", "GET"),
    ("/api/config", "GET"),
    ("/api/diagnostics", "GET"),
    ("/api/sensors/current", "GET"),
    ("/api/energy/current", "GET"),
    ("/api/devices", "GET"),
    ("/api/diary", "GET"),
    ("/api/plants", "GET"),
    ("/api/admin/config", "GET")
]

def run_tests():
    print("Starte GrowMate Auto-Test...\n")
    errors = []
    
    for endpoint, method in ENDPOINTS:
        url = f"{BASE_URL}{endpoint}"
        req = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                status = response.getcode()
                body = response.read().decode('utf-8')
                
                if status == 200:
                    try:
                        data = json.loads(body)
                        if data.get("success", False):
                            print(f"[OK] {endpoint} (200)")
                        else:
                            print(f"[WARN] {endpoint} (200) - Success=False: {data}")
                            errors.append(f"{endpoint} meldete success=False")
                    except json.JSONDecodeError:
                        print(f"[ERROR] {endpoint} - Ungültiges JSON")
                        errors.append(f"{endpoint} lieferte kein gültiges JSON")
                else:
                    print(f"[ERROR] {endpoint} - HTTP {status}")
                    errors.append(f"{endpoint} antwortete mit HTTP {status}")
                    
        except urllib.error.URLError as e:
            print(f"[ERROR] {endpoint} - Netzwerkfehler: {e}")
            errors.append(f"{endpoint} nicht erreichbar: {e}")
        except Exception as e:
            print(f"[ERROR] {endpoint} - Interner Fehler: {e}")
            errors.append(f"{endpoint} Fehler: {e}")

    print("\nTest-Zusammenfassung:")
    if not errors:
        print("✅ Alle getesteten Endpoints funktionieren einwandfrei.")
        sys.exit(0)
    else:
        print("❌ Folgende Fehler sind aufgetreten:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
