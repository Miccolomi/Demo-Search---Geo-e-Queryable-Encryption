"""Funzioni condivise: connessione, stampa e piccoli calcoli usati dalla demo."""
import json
import math

from bson import json_util
from pymongo import MongoClient

import config

_client = None


def client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(config.MONGODB_URI)
    return _client


def db():
    return client()[config.DB_NAME]


# ---------------------------------------------------------------------------
# Stampa (script di setup)
# ---------------------------------------------------------------------------
def to_json(obj, indent=2) -> str:
    return json.dumps(json.loads(json_util.dumps(obj)), indent=indent, ensure_ascii=False)


def mostra(obj, max_len: int = 4000):
    s = to_json(obj)
    print(s if len(s) <= max_len else s[:max_len] + "\n  ... (troncato)")


def titolo(testo: str):
    print(f"\n{'=' * 78}\n  {testo}\n{'=' * 78}")


# ---------------------------------------------------------------------------
# Calcoli usati per verificare i risultati
# ---------------------------------------------------------------------------
def evidenzia(highlights) -> str:
    """Ricostruisce il testo con le parole trovate marcate «così»."""
    return " | ".join("".join(f"«{t['value']}»" if t["type"] == "hit" else t["value"] for t in h["texts"])
                      for h in highlights or [])


def metri(a, b) -> float:
    """Distanza in metri tra due punti [lon, lat] (formula dell'emisenoverso)."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def dentro_poligono(p, anello) -> bool:
    """Ray casting: True se il punto [lon, lat] è dentro l'anello [[lon, lat], ...]."""
    x, y, dentro = p[0], p[1], False
    for i in range(len(anello) - 1):
        (x1, y1), (x2, y2) = anello[i], anello[i + 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            dentro = not dentro
    return dentro


def lettere_diverse(a: str, b: str) -> int:
    """Distanza di Levenshtein: quante lettere cambiare per passare da a a b."""
    a, b = a.lower(), b.lower()
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
