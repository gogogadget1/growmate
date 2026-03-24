"""
GrowMate – Wissensbasis vektorisieren
═══════════════════════════════════════════════════════════════════════════════
Einmaliges Script: Wandelt alle 66 PLANT_KNOWLEDGE-Einträge in Vektoren um
und speichert sie als knowledge_vectors.json im Projektverzeichnis.

Ausführen:
    python build_vectors.py

Voraussetzungen:
    pip install onnxruntime tokenizers numpy
    model/model.onnx      (ONNX-Modell, siehe README für Download-Befehl)
    model/tokenizer.json  (Tokenizer-Konfiguration, ebenfalls Download)

Ausgabe:
    knowledge_vectors.json  →  ins Projektverzeichnis legen
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import os
import sys
import time
import numpy as np

# ─── Pfade ────────────────────────────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH     = os.path.join(BASE_DIR, "model", "model.onnx")
TOKENIZER_PATH = os.path.join(BASE_DIR, "model", "tokenizer.json")
OUTPUT_PATH    = os.path.join(BASE_DIR, "knowledge_vectors.json")

# ─── Preflight-Checks ─────────────────────────────────────────────────────────
def check_prerequisites():
    errors = []
    if not os.path.exists(MODEL_PATH):
        errors.append(f"  ✗ Modell nicht gefunden: {MODEL_PATH}")
    if not os.path.exists(TOKENIZER_PATH):
        errors.append(f"  ✗ Tokenizer nicht gefunden: {TOKENIZER_PATH}")
    try:
        import onnxruntime
    except ImportError:
        errors.append("  ✗ onnxruntime fehlt  →  pip install onnxruntime")
    try:
        import tokenizers
    except ImportError:
        errors.append("  ✗ tokenizers fehlt   →  pip install tokenizers")
    try:
        import numpy
    except ImportError:
        errors.append("  ✗ numpy fehlt        →  pip install numpy")

    if errors:
        print("\n❌ Preflight fehlgeschlagen:\n")
        for e in errors:
            print(e)
        print()
        sys.exit(1)
    print("✓ Alle Voraussetzungen erfüllt.\n")


# ─── Modell laden ─────────────────────────────────────────────────────────────
def load_model():
    import onnxruntime as ort
    from tokenizers import Tokenizer

    print(f"Lade Tokenizer aus {TOKENIZER_PATH} ...")
    tokenizer = Tokenizer.from_file(TOKENIZER_PATH)
    # Padding und Truncation konfigurieren
    tokenizer.enable_padding(
        direction="right",
        pad_id=0,
        pad_token="[PAD]",
    )
    tokenizer.enable_truncation(max_length=256)

    print(f"Lade ONNX-Modell aus {MODEL_PATH} ...")
    t0 = time.time()
    # Nur CPU – kein GPU nötig für 66 Einträge
    session = ort.InferenceSession(
        MODEL_PATH,
        providers=["CPUExecutionProvider"]
    )
    print(f"Modell geladen in {time.time() - t0:.1f}s\n")

    # Input-Namen aus Modell auslesen – nicht hardcoden
    input_names  = [inp.name for inp in session.get_inputs()]
    output_names = [out.name for out in session.get_outputs()]
    print(f"Modell-Inputs:  {input_names}")
    print(f"Modell-Outputs: {output_names}\n")

    return tokenizer, session, input_names, output_names


# ─── Embedding-Funktion ───────────────────────────────────────────────────────
def embed(texts: list, tokenizer, session, input_names: list, output_names: list) -> np.ndarray:
    """
    Wandelt eine Liste von Texten in normalisierte Embeddings um.
    Gibt numpy-Array der Form (n_texts, 384) zurück.
    """
    encodings = tokenizer.encode_batch(texts)

    # Padding auf gleiche Länge innerhalb des Batches
    max_len = max(len(e.ids) for e in encodings)
    n = len(encodings)

    input_ids      = np.zeros((n, max_len), dtype=np.int64)
    attention_mask = np.zeros((n, max_len), dtype=np.int64)
    token_type_ids = np.zeros((n, max_len), dtype=np.int64)

    for i, enc in enumerate(encodings):
        seq_len = len(enc.ids)
        input_ids[i, :seq_len]      = enc.ids
        attention_mask[i, :seq_len] = enc.attention_mask

    # Feed-Forward durch ONNX
    feed = {}
    for name in input_names:
        if "input_ids" in name:
            feed[name] = input_ids
        elif "attention_mask" in name:
            feed[name] = attention_mask
        elif "token_type" in name:
            feed[name] = token_type_ids

    outputs = session.run(output_names, feed)
    token_embeddings = outputs[0]  # (batch, seq_len, hidden_size)

    # Mean-Pooling: Durchschnitt über Token-Dimension, gewichtet mit Attention-Mask
    mask = attention_mask[:, :, np.newaxis].astype(np.float32)
    sum_emb  = (token_embeddings * mask).sum(axis=1)
    sum_mask = mask.sum(axis=1)
    embeddings = sum_emb / np.maximum(sum_mask, 1e-9)

    # L2-Normalisierung → Cosinus-Ähnlichkeit = Dot-Product
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    return embeddings / np.maximum(norms, 1e-9)


# ─── PLANT_KNOWLEDGE importieren ─────────────────────────────────────────────
def load_knowledge():
    """Importiert PLANT_KNOWLEDGE direkt aus analyzer.py."""
    try:
        sys.path.insert(0, BASE_DIR)
        from analyzer import PLANT_KNOWLEDGE, KNOWLEDGE_VERSION
        print(f"✓ {len(PLANT_KNOWLEDGE)} Einträge aus analyzer.py geladen (v{KNOWLEDGE_VERSION})\n")
        return PLANT_KNOWLEDGE, KNOWLEDGE_VERSION
    except ImportError as e:
        print(f"❌ Konnte analyzer.py nicht importieren: {e}")
        sys.exit(1)


# ─── Hauptprogramm ────────────────────────────────────────────────────────────
def main():
    print("═" * 60)
    print("  GrowMate – Wissensbasis vektorisieren")
    print("═" * 60 + "\n")

    check_prerequisites()

    knowledge, version = load_knowledge()
    tokenizer, session, input_names, output_names = load_model()

    texts     = [entry[0]  for entry in knowledge]
    metadatas = [entry[1]  for entry in knowledge]

    print(f"Vektorisiere {len(texts)} Einträge ...")
    t0 = time.time()

    # In Batches verarbeiten (robuster auf wenig RAM)
    BATCH_SIZE = 16
    all_vectors = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        vecs  = embed(batch, tokenizer, session, input_names, output_names)
        all_vectors.append(vecs)
        print(f"  Batch {i//BATCH_SIZE + 1}/{(len(texts)-1)//BATCH_SIZE + 1} fertig")

    vectors = np.vstack(all_vectors)
    elapsed = time.time() - t0
    print(f"\n✓ {len(vectors)} Vektoren in {elapsed:.1f}s berechnet")
    print(f"  Dimensionen: {vectors.shape[1]}\n")

    # Qualitätscheck: Durchschnittsnorm sollte ~1.0 sein (normalisiert)
    norms = np.linalg.norm(vectors, axis=1)
    print(f"  Norm-Check: min={norms.min():.4f}  max={norms.max():.4f}  "
          f"mean={norms.mean():.4f}  (Ziel: 1.0000)")
    if abs(norms.mean() - 1.0) > 0.01:
        print("  ⚠ Warnung: Normierung ungenau – Modell-Output prüfen.")
    else:
        print("  ✓ Normierung korrekt.\n")

    # Ähnlichkeits-Stichprobe: erste zwei Einträge sollten sich ähneln
    sim_01 = float(vectors[0] @ vectors[1])
    sim_0_last = float(vectors[0] @ vectors[-1])
    print(f"  Ähnlichkeits-Stichprobe:")
    print(f"    Eintrag 0 ↔ Eintrag 1 (beide Hitzestress):  {sim_01:.3f}  (erwartet: >0.6)")
    print(f"    Eintrag 0 ↔ letzter (Botrytis):             {sim_0_last:.3f}  (erwartet: <0.6)\n")

    # JSON bauen
    output = {
        "version":    version,
        "model":      "sentence-transformers/all-MiniLM-L6-v2",
        "dimensions": int(vectors.shape[1]),
        "count":      len(vectors),
        "entries": [
            {
                "id":       i,
                "text":     texts[i],
                "vector":   vectors[i].tolist(),
                "metadata": metadatas[i],
            }
            for i in range(len(vectors))
        ]
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"✓ Gespeichert: {OUTPUT_PATH}")
    print(f"  Dateigröße: {size_kb:.1f} KB\n")
    print("═" * 60)
    print("  Fertig! Lege knowledge_vectors.json ins Projektverzeichnis.")
    print("═" * 60)


if __name__ == "__main__":
    main()
