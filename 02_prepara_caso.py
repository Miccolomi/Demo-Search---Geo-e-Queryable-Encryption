"""
02 - Prepara il "Caso investigativo": inserisce tre persone costruite apposta per la storia.

  Testimone: uomo con tatuaggio a forma di drago, visto vicino al Bar del Porto,
             cognome sentito come "Rosi". Indagine: Operazione Lanterna.

  - Marco Rosso   : tatuaggio drago, abita vicino al bar, frequenta il bar  -> 4 indizi su 4
  - Davide Rossi  : tatuaggio drago, abita vicino al bar, NON lo frequenta -> 3 su 4
  - Stefano Rosso : tatuaggio drago, frequenta il bar, abita lontano (Pegli) -> 3 su 4

Si può rilanciare: prima cancella le persone inserite la volta precedente (tag "CasoDemo").
Va lanciato prima di 03_qe_setup.py, così anche i sospettati finiscono nella collection cifrata.
"""
import importlib
import random
from datetime import datetime, timedelta, timezone

import config
from common import db

gen = importlib.import_module("00_genera_dati")
INDAGINE = "ff7f103e-8a54-4edb-878b-37c462b17eb5"   # la più numerosa: "Operazione Lanterna" nella demo
TAG = "CasoDemo"
ORA = datetime(2026, 10, 1, tzinfo=timezone.utc)

SOSPETTATI = [
    # nome, cognome, soprannome, segni, vicino al bar?, frequenta?, quartiere se lontano
    ("Marco", "Rosso", "il Biondo", "tatuaggio drago braccio sinistro", True, True, None),
    ("Davide", "Rossi", None, "tatuaggio drago sulla spalla", True, False, None),
    ("Stefano", "Rosso", "Baffo", "tatuaggio drago avambraccio destro", False, True, "Pegli"),
]


def main():
    d = db()
    random.seed(7)
    bar = d[config.COLL_LUOGO].find_one({"properties.luogo.nomeLuogo": "Bar del Porto"})
    if not bar:
        raise SystemExit("Luogo 'Bar del Porto' non trovato: lancia prima 00_genera_dati.py")
    blon, blat = bar["properties"]["luogo"]["geoJson"]["coordinates"]
    q_bar = next(q for q in gen.QUARTIERI if q[0] == bar["properties"]["luogo"]["frazione"])

    # pulizia dei sospettati di un'esecuzione precedente
    vecchi = [p["_id"] for p in d[config.COLL_PERSONA].find({"tags": TAG}, {"_id": 1})]
    if vecchi:
        rel = list(d[config.COLL_RELAZIONE].find({"idEntita1": {"$in": vecchi}}, {"idEntita2": 1, "codiceRelazione": 1}))
        luoghi_propri = [x for r in rel if r["codiceRelazione"] != "PersonaFisica_Luogo_Frequenta" for x in r["idEntita2"]]
        d[config.COLL_LUOGO].delete_many({"_id": {"$in": luoghi_propri}})
        d[config.COLL_RELAZIONE].delete_many({"idEntita1": {"$in": vecchi}})
        d[config.COLL_PERSONA].delete_many({"_id": {"$in": vecchi}})
        print(f"Rimossi {len(vecchi)} sospettati della volta precedente")

    for nome, cognome, sopr, segni, vicino, frequenta, quartiere in SOSPETTATI:
        if vicino:
            res = gen.oggetto_luogo(quartiere=q_bar, lat=round(blat + random.uniform(-0.002, 0.002), 7),
                                    lon=round(blon + random.uniform(-0.002, 0.002), 7))
        else:
            res = gen.oggetto_luogo(quartiere=next(q for q in gen.QUARTIERI if q[0] == quartiere))
        p = gen.doc_persona(nome, cognome, "M", res, INDAGINE, ORA)
        p["properties"]["segniParticolari"] = segni
        p["properties"]["soprannomi"] = [sopr] if sopr else None
        p["tags"] = [TAG]
        l_res = gen.doc_luogo(res, INDAGINE, ORA)
        rels = [gen.doc_relazione(p["_id"], l_res["_id"], "PersonaFisica_Luogo_Residente", INDAGINE, ORA,
                                  ORA - timedelta(days=2000), None)]
        if frequenta:
            rels.append(gen.doc_relazione(p["_id"], bar["_id"], "PersonaFisica_Luogo_Frequenta", INDAGINE, ORA, None, None))
        d[config.COLL_PERSONA].insert_one(p)
        d[config.COLL_LUOGO].insert_one(l_res)
        d[config.COLL_RELAZIONE].insert_many(rels)
        print(f"Inserito {nome} {cognome:6s} – {res['frazione']:14s} vicino al bar: {'sì' if vicino else 'no'}  "
              f"frequenta: {'sì' if frequenta else 'no'}")
    print("\nFatto. Ora lancia 03_qe_setup.py per creare la collection cifrata.")


if __name__ == "__main__":
    main()
