"""
GrowMate – Alerting System
Sendet Benachrichtigungen an Telegram oder Discord via Webhooks.
"""

import logging
import requests
import os

logger = logging.getLogger("growmate.alerts")

def send_webhook_alert(message, webhook_url=None):
    """Sendet eine Nachricht an einen konfigurierten Webhook."""
    url = webhook_url or os.environ.get("ALERT_WEBHOOK_URL")
    
    if not url:
        logger.debug("Kein Webhook konfiguriert, überspringe Alert.")
        return False
        
    try:
        # Erkennung ob Discord oder Telegram (vereinfacht)
        if "discord.com" in url:
            payload = {"content": f"🚨 **GrowMate Alert** 🚨\n{message}"}
        else:
            # Standardmäßig als generischer Text-POST
            payload = {"text": f"GrowMate Alert: {message}"}
            
        res = requests.post(url, json=payload, timeout=5)
        res.raise_for_status()
        logger.info(f"Alert erfolgreich gesendet: {message}")
        return True
    except Exception as e:
        logger.error(f"Fehler beim Senden des Alerts: {e}")
        return False

def check_thresholds(readings, config):
    """Prüft Sensorwerte gegen Schwellenwerte und triggert ggf. Alerts."""
    alerts_triggered = []
    
    # ─── Beispiel: Temperatur ───
    max_temp = config.get("alert_temp_max", 35)
    min_temp = config.get("alert_temp_min", 15)
    
    for r in readings:
        temp = r.get("temperature")
        if temp is not None:
            if temp > max_temp:
                alerts_triggered.append(f"🔥 Kritische Hitze bei {r['sensor_name']}: {temp}°C (Limit: {max_temp}°C)")
            elif temp < min_temp:
                alerts_triggered.append(f"❄️ Kritische Kälte bei {r['sensor_name']}: {temp}°C (Limit: {min_temp}°C)")
                
    # ─── Beispiel: Feuchtigkeit ───
    max_hum = config.get("alert_hum_max", 85)
    if any(r.get("humidity", 0) > max_hum for r in readings if r.get("humidity") is not None):
        alerts_triggered.append(f"💦 Zu hohe Luftfeuchtigkeit (> {max_hum}%)! Schimmelrisiko!")
        
    return alerts_triggered
