"""
GrowMate – Govee BLE Sensor Scanner
Scannt nach Govee Bluetooth Low Energy Sensoren und parsed die Advertisement-Daten.
Unterstützte Modelle: H5075, H5074, H5179, H5072, H5102
"""

import asyncio
import struct
import logging
from datetime import datetime
from typing import List, Dict, Any, cast, Optional

logger = logging.getLogger("growmate.govee")

# Govee Hersteller-IDs und Modellnamen
GOVEE_COMPANY_IDS = {0xEC88, 0x0001}  # Bekannte Govee Company IDs
GOVEE_NAME_PREFIXES = ("GVH5075", "GVH5074", "GVH5179", "GVH5072", "GVH5102", "Govee_H")


def decode_govee_temp_humidity(raw_value):
    """
    Decodiert den Temperatur-/Feuchtigkeitswert aus den Govee BLE-Daten.
    Format: 3 Bytes, Big-Endian Integer.
    - Temperatur = Wert / 10000 (°C)
    - Luftfeuchtigkeit = (Wert % 1000) / 10 (%)
    - Negativ-Flag im höchsten Bit
    """
    is_negative = raw_value & 0x800000
    raw_value = raw_value & 0x7FFFFF

    temp = raw_value / 10000.0
    humidity = (raw_value % 1000) / 10.0

    if is_negative:
        temp = -temp

    return round(temp, 1), round(humidity, 1)


def parse_govee_advertisement(device, advertisement_data):
    """
    Parsed ein Govee BLE Advertisement.
    Gibt ein Dictionary mit Temperatur, Feuchtigkeit und Batterie zurück oder None.
    """
    name = advertisement_data.local_name or device.name or ""

    # Prüfe ob es ein Govee-Gerät ist
    is_govee = any(name.startswith(prefix) for prefix in GOVEE_NAME_PREFIXES)
    if not is_govee:
        return None

    result = {
        "name": name,
        "address": device.address,
        "rssi": advertisement_data.rssi if hasattr(advertisement_data, 'rssi') else None,
        "temperature": None,
        "humidity": None,
        "battery": None,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Versuche Manufacturer Data zu parsen
    for company_id, data in advertisement_data.manufacturer_data.items():
        try:
            if isinstance(data, (bytes, bytearray)) and len(data) >= 6:
                # Use explicit indexing to satisfy some strict type checkers
                b3, b4, b5 = data[3], data[4], data[5]
                raw_value = (b3 << 16) | (b4 << 8) | b5

                temp, hum = decode_govee_temp_humidity(raw_value)

                # Plausibilitätsprüfung
                if -40 <= temp <= 60 and 0 <= hum <= 100:
                    result["temperature"] = temp
                    result["humidity"] = hum

                # Batterie ist oft das letzte Byte
                if len(data) >= 7:
                    battery = data[6]
                    if 0 <= battery <= 100:
                        result["battery"] = battery
                elif len(data) >= 4:
                    # Alternative Position bei manchen Modellen
                    battery = data[-1]
                    if 0 <= battery <= 100:
                        result["battery"] = battery

        except (IndexError, ValueError) as e:
            logger.debug(f"Fehler beim Parsen der Govee-Daten von {name}: {e}")
            continue

    # Nur zurückgeben wenn wir Daten haben
    if result["temperature"] is not None:
        return result

    return None


async def scan_govee_sensors(duration=10):
    """
    Scannt nach Govee BLE Sensoren für die angegebene Dauer.
    Gibt eine Liste von gefundenen Sensordaten zurück.

    Args:
        duration: Scan-Dauer in Sekunden (Standard: 10)

    Returns:
        Liste von Dictionaries mit Sensordaten
    """
    try:
        from bleak import BleakScanner
    except ImportError:
        logger.error("bleak ist nicht installiert. Bitte 'pip install bleak' ausführen.")
        return []

    found_sensors = {}

    def detection_callback(device, advertisement_data):
        result = parse_govee_advertisement(device, advertisement_data)
        if result:
            # Nur das neueste Ergebnis pro Gerät behalten
            found_sensors[device.address] = result
            logger.info(
                f"Govee Sensor gefunden: {result['name']} "
                f"({result['address']}) - "
                f"{result['temperature']}°C, "
                f"{result['humidity']}% RH"
            )

    try:
        scanner = BleakScanner(detection_callback=detection_callback)
        logger.info(f"Starte BLE-Scan für {duration} Sekunden...")
        await scanner.start()
        await asyncio.sleep(duration)
        await scanner.stop()
        logger.info(f"BLE-Scan abgeschlossen. {len(found_sensors)} Govee-Sensoren gefunden.")
    except Exception as e:
        logger.error(f"Fehler beim BLE-Scan: {e}")

    return list(found_sensors.values())


def scan_govee_sync(duration=10) -> List[Dict[str, Any]]:
    """
    Synchroner Wrapper für scan_govee_sensors.
    Kann direkt aus nicht-async Code aufgerufen werden.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Wir sind bereits in einer async Loop – neuen Thread verwenden
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                def _run_in_thread() -> List[Dict[str, Any]]:
                    # Explicitly cast result to stop Pyright from thinking it's a Coroutine
                    return cast(List[Dict[str, Any]], asyncio.run(scan_govee_sensors(duration)))
                future = pool.submit(_run_in_thread)
                return cast(List[Dict[str, Any]], future.result(timeout=duration + 10))
        else:
            return cast(List[Dict[str, Any]], loop.run_until_complete(scan_govee_sensors(duration)))
    except RuntimeError:
        return cast(List[Dict[str, Any]], asyncio.run(scan_govee_sensors(duration)))
    except Exception as e:
        logger.error(f"Fehler in scan_govee_sync: {e}")
        return []


# ─── Demo / Test ────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Scanne nach Govee BLE Sensoren...")
    results = scan_govee_sync(duration=15)
    if results:
        for sensor in results:
            print(f"\n📡 {sensor['name']} ({sensor['address']})")
            print(f"   🌡️  Temperatur: {sensor['temperature']}°C")
            print(f"   💧 Feuchtigkeit: {sensor['humidity']}%")
            if sensor['battery'] is not None:
                print(f"   🔋 Batterie: {sensor['battery']}%")
    else:
        print("Keine Govee-Sensoren gefunden.")
