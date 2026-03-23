"""
GrowMate – Metrics Engine
Wissenschaftliche Berechnungen für VPD (Vapor Pressure Deficit) und DLI (Daily Light Integral).
"""

import math

def calculate_vpd(temp_c, rh_percent, leaf_temp_offset=-2.0):
    """
    Berechnet den VPD-Wert (Vapor Pressure Deficit) in kPa.
    Assumption: Leaf temp is typically 2°C lower than room temp under LED.
    """
    if temp_c is None or rh_percent is None:
        return None
        
    leaf_temp = temp_c + leaf_temp_offset
    
    # Saturation Vapor Pressure (SVP) in kPa
    # Formula: 0.61078 * exp(17.27 * T / (T + 237.3))
    svp_air = 0.61078 * math.exp((17.27 * temp_c) / (temp_c + 237.3))
    svp_leaf = 0.61078 * math.exp((17.27 * leaf_temp) / (leaf_temp + 237.3))
    
    # Actual Vapor Pressure (AVP) in kPa
    avp_air = svp_air * (rh_percent / 100.0)
    
    # VPD in kPa
    vpd = svp_leaf - avp_air
    return max(0, round(vpd, 3))

def calculate_dli(ppfd, hours_on):
    """
    Berechnet das Daily Light Integral (DLI) in mol/m²/d.
    Formula: (PPFD * seconds_on) / 1,000,000
    """
    if ppfd is None or hours_on is None:
        return None
        
    dli = (ppfd * hours_on * 3600) / 1_000_000
    return round(dli, 2)
