"""
GrowMate – Tapo Geräte-Steuerung
Steckdosen ein-/ausschalten und Energieverbrauch auslesen über PyP100.
"""

import logging
from datetime import datetime
import asyncio
from tapo import ApiClient
from typing import Any, List, Dict, Tuple, cast, Optional
import config

logger = logging.getLogger("growmate.tapo")


def get_plug_status(ip, tapo_email, tapo_password):
    """Holt Status einer P100/P110 Steckdose via tapo"""
    async def _async_get_plug_status():
        try:
            client = ApiClient(tapo_email, tapo_password)
            try:
                device = await client.p110(ip)
                info = await device.get_device_info()
                has_energy = True
            except Exception:
                device = await client.p100(ip)
                info = await device.get_device_info()
                has_energy = False
                
            info_dict = info.to_dict()
            result = {
                "success": True,
                "device_on": info.device_on if hasattr(info, 'device_on') else getattr(info, 'device_on', False),
                "ip": ip,
                "info": info_dict
            }
            
            if has_energy:
                try:
                    energy = await device.get_energy_usage()
                    result["power_w"] = getattr(energy, 'current_power', 0) / 1000.0 if getattr(energy, 'current_power', None) is not None else 0.0
                    result["energy_today_wh"] = getattr(energy, 'today_energy', 0)
                    result["energy_month_wh"] = getattr(energy, 'month_energy', 0)
                except:
                    pass
                    
            return result
        except Exception as e:
            return {"success": False, "error": str(e), "ip": ip}
            
    return _run_async(_async_get_plug_status())


async def test_tapo_credentials_async(email, password, ip=None):
    """Testet die Tapo Zugangsdaten asynchron via tapo library"""
    try:
        client = ApiClient(email, password)
        if ip:
            device = await client.p100(ip)
            await device.get_device_info()
        return {"success": True, "message": "Zugangsdaten gültig"}
    except Exception as e:
        return {"success": False, "message": str(e)}

def test_tapo_credentials(email, password, ip=None):
    """Synchroner Wrapper zum Testen von Tapo Credentials"""
    return _run_async(test_tapo_credentials_async(email, password, ip))


async def scan_tapo_hubs_async(email, password, hubs):
    """
    Scans Tapo Hubs (zum Beispiel H100) and retrieves data for connected sensors
    like the T300 Water Leak Sensor.
    """
    results = []
    client = ApiClient(email, password)
    
    for hub_cfg in hubs:
        ip = hub_cfg.get('ip')
        name = hub_cfg.get('name')
        try:
            hub = await client.h100(ip)
            # Fetch connected devices/sensors from the hub
            hub_info = await hub.get_device_info()
            child_devices = await hub.get_child_device_list()
            
            # Analyze child devices
            for child in child_devices:
                device_id = child.device_id
                child_info = child.to_dict()
                
                # Check for Water Leak Sensor (T300) and Temp/Hum (T315)
                is_leak = False
                temp = None
                hum = None
                
                category = child_info.get("category", "")
                
                if "water-leak-sensor" in category:
                    is_leak = child_info.get("water_leak_status") != "water_dry"
                elif "temp" in category:
                    temp = child_info.get("current_temp")
                    hum = child_info.get("current_humidity")
                    
                sensor_data = {
                    "sensor_name": child_info.get('nickname', category),
                    "type": "tapo_sensor",
                    "category": category,
                    "is_leak": is_leak,
                    "temperature": temp,
                    "humidity": hum,
                    "battery": child_info.get("battery_percentage", None),
                    "at_low_battery": child_info.get("at_low_battery", False),
                    "online": child_info.get("status") == "online",
                    "raw_data": child_info
                }
                results.append(sensor_data)
        except Exception as e:
            print(f"Error scanning hub {name} ({ip}): {e}")
            
    return results

def scan_tapo_hubs_sync(email, password, hubs):
    if not email or not password or not hubs:
        return []
    return _run_async(scan_tapo_hubs_async(email, password, hubs))


async def _get_device_async(ip: str, email: str, password: str) -> Tuple[Any, Optional[str]]:
    client = ApiClient(email, password)
    try:
        device = await client.p110(ip)
        await device.get_device_info() # Test connection
        return device, "P110"
    except Exception:
        try:
            device = await client.p100(ip)
            await device.get_device_info() # Test connection
            return device, "P100"
        except Exception as e:
            logger.error(f"Verbindung zu Tapo-Steckdose {ip} fehlgeschlagen: {e}")
            return None, None

import concurrent.futures

# Globaler Executor für asynchrone Aufrufe in synchronem Kontext
# Verhindert Thread-Erschöpfung durch Wiederverwendung
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)

