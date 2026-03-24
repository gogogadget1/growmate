"""
GrowMate – Analyse-Engine (ONNX Vector Advisor)
═══════════════════════════════════════════════════════════════════════════════
Semantische Suche via ONNX + vorberechnete Vektoren.
Kein ChromaDB, kein PyTorch, kein Internet zur Laufzeit.

Abhängigkeiten (leichtgewichtig):
    pip install onnxruntime tokenizers numpy

Benötigte Dateien im Projektverzeichnis:
    model/model.onnx        – ONNX-Modell (Download-Befehl in README)
    model/tokenizer.json    – Tokenizer-Konfiguration
    knowledge_vectors.json  – Vorberechnete Vektoren (via build_vectors.py)

Fallback-Kaskade (automatisch, kein Eingriff nötig):
    1. ONNX + knowledge_vectors.json  ← Normalfall
    2. Nur Fallback-Regelengine        ← wenn Modell oder Vektordatei fehlen

Schnittstelle nach außen UNVERÄNDERT:
    analyzer.analyze_plant_needs() → list[dict]
    Felder: type | title | message | scientific_ref
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import math
import os
import sys
import logging
import threading
import time
from datetime import datetime

import numpy as np

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
import config
from database import get_latest_sensor_readings, get_diary_entries

log = logging.getLogger("growmate.analyzer")

# ─── Pfade ────────────────────────────────────────────────────────────────────
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
VECTORS_PATH    = os.path.join(BASE_DIR, "knowledge_vectors.json")
MODEL_PATH      = os.path.join(BASE_DIR, "model", "model.onnx")
TOKENIZER_PATH  = os.path.join(BASE_DIR, "model", "tokenizer.json")

# ─── Analyse-Cache ────────────────────────────────────────────────────────────
# Verhindert ONNX-Queries bei jedem Frontend-Poll. TTL: 60s. Thread-safe.
_CACHE_TTL_SECONDS = 60
_cache_result: list = []
_cache_timestamp: float = 0.0
_cache_lock = threading.Lock()


def _get_cached_or_none() -> list | None:
    with _cache_lock:
        if _cache_result and (time.monotonic() - _cache_timestamp) < _CACHE_TTL_SECONDS:
            return list(_cache_result)
    return None


def _set_cache(result: list) -> None:
    global _cache_result, _cache_timestamp
    with _cache_lock:
        _cache_result = list(result)
        _cache_timestamp = time.monotonic()


def invalidate_analysis_cache() -> None:
    """Cache manuell leeren – z.B. nach neuem Sensor-/Tagebucheintrag."""
    global _cache_result, _cache_timestamp
    with _cache_lock:
        _cache_result = []
        _cache_timestamp = 0.0


# ─── ONNX Engine ──────────────────────────────────────────────────────────────
# Wird einmalig beim ersten Aufruf initialisiert und dann dauerhaft gehalten.
# Modell bleibt im RAM (~80MB) – kein Reload bei jedem Query.

_ort_session   = None
_ort_tokenizer = None
_ort_input_names: list = []
_ort_lock = threading.Lock()

# Vorberechnete Wissens-Vektoren: numpy-Array (n_entries, 384) + Metadaten
_kv_vectors:   np.ndarray | None = None
_kv_metadatas: list = []
_kv_loaded = False


def _load_onnx_engine() -> bool:
    """
    Lädt ONNX-Modell und Tokenizer einmalig.
    Gibt True zurück wenn erfolgreich, False bei jedem Fehler.
    Idempotent – mehrfache Aufrufe sicher.
    """
    global _ort_session, _ort_tokenizer, _ort_input_names

    with _ort_lock:
        if _ort_session is not None:
            return True  # bereits geladen

        # Voraussetzungs-Check
        missing = []
        if not os.path.exists(MODEL_PATH):
            missing.append(f"model/model.onnx (fehlt in {BASE_DIR})")
        if not os.path.exists(TOKENIZER_PATH):
            missing.append(f"model/tokenizer.json (fehlt in {BASE_DIR})")
        try:
            import onnxruntime
            import tokenizers as _tok_lib
        except ImportError as e:
            log.warning(
                f"ONNX-Engine nicht verfügbar: {e}. "
                "Installation: pip install onnxruntime tokenizers  →  Fallback aktiv."
            )
            return False

        if missing:
            log.warning(
                f"ONNX-Engine: Dateien fehlen: {missing}. "
                "Bitte model/ Verzeichnis befüllen (siehe README).  →  Fallback aktiv."
            )
            return False

        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            tok = Tokenizer.from_file(TOKENIZER_PATH)
            tok.enable_padding(direction="right", pad_id=0, pad_token="[PAD]")
            tok.enable_truncation(max_length=256)

            sess = ort.InferenceSession(
                MODEL_PATH,
                providers=["CPUExecutionProvider"]
            )
            input_names = [inp.name for inp in sess.get_inputs()]

            _ort_tokenizer  = tok
            _ort_session    = sess
            _ort_input_names = input_names
            log.info(f"ONNX-Engine geladen: {MODEL_PATH}")
            return True

        except Exception as exc:
            log.error(f"ONNX-Engine Ladefehler: {exc}  →  Fallback aktiv.")
            return False


def _load_knowledge_vectors() -> bool:
    """
    Lädt vorberechnete Vektoren aus knowledge_vectors.json.
    Gibt True zurück wenn erfolgreich.
    """
    global _kv_vectors, _kv_metadatas, _kv_loaded

    if _kv_loaded:
        return _kv_vectors is not None

    if not os.path.exists(VECTORS_PATH):
        log.warning(
            f"knowledge_vectors.json fehlt ({VECTORS_PATH}). "
            "Bitte build_vectors.py ausführen.  →  Fallback aktiv."
        )
        _kv_loaded = True
        return False

    try:
        with open(VECTORS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        entries = data.get("entries", [])
        if not entries:
            raise ValueError("Keine Einträge in knowledge_vectors.json")

        vectors   = np.array([e["vector"]   for e in entries], dtype=np.float32)
        metadatas = [e["metadata"] for e in entries]

        # Sanity-Check: alle Vektoren sollten normalisiert sein (Norm ≈ 1.0)
        norms = np.linalg.norm(vectors, axis=1)
        if abs(norms.mean() - 1.0) > 0.05:
            log.warning("knowledge_vectors.json: Vektoren nicht normalisiert – neu bauen empfohlen.")
            # Normalisieren als Self-Repair
            vectors = vectors / np.maximum(norms[:, np.newaxis], 1e-9)

        _kv_vectors   = vectors
        _kv_metadatas = metadatas
        _kv_loaded    = True

        file_version = data.get("version", "?")
        log.info(
            f"Wissens-Vektoren geladen: {len(entries)} Einträge "
            f"(v{file_version}, {vectors.shape[1]}D)"
        )

        # Versions-Check: Warnung wenn Vektordatei veraltet
        if file_version != KNOWLEDGE_VERSION:
            log.warning(
                f"Versions-Mismatch: knowledge_vectors.json=v{file_version}, "
                f"analyzer.py=v{KNOWLEDGE_VERSION}. "
                "Bitte build_vectors.py erneut ausführen."
            )

        return True

    except Exception as exc:
        log.error(f"Fehler beim Laden von knowledge_vectors.json: {exc}  →  Fallback aktiv.")
        _kv_loaded = True
        return False


def _embed_query(text: str) -> np.ndarray | None:
    """
    Vektorisiert einen einzelnen Query-Text via ONNX.
    Gibt normalisierten Vektor (384,) zurück oder None bei Fehler.
    """
    if _ort_session is None or _ort_tokenizer is None:
        return None

    try:
        enc = _ort_tokenizer.encode(text)

        input_ids      = np.array([enc.ids],            dtype=np.int64)
        attention_mask = np.array([enc.attention_mask], dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids,       dtype=np.int64)

        feed = {}
        for name in _ort_input_names:
            if "input_ids"      in name: feed[name] = input_ids
            elif "attention"    in name: feed[name] = attention_mask
            elif "token_type"   in name: feed[name] = token_type_ids

        outputs = _ort_session.run(None, feed)
        token_embeddings = outputs[0]  # (1, seq_len, 384)

        mask = attention_mask[:, :, np.newaxis].astype(np.float32)
        emb  = (token_embeddings * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1e-9)
        emb  = emb[0]  # (384,)

        norm = np.linalg.norm(emb)
        return emb / max(norm, 1e-9)

    except Exception as exc:
        log.error(f"ONNX Query-Fehler: {exc}")
        return None


def _search(query_text: str, threshold: float = 0.55, top_k: int = 3) -> list[dict]:
    """
    Semantische Suche: Query-Text gegen alle vorberechneten Vektoren.
    Gibt die Metadaten der besten Treffer zurück (bis zu top_k).
    """
    engine_ok  = _load_onnx_engine()
    vectors_ok = _load_knowledge_vectors()
    
    if not engine_ok or not vectors_ok or _kv_vectors is None:
        return []

    q_vec = _embed_query(query_text)
    if q_vec is None:
        return []

    import numpy as np
    # Dot-Product gegen alle Vektoren gleichzeitig
    scores = _kv_vectors @ q_vec
    
    # Indizes der Treffer über dem Threshold finden
    valid_indices = np.where(scores >= threshold)[0]
    if len(valid_indices) == 0:
        log.debug(f"Kein Treffer für '{query_text[:50]}…'")
        return []

    # Nach Score absteigend sortieren
    sorted_indices = valid_indices[np.argsort(-scores[valid_indices])]
    top_indices = sorted_indices[:top_k]

    results = []
    for idx in top_indices:
        score = float(scores[idx])
        log.debug(f"Treffer: '{_kv_metadatas[idx]['title']}' (Score: {score:.3f})")
        results.append(_kv_metadatas[idx])
        
    return results

# ─── VPD-Berechnung ───────────────────────────────────────────────────────────

def calc_vpd(temp_c: float, rh_percent: float) -> float:
    """Berechnet Vapor Pressure Deficit in kPa aus Temperatur und Luftfeuchte."""
    svp = 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))
    return round(svp * (1 - rh_percent / 100), 3)


# ─── Wissensbasis v2.0 ────────────────────────────────────────────────────────
# Kategorien: A.Temperatur B.Luftfeuchtigkeit C.VPD D.pH E.Bewässerung
#             F.Nährstoffe-Mangel G.Nährstoffe-Überschuss H.Wachstum
#             I.Energie/Licht J.Schädlinge K-W (Wurzeln bis Düngestrategie)  –  GESAMT: 154 Einträge
#
# Erweitern: Tupel ans Ende, KNOWLEDGE_VERSION erhöhen → App neu starten.

PLANT_KNOWLEDGE = [

    # ══ A. TEMPERATUR ══════════════════════════════════════════════════════════
    (
        "Temperatur zu hoch Hitzestress Cannabis Blüte Blütephase über 28 Grad "
        "warm überhitzt Blütenentwicklung gestört Terpene verdampfen",
        {"type": "warning", "title": "Hitzestress – Blütephase",
         "message": ("Temperatur zu hoch für die Blütephase (Optimum 20–26 °C). "
                     "Ab 28 °C verdampfen Terpene und die Blütenentwicklung leidet. "
                     "→ Lüftung erhöhen, Lampe höher hängen, Lichtplan auf Nacht verschieben."),
         "scientific_ref": "Ref: Larcher, W. (2003). / Jin et al. (2019). American Journal of Plant Sciences."},
    ),
    (
        "Temperatur zu hoch Hitzestress Cannabis Sämling Keimling Steckling über 28 Grad "
        "junge Pflanze empfindlich Wurzelbildung gestört",
        {"type": "warning", "title": "Hitzestress – Sämling/Steckling",
         "message": ("Junge Pflanzen reagieren besonders empfindlich auf Hitze. "
                     "Optimum: 20–25 °C. Über 28 °C droht Welke und gehemmte Wurzelbildung. "
                     "→ Lampe weiter entfernen, Lüftung prüfen."),
         "scientific_ref": "Ref: Larcher, W. (2003)."},
    ),
    (
        "Temperatur zu hoch Hitzestress Cannabis vegetativ Wachstum über 30 Grad "
        "Stomata schließen CO2 Aufnahme reduziert Wachstum verlangsamt",
        {"type": "warning", "title": "Hitzestress – Vegetative Phase",
         "message": ("Temperatur über 30 °C: Stomata schließen, CO2-Aufnahme sinkt, "
                     "Wachstum verlangsamt sich. "
                     "→ Lüftung erhöhen, Klimaanlage prüfen, Lichtplan optimieren."),
         "scientific_ref": "Ref: Larcher, W. (2003)."},
    ),
    (
        "Kritische Temperaturen über 35 Grad führen zu irreversiblen Zellschäden und gefährden die Ernte.",
        {"type": "warning", "title": "Kritische Hitze – Sofortmaßnahme",
         "message": ("KRITISCH: Über 35 °C drohen irreversible Zellschäden. "
                     "→ Licht sofort abschalten, maximale Lüftung, Türen öffnen."),
         "scientific_ref": "Ref: Larcher, W. (2003)."},
    ),
    (
        "Temperatur zu niedrig Kältestress Cannabis kalt unter 18 Grad "
        "Wachstum gehemmt Nährstoffaufnahme Phosphor nicht verfügbar",
        {"type": "warning", "title": "Kältestress",
         "message": ("Temperatur zu niedrig (Minimum 18 °C). "
                     "Unter 15 °C wird Phosphor kaum aufgenommen, Wachstum stoppt. "
                     "→ Heizung prüfen, Zugluft eliminieren, Substrat wärmen."),
         "scientific_ref": "Ref: Larcher, W. (2003)."},
    ),
    (
        "Starke Temperaturschwankungen von mehr als 10 Grad zwischen Tag und Nacht verursachen bei der Cannabis-Pflanze starken Stress.",
        {"type": "info", "title": "Große Temperaturschwankung Tag/Nacht",
         "message": ("Tag-Nacht-Unterschied über 10 °C stresst die Pflanze. "
                     "Ideal: max. 5–8 °C Differenz. "
                     "→ Nachttemperatur durch Zeitschaltuhr oder Heizung stabilisieren."),
         "scientific_ref": ""},
    ),
    (
        "In der Spätblüte und vor der Ernte sind 20 bis 26 Grad optimal für die Reifung von Terpenen und Harz.",
        {"type": "info", "title": "Temperatur Spätblüte",
         "message": ("Für optimale Terpene und Harzbildung: 20–26 °C tagsüber, "
                     "leicht kühler (16–20 °C) nachts. "
                     "Leichte Nachtabkühlung kann Anthocyanin-Färbung fördern."),
         "scientific_ref": "Ref: Jin et al. (2019). American Journal of Plant Sciences."},
    ),
    (
        "Temperatur Substrat Boden zu kalt unter 20 Grad Wurzeln "
        "Nährstoffaufnahme gestört Phosphor Kalium blockiert",
        {"type": "warning", "title": "Substrattemperatur zu niedrig",
         "message": ("Substrat unter 20 °C blockiert Phosphor- und Kaliumaufnahme. "
                     "→ Topf auf Styropor stellen, Heizmatte verwenden, "
                     "kaltes Gießwasser vermeiden."),
         "scientific_ref": "Ref: Extension USU – Nutrient Deficiencies (2024)."},
    ),

    # ══ B. LUFTFEUCHTIGKEIT ════════════════════════════════════════════════════
    (
        "Luftfeuchtigkeit zu hoch Schimmel Botrytis Grauschimmel Blüte Blütephase "
        "über 65 Prozent feucht Pilzbefall Budfäule kritisch",
        {"type": "warning", "title": "Schimmelgefahr – Blütephase",
         "message": ("Luftfeuchtigkeit zu hoch für die Blütephase (Maximum: 50–60 %). "
                     "Akutes Botrytis cinerea Risiko! "
                     "→ Sofort lüften, Luftentfeuchter einschalten, "
                     "Luftzirkulation an den Blüten verbessern."),
         "scientific_ref": "Ref: Elad, Y. et al. (1997). Botrytis cinerea management."},
    ),
    (
        "Bei extrem hoher Luftfeuchtigkeit über 80 Prozent in der Blütephase muss sofort gehandelt werden, da Pilze innerhalb von Stunden entstehen.",
        {"type": "warning", "title": "Kritische Luftfeuchtigkeit – Sofortmaßnahme",
         "message": ("KRITISCH: Über 80 % in der Blütephase – Schimmel kann "
                     "innerhalb von Stunden entstehen. "
                     "→ Alle Lüftungen maximieren, Entfeuchter auf Maximum, "
                     "befallene Blüten sofort entfernen."),
         "scientific_ref": "Ref: Elad, Y. et al. (1997)."},
    ),
    (
        "In der vegetativen Phase erhöht eine Luftfeuchtigkeit über 70 Prozent das Risiko für echten Mehltau.",
        {"type": "warning", "title": "Zu hohe Luftfeuchtigkeit – Vegetative Phase",
         "message": ("Luftfeuchtigkeit über 70 % – erhöhtes Mehltau-Risiko. "
                     "Für die vegetative Phase: 50–70 % optimal. "
                     "→ Lüftung erhöhen, Pflanzendichte reduzieren."),
         "scientific_ref": ""},
    ),
    (
        "Stecklinge und Sämlinge benötigen eine hohe Luftfeuchtigkeit, jedoch droht bei durchgehend über 85 Prozent Fäulnis an den Wurzeln.",
        {"type": "info", "title": "Luftfeuchtigkeit – Steckling/Sämling",
         "message": ("Stecklinge ohne Wurzeln: 75–90 % normal. "
                     "Mit ersten Wurzeln: Feuchtigkeit langsam auf 65–70 % senken "
                     "um Wurzelbildung zu fördern."),
         "scientific_ref": "Ref: Koolfog Cannabis Cultivation VPD Guide (2024)."},
    ),
    (
        "Luftfeuchtigkeit zu niedrig trocken Cannabis unter 40 Prozent "
        "Transpiration gehemmt Stomata schließen",
        {"type": "warning", "title": "Zu trockene Luft",
         "message": ("Luftfeuchtigkeit unter 40 % – Stomata schließen, "
                     "Transpiration und Nährstoffaufnahme sinken. "
                     "→ Luftbefeuchter einschalten, Wasserschalen aufstellen."),
         "scientific_ref": "Ref: Larcher, W. (2003)."},
    ),
    (
        "Fällt die Luftfeuchtigkeit in der Blüte unter 35 Prozent, verursacht die extreme Trockenheit Stress und beeinträchtigt die Ertragsqualität.",
        {"type": "warning", "title": "Extrem trockene Luft – Blütephase",
         "message": ("Unter 35 % führt zu Trockenstress und übermäßiger Transpiration. "
                     "Ertragsqualität leidet langfristig. "
                     "→ Luftbefeuchter, Gießwassertemperatur angleichen."),
         "scientific_ref": ""},
    ),
    (
        "In den letzten Wochen vor der Ernte fördert eine Luftfeuchtigkeit von 40 bis 50 Prozent die Harzproduktion und senkt das Schimmelrisiko.",
        {"type": "info", "title": "Luftfeuchtigkeit Spätblüte",
         "message": ("In den letzten 2 Wochen vor Ernte: 40–50 % anstreben. "
                     "Fördert Harzproduktion, reduziert Schimmelrisiko beim Trocknen."),
         "scientific_ref": "Ref: Dutch Passion VPD Guide (2025)."},
    ),
    (
        "Wenn nachts die Temperatur fällt und die Luftfeuchtigkeit steigt, bildet sich Kondenswasser auf den Blättern, was Pilzinfektionen begünstigt.",
        {"type": "warning", "title": "Kondensation / Nachtfeuchtigkeit",
         "message": ("Stark fallende Nachttemperatur → Kondenswasser auf Blättern → "
                     "Pilzgefahr. → Nacht-Lüftung aktiv halten, "
                     "Temperaturabfall auf max. 8 °C begrenzen."),
         "scientific_ref": "Ref: Dutch Passion VPD Guide – Night VPD (2025)."},
    ),

    # ══ C. VPD ════════════════════════════════════════════════════════════════
    (
        "VPD zu niedrig unter 0.4 kPa Cannabis Transpiration gehemmt "
        "Nährstoffaufnahme blockiert Schimmel Stomata",
        {"type": "warning", "title": "VPD zu niedrig – Transpiration blockiert",
         "message": ("VPD unter 0.4 kPa: Luft zu feucht – Pflanze kann kaum transpirieren. "
                     "Nährstoffaufnahme und CO2-Austausch gestört, Schimmelrisiko steigt. "
                     "→ Luftfeuchtigkeit senken oder Temperatur erhöhen."),
         "scientific_ref": "Ref: Emerald Harvest – Managing VPD for Cannabis (2024)."},
    ),
    (
        "Ein VPD über 1.6 kPa führt zu extremem Trockenstress, zwingt die Pflanze zum Schliessen der Stomata und verursacht Nutrient Burn.",
        {"type": "warning", "title": "VPD zu hoch – Trockenstress",
         "message": ("VPD über 1.6 kPa: Pflanze transpiriert zu stark, "
                     "Nährstoffe stauen sich an (Nutrient Burn). "
                     "→ Luftfeuchtigkeit erhöhen und/oder Temperatur senken."),
         "scientific_ref": "Ref: Norddampf VPD Guide (2026). / Quest Climate VPD Flowering."},
    ),
    (
        "Ein VPD über 0.8 kPa ist für Sämlinge und unbewurzelte Stecklinge zu hoch und führt zu rascher Austrocknung.",
        {"type": "warning", "title": "VPD zu hoch für Sämling/Steckling",
         "message": ("Zielwert für Sämlinge/Stecklinge: 0.4–0.8 kPa. "
                     "Zu hohes VPD trocknet Stecklinge ohne Wurzeln aus. "
                     "→ Luftfeuchtigkeit auf 75–85 % erhöhen."),
         "scientific_ref": "Ref: 2Fast4Buds VPD Guide (2024)."},
    ),
    (
        "In der vegetativen Phase führt ein niedriges VPD unter 0.7 kPa zu einem sehr langsamen Wachstum der Pflanze.",
        {"type": "info", "title": "VPD leicht niedrig – Vegetative Phase",
         "message": ("VPD-Ziel vegetativ: 0.8–1.2 kPa. "
                     "Zu niedriges VPD verlangsamt Transpiration und Nährstoffversorgung. "
                     "→ Luftfeuchtigkeit etwas senken oder Temperatur leicht erhöhen."),
         "scientific_ref": "Ref: GrowSensor VPD Veg Guide (2024)."},
    ),
    (
        "Ein VPD über 1.2 kPa in der Wachstumsphase stresst die Pflanze, so dass CO2-Aufnahme und Wachstum einbrechen.",
        {"type": "warning", "title": "VPD zu hoch – Vegetative Phase",
         "message": ("VPD über 1.2 kPa in der Veg-Phase: Stomata schließen, "
                     "CO2-Aufnahme und Wachstum sinken. "
                     "→ Luftfeuchtigkeit erhöhen (Ziel: 55–70 % bei 24 °C)."),
         "scientific_ref": "Ref: Cannabis Science & Technology – VPD (2024)."},
    ),
    (
        "Ein VPD unter 1.0 kPa während der Blütephase verhindert eine gute Transpiration und begünstigt Budrot und Schimmel.",
        {"type": "warning", "title": "VPD zu niedrig – Blütephase",
         "message": ("VPD unter 1.0 kPa in der Blütephase erhöht das Botrytis-Risiko. "
                     "Zielwert: 1.0–1.5 kPa. "
                     "→ Luftfeuchtigkeit senken (Ziel: 45–55 %) und Lüftung erhöhen."),
         "scientific_ref": "Ref: Cannabis Science & Technology (2024). / Quest Climate."},
    ),
    (
        "Ein zu hohes VPD über 1.6 kPa in der Blüte schädigt durch Trockenstress die Harz- und Terpenqualität der Blüten.",
        {"type": "warning", "title": "VPD zu hoch – Blütephase",
         "message": ("VPD über 1.6 kPa in der Blüte: Stress, Nutrient Burn, "
                     "reduzierte Terpene/Harz-Qualität. "
                     "→ Luftfeuchtigkeit auf 45–55 % erhöhen, Temperatur prüfen."),
         "scientific_ref": "Ref: Mr. GrowIt VPD Guide (2025)."},
    ),
    (
        "In der Spätblüte ist ein VPD zwischen 1.2 und 1.6 kPa ideal für die maximale Ausprägung von Terpenen und Harz.",
        {"type": "info", "title": "VPD Spätblüte – Zielwert",
         "message": ("Letzte 2–3 Wochen: VPD 1.2–1.6 kPa anstreben. "
                     "Fördert Terpene und Harzbildung, reduziert Schimmelrisiko. "
                     "→ Luftfeuchtigkeit auf 40–50 % senken."),
         "scientific_ref": "Ref: Mr. GrowIt VPD Guide (2025). / Dutch Passion VPD."},
    ),
    (
        "Wenn das VPD nachts durch Temperaturabfall zu tief sinkt, staut sich Feuchtigkeit, was akute Schimmelgefahr bedeutet.",
        {"type": "warning", "title": "Nacht-VPD zu niedrig",
         "message": ("Nachts fällt das VPD oft stark ab. Änderungen >0.4 kPa Tag/Nacht "
                     "können Ertragsverluste verursachen. "
                     "→ Nacht-Lüftung aktiv lassen, Temperaturabfall begrenzen."),
         "scientific_ref": "Ref: Dutch Passion VPD – Night Values (2025)."},
    ),
    (
        "Zu grosse VPD-Schwankungen zwischen Tag und Nacht stressen die Pflanze enorm und führen zu signifikanten Ertragsverlusten.",
        {"type": "info", "title": "VPD-Schwankungen zu groß",
         "message": ("Starke VPD-Schwankungen (>0.4 kPa Tag/Nacht) wurden mit "
                     "bis zu 20 % Ertragsverlust assoziiert. "
                     "→ Heizung, Entfeuchter und Lüftung auf Zeitschaltuhren abstimmen."),
         "scientific_ref": "Ref: Dutch Passion VPD Guide – Yield losses (2025)."},
    ),

    # ══ D. pH-WERT ════════════════════════════════════════════════════════════
    (
        "pH Wert zu hoch alkalisch Cannabis Erde über 7.0 "
        "Nährstoffblockade Phosphor Eisen Mangan Zink Lockout",
        {"type": "warning", "title": "pH zu hoch – Nährstoff-Lockout",
         "message": ("pH über 7.0 in Erde blockiert Phosphor, Eisen, Mangan und Zink. "
                     "Optimum Erde: 6.0–6.5. "
                     "→ pH-Down (Zitronensäure) beim Gießen, Substrat ggf. spülen."),
         "scientific_ref": "Ref: Royal Queen Seeds – Nutrient Deficiency Guide. / RQS Blog (2020)."},
    ),
    (
        "pH Wert zu niedrig sauer Cannabis Erde unter 5.8 "
        "Calcium Magnesium Kalium blockiert Mangantoxizität",
        {"type": "warning", "title": "pH zu niedrig – Säurestress",
         "message": ("pH unter 5.8 blockiert Calcium, Magnesium und Kalium. "
                     "Optimum Erde: 6.0–6.5. "
                     "→ pH-Up beim Gießen, Kalk ins Substrat einarbeiten."),
         "scientific_ref": "Ref: Humboldt Seed Company – Deficiencies (2026). / RQS Blog."},
    ),
    (
        "In Hydroponik oder Kokos blockiert ein pH über 6.5 rasch wichtiges Eisen, was zu Vergilbung der jungen Blätter führt.",
        {"type": "warning", "title": "pH zu hoch – Hydroponik/Coco",
         "message": ("pH über 6.5 in Hydro/Coco blockiert Eisen – "
                     "sichtbar als Vergilbung junger Blätter. "
                     "Optimum: 5.5–6.2. → pH-Lösung anpassen, Nährlösung erneuern."),
         "scientific_ref": "Ref: Cannabiz Credit – Cannabis Deficiencies Chart (2025)."},
    ),
    (
        "Ein pH-Wert unter 5.5 in Hydroponik und Kokos führt zu massiven Kalzium- und Magnesiumblockaden und Wurzelschäden.",
        {"type": "warning", "title": "pH zu niedrig – Hydroponik/Coco",
         "message": ("pH unter 5.5: Calcium und Magnesium blockiert, Wurzelschäden möglich. "
                     "→ pH-Up verwenden, Nährlösung erneuern, Wurzeln prüfen."),
         "scientific_ref": "Ref: Cannabiz Credit – Cannabis Deficiencies Chart (2025)."},
    ),
    (
        "Ein pH-Wert zwischen 5.8 und 6.0 in Erde ist grenzwertig niedrig; achten Sie besonders auf mögliche Verschlechterungen bei der Nährstoffaufnahme.",
        {"type": "info", "title": "pH knapp am unteren Limit",
         "message": ("pH 5.8–6.0 in Erde ist grenzwertig. "
                     "Eisen- und Manganverfügbarkeit beobachten. "
                     "Idealwert: 6.0–6.5. → Etwas pH-Up beim nächsten Gießen."),
         "scientific_ref": ""},
    ),
    (
        "Stark schwankende pH-Werte deuten meist auf aufgebaute Mineralsalze im Substrat hin, weshalb ein sofortiger Flush notwendig ist.",
        {"type": "warning", "title": "pH-Schwankungen / Salz-Aufbau",
         "message": ("Stark schwankender pH deutet auf Salzaufbau hin. "
                     "→ Substrat mit 3× Topfvolumen pH-neutralem Wasser spülen (Flush)."),
         "scientific_ref": "Ref: RQS – Nutrient Deficiency Guide (2020)."},
    ),
    (
        "Der pH-Wert im Erdanbau liegt zwischen 6.0 und 6.5 optimal, womit die maximale Aufnahme aller Makro- und Mikronährstoffe gesichert ist.",
        {"type": "info", "title": "pH im optimalen Bereich (Erde)",
         "message": ("pH im optimalen Bereich für Erdkultur (6.0–6.5). "
                     "Alle Nährstoffe maximal verfügbar. Weiterhin regelmäßig kontrollieren."),
         "scientific_ref": ""},
    ),
    (
        "Der pH-Wert befindet sich im absolut perfekten Bereich für kokosbasierte Substrate oder hydroponische Systeme.",
        {"type": "info", "title": "pH im optimalen Bereich (Hydro/Coco)",
         "message": ("pH im optimalen Bereich für Hydro/Coco (5.5–6.2). "
                     "Hydroponik-pH driftet schneller – regelmäßig kontrollieren."),
         "scientific_ref": ""},
    ),

    # ══ E. BEWÄSSERUNG ════════════════════════════════════════════════════════
    (
        "Bisher wurde noch nie eine Bewässerung im Tagebuch dokumentiert, weshalb das System nicht weiss, wie feucht das Substrat ist.",
        {"type": "info", "title": "Keine Bewässerung dokumentiert",
         "message": ("Noch keine Gießaktivitäten im Tagebuch. "
                     "→ Erde manuell prüfen (Finger 2–3 cm tief: trocken = gießen). "
                     "Erste Bewässerung dokumentieren."),
         "scientific_ref": ""},
    ),
    (
        "Die letzte Bewässerung ist bereits sehr lange her, was bedeutet, dass die Erde wahrscheinlich komplett trocken ist und die Pflanze sofort gegossen werden muss.",
        {"type": "info", "title": "Bewässerung überfällig",
         "message": ("Letzte Bewässerung liegt mehrere Tage zurück. "
                     "→ Erde prüfen: Finger 2–3 cm ins Substrat – trocken = sofort gießen. "
                     "Topf wiegen als Alternative (leicht = trocken)."),
         "scientific_ref": ""},
    ),
    (
        "Wenn die Pflanze zu oft gegossen wird, leidet sie unter Sauerstoffmangel im Wurzelbereich, was Wurzelfäule und hängende Blätter verursacht.",
        {"type": "warning", "title": "Mögliche Überwässerung",
         "message": ("Zu häufiges Gießen → Sauerstoffmangel an Wurzeln. "
                     "Symptome: hängende Blätter trotz feuchter Erde, Vergilbung. "
                     "→ Gießintervall verlängern, Drainage prüfen."),
         "scientific_ref": "Ref: 24high.com – Nutrient Deficiencies Cannabis (2025)."},
    ),
    (
        "Hartes, kalkhaltiges Leitungswasser muss immer auf einen passenden pH-Wert korrigiert werden, bevor die Pflanze gegossen wird.",
        {"type": "info", "title": "Gießwasser-pH prüfen",
         "message": ("Hartes Leitungswasser (pH 7–8) verschiebt langfristig den Substrat-pH. "
                     "→ Gießwasser auf pH 6.0–6.5 (Erde) bzw. 5.5–6.2 (Hydro) einstellen."),
         "scientific_ref": ""},
    ),

    # ══ F. NÄHRSTOFFE – MANGEL ════════════════════════════════════════════════
    (
        "Die alten, großen Blätter im unteren Bereich der Pflanze werden flächig gelb, was deutlich auf einen Stickstoffmangel hindeutet.",
        {"type": "warning", "title": "Stickstoffmangel (N)",
         "message": ("Vergilbung beginnt an unteren/älteren Blättern (mobiler Nährstoff). "
                     "→ Stickstoffreichen Dünger, pH prüfen (6.0–6.5), nicht überwässern."),
         "scientific_ref": "Ref: Leafly – Nutrient Deficiencies. / RQS Nutrient Guide."},
    ),
    (
        "Ein Phosphormangel zeigt sich durch extrem dunkelgrüne Blätter sowie rötlich oder violett verfärbte Stängel, begleitet von einer sehr verzögerten Blütenbildung.",
        {"type": "warning", "title": "Phosphormangel (P)",
         "message": ("Rote/lila Stängel, dunkelgrüne Blätter, verzögerte Blütenbildung. "
                     "Oft durch kaltes Substrat oder pH > 7 ausgelöst. "
                     "→ Phosphorreichen Dünger, Substrat >20 °C, pH 6.0–6.5."),
         "scientific_ref": "Ref: Leafly. / Humboldt Seed Company – Deficiencies (2026)."},
    ),
    (
        "Die Ränder und Spitzen der Blätter verfärben sich erst gelblich, dann braun und rollen sich nach oben ein, was ein klassischer Kaliummangel ist.",
        {"type": "warning", "title": "Kaliummangel (K)",
         "message": ("Braune/gelbe Blattränder, einrollende Blätter, schwache Stängel. "
                     "→ Kaliumreichen Dünger, Flush bei Salzaufbau, pH korrigieren."),
         "scientific_ref": "Ref: Dutch Passion Deficiency Guide. / Leafly."},
    ),
    (
        "Bei älteren Blättern vergilben die Flächen zwischen den Blattadern, während die Adern selbst grün bleiben; dies ist das Leitsymptom für Magnesiummangel.",
        {"type": "warning", "title": "Magnesiummangel (Mg)",
         "message": ("Vergilbung zwischen Blattadern, Adern bleiben grün. "
                     "Beginnt an älteren Blättern. Oft bei niedrigem pH oder viel Kalium. "
                     "→ Cal-Mag Lösung oder Bittersalz (Epsomsalz) als Blattspray."),
         "scientific_ref": "Ref: Leafly – Magnesium. / Dinafem Nutrient Guide."},
    ),
    (
        "Neue Blätter wachsen deformiert oder kräftig verdreht und bilden unregelmässige, nekrotische braune Flecken aus, verursacht durch zu wenig Calcium.",
        {"type": "warning", "title": "Calciummangel (Ca)",
         "message": ("Braune Flecken, verformte junge Blätter (immobiler Nährstoff). "
                     "Häufig bei niedrigem pH oder in Hydroponik. "
                     "→ Cal-Mag Lösung, pH auf 6.0–6.5."),
         "scientific_ref": "Ref: RQS Nutrient Guide. / Leafly – Calcium."},
    ),
    (
        "Die jüngsten Blätter an den Triebspitzen wachsen völlig gelb heran, während ihre feinen Adern dunkelgrün bleiben, ausgelöst durch Eisenmangel wegen zu hohem pH.",
        {"type": "warning", "title": "Eisenmangel (Fe)",
         "message": ("Vergilbung junger Blätter/Triebspitzen, Adern bleiben grün. "
                     "Fast immer pH-bedingt (>7.0). "
                     "→ pH auf 6.0–6.5 senken. Cheliertes Eisen als Sofortmaßnahme."),
         "scientific_ref": "Ref: Leafly – Iron. / Dutch Passion Deficiency Guide."},
    ),
    (
        "Junge Blätter bekommen hellgrüne bis gelbe Bereiche zwischen den Blattadern, ein Manganmangel, der fast an einen Eisenmangel erinnert.",
        {"type": "warning", "title": "Manganmangel (Mn)",
         "message": ("Interveinalchlorose an jungen Blättern, ähnlich Eisenmangel. "
                     "Ursache: pH zu hoch oder Eisen-Überschuss. "
                     "→ pH 6.0–6.5, Eisen-Düngung reduzieren."),
         "scientific_ref": "Ref: RQS Nutrient Guide. / Leafly – Manganese."},
    ),
    (
        "Triebspitzen wachsen mit stark verkleinerten, verdrehten Blättern heran und der Stängel bleibt extrem kurz, typisch für einen Zinkmangel.",
        {"type": "warning", "title": "Zinkmangel (Zn)",
         "message": ("Neue Blätter klein und verdreht, kurze Internodien. "
                     "Häufig bei alkalischem pH. "
                     "→ pH senken, Spurenelemente-Dünger ergänzen."),
         "scientific_ref": "Ref: Leafly – Zinc. / Humboldt Seed Company."},
    ),
    (
        "Ein seltener Mangel an Schwefel oder Bor äußert sich durch verdreht wachsende Triebspitzen und eine gelbliche Verfärbung ganz oben an der Pflanze.",
        {"type": "info", "title": "Schwefel/Bormangel",
         "message": ("Schwefel: junge Blätter hellgelb. Bor: neue Triebe verdrehen sich. "
                     "Beide selten – erst pH und Grundnährstoffe prüfen. "
                     "→ Komplettdünger mit Spurenelementen."),
         "scientific_ref": "Ref: Leafly – Sulfur & Boron. / RQS Nutrient Guide."},
    ),
    (
        "Die Pflanze zeigt plötzlich verschiedene Mangelerscheinungen gleichzeitig, weil falsche pH-Werte oder Düngersalze die Wurzeln blockieren.",
        {"type": "warning", "title": "Nährstoff-Lockout",
         "message": ("Mehrere Mängel trotz Düngung = Blockade. "
                     "Ursache: falscher pH oder Salzaufbau. "
                     "→ Flush (3× Topfvolumen), pH prüfen, "
                     "danach mit halber Düngerkonzentration neu starten."),
         "scientific_ref": "Ref: 24high.com Nutrient Deficiencies (2025). / Myplantin."},
    ),
    (
        "Die Pflanze befindet sich im Blüte-Phasenwechsel und benötigt dringend weniger Stickstoff, aber massiv mehr Phosphor und Kalium zur Blütenbildung.",
        {"type": "info", "title": "Nährstoffbedarf Phasenwechsel",
         "message": ("In der Blütephase: weniger Stickstoff, mehr P und K. "
                     "Vegetativer Dünger allein reicht nicht. "
                     "→ Auf Blütedünger mit P-K-Boost wechseln."),
         "scientific_ref": "Ref: 2Fast4Buds Nutrient Guide. / Dutch Passion."},
    ),
    (
        "Die Blätter sind unnatürlich dunkelgrün und an den Enden hakenförmig nach unten gebogen, ein Anzeichen für hochgradigen Stickstoff-Überschuss.",
        {"type": "warning", "title": "Stickstoff-Überschuss (N-Toxizität)",
         "message": ("Extrem dunkelgrüne Blätter, nach unten rollende Blattspitzen ('Clawing'). "
                     "→ Düngermenge halbieren oder Flush, dann reduziert neu starten."),
         "scientific_ref": "Ref: Dinafem – Nutrient Excess Guide."},
    ),

    # ══ G. NÄHRSTOFFE – ÜBERSCHUSS ════════════════════════════════════════════
    (
        "Die äußersten Blattspitzen sind verbrannt, krümelig und braun verfärbt; die klassische toxische Überdüngung beziehungsweise Nutrient Burn.",
        {"type": "warning", "title": "Nutrient Burn – Überdüngung",
         "message": ("Braune, verbrannte Blattspitzen = Nutrient Burn. "
                     "→ Flush (3× Topfvolumen), danach mit 50 % Dosis neu starten. "
                     "EC-Wert des Abflusswassers messen."),
         "scientific_ref": "Ref: Quest Climate – VPD Nutrient Burn. / Dinafem."},
    ),
    (
        "Zu exzessive Gaben von Cal-Mag Produkten führen zu Überschüssen, die wiederum Kalium, Mangan und Eisen im Substrat sperren.",
        {"type": "info", "title": "Cal-Mag-Überschuss",
         "message": ("Zu viel Calcium blockiert Kalium, Mangan und Eisen. "
                     "Zu viel Magnesium blockiert Calcium. "
                     "→ Cal-Mag wie empfohlen dosieren, nicht prophylaktisch überdosieren."),
         "scientific_ref": "Ref: Dinafem – Nutrient Excess. / Myplantin."},
    ),
    (
        "Wenn Blütebooster mit zu stark konzentriertem Phosphor und Kalium gegeben werden, entstehen schnelle Mängel an Eisen, Magnesium und Zink.",
        {"type": "info", "title": "PK-Überschuss",
         "message": ("Zu viel P blockiert Zn, Fe, Mg. Zu viel K blockiert Mg und Mn. "
                     "→ In letzten 1–2 Wochen vor Ernte: Clean Flush empfohlen."),
         "scientific_ref": "Ref: Dutch Passion – Nutrient Excess. / Dinafem."},
    ),
    (
        "In den allerletzten Wochen vor der Ernte wird nur noch mit reinem Wasser gegossen, damit die überschüssigen Nährstoffe herausgewaschen werden und eine weisse Asche entsteht.",
        {"type": "info", "title": "Pre-Harvest Flush empfohlen",
         "message": ("Letzte 10–14 Tage: nur pH-korrigiertes Wasser, kein Dünger. "
                     "Pflanze baut gespeicherte Nährstoffe ab. "
                     "Ergebnis: saubererer Geschmack, weiße Asche."),
         "scientific_ref": ""},
    ),

    # ══ H. PFLANZENWACHSTUM ═══════════════════════════════════════════════════
    (
        "Das Längenwachstum stagniert komplett und die Pflanze gewinnt nicht mehr an Höhe, was auf Stress oder zu kleine Pflanztöpfe schliessen lässt.",
        {"type": "warning", "title": "Wachstumsstagnation",
         "message": ("Höhe seit mehreren Tagen unverändert. "
                     "Mögliche Ursachen: Topf zu klein, Nährstoffmangel, pH, Überwässerung. "
                     "→ Topfgröße, Nährstoffe und pH kontrollieren."),
         "scientific_ref": ""},
    ),
    (
        "Die Pflanze schiesst rapide in die Höhe, bildet lange Abstände zwischen Blättern und wirkt schwächlich, da ihr oft nicht genügend starkes Licht zur Verfügung steht.",
        {"type": "info", "title": "Übermäßiges Strecken (Stretching)",
         "message": ("Starkes Längenwachstum ohne Substanz = Lichtmangel. "
                     "In erster Blütewoche normal (1–2×). Exzessiv = Lampe zu weit/schwach. "
                     "→ Lampenabstand reduzieren, PPFD erhöhen."),
         "scientific_ref": ""},
    ),
    (
        "Die kleinen Harzdrüsen oder Trichome werden milchig trüb, teils bernsteinfarben und die meisten Pistillen sind braun, weshalb die Ernte ansteht.",
        {"type": "info", "title": "Erntezeitpunkt prüfen",
         "message": ("Trichome unter Lupe: Klar = zu früh. Milchig = maximaler THC. "
                     "Amber = CBN-Abbau beginnt. "
                     "Pistillen: 70–90 % braun = Richtwert."),
         "scientific_ref": "Ref: Jin et al. (2019). American Journal of Plant Sciences."},
    ),
    (
        "Die Pflanze hängt insgesamt welk, schwach und krank herab; die Ursache erfordert eine sofortige Kontrolle von Wurzeln, Gießwasser, Erde und Schädlingen.",
        {"type": "warning", "title": "Allgemeiner Pflanzenstress",
         "message": ("Systematische Diagnose: (1) pH, (2) Substratfeuchtigkeit, "
                     "(3) Temperatur und VPD, (4) Schädlinge (Blattunterseiten!), "
                     "(5) Wurzeln auf Farbe/Geruch prüfen."),
         "scientific_ref": ""},
    ),

    # ══ I. ENERGIE / LICHT ════════════════════════════════════════════════════
    (
        "Der Stromverbrauch am Smart-Plug ist stark gestiegen, was einen Defekt der Leuchtmittel oder ungewollt angeschaltete Zweitgeräte andeutet.",
        {"type": "warning", "title": "Ungewöhnlich hoher Energieverbrauch",
         "message": ("Verbrauch deutlich über Normalwert. "
                     "Mögliche Ursachen: Defekt, Leckage, unbeabsichtigte Geräte aktiv. "
                     "→ Alle Geräte und Verkabelung prüfen."),
         "scientific_ref": ""},
    ),
    (
        "Der Energieverbrauch ist unerwartet niedrig oder auf null gefallen, weshalb die Pflanzenlampe womöglich durch einen Zeitschaltuhrfehler ausgefallen ist.",
        {"type": "warning", "title": "Energieverbrauch zu niedrig – Lampe ausgefallen?",
         "message": ("Verbrauch stark gesunken oder null – Lampe defekt oder Zeitschaltuhr-Fehler. "
                     "→ Lampe und Zeitschaltuhr sofort prüfen. "
                     "Unerwartete Dunkelphase in Blüte ist kritisch."),
         "scientific_ref": ""},
    ),
    (
        "Unerwartetes Fremdlicht während der programmierten Dunkelphase stört die innere Uhr der Pflanze und kann gefährliche Zwitter auslösen.",
        {"type": "info", "title": "Lichtplan prüfen",
         "message": ("Vegetativ: 18h Licht / 6h Dunkel. Blüte: 12h / 12h. "
                     "Lichtverschmutzung in Dunkelphase kann Hermaphroditismus auslösen. "
                     "→ Zeitschaltuhr und Abdunkelung kontrollieren."),
         "scientific_ref": "Ref: Jin et al. (2019). American Journal of Plant Sciences."},
    ),
    (
        "Die Lichtintensität beziehungsweise die PPFD-Werte sind zu schwach, wodurch sich nur lockere, kleine Knospen entwickeln und die Ernte gering ausfällt.",
        {"type": "info", "title": "Lichtintensität möglicherweise zu niedrig",
         "message": ("Zu wenig Licht → Stretching, lockere Knospen, geringe Erträge. "
                     "PPFD-Ziele: Vegetativ 400–600, Blüte 600–900 µmol/m²/s. "
                     "→ Lampenabstand verringern oder stärkere Lampe."),
         "scientific_ref": "Ref: GrowSensor – PPFD Monitoring."},
    ),

    # ══ J. SCHÄDLINGE & KRANKHEITEN ═══════════════════════════════════════════
    (
        "Kleine helle Punkte auf den Blättern und feine Spinnennetze an den Blattunterseiten sind ein klarer Befall mit Spinnmilben.",
        {"type": "warning", "title": "Spinnmilben-Befall",
         "message": ("Weiße/gelbe Punkte auf Blättern, Gespinste an Blattunterseiten. "
                     "Breiten sich bei Hitze und niedriger Luftfeuchtigkeit schnell aus. "
                     "→ Befallene Blätter entfernen, Neem-Öl oder Pyrethrum "
                     "(nicht in Blüte!), Luftfeuchtigkeit erhöhen."),
         "scientific_ref": ""},
    ),
    (
        "Es fliegen kleine schwarze Fliegen aus der konstant zu feuchten Erde empor, was auf einen starken Befall mit Trauermücken hinweist.",
        {"type": "warning", "title": "Trauermücken / Fungus Gnats",
         "message": ("Kleine schwarze Fliegen am Substrat = Trauermücken. "
                     "Larven fressen Wurzelhaare, übertragen Pilze. Ursache: Überwässerung. "
                     "→ Substrat abtrocknen, Quarzsand-Oberfläche, "
                     "Bacillus thuringiensis israelensis (Bti) einwässern."),
         "scientific_ref": ""},
    ),
    (
        "Auf der Oberseite älterer und jüngerer Blätter breitet sich ein pudriger, weisser Belag aus, der Echter Mehltau genannt wird.",
        {"type": "warning", "title": "Echter Mehltau",
         "message": ("Weißer, puderartiger Belag = Echter Mehltau. "
                     "Entsteht bei wechselnder Feuchte und schlechter Luftzirkulation. "
                     "→ Befallene Blätter entfernen (Tüte!), Backpulver-Spray (1 TL/l), "
                     "Luftzirkulation verbessern, Feuchte unter 50 %."),
         "scientific_ref": "Ref: Elad, Y. (1997)."},
    ),
    (
        "Im Inneren kompakter Blüten entstehen weiche, braun-graue verfaulte Stellen, was der hochgradig ansteckende Botrytis-Pilz, auch Budrot genannt, ist.",
        {"type": "warning", "title": "Botrytis – Bud Rot",
         "message": ("Braune, weiche Stellen in Blüten = Botrytis cinerea. "
                     "KRITISCH: Breitet sich schnell aus, gefährdet Gesamternte. "
                     "→ Befallene Teile sofort entfernen, Feuchte unter 50 %, "
                     "Luftzirkulation maximieren. Bei starkem Befall: Ernte vorziehen."),
         "scientific_ref": "Ref: Elad, Y. et al. (1997). Botrytis cinerea in cannabis."},
    ),


    # ══ K. WURZELN & RHIZOSPHÄRE ══════════════════════════════════════════════
    (
        "Wurzelfäule Cannabis braune schleimige Wurzeln Pythium Fusarium "
        "Wurzeln stinken verfärbt Pflanze welkt trotz feuchter Erde",
        {"type": "warning", "title": "Wurzelfäule – Pythium/Fusarium",
         "message": ("Braune, schleimige Wurzeln mit fauligem Geruch deuten auf "
                     "Pythium- oder Fusarium-Befall hin. Häufigste Ursache: Überwässerung "
                     "und Sauerstoffmangel an der Wurzel. "
                     "→ Pflanze vorsichtig aus dem Medium nehmen, kranke Wurzeln abschneiden, "
                     "Wurzeln mit Wasserstoffperoxid (3 %) spülen, "
                     "Trichoderma oder Bacillus subtilis einsetzen, Gießintervall verlängern."),
         "scientific_ref": "Ref: Punja et al. (2019). Pythium/Fusarium in Cannabis. / GPN Mag."},
    ),
    (
        "Wurzeln gesund weiß Cannabis Kontrolle Rhizosphäre Wurzelcheck Topf "
        "gut entwickelt stark verzweigt",
        {"type": "info", "title": "Gesunde Wurzeln – Referenzpunkt",
         "message": ("Gesunde Cannabis-Wurzeln sind strahlend weiß bis cremeweiß, "
                     "fest, geruchsneutral und gut verzweigt. "
                     "Braune oder schleimige Stellen sind immer ein Warnsignal. "
                     "→ Regelmäßiger Wurzel-Check beim Umtopfen empfohlen."),
         "scientific_ref": "Ref: Cannoptikum – Root Health Guide (2024)."},
    ),
    (
        "Topf zu klein Cannabis Pflanze wurzelgebunden rootbound Wachstum stoppt "
        "Wurzeln kommen aus Drainagelöchern heraus Topf voll",
        {"type": "warning", "title": "Topf zu klein – Rootbound",
         "message": ("Wurzeln wachsen aus den Drainagelöchern oder sind komplett "
                     "verfilzt – die Pflanze ist rootbound. "
                     "Nährstoffaufnahme und Wachstum werden stark eingeschränkt. "
                     "→ Sofort in einen Topf mit mindestens dem doppelten Volumen umtopfen. "
                     "Faustformel: 1 Liter pro Woche geplante Kulturdauer."),
         "scientific_ref": ""},
    ),
    (
        "Luftbeschneidung Wurzeln Cannabis Air Pruning Fabric Pot Stofftopf "
        "Wurzelqualität verbessern mehr Seitenäste Rhizosphäre",
        {"type": "info", "title": "Air Pruning – Fabric Pots",
         "message": ("Stofftöpfe ermöglichen natürliche Luftbeschneidung der Wurzeln: "
                     "Wurzelspitzen sterben an der Luft ab und die Pflanze bildet "
                     "mehr Seitenwurzeln, was die Nährstoffaufnahme erheblich verbessert. "
                     "→ Fabric Pots empfohlen gegenüber Plastiktöpfen, "
                     "besonders für größere Pflanzen."),
         "scientific_ref": "Ref: Cannabis Business Times – Root Health (2024)."},
    ),
    (
        "Mykorrhiza Cannabis Wurzel Pilzgeflecht Trichoderma Bacillus "
        "Nützlinge Rhizosphäre gesund Mikrobenmilieu",
        {"type": "info", "title": "Mykorrhiza & Nützlinge für Wurzelgesundheit",
         "message": ("Arbuskuläre Mykorrhizapilze und Bacillus-Bakterien "
                     "bilden eine Schutzzone um die Wurzeln und verbessern "
                     "die Phosphor- und Mikronährstoffaufnahme um bis zu 30 %. "
                     "→ Beim Einpflanzen Mykorrhiza-Granulat direkt an die Wurzeln geben. "
                     "Nicht gleichzeitig mit fungiziden Produkten einsetzen."),
         "scientific_ref": "Ref: GPNMag – Beneficial Microbes Cannabis (2019). / Cannoptikum."},
    ),
    (
        "Wurzeln kreisen Cannabis Spirale im Topf Circling Roots Bonsai-Effekt "
        "Entwicklung gehemmt",
        {"type": "warning", "title": "Kreisende Wurzeln – Topfform prüfen",
         "message": ("Wurzeln die in kreisenden Spiralen wachsen (typisch bei "
                     "zu langer Standzeit in kleinen Töpfen oder falscher Topfform) "
                     "können die Pflanzenbasis einschnüren und das Wachstum dauerhaft hemmen. "
                     "→ Beim Umtopfen kreisende Wurzeln vorsichtig auseinander führen, "
                     "quadratische Töpfe oder Fabric Pots bevorzugen."),
         "scientific_ref": ""},
    ),
    (
        "Anaerobe Bedingungen Wurzelzone Cannabis Sauerstoffmangel Substrat "
        "verdichtet kein Austausch schlechter Gasaustausch",
        {"type": "warning", "title": "Sauerstoffmangel in der Wurzelzone",
         "message": ("Verdichtetes oder dauerhaft nasses Substrat verhindert den "
                     "Gasaustausch in der Wurzelzone – Sauerstoffmangel fördert "
                     "anaerobe Pathogene wie Pythium. "
                     "→ Perlite-Anteil auf 20–30 % erhöhen, Wet-Dry-Zyklus einhalten, "
                     "keine Untertassen stehen lassen."),
         "scientific_ref": "Ref: Punja et al. (2019). / GPN Mag – Indoor Cannabis Root Rots."},
    ),
    (
        "Umtopfen Cannabis richtiger Zeitpunkt Stress minimieren vegetativ "
        "Wachstum nicht stören Timing Topfgröße",
        {"type": "info", "title": "Umtopfen – Timing & Technik",
         "message": ("Optimaler Umtopf-Zeitpunkt: wenn Wurzeln gerade die Topfwände "
                     "erreichen, aber noch nicht kreisen. "
                     "Niemals während Blüteninduktion oder unter starkem Stress umtopfen. "
                     "→ 1–2 Stunden vor dem Umtopfen gießen, damit der Erdballen hält. "
                     "Substrate angleichen um Wasser-Wicking zu vermeiden."),
         "scientific_ref": ""},
    ),

    # ══ L. CO2-MANAGEMENT ═════════════════════════════════════════════════════
    (
        "CO2 Konzentration zu niedrig Cannabis unter 400 ppm "
        "Photosynthese eingeschränkt schlechte Belüftung",
        {"type": "warning", "title": "CO2 zu niedrig – Photosynthese gehemmt",
         "message": ("Unter 400 ppm CO2 wird die Photosynthese merklich eingeschränkt. "
                     "In schlecht belüfteten Räumen kann der CO2-Gehalt durch die Pflanzen "
                     "tagsüber auf Werte unter 300 ppm sinken. "
                     "→ Frischluftzufuhr erhöhen, Lüftungsintervalle anpassen."),
         "scientific_ref": "Ref: GrowSensor – CO2 Monitoring Cannabis (2024)."},
    ),
    (
        "CO2 Anreicherung Cannabis 1000 1500 ppm Ertrag steigern "
        "Photosynthese optimiert supplemental CO2",
        {"type": "info", "title": "CO2-Anreicherung – Optimaler Bereich",
         "message": ("Bei CO2-Anreicherung auf 1000–1500 ppm können Erträge "
                     "um 20–40 % gesteigert werden – aber nur wenn gleichzeitig "
                     "Licht (PPFD >600) und Temperatur (26–30 °C) erhöht werden. "
                     "CO2 ohne ausreichend Licht bringt keinen Mehrwert. "
                     "→ CO2-Zufuhr nur während der Lichtphase, nie in der Dunkelphase."),
         "scientific_ref": "Ref: Cannabis Science & Technology – CO2 Supplementation (2024)."},
    ),
    (
        "CO2 zu hoch Cannabis über 2000 ppm toxisch Pflanze Stress "
        "Blätter einrollen schließen",
        {"type": "warning", "title": "CO2 zu hoch – Toxisch für die Pflanze",
         "message": ("Über 2000 ppm CO2 können Stomata beschädigen und "
                     "die Pflanze in Stress versetzen. "
                     "Auch für den Züchter sind Werte über 5000 ppm gesundheitsschädlich. "
                     "→ CO2-Zufuhr sofort drosseln, CO2-Sensor kalibrieren."),
         "scientific_ref": "Ref: GrowSensor – CO2 Safety Cannabis."},
    ),
    (
        "CO2 nur Lichtphase Cannabis sinnvoll Dunkelphase abschalten "
        "Photosynthese nachts nicht aktiv",
        {"type": "info", "title": "CO2-Timing – Nur in der Lichtphase",
         "message": ("Pflanzen nutzen CO2 ausschließlich während der Photosynthese "
                     "in der Lichtphase. CO2-Zufuhr in der Dunkelphase ist "
                     "pure Verschwendung und erhöht das CO2-Niveau unnötig. "
                     "→ CO2-Controller mit Lichtschalter synchronisieren."),
         "scientific_ref": ""},
    ),
    (
        "CO2 und Temperatur Cannabis zusammen erhöhen Hitzefenster "
        "Pflanze verträgt mehr Wärme bei hohem CO2",
        {"type": "info", "title": "CO2 & Temperatur kombinieren",
         "message": ("Bei erhöhtem CO2 (1000–1500 ppm) können Pflanzen "
                     "höhere Temperaturen (bis 28–30 °C) besser tolerieren, "
                     "da die Photosynthese auch bei höherer Wärme effizient bleibt. "
                     "→ CO2-Supplementation immer mit Temperaturerhöhung kombinieren, "
                     "VPD im Blick behalten."),
         "scientific_ref": "Ref: Emerald Harvest – CO2 & Temperature Cannabis."},
    ),
    (
        "CO2 Messung PPM ungenau Sensor Kalibrierung Cannabis Grow Room",
        {"type": "info", "title": "CO2-Sensor kalibrieren",
         "message": ("NDIR-CO2-Sensoren driften über Zeit und liefern ungenaue Werte. "
                     "→ Sensor alle 6 Monate mit Außenluft (ca. 420 ppm) kalibrieren. "
                     "Günstige Sensoren oft ungenau – vor dem Investieren in CO2-Ausrüstung "
                     "einen zuverlässigen Sensor sicherstellen."),
         "scientific_ref": ""},
    ),

    # ══ M. SUBSTRAT & GROWING MEDIUM ══════════════════════════════════════════
    (
        "Erde verdichtet Cannabis Substrat hart kompakt Wasser fließt "
        "schlecht Drainage gestört Luftmangel",
        {"type": "warning", "title": "Substrat verdichtet – Drainage prüfen",
         "message": ("Verdichtetes Substrat verhindert Gasaustausch und "
                     "führt zu Staunässe. Wasser sollte nach dem Gießen "
                     "binnen 30 Sekunden am Drain ablaufen. "
                     "→ Perlite (20–30 %) nachträglich nicht mehr einmischen – "
                     "für den nächsten Zyklus Substratmischung überarbeiten. "
                     "Akut: Stäbchen vorsichtig in den Erdballen stechen."),
         "scientific_ref": ""},
    ),
    (
        "Perlite Anteil Cannabis Erde Mischung Drainage Luftporen "
        "optimal Verhältnis Substrat lockern",
        {"type": "info", "title": "Perlite-Anteil für optimale Drainage",
         "message": ("Ein Perlite-Anteil von 20–30 % in der Erdmischung "
                     "verbessert Drainage und Belüftung der Wurzelzone erheblich. "
                     "Bei reiner Coco 30–40 % empfohlen. "
                     "Zu viel Perlite (>40 %) reduziert die Wasserhaltekapazität "
                     "und erfordert häufigeres Gießen."),
         "scientific_ref": "Ref: Dutch Passion Growing Medium Guide (2025)."},
    ),
    (
        "Coco Coir Cannabis Kokos Medium puffert Nährstoffe "
        "Calcium Magnesium Coco vor Gebrauch wässern",
        {"type": "info", "title": "Coco Coir – Eigenschaften & Vorbereitung",
         "message": ("Coco Coir hat eine natürliche Affinität für Calcium und Magnesium "
                     "und bindet diese aus der Nährlösung – Cal-Mag-Mangel ist daher "
                     "in Coco besonders häufig. "
                     "→ Rohe Coco vor Gebrauch mit Cal-Mag-Lösung vorwässern ('buffern'), "
                     "pH auf 5.8–6.0, EC-Wert der Lösung auf 0.5–1.0 einstellen."),
         "scientific_ref": "Ref: Canna Coco Professional Guide (2024)."},
    ),
    (
        "Bioerde lebend Cannabis organisch Humus Mikrobiom aktivieren "
        "Aufwärmphase nötig Zeit",
        {"type": "info", "title": "Bioboden – Aktivierungszeit",
         "message": ("Hochwertiger Bioboden braucht 1–2 Wochen um sein mikrobielles "
                     "Ökosystem nach dem Einpflanzen zu aktivieren. "
                     "In dieser Zeit können Pflanzen trotz vollem Substrat "
                     "Mangelerscheinungen zeigen. "
                     "→ Nicht sofort mit zusätzlichem Dünger reagieren – "
                     "Geduld und Beobachtung."),
         "scientific_ref": ""},
    ),
    (
        "Substrat alt erschöpft Cannabis recycled Erde Nährstoffe aufgebraucht "
        "pH verschoben Salze angehäuft",
        {"type": "warning", "title": "Erschöpftes Substrat",
         "message": ("Wiederverwendetes Substrat ohne Aufbereitung enthält "
                     "Salzablagerungen, verschobenen pH und kaum verwertbare Nährstoffe. "
                     "→ Alte Erde 1:1 mit frischem Substrat mischen, "
                     "Perlite ergänzen, mit Bacillus/Trichoderma reaktivieren "
                     "oder frisches Substrat verwenden."),
         "scientific_ref": ""},
    ),
    (
        "Hydroton LECA Blähton Cannabis Hydroponik Medium steril "
        "inert gut für DWC NFT kratky",
        {"type": "info", "title": "LECA / Hydroton – Eigenschaften",
         "message": ("Blähton (LECA) ist inert, steril und bietet excellente "
                     "Sauerstoffversorgung der Wurzeln. Kein Nährstoffpuffer – "
                     "die gesamte Ernährung muss über die Nährlösung erfolgen. "
                     "→ Vor Erstverwendung gründlich waschen und pH-neutralisieren. "
                     "Ideal für DWC, NFT und Kratky-Methode."),
         "scientific_ref": ""},
    ),
    (
        "Staunässe Cannabis Topf kein Abfluss Untersetzer voll "
        "Wasser steht Wurzeln ersticken",
        {"type": "warning", "title": "Staunässe – Sofortmaßnahme",
         "message": ("Stehendes Wasser im Untersetzer oder verstopfte Drainage "
                     "führt innerhalb von 24–48 Stunden zu Wurzelschäden. "
                     "→ Untersetzer sofort leeren, Drainage-Löcher prüfen, "
                     "Pflanze für 1–2 Stunden aus dem Topf nehmen um Wurzeln "
                     "Luft zu gönnen."),
         "scientific_ref": ""},
    ),
    (
        "Substrat Wasser nicht absorbiert Cannabis hydrophob ausgetrocknet "
        "Erde nimmt kein Wasser an",
        {"type": "warning", "title": "Hydrophobes Substrat",
         "message": ("Stark ausgetrocknetes Substrat kann hydrophob werden: "
                     "Wasser läuft an den Topfwänden ab ohne einzudringen. "
                     "→ Topf für 30 Minuten in einen Wassereimer stellen "
                     "(Bottom Watering), oder ein Tröpfchen Netzmittel ins Gießwasser. "
                     "Danach Gießintervalle verkürzen."),
         "scientific_ref": ""},
    ),


    # ══ N. ERNTE, TROCKNUNG & CURING ══════════════════════════════════════════
    (
        "Trocknung Cannabis Temperatur optimal 15 bis 21 Grad "
        "langsam trocknen Terpene erhalten Qualität",
        {"type": "info", "title": "Trocknung – Optimale Temperatur",
         "message": ("Optimale Trocknungstemperatur: 15–21 °C. "
                     "Über 25 °C verdampfen Terpene zu schnell, das Endprodukt "
                     "verliert Aroma und Qualität. Unter 15 °C trocknet zu langsam "
                     "und fördert Schimmel. "
                     "→ Temperatur mit Thermometer überwachen, "
                     "kein direkter Lichteinfall auf die Blüten."),
         "scientific_ref": "Ref: Jin et al. (2019). / Leafly – Cannabis Drying Guide."},
    ),
    (
        "Trocknung Cannabis Luftfeuchtigkeit optimal 45 bis 55 Prozent "
        "Trockenraum langsam schonend",
        {"type": "info", "title": "Trocknung – Optimale Luftfeuchtigkeit",
         "message": ("Beim Trocknen sollte die Luftfeuchtigkeit zwischen 45–55 % liegen. "
                     "Unter 40 % trocknet die Oberfläche zu schnell während innen "
                     "noch Feuchtigkeit steckt (harshes Endprodukt). "
                     "Über 60 % besteht Schimmelgefahr. "
                     "→ Hygrometer im Trockenraum obligatorisch."),
         "scientific_ref": "Ref: Dutch Passion – Drying & Curing Guide (2025)."},
    ),
    (
        "Zu schnell getrocknet Cannabis Gras riecht nach Heu "
        "Chlorophyll nicht abgebaut Qualität schlecht",
        {"type": "warning", "title": "Zu schnell getrocknet – Heu-Geruch",
         "message": ("Wenn Cannabis nach Heu riecht, wurden die Pflanzen zu schnell "
                     "bei zu hoher Temperatur oder zu niedriger Luftfeuchtigkeit getrocknet. "
                     "Chlorophyll und andere pflanzliche Verbindungen konnten nicht "
                     "ordentlich abgebaut werden. "
                     "→ Longer Cure in geschlossenen Gläsern (4–8 Wochen) "
                     "kann den Geruch noch verbessern, jedoch nicht vollständig beheben."),
         "scientific_ref": ""},
    ),
    (
        "Schimmel Trocknung Cannabis Botrytis Blüten feucht nass "
        "Trockenraum zu feucht weiß grau Belag",
        {"type": "warning", "title": "Schimmel beim Trocknen",
         "message": ("Schimmel beim Trocknen entsteht bei Luftfeuchtigkeit über 60 % "
                     " oder schlechter Luftzirkulation. "
                     "→ Befallene Blüten sofort entfernen und entsorgen. "
                     "Ventilator auf niedrigster Stufe für Luftbewegung (nicht direkt "
                     "auf die Blüten richten). Luftentfeuchter einsetzen."),
         "scientific_ref": "Ref: Elad, Y. et al. (1997). / Dutch Passion Drying Guide."},
    ),
    (
        "Curing Cannabis Gläser Weckgläser einlegen reifen Aroma "
        "Terpen Entwicklung Qualität verbessern",
        {"type": "info", "title": "Curing – Reifung in Gläsern",
         "message": ("Nach dem Trocknen (Stiele knacken, Außenseite trocken) "
                     "Blüten in luftdichte Weckgläser (70–80 % voll) einlegen. "
                     "Feuchtigkeitsziel im Glas: 58–62 % (mit Boveda-Packs messbar). "
                     "Curing für 4–8 Wochen verbessert Geschmack, "
                     "Aroma und die psychoaktive Wirkung merklich."),
         "scientific_ref": "Ref: Dutch Passion – Curing Guide (2025)."},
    ),
    (
        "Burping Gläser Cannabis Curing Lüften täglich erste Woche "
        "Feuchte regulieren Sauerstoff zuführen",
        {"type": "info", "title": "Curing – Burping (Lüften der Gläser)",
         "message": ("In der ersten Woche des Curings die Gläser täglich für "
                     "15–30 Minuten öffnen um Restfeuchte abzuführen und "
                     "frischen Sauerstoff zuzuführen. "
                     "Kondensation an den Glasinnenwänden = zu feucht, sofort länger lüften. "
                     "Nach 2 Wochen reicht wöchentliches Lüften."),
         "scientific_ref": ""},
    ),
    (
        "Ernte Zeitpunkt Cannabis Trichome Lupe Mikroskop klar milchig amber "
        "Wirkung Profil THC CBN",
        {"type": "info", "title": "Erntezeitpunkt – Trichom-Analyse",
         "message": ("Klare Trichome: unreif, zu früh. "
                     "Milchweiße Trichome: maximaler THC-Gehalt, energetische Wirkung. "
                     "Bernsteinfarbene (Amber) Trichome: THC baut zu CBN ab, "
                     "sedative Wirkung. "
                     "Empfehlung: 10–30 % Amber für ausgewogene Wirkung. "
                     "Pistillen allein sind unzuverlässig – Lupe oder Mikroskop nutzen."),
         "scientific_ref": "Ref: Jin et al. (2019). American Journal of Plant Sciences."},
    ),
    (
        "Trocknung Stiele knacken Test Cannabis bereit zum Curing "
        "Außen trocken innen noch Feuchte",
        {"type": "info", "title": "Trocknungstest – Stielknack-Methode",
         "message": ("Cannabis ist bereit für das Curing wenn kleine Stiele "
                     "beim Biegen hörbar knacken statt sich zu biegen. "
                     "Typische Trocknungsdauer: 7–14 Tage je nach Umgebung. "
                     "→ Nicht zu früh in Gläser – Restfeuchte über 65 % im Glas "
                     "führt zu Schimmel."),
         "scientific_ref": ""},
    ),
    (
        "Ernte Tageszeit Cannabis morgens früh Harz Terpene maximal "
        "vor Beleuchtung optimaler Moment",
        {"type": "info", "title": "Erntezeit – Morgens vor Belichtungsbeginn",
         "message": ("Das Ernten kurz vor Beginn der Lichtphase gilt als optimal, "
                     "da Terpene und Harze sich nachts in den Blüten ansammeln "
                     "und bei Wärme und Licht schneller verdampfen. "
                     "→ Pflanzen in den letzten 24–48 h vor Ernte verdunkeln "
                     "für maximale Harzproduktion."),
         "scientific_ref": "Ref: Jin et al. (2019)."},
    ),
    (
        "Blüten Gewicht nach Trocknung Verlust Cannabis Wasserverlust "
        "frisch zu trocken Verhältnis normal",
        {"type": "info", "title": "Gewichtsverlust beim Trocknen",
         "message": ("Beim Trocknen verliert Cannabis typischerweise 70–80 % "
                     "seines Frischgewichts durch Wasserentzug. "
                     "Aus 100 g frischen Blüten entstehen ca. 20–30 g getrocknetes Material. "
                     "→ Dieser Verlust ist normal und kein Zeichen schlechter Qualität."),
         "scientific_ref": ""},
    ),

    # ══ O. TRAINING & ERZIEHUNGSMETHODEN ══════════════════════════════════════
    (
        "LST Low Stress Training Cannabis Äste biegen befestigen "
        "Lichtverteilung verbessern flacher Wuchs mehr Knospen",
        {"type": "info", "title": "LST – Low Stress Training",
         "message": ("LST (Low Stress Training) bedeutet Äste sanft biegen und "
                     "mit Binddraht oder Clips befestigen um eine flache, "
                     "horizontale Krone zu formen. "
                     "Alle Knospenansätze bekommen gleichmäßig Licht → mehr Ertrag. "
                     "→ Ideal in der vegetativen Phase, Autoflowering ebenfalls möglich. "
                     "Vorsicht: Äste zu Beginn der Blüte deutlich weniger biegen "
                     "– sie werden spröde."),
         "scientific_ref": ""},
    ),
    (
        "Topping Cannabis Triebspitze abschneiden zwei Haupttriebe "
        "Ertrag verdoppeln Buschform vegetativ",
        {"type": "info", "title": "Topping – Zwei Haupttriebe erzeugen",
         "message": ("Beim Topping wird der apikale Meristem (Haupttrieb) "
                     "abgeschnitten, wodurch die Pflanze zwei gleichwertige "
                     "Haupttriebe entwickelt. "
                     "Mehrfaches Topping erzeugt einen buschigen Wuchs mit "
                     "vielen Hauptknospen. "
                     "→ Erst nach 4–5 Blattpaaren toppen. "
                     "Mindestens 2 Wochen Erholung vor Blüteninduktion. "
                     "Niemals bei Autoflowering empfohlen."),
         "scientific_ref": ""},
    ),
    (
        "FIM Cannabis Technik weniger Stress als Topping vier Triebe "
        "Wachstumsspitze teilweise entfernen",
        {"type": "info", "title": "FIM – Vier Triebe statt zwei",
         "message": ("Die FIM-Technik ('F**k I Missed') entfernt nur 75 % "
                     "der Wachstumsspitze anstatt sie komplett abzuschneiden. "
                     "Das Ergebnis sind 3–4 neue Haupttriebe und weniger Stress "
                     "als beim vollständigen Topping. "
                     "→ Mit einer scharfen Schere schräg in die Triebspitze schneiden. "
                     "Ergebnis ist weniger vorhersehbar als Topping."),
         "scientific_ref": ""},
    ),
    (
        "SCROG Screen of Green Cannabis Netz Gitter Blüten gleichmäßig "
        "Licht maximieren Ertrag Indoor",
        {"type": "info", "title": "SCROG – Screen of Green",
         "message": ("SCROG nutzt ein horizontales Netz in ca. 20–40 cm Pflanzenhöhe. "
                     "Triebe werden durch die Maschen geführt um eine gleichmäßige "
                     "Blütenebene zu erzeugen – alle Knospen im gleichen Abstand zur Lampe. "
                     "→ Netz 2–4 Wochen vor Blüteninduktion einsetzen. "
                     "Kein Umsetzen nach dem Einnetzen möglich."),
         "scientific_ref": ""},
    ),
    (
        "Lollipopping Defoliation Cannabis untere Äste entfernen "
        "Energiefluss nach oben Blätter ausdünnen Hauptblüten fördern",
        {"type": "info", "title": "Lollipopping & Defoliation",
         "message": ("Beim Lollipopping werden die unteren Äste und Knospen "
                     "die wenig Licht bekommen entfernt. Die Pflanze lenkt ihre "
                     "Energie in die oberen Hauptknospen. "
                     "→ Zu Beginn der Blüte (Woche 1–2) und erneut in Woche 3–4 möglich. "
                     "Nicht mehr als 20–30 % der Blattmasse auf einmal entfernen."),
         "scientific_ref": ""},
    ),
    (
        "Supercropping Cannabis Knickung Stängel harte Stressmethode "
        "HST High Stress Training verdicken mehr Nährstoffe",
        {"type": "info", "title": "Supercropping – Kontrolliertes Knicken",
         "message": ("Supercropping bedeutet einen Stängel vorsichtig zwischen "
                     "Daumen und Zeigefinger weich zu kneten bis er sich biegt "
                     "ohne zu brechen. Die Pflanze bildet an der Knickstelle "
                     "eine verdickte Narbe ('Knoten') die als Nährstoffpumpe wirkt. "
                     "→ Nur an gesunden, gut entwickelten Pflanzen in der Veg-Phase anwenden. "
                     "Geknickte Stelle mit Tape fixieren."),
         "scientific_ref": ""},
    ),
    (
        "Mainlining Manifold Cannabis symmetrische Struktur acht Knospen "
        "gleichmäßig Training Topfen",
        {"type": "info", "title": "Mainlining / Manifold",
         "message": ("Mainlining kombiniert Topping, LST und Defoliation "
                     "um eine perfekt symmetrische Pflanzenkrone mit "
                     "genau 8 gleichstarken Hauptästen zu erzeugen. "
                     "→ Zeitintensiv (6–8 Wochen reine Veg-Phase nötig), "
                     "aber mit sehr gleichmäßigem Ertrag. "
                     "Nicht für Autoflowering geeignet."),
         "scientific_ref": ""},
    ),
    (
        "SOG Sea of Green Cannabis viele kleine Pflanzen schnell blühen "
        "Ertrag maximieren kurze Vegetationszeit",
        {"type": "info", "title": "SOG – Sea of Green",
         "message": ("SOG nutzt viele kleine Pflanzen (4–16 pro m²) "
                     "die nach nur 1–2 Wochen Vegetationszeit zur Blüte gebracht werden. "
                     "Jede Pflanze bildet einen großen Hauptknospen. "
                     "→ Klone statt Samen für gleichmäßige Größe. "
                     "Hohe Pflanzendichte erfordert gute Luftzirkulation "
                     "um Schimmelrisiko zu minimieren."),
         "scientific_ref": ""},
    ),

    # ══ P. AUTOFLOWERING – BESONDERHEITEN ═════════════════════════════════════
    (
        "Autoflowering Cannabis kein 12 12 Lichtwechsel nötig "
        "automatisch blüht nach Zeit ruderalis",
        {"type": "info", "title": "Autoflowering – Lichtzyklus",
         "message": ("Autoflowering-Sorten (Cannabis ruderalis-Hybriden) "
                     "blühen zeitgesteuert unabhängig vom Lichtzyklus. "
                     "Optimaler Lichtplan: 18–20 Stunden Licht täglich von Keimung bis Ernte. "
                     "→ Kein 12/12-Wechsel nötig oder sinnvoll. "
                     "Mehr Licht = mehr Energie = mehr Ertrag."),
         "scientific_ref": "Ref: 2Fast4Buds Autoflowering Guide (2024)."},
    ),
    (
        "Autoflowering Stress vermeiden Cannabis Umtopfen Topping "
        "HST keine Zeit zur Erholung kurze Lebenszeit",
        {"type": "warning", "title": "Autoflowering – Stress minimieren",
         "message": ("Autoflowering-Pflanzen haben einen festgelegten Lebenszyklus "
                     "von 60–90 Tagen und kaum Zeit um sich von Stress zu erholen. "
                     "Topping, HST, häufiges Umtopfen und starker Nährstoffstress "
                     "können den Endertrag erheblich reduzieren. "
                     "→ LST ist akzeptabel, invasive Methoden vermeiden. "
                     "Gleich in den Endtopf pflanzen."),
         "scientific_ref": "Ref: Royal Queen Seeds – Autoflowering Growing Tips (2024)."},
    ),
    (
        "Autoflowering Düngung Cannabis weniger Nährstoffe als Photoperiod "
        "EC niedriger empfindlich",
        {"type": "info", "title": "Autoflowering – Nährstoffbedarf",
         "message": ("Autoflowering-Pflanzen haben in der Regel einen geringeren "
                     "Nährstoffbedarf als Photoperiod-Sorten. "
                     "EC-Werte sollten 20–30 % unter den Empfehlungen für "
                     "normale Cannabis-Sorten liegen. "
                     "→ Mit halber Dosis beginnen und langsam steigern. "
                     "Nutrient Burn bei Autos ist häufig."),
         "scientific_ref": "Ref: Fast Buds – Auto Nutrient Guide (2024)."},
    ),
    (
        "Autoflowering Topfgröße Cannabis 11 15 Liter optimal "
        "nicht zu groß nicht zu klein Wachstum",
        {"type": "info", "title": "Autoflowering – Optimale Topfgröße",
         "message": ("Für Autoflowering-Sorten sind 11–15 Liter Töpfe optimal. "
                     "Zu kleine Töpfe (unter 7 L) schränken das Wurzelwachstum ein, "
                     "zu große Töpfe (über 20 L) können zu Überwässerungsproblemen führen. "
                     "→ Direkt in den Endtopf säen – Umtopfen kostet wertvolle Zeit."),
         "scientific_ref": "Ref: 2Fast4Buds Autoflowering Guide (2024)."},
    ),
    (
        "Autoflowering Klon Steckling Cannabis nicht sinnvoll "
        "genetische Uhr läuft weiter Klone blühen sofort",
        {"type": "info", "title": "Autoflowering – Kein Cloning empfohlen",
         "message": ("Klone von Autoflowering-Pflanzen übernehmen die genetische 'Uhr' "
                     "der Mutterpflanze und beginnen sofort zu blühen, "
                     "ohne nennenswerte Vegetationszeit. "
                     "Ertrag ist damit minimal. "
                     "→ Autoflowering immer aus Samen anbauen, nicht aus Klonen."),
         "scientific_ref": ""},
    ),
    (
        "Autoflowering frühes Blühen Cannabis Woche 3 4 Vorblüte "
        "keine Panik normal automatisch Blütenstimulation",
        {"type": "info", "title": "Autoflowering – Frühe Blütenanzeichen normal",
         "message": ("Autoflowering-Pflanzen zeigen oft schon in Woche 3–4 "
                     "erste Vorblütezeichen. Das ist völlig normal und kein Problem. "
                     "Die Pflanze wächst vegetativ weiter während die Blüte beginnt. "
                     "→ Jetzt auf Blütedünger mit mehr P und K umstellen."),
         "scientific_ref": ""},
    ),

    # ══ Q. HYDROPONIK & COCO-SPEZIFIKA ════════════════════════════════════════
    (
        "EC Wert zu hoch Cannabis Hydroponik Coco über 3.5 "
        "Nutrient Burn Blattspitzen verbrannt Salzstress",
        {"type": "warning", "title": "EC zu hoch – Salzstress",
         "message": ("Ein EC-Wert über 3.5 mS/cm in der Nährlösung kann "
                     "osmotischen Stress verursachen: Pflanze nimmt kaum noch Wasser auf, "
                     "Blattspitzen verbrennen. "
                     "→ Nährlösung mit pH-neutralem Wasser verdünnen, "
                     "System durchspülen, EC auf Zielwert senken."),
         "scientific_ref": "Ref: Cannabis Science & Technology – EC Management (2024)."},
    ),
    (
        "EC Wert zu niedrig Cannabis Hydroponik unter 0.8 "
        "Nährstoffmangel Pflanze hungert langsames Wachstum",
        {"type": "warning", "title": "EC zu niedrig – Pflanze hungert",
         "message": ("Ein EC-Wert unter 0.8 mS/cm bedeutet zu wenige Nährstoffe "
                     "in der Lösung. Die Pflanze zeigt langsames Wachstum und "
                     "Mangelerscheinungen trotz ausreichend Wasser. "
                     "→ Nährstoffkonzentration erhöhen, Zielwert je nach Phase: "
                     "Sämling 0.5–0.8, Veg 1.0–2.0, Blüte 1.5–2.5 mS/cm."),
         "scientific_ref": ""},
    ),
    (
        "EC Abfluss Messung Cannabis Runoff Erde Coco Salze aufgebaut "
        "Kontrolle Flush nötig",
        {"type": "info", "title": "Runoff-EC messen",
         "message": ("Den EC-Wert des Abflusswassers (Runoff) messen zeigt an, "
                     "ob sich Salze im Substrat aufbauen. "
                     "Runoff-EC mehr als 0.5 über dem Einlauf-EC = Salzaufbau. "
                     "→ Mit 3× Topfvolumen pH-korrigiertem Wasser spülen "
                     "und danach mit normaler Düngung neu starten."),
         "scientific_ref": "Ref: Canna – EC Management in Coco (2024)."},
    ),
    (
        "Reservoirtemperatur DWC Cannabis Wasser zu warm über 22 Grad "
        "Sauerstoff sinkt Wurzelfäule Risiko",
        {"type": "warning", "title": "Reservoir zu warm – DWC Sauerstoffproblem",
         "message": ("Nährlösung in DWC-Systemen über 22 °C enthält deutlich "
                     "weniger gelösten Sauerstoff und begünstigt Pythium-Wachstum. "
                     "Optimale Reservoir-Temperatur: 18–20 °C. "
                     "→ Reservoir isolieren, Eisblöcke in gefrorenen Wasserflaschen, "
                     "Aquarium-Kühlsystem oder Klimaanlage."),
         "scientific_ref": "Ref: ILGM – DWC Root Rot Prevention (2025)."},
    ),
    (
        "Bewässerungsfrequenz Coco Cannabis täglich mehrmals "
        "immer feucht nicht nass wet dry Zyklus",
        {"type": "info", "title": "Coco – Bewässerungsfrequenz",
         "message": ("Coco Coir verträgt anders als Erde häufigeres Gießen: "
                     "1–3× täglich gießen ist bei gut entwickelten Pflanzen normal. "
                     "Ziel: Coco soll nie vollständig austrocknen, "
                     "aber auch nicht dauerhaft durchnässt sein. "
                     "→ 10–20 % Runoff bei jeder Bewässerung anstreben "
                     "um Salzaufbau zu verhindern."),
         "scientific_ref": "Ref: Canna – Coco Growing Guide (2024)."},
    ),
    (
        "Nährlösung Wechsel Hydroponik DWC Cannabis Reservoirwechsel "
        "Woche Intervall frisch halten",
        {"type": "info", "title": "DWC – Nährlösungswechsel",
         "message": ("In DWC-Systemen sollte die Nährlösung alle 1–2 Wochen "
                     "komplett gewechselt werden um pH-Drift, "
                     "Salzaufbau und Bakterienwachstum zu verhindern. "
                     "→ Beim Wechsel Reservoir reinigen, Wurzeln auf Gesundheit prüfen "
                     "und frische Lösung auf die richtige Temperatur bringen."),
         "scientific_ref": ""},
    ),
    (
        "Sauerstoff DWC Cannabis Luftpumpe Luftstein Belüftung "
        "dissolved oxygen Wurzeln atmen",
        {"type": "info", "title": "DWC – Sauerstoffversorgung",
         "message": ("In DWC-Systemen ist die Sauerstoffversorgung der Wurzeln kritisch. "
                     "Mindestens 1 Luftstein pro 10 Liter Reservoir. "
                     "Gelöster Sauerstoff (DO) sollte über 6 mg/l liegen. "
                     "→ Luftpumpe nie ausschalten, auch nicht nachts. "
                     "Größerer Luftstein und stärkere Pumpe bei großen Reservoirs."),
         "scientific_ref": "Ref: Cannoptikum – DWC Oxygen Guide (2024)."},
    ),
    (
        "Flush Hydroponik Coco Cannabis Ende Blüte Nährstoffe abbau "
        "klares Wasser Geschmack verbessern",
        {"type": "info", "title": "Flush in Hydro/Coco",
         "message": ("In Hydro und Coco ist der Pre-Harvest Flush einfacher als in Erde: "
                     "In den letzten 7–10 Tagen vor Ernte nur pH-korrigiertes Wasser verwenden. "
                     "In DWC das Reservoir mit reinem Wasser füllen. "
                     "→ EC des Runoffs sollte auf unter 0.5 sinken "
                     "bevor geerntet wird."),
         "scientific_ref": ""},
    ),

    # ══ R. SEXBESTIMMUNG & HERMAPHRODITISMUS ══════════════════════════════════
    (
        "Hermaphroditismus Cannabis Pflanze Nanners Bananenstaubgefäße "
        "Selbstbestäubung Samen Stressgenetik",
        {"type": "warning", "title": "Hermaphroditismus – Nanners entdeckt",
         "message": ("Nanners (bananenförmige Staubgefäße mitten in Blüten) bedeuten, "
                     "dass die Pflanze Pollen produziert und sich selbst "
                     "oder Nachbarpflanzen bestäuben kann. "
                     "→ Nanners täglich mit feuchter Pinzette entfernen, "
                     "Raum auf Pollenkontamination überprüfen. "
                     "Bei starkem Befall: Ernte vorziehen oder Pflanze isolieren."),
         "scientific_ref": ""},
    ),
    (
        "Hermaphroditismus Auslöser Cannabis Lichtverschmutzung Stress "
        "Hitzestress genetische Instabilität Feminisierung",
        {"type": "warning", "title": "Hermaphroditismus – Ursachen",
         "message": ("Häufigste Auslöser für Hermaphroditismus: "
                     "Lichtverschmutzung während der Dunkelphase, "
                     "extremer Hitzestress, Nährstoffmangel in der Blüte, "
                     "und genetisch instabile feminisierte Samen. "
                     "→ Dunkelphase vollständig abdunkeln, "
                     "Stress minimieren, auf Samen von renommierten Züchtern setzen."),
         "scientific_ref": "Ref: Jin et al. (2019). / RQS Hermaphrodite Guide."},
    ),
    (
        "Männliche Pflanze Cannabis erkennen Pollensäcke vegetativ "
        "vor Blüte Geschlecht bestimmen Vorblüte",
        {"type": "warning", "title": "Männliche Pflanze erkennen",
         "message": ("Männliche Cannabis-Pflanzen zeigen in der Vorblüte "
                     "(nach 4–6 Wochen oder bei 12/12) kleine, traubenartige "
                     "Pollensäcke an den Knoten – keine Kelchblätter mit Pistillen. "
                     "→ Männliche Pflanzen sofort und vorsichtig aus dem Grow-Raum entfernen "
                     "bevor die Pollensäcke öffnen. Kontakt mit weiblichen Blüten vermeiden."),
         "scientific_ref": ""},
    ),
    (
        "Weibliche Pflanze Cannabis erkennen Vorblüte Pistillen weiße Haare "
        "Kelchblatt Calyx Vorblüte",
        {"type": "info", "title": "Weibliche Pflanze erkennen",
         "message": ("Weibliche Cannabis-Pflanzen zeigen in der Vorblüte "
                     "Kelchblätter (Calyxe) mit zwei weißen Pistillen (Haaren). "
                     "Diese erscheinen zuerst an den obersten Knoten. "
                     "→ Bestätigung abwarten bevor alle Pflanzen auf 12/12 gewechselt werden. "
                     "Feminisierte Samen eliminieren diesen Schritt weitgehend."),
         "scientific_ref": ""},
    ),
    (
        "Pollenkontamination Cannabis Samen ungewollt bestäubt "
        "Blüten voller Samen Ernte ruiniert",
        {"type": "warning", "title": "Pollenkontamination – Ernte beeinträchtigt",
         "message": ("Bestäubte Cannabis-Blüten bilden Samen und reduzieren "
                     "den Cannabinoid- und Terpengehalt erheblich. "
                     "Das Ergebnis ist minderwertige, samenhaltige Ernte. "
                     "→ Kontaminationsquelle identifizieren (männliche Pflanze, Nanners), "
                     "Raum mit feuchten Tüchern auswischen um Pollen zu binden, "
                     "Pflanzen notfalls früh ernten."),
         "scientific_ref": ""},
    ),

    # ══ S. KEIMUNG & FRÜHE ENTWICKLUNG ════════════════════════════════════════
    (
        "Keimung Cannabis Temperatur optimal 22 bis 26 Grad "
        "Samen keimen nicht zu kalt zu warm",
        {"type": "info", "title": "Keimung – Optimale Temperatur",
         "message": ("Cannabis-Samen keimen am zuverlässigsten bei 22–26 °C. "
                     "Unter 20 °C verlangsamt sich die Keimung stark, "
                     "über 30 °C können Keimwurzeln beschädigt werden. "
                     "→ Samen in feuchtes Papiertuch wickeln, "
                     "in einem warmen Ort (z.B. oben auf Kühlschrank) lagern."),
         "scientific_ref": "Ref: Royal Queen Seeds – Germination Guide (2024)."},
    ),
    (
        "Samen keimt nicht Cannabis tot schlechte Qualität "
        "alte Samen zu trocken zu nass nicht keimfähig",
        {"type": "warning", "title": "Samen keimt nicht – Ursachen",
         "message": ("Wenn Samen nach 5–7 Tagen noch nicht gekeimt sind: "
                     "Mögliche Ursachen sind zu alte Samen (über 2 Jahre), "
                     "zu kalte Umgebung, zu trockenes oder zu nasses Keimmedium, "
                     "oder beschädigte Samenschale. "
                     "→ Schale vorsichtig mit Sandpapier anritzen (Scarification), "
                     "erneut in frischem Wasser für 12–24 h einweichen."),
         "scientific_ref": ""},
    ),
    (
        "Keimling kippt um Cannabis Damping Off Fusarium Substrat "
        "zu feucht Pilz Stängel eingeschnürt",
        {"type": "warning", "title": "Damping Off – Keimling kippt um",
         "message": ("Wenn Keimlinge plötzlich an der Substratoberfläche umkippen "
                     "und absterben, handelt es sich wahrscheinlich um 'Damping Off' "
                     "verursacht durch Fusarium oder Pythium. "
                     "Ursache: zu feuchtes Substrat und schlechte Luftzirkulation. "
                     "→ Substrat abtrocknen lassen, Luftzirkulation verbessern, "
                     "befallene Pflanzen sofort entfernen."),
         "scientific_ref": "Ref: GPNMag – Root Rots and Damping-Off Cannabis (2019)."},
    ),
    (
        "Keimling streckt sich Cannabis zu wenig Licht Etiolierung "
        "langer dünner Stängel Lampe zu weit weg",
        {"type": "warning", "title": "Keimling streckt sich – Lichtmangel",
         "message": ("Ein Keimling der sich stark in die Höhe streckt "
                     "(langer, dünner Stängel) sucht nach Licht. "
                     "→ Lampe näher heranführen (LED: 30–40 cm, CFL: 10–15 cm), "
                     "Stängel bis zu den Keimblättern mit Substrat aufschütten "
                     "um ihn zu stützen."),
         "scientific_ref": ""},
    ),
    (
        "Keimblätter Cannabis gelb falten Cotyledonen Fehler "
        "zu viel Dünger Sämlinge empfindlich",
        {"type": "warning", "title": "Keimblätter gelb – Überdüngung",
         "message": ("Gelbe oder sich faltende Keimblätter bei sehr jungen Sämlingen "
                     "deuten fast immer auf zu viel Dünger oder zu starkes Licht hin. "
                     "Sämlinge brauchen in den ersten 1–2 Wochen keinen Zusatzdünger "
                     "wenn nahrhaftes Substrat verwendet wird. "
                     "→ Nur mit klarem Wasser gießen bis die ersten Blattpaare erscheinen."),
         "scientific_ref": ""},
    ),
    (
        "Keimlingspflege erste Woche Cannabis sanftes Licht "
        "Feuchtigkeit Dome Schutz Temperatur stabil",
        {"type": "info", "title": "Keimlingsphase – Optimale Bedingungen",
         "message": ("In der ersten Woche nach dem Keimen brauchen Sämlinge: "
                     "sanftes, indirektes Licht (keine volle LED-Intensität), "
                     "Luftfeuchtigkeit 60–70 % (Dome oder Plastikabdeckung), "
                     "Temperatur 22–25 °C und minimale Luftbewegung. "
                     "→ Erst nach 1–2 Wochen schrittweise an normale Bedingungen gewöhnen."),
         "scientific_ref": ""},
    ),

    # ══ T. KLONE & MUTTERPFLANZEN ══════════════════════════════════════════════
    (
        "Steckling welkt Cannabis nach dem Schnitt normal Wassertransport "
        "noch keine Wurzeln Dome Feuchtigkeit",
        {"type": "info", "title": "Steckling welkt – Normal in den ersten Tagen",
         "message": ("Frisch geschnittene Stecklinge ohne Wurzeln nehmen "
                     "Wasser ausschließlich über die Blätter auf. "
                     "Leichtes Welken in den ersten 2–3 Tagen ist normal. "
                     "→ Luftfeuchtigkeit im Dome auf 80–90 % halten, "
                     "kein direktes starkes Licht, nicht täglich sprühen."),
         "scientific_ref": ""},
    ),
    (
        "Steckling Bewurzelung Cannabis Wurzelhormon Clonex "
        "IBA Indolbuttersäure Erfolgsrate verbessern",
        {"type": "info", "title": "Steckling – Bewurzelungshormon",
         "message": ("Das Eintauchen des Stielansatzes in Bewurzelungshormon "
                     "(IBA, z.B. Clonex-Gel) erhöht die Erfolgsrate bei Klonen erheblich. "
                     "→ Schnitt im 45°-Winkel unter Wasser ausführen, "
                     "sofort in Gel tauchen, dann ins Anzuchtmedium stecken. "
                     "Erste Wurzeln nach 7–14 Tagen sichtbar."),
         "scientific_ref": ""},
    ),
    (
        "Mutterpflanze Cannabis vegetativ dauerhaft gesund halten "
        "Klonquelle 18 6 Lichtplan Nährstoffe",
        {"type": "info", "title": "Mutterpflanze – Pflege & Erhalt",
         "message": ("Mutterpflanzen werden dauerhaft unter 18/6 gehalten "
                     "um den vegetativen Zustand zu erhalten. "
                     "Sie brauchen regelmäßige Stickstoffversorgung und "
                     "dürfen nie blühen. "
                     "→ Alle 3–4 Monate auffrischen (zurückschneiden, neues Substrat). "
                     "Kranke Mutterpflanzen niemals klonen."),
         "scientific_ref": ""},
    ),
    (
        "Steckling Krankheit Virus Cannabis von Mutterpflanze "
        "übertragen hop latent viroid HLVd",
        {"type": "warning", "title": "Krankheitsübertragung via Klon",
         "message": ("Klone übertragen alle Krankheiten der Mutterpflanze, "
                     "einschließlich Hop Latent Viroid (HLVd), das Erträge "
                     "um 30–50 % reduzieren kann ohne sichtbare Symptome. "
                     "→ Neue Genetiken immer quarantänisieren, "
                     "Werkzeug nach jedem Schnitt desinfizieren (70 % Isopropanol)."),
         "scientific_ref": "Ref: UC Davis – HLVd Cannabis Research (2022)."},
    ),
    (
        "Klon Bewurzelung zu langsam Cannabis mehr als 3 Wochen "
        "keine Wurzeln Steckling stirbt Problem Medium",
        {"type": "warning", "title": "Steckling – Bewurzelung verzögert",
         "message": ("Wenn Stecklinge nach 3 Wochen noch keine sichtbaren Wurzeln haben: "
                     "Mögliche Ursachen sind zu hohe oder zu niedrige Temperatur "
                     "(optimal: 22–25 °C), falsche Luftfeuchtigkeit, "
                     "zu tiefes oder zu flaches Stecken, oder kranke Mutterpflanze. "
                     "→ Medium prüfen, Luftfeuchtigkeit erhöhen, Licht reduzieren."),
         "scientific_ref": ""},
    ),


    # ══ U. WEITERE SCHÄDLINGE & KRANKHEITEN ══════════════════════════════════
    (
        "Blattläuse Cannabis Aphiden grün weiß schwarz Kolonie "
        "Unterseite klebriger Honigtau klebrig",
        {"type": "warning", "title": "Blattläuse (Aphiden)",
         "message": ("Blattläuse saugen Pflanzensaft und scheiden klebrigen Honigtau aus, "
                     "der Rußtau-Pilze fördert. Kolonien wachsen schnell. "
                     "→ Nützlinge einsetzen (Schlupfwespen, Marienkäfer), "
                     "Neem-Öl Spray (nicht in Blüte), befallene Triebe entfernen. "
                     "Ameisen vom Grow fernhalten – sie 'züchten' Blattläuse."),
         "scientific_ref": ""},
    ),
    (
        "Thripse Cannabis silbrige Streifen Blätter Schabspuren "
        "winzige Insekten Fliegen Larven",
        {"type": "warning", "title": "Thripse",
         "message": ("Thripse hinterlassen silbrige Schabspuren und winzige "
                     "schwarze Kotpunkte auf Blättern. "
                     "Sie übertragen Pflanzenviren und können sich schnell ausbreiten. "
                     "→ Gelbklebe-Fallen aufstellen, Spinosad oder Pyrethrum sprühen "
                     "(nicht in Blüte), Steinernema feltiae Nematoden im Substrat."),
         "scientific_ref": ""},
    ),
    (
        "Weiße Fliegen Cannabis Mottenschildläuse Unterseite "
        "weiße Fliegen aufscheuchen Blätter gelb",
        {"type": "warning", "title": "Weiße Fliegen (Mottenschildläuse)",
         "message": ("Weiße Fliegen (Trialeurodes vaporariorum) saugen an den "
                     "Blattunterseiten und verursachen Vergilbung und Schwächung. "
                     "→ Gelbklebe-Fallen, Encarsia formosa Schlupfwespen einsetzen, "
                     "befallene Blätter entfernen. Neem-Öl als Spray wirksam."),
         "scientific_ref": ""},
    ),
    (
        "Raupen Eulenfalter Cannabis Blüten fressen Schmetterlinge Larven "
        "Echter Caterpillar Schaden Blüte",
        {"type": "warning", "title": "Raupen – Blütenfresser",
         "message": ("Raupen (v.a. Eulenfalter-Larven) fressen sich in Blüten hinein "
                     "und hinterlassen Kotspuren und beschädigte Knospen. "
                     "Der Fraß öffnet Eintrittstore für Botrytis. "
                     "→ Täglich Blüten kontrollieren, Raupen von Hand entfernen, "
                     "Bacillus thuringiensis (Bt) als biologisches Insektizid sprühen."),
         "scientific_ref": ""},
    ),
    (
        "Wurzelläuse Cannabis Befall Substrat weiße Insekten Wurzeln "
        "Nährstoffaufnahme gestört Wachstum stoppt",
        {"type": "warning", "title": "Wurzelläuse",
         "message": ("Wurzelläuse (Phylloxera, Wurzelläuse) sind schwer zu entdecken "
                     "und leben direkt an den Wurzeln. Symptome ähneln Nährstoffmangel "
                     "oder Überwässerung trotz normaler Pflege. "
                     "→ Wurzeln beim Umtopfen inspizieren, "
                     "Steinernema carpocapsae Nematoden ins Substrat gießen."),
         "scientific_ref": ""},
    ),
    (
        "Spinnmilben Rote Spinne Cannabis Blüte behandeln "
        "Pyrethrum nicht empfohlen alternative Behandlung",
        {"type": "warning", "title": "Spinnmilben in der Blüte – Eingeschränkte Optionen",
         "message": ("In der Blütephase sind chemische Behandlungen stark eingeschränkt. "
                     "Pyrethrum und Neem sollten in der Blüte nicht mehr eingesetzt werden. "
                     "→ Raubmilben (Phytoseiulus persimilis) einsetzen, "
                     "Kaliumseife-Spray auf Blattunterseiten, Luftfeuchtigkeit erhöhen. "
                     "Bei starkem Befall in Blüte: Ernte vorziehen."),
         "scientific_ref": ""},
    ),
    (
        "Bakteriose Cannabis Pseudomonas Feuerbrand weiche faulende Stellen "
        "Stängel Blätter braun nass verrottet",
        {"type": "warning", "title": "Bakterielle Infektion",
         "message": ("Weiche, wässrig-braune Stellen an Stängeln oder Blättern "
                     "können auf bakterielle Infektionen (z.B. Pseudomonas) hindeuten. "
                     "Häufig ausgelöst durch mechanische Beschädigung oder "
                     "zu hohe Luftfeuchtigkeit kombiniert mit Wunden. "
                     "→ Betroffene Teile sauber entfernen, Schnittflächen mit "
                     "Colloidal Silver oder Kupfersulfat behandeln."),
         "scientific_ref": ""},
    ),
    (
        "Hopfen Latentes Viroid HLVd Cannabis Stunting Zwergwuchs "
        "schlechte Ernte keine Symptome sichtbar Virus",
        {"type": "warning", "title": "Hop Latent Viroid (HLVd)",
         "message": ("HLVd ist ein hochansteckendes Viroid das Erträge um 30–50 % "
                     "reduziert, oft ohne sichtbare Symptome. "
                     "Übertragung durch kontaminiertes Schneidwerkzeug oder infizierte Klone. "
                     "→ Werkzeug nach jedem Schnitt mit 70 % Isopropanol desinfizieren, "
                     "neue Genetiken quarantänisieren und testen lassen."),
         "scientific_ref": "Ref: UC Davis – HLVd in Cannabis sativa (2022)."},
    ),

    # ══ V. BLÜTENINDUKTION & PHOTOPERIODE ═════════════════════════════════════
    (
        "Blüteninduktion Cannabis 12 12 Lichtwechsel erste Woche "
        "Strecken Stretch normal wie viel",
        {"type": "info", "title": "Blüteninduktion – Erwarteter Stretch",
         "message": ("Nach dem Wechsel auf 12/12 strecken sich die meisten "
                     "Photoperiod-Cannabis-Sorten in den ersten 2 Wochen stark. "
                     "Sativa-dominante Sorten können sich auf das 2–3-fache strecken, "
                     "Indica-dominante auf das 1.5–2-fache. "
                     "→ Lampenabstand rechtzeitig anpassen, Endgröße einkalkulieren."),
         "scientific_ref": ""},
    ),
    (
        "Vorblüte Cannabis Geschlecht erkennen Kelchblätter Pistillen "
        "Knoten Präblüte Bestimmung",
        {"type": "info", "title": "Vorblüte – Geschlechtsbestimmung",
         "message": ("In der Vorblüte (nach 4–8 Wochen vegetativ oder bei kurzen Lichttagen) "
                     "erscheinen an den Knoten erste Blütenanlagen. "
                     "Weiblich: kleine Calyxe mit zwei weißen Härchen (Pistillen). "
                     "Männlich: kleine, runde traubenartige Pollensäcke. "
                     "→ Lupe verwenden, mehrere Knoten kontrollieren."),
         "scientific_ref": ""},
    ),
    (
        "Revegging Cannabis Reblüte aus Blüte zurück vegetativ "
        "Monster Cropping Klone aus Blüte",
        {"type": "info", "title": "Re-Vegging – Zurück in die Vegetationsphase",
         "message": ("Re-Vegging (Erneutes Vegetieren) geschieht wenn eine blühende "
                     "Pflanze wieder auf 18/6 Licht gesetzt wird. "
                     "Die Pflanze bildet unförmige, mehrlappige Blätter "
                     "und wächst wieder vegetativ. "
                     "→ Re-Vegging dauert 4–6 Wochen, ist für Monster-Cropping (Klone "
                     "aus der Blüte) nützlich, aber zeitaufwändig."),
         "scientific_ref": ""},
    ),
    (
        "Lichtplan Cannabis 12 12 Dunkelphase stören Lichtverschmutzung "
        "Hermi Stresslicht Timer Fehler",
        {"type": "warning", "title": "Dunkelphase – Keine Unterbrechung",
         "message": ("Jede Lichtunterbrechung während der Dunkelphase – "
                     "auch kurz (z.B. Handytaschenlampe) – kann bei Photoperiod-Sorten "
                     "den Blührhythmus stören und Hermaphroditismus auslösen. "
                     "→ Grow-Tent vollständig lichtdicht machen, "
                     "Timer-Einstellungen doppelt prüfen, "
                     "Grow-Raum nur in der Lichtphase betreten."),
         "scientific_ref": "Ref: Jin et al. (2019). / RQS Photoperiod Guide."},
    ),
    (
        "Cannabis Sättigungsphotoperiode nicht blühen Photoperiod Samen "
        "lange Vegetationszeit geplant",
        {"type": "info", "title": "Vegetationsphase verlängern",
         "message": ("Photoperiod-Pflanzen blühen nicht solange sie mehr als "
                     "14–16 Stunden Licht pro Tag erhalten. "
                     "→ 18/6-Lichtplan für unbegrenzte Vegetationszeit. "
                     "Länger vegetieren = größere Pflanze = mehr Ertrag, "
                     "aber auch mehr Platz und Zeit nötig."),
         "scientific_ref": ""},
    ),

    # ══ W. EC, NÄHRLÖSUNGSMANAGEMENT & DÜNGESTRATEGIE ═════════════════════════
    (
        "EC Phasen Cannabis Sämling Veg Blüte optimaler Wert "
        "Nährstoffkonzentration Tabelle",
        {"type": "info", "title": "EC-Zielwerte nach Wachstumsphase",
         "message": ("Empfohlene EC-Werte nach Phase: "
                     "Sämling/Steckling: 0.4–0.8 mS/cm, "
                     "Vegetativ: 1.0–2.0 mS/cm, "
                     "Frühe Blüte: 1.5–2.2 mS/cm, "
                     "Späte Blüte: 1.8–2.5 mS/cm, "
                     "Pre-Harvest Flush: unter 0.5 mS/cm. "
                     "→ Immer mit Runoff-Messung kontrollieren."),
         "scientific_ref": "Ref: Canna – EC Guide for Cannabis (2024)."},
    ),
    (
        "TDS EC Unterschied Cannabis Messung ppm mS cm Umrechnung "
        "Messgerät Kalibrierung",
        {"type": "info", "title": "TDS vs. EC – Umrechnung",
         "message": ("TDS (ppm) und EC (mS/cm) messen das Gleiche auf unterschiedlichen Skalen. "
                     "Umrechnung: EC (mS/cm) × 500 = ppm (500er Skala) oder × 700 = ppm (700er Skala). "
                     "→ Immer auf die gleiche Skala achten – verschiedene Messgeräte "
                     "nutzen unterschiedliche Faktoren. EC-Meter monatlich kalibrieren."),
         "scientific_ref": ""},
    ),
    (
        "Organischer Dünger Cannabis Boden biologisch Mikrobiom "
        "Guano Wurmhumus Kompost langsam wirkend",
        {"type": "info", "title": "Organische Düngung – Eigenschaften",
         "message": ("Organische Dünger wirken über Mikroorganismen im Substrat "
                     "und sind schwer zu überdosieren, wirken aber langsamer als mineralische. "
                     "Guano, Wurmhumus und Komposttee sind populäre organische Quellen. "
                     "→ Organische Düngung erfordert ein aktives Bodenmikrobiom – "
                     "nicht mit Fungiziden oder starken Flush-Aktionen zerstören."),
         "scientific_ref": ""},
    ),
    (
        "Mineraldünger Cannabis synthetisch schnell wirkend "
        "EC messbar Kontrolle sofort verfügbar Hydro",
        {"type": "info", "title": "Mineralische Düngung – Eigenschaften",
         "message": ("Mineralische (synthetische) Dünger sind sofort pflanzenverfügbar, "
                     "EC-messbar und gut kontrollierbar. "
                     "Sie bauen schneller Salze auf und erfordern regelmäßiges Monitoring. "
                     "→ Ideal für Hydroponik und Coco. "
                     "In Erde mit organischem Substrat kombinieren für optimale Ergebnisse."),
         "scientific_ref": ""},
    ),
    (
        "Blattdüngung Cannabis Foliar Spray Nährstoffe schnell "
        "Mangel kurzfristig beheben Blätter aufnehmen",
        {"type": "info", "title": "Blattdüngung – Schnellhilfe bei Mängeln",
         "message": ("Blattsprays mit verdünnter Nährlösung können "
                     "Mängel (besonders Mg, Ca, Fe) schneller beheben als Bodendüngung, "
                     "da Nährstoffe direkt über die Blätter aufgenommen werden. "
                     "→ Nur in der Lichtphase mit abgeschalteter Lampe sprühen, "
                     "EC der Lösung unter 0.8 halten, "
                     "in Blütephase ab Woche 4 nicht mehr auf Blüten sprühen."),
         "scientific_ref": "Ref: Alchimia – Foliar Spray Cannabis Guide (2024)."},
    ),
    (
        "Molybdänmangel Cannabis junge Blätter vergilben Randbräune "
        "Mo Mangel pH hoch selten",
        {"type": "warning", "title": "Molybdänmangel (Mo)",
         "message": ("Molybdänmangel zeigt sich als Vergilbung und Randnekrose "
                     "an mittleren bis älteren Blättern. "
                     "Sehr selten und fast immer pH-bedingt (pH > 7). "
                     "Zu hoher Mo-Überschuss erzeugt Eisenmangel-ähnliche Symptome. "
                     "→ pH auf 6.0–6.5 korrigieren, Volldünger mit Spurenelementen verwenden."),
         "scientific_ref": "Ref: Myplantin – Molybdenum Cannabis (2023)."},
    ),
    (
        "Kupfermangel Cannabis Cu junge Blätter blaugrün welken "
        "Interveinalchlorose ungewöhnlich Wachstumsspitze",
        {"type": "warning", "title": "Kupfermangel (Cu)",
         "message": ("Kupfermangel ist selten, zeigt sich aber als bläulich-grüne "
                     "Verfärbung junger Blätter und ungewöhnliches Welken der Wachstumsspitze. "
                     "Kupfer ist wichtig für den Zellwandaufbau. "
                     "→ Spurenelemente-Dünger mit Kupfer, pH korrigieren. "
                     "Kupfer-Überschuss ist toxisch – vorsichtig dosieren."),
         "scientific_ref": "Ref: Cockson et al. (2019). / Characterization Nutrient Disorders Cannabis."},
    ),
    (
        "Silizidum Cannabis Si Dünger Stängel stärker Schimmelresistenz "
        "Hitzestress Kieselsäure",
        {"type": "info", "title": "Silizium – Stärkung der Pflanze",
         "message": ("Silizium (Si) ist kein essentieller Nährstoff, "
                     "verbessert aber nachweislich Stängelstabilität, "
                     "Widerstandsfähigkeit gegen Hitzestress und Schimmelresistenz. "
                     "→ Kieselsäure-Dünger (z.B. Silica) in EC-Berechnungen einbeziehen. "
                     "Immer zuerst in Wasser lösen bevor andere Dünger hinzugefügt werden."),
         "scientific_ref": "Ref: Cannabis Business Times – Silicon Benefits (2024)."},
    ),
    (
        "Humate Huminsäure Cannabis Fulvinsäure Nährstoffaufnahme "
        "verbessern Chelator Boden Aktivator",
        {"type": "info", "title": "Humin- & Fulvinsäuren",
         "message": ("Huminsäuren und Fulvinsäuren sind natürliche Chelatoren: "
                     "Sie binden Nährstoffe in eine für die Wurzeln leichter aufnehmbare Form "
                     "und verbessern die Substratstruktur. "
                     "→ Als Zusatz zu Erde und Coco sinnvoll, "
                     "EC-neutral, gut kombinierbar mit anderen Düngern."),
         "scientific_ref": ""},
    ),

]

KNOWLEDGE_VERSION = "3.0"


# ─── Haupt-Funktion ───────────────────────────────────────────────────────────

def _get_kb_entry(title: str) -> dict | None:
    for _, meta in PLANT_KNOWLEDGE:
        if meta["title"] == title:
            return meta
    return None

def analyze_plant_needs() -> list:
    """
    Analysiert Sensordaten und Tagebuch direkt via Thresholds und Dictionary Lookup.
    """
    cached = _get_cached_or_none()
    if cached is not None:
        return cached

    sensors = get_latest_sensor_readings()
    diary   = get_diary_entries(limit=10)

    tips: list = []
    seen: set  = set()

    def add_tip(title: str, name: str, extra_msg: str):
        if title in seen: return
        meta = _get_kb_entry(title)
        if meta:
            t = dict(meta)
            t["title"] = f"{t['title']} ({name})" if name else t["title"]
            t["message"] = f"{t['message']} {extra_msg}"
            tips.append(t)
            seen.add(title)

    current_phase = "Vegetativ"
    for entry in diary:
        if entry.get("plant_phase"):
            current_phase = entry["plant_phase"]
            break

    # ── Sensor-Checks ─────────────────────────────────────────────────────────
    for s in sensors:
        temp = s.get("temperature")
        hum  = s.get("humidity")
        name = s.get("sensor_name", "Haupt-Sensor")

        vpd = calc_vpd(temp, hum) if (temp is not None and hum is not None) else None

        # Temperatur
        if temp is not None:
            if temp > 35:
                add_tip("Kritische Hitze – Sofortmaßnahme", name, f"[Aktuell: {temp:.1f} °C]")
            elif temp > 30 and current_phase == "Vegetativ":
                add_tip("Hitzestress – Vegetative Phase", name, f"[Aktuell: {temp:.1f} °C]")
            elif temp > 28 and current_phase == "Blüte":
                add_tip("Hitzestress – Blütephase", name, f"[Aktuell: {temp:.1f} °C]")
            elif temp > 28 and current_phase in ["Sämling", "Keimling", "Steckling"]:
                add_tip("Hitzestress – Sämling/Steckling", name, f"[Aktuell: {temp:.1f} °C]")
            elif temp < 18:
                add_tip("Kältestress", name, f"[Aktuell: {temp:.1f} °C]")

        # Luftfeuchtigkeit
        if hum is not None:
            if hum > 80 and current_phase == "Blüte":
                add_tip("Kritische Luftfeuchtigkeit – Sofortmaßnahme", name, f"[Aktuell: {hum:.1f} %]")
            elif hum > 65 and current_phase == "Blüte":
                add_tip("Schimmelgefahr – Blütephase", name, f"[Aktuell: {hum:.1f} %]")
            elif hum > 70 and current_phase == "Vegetativ":
                add_tip("Zu hohe Luftfeuchtigkeit – Vegetative Phase", name, f"[Aktuell: {hum:.1f} %]")
            elif hum < 40:
                add_tip("Zu trockene Luft", name, f"[Aktuell: {hum:.1f} %]")

        # VPD
        if vpd is not None:
            if vpd < 0.4:
                add_tip("VPD zu niedrig – Transpiration blockiert", name, f"[Aktuell: {"%.2f" % vpd} kPa]")
            elif vpd > 1.6:
                add_tip("VPD zu hoch – Trockenstress", name, f"[Aktuell: {"%.2f" % vpd} kPa]")

    # ── pH aus Tagebuch ───────────────────────────────────────────────────────
    ph_entries = [e for e in diary if e.get("ph_value") is not None]
    if ph_entries:
        ph = ph_entries[0].get("ph_value")
        if ph is not None:
            if ph > 7.0:
                add_tip("pH zu hoch – Nährstoff-Lockout", "", f"[Aktuell: pH {ph:.1f}]")
            elif ph < 5.8:
                add_tip("pH zu niedrig – Säurestress", "", f"[Aktuell: pH {ph:.1f}]")

    # ── Bewässerungs-Check ────────────────────────────────────────────────────
    watering = [e for e in diary if e.get("entry_type") == "Bewässerung"]
    if not watering:
        add_tip("Keine Bewässerung dokumentiert", "", "")
    else:
        last_date_str = watering[0].get("entry_date")
        if last_date_str:
            try:
                days_ago = (datetime.now() - datetime.strptime(last_date_str, "%Y-%m-%d")).days
                if days_ago >= 3:
                    add_tip("Bewässerung überfällig", "", f"[Letzte Bewässerung: vor {days_ago} Tagen]")
            except ValueError:
                log.warning(f"Ungültiges Datumsformat: '{last_date_str}' (erwartet YYYY-MM-DD)")

    _set_cache(tips)
    return tips