def _run_async(coro):
    """
    Sicherer Wrapper, um asynchrone Coroutinen in Threads (Flask/Scheduler) auszuführen.
    Verhindert 'Event loop is running' Fehler und Thread-Erschöpfung.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # In einem laufenden Loop (z.B. innerhalb von Gunicorn Threads)
            # führen wir die Coroutine in einem separaten Thread in einem neuen Loop aus.
            # Wir nutzen den globalen Executor zur Ressourcenschonung.
            from typing import cast, Callable, Any
            def _thread_worker() -> Any:
                return asyncio.run(coro)
                
            future = _executor.submit(cast(Callable[..., Any], _thread_worker))
            return future.result(timeout=20)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        # Kein Loop vorhanden
        return asyncio.run(coro)
    except Exception as e:
        logger.error(f"Async-Bridge Error: {e}")
        return {"success": False, "error": str(e)}

async def _turn_on_async(ip, email, password):
    res = await _get_device_async(ip, email, password)
    device, model = res
    if device:
        try:
            await device.on()
            logger.info(f"Tapo {model} ({ip}) eingeschaltet.")
            return {"success": True, "message": f"Steckdose {ip} eingeschaltet"}
        except Exception as e:
            logger.error(f"Fehler beim Einschalten von {ip}: {e}")
            return {"success": False, "message": str(e)}
    return {"success": False, "message": "Verbindung fehlgeschlagen"}

def turn_on(ip, email, password):
    return _run_async(_turn_on_async(ip, email, password))


async def _turn_off_async(ip, email, password):
    res = await _get_device_async(ip, email, password)
    device, model = res
    if device:
        try:
            await device.off()
            logger.info(f"Tapo {model} ({ip}) ausgeschaltet.")
            return {"success": True, "message": f"Steckdose {ip} ausgeschaltet"}
        except Exception as e:
            logger.error(f"Fehler beim Ausschalten von {ip}: {e}")
            return {"success": False, "message": str(e)}
    return {"success": False, "message": "Verbindung fehlgeschlagen"}

def turn_off(ip, email, password):
    return _run_async(_turn_off_async(ip, email, password))


async def _get_device_info_async(ip, email, password):
    res = await _get_device_async(ip, email, password)
    device, model = res
    if device:
        try:
            info = await device.get_device_info()
            on_state = getattr(info, 'device_on', False)
            nickname = getattr(info, 'nickname', "Unbekannt")
            return {
                "success": True,
                "model": model,
                "device_on": on_state,
                "nickname": nickname,
                "ip": ip,
                "signal_level": getattr(info, 'signal_level', 0),
                "on_time": getattr(info, 'on_time', 0),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Geräteinfo von {ip}: {e}")
            return {"success": False, "message": str(e)}
    return {"success": False, "message": "Verbindung fehlgeschlagen"}

def get_device_info(ip, email, password):
    return _run_async(_get_device_info_async(ip, email, password))


async def _get_energy_usage_async(ip, email, password):
    res = await _get_device_async(ip, email, password)
    device, model = res
    if device and model == "P110":
        try:
            energy = await device.get_energy_usage()
            return {
                "success": True,
                "power_w": getattr(energy, 'current_power', 0) / 1000.0,  # mW -> W
                "energy_today_wh": getattr(energy, 'today_energy', 0),
                "energy_month_wh": getattr(energy, 'month_energy', 0),
                "energy_runtime_min": getattr(energy, 'today_runtime', 0),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des Energieverbrauchs von {ip}: {e}")
            return {"success": False, "message": str(e)}
    return {"success": False, "message": "P110 Funktion oder Verbindung fehlgeschlagen"}

def get_energy_usage(ip, email, password):
    return _run_async(_get_energy_usage_async(ip, email, password))


def toggle_device(ip, email, password):
    """Schaltet eine Steckdose um (toggle)."""
    info = get_device_info(ip, email, password)
    if info and info.get("success"):
        if info.get("device_on"):
            return turn_off(ip, email, password)
        else:
            return turn_on(ip, email, password)
    return info


def scan_tapo_plugs(devices_config, email, password):
    """
    Scannt alle konfigurierten Tapo-Steckdosen und gibt deren Status zurück.

    Args:
        devices_config: Liste von Geräte-Configs mit 'ip' und 'name'
        email: Tapo Account E-Mail
        password: Tapo Account Passwort

    Returns:
        Liste von Geräte-Status-Dictionaries
    """
    from typing import Any
    results: list[dict[str, Any]] = []
    for device in devices_config:
        ip = device.get("ip", "")
        name = device.get("name", ip)

        if not ip:
            continue

        info = get_device_info(ip, email, password)
        if info and isinstance(info, dict) and info.get("success"):
            # Cast for type checker safety
            status_dict = cast(Dict[str, Any], info)
            status_dict["configured_name"] = name
            # Versuche auch Energiedaten zu holen
            energy = get_energy_usage(ip, email, password)
            if energy and isinstance(energy, dict) and energy.get("success"):
                energy_dict = cast(Dict[str, Any], energy)
                status_dict.update(energy_dict)
            results.append(status_dict)
        else:
            msg = "Nicht erreichbar"
            if info and isinstance(info, dict):
                msg = info.get("message", msg)
                
            results.append({
                "success": False,
                "configured_name": name,
                "ip": ip,
                "message": msg,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    return results


# ─── Demo / Test ────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Tapo Geräte-Test")
    print("=" * 40)
    print("Nutzung: Passe die IP, E-Mail und Passwort an und führe dieses Skript aus.")
    print()
    print('Beispiel:')
    print('  from sensors.tapo_devices import get_device_info')
    print('  info = get_device_info("192.168.1.100", "email@example.com", "password")')
    print('  print(info)')
