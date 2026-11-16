"""
03 - Setup Queryable Encryption (MongoDB 9.0+).

Crea la collection cifrata personaFisicaQE e ci copia N_PERSONE_QE persone
da personaFisica, passando dal client cifrante: i campi sensibili arrivano
al server già cifrati.

Scelta di design (campo per campo):
  codiceFiscale     -> equality             (ricerca esatta)
  dataNascita       -> range                (intervalli di date)
  matricolaSidet    -> prefix + suffix      (ricerca parziale su identificativo)
  segniParticolari  -> substring            (parole contenute nel testo)
  nome, cognome, luogoResidenza -> IN CHIARO: indicizzati da MongoDB Search e 2dsphere
"""
from datetime import datetime

from pymongo import GEOSPHERE
from pymongo.operations import SearchIndexModel

import config
from common import mostra, titolo
from qe_common import client_cifrante, client_encryption, client_in_chiaro

ENCRYPTED_FIELDS = {
    "fields": [
        {"path": "properties.codiceFiscale", "bsonType": "string",
         "queries": [{"queryType": "equality"}]},
        {"path": "properties.dataNascita", "bsonType": "date",
         "queries": [{"queryType": "range", "min": datetime(1930, 1, 1), "max": datetime(2010, 12, 31)}]},
        {"path": "properties.matricolaSidet", "bsonType": "string",
         "queries": [
             {"queryType": "prefix", "strMinQueryLength": 3, "strMaxQueryLength": 10,
              "caseSensitive": False, "diacriticSensitive": False},
             {"queryType": "suffix", "strMinQueryLength": 3, "strMaxQueryLength": 10,
              "caseSensitive": False, "diacriticSensitive": False},
         ]},
        {"path": "properties.segniParticolari", "bsonType": "string",
         "queries": [{"queryType": "substring", "strMaxLength": 50,
                      "strMinQueryLength": 3, "strMaxQueryLength": 6,
                      "caseSensitive": False, "diacriticSensitive": False}]},
    ]
}

SEARCH_DEF_QE = {
    "mappings": {
        "dynamic": False,
        "fields": {
            "properties": {
                "type": "document",
                "fields": {
                    "nome": [{"type": "string", "analyzer": "lucene.italian"},
                             {"type": "autocomplete", "tokenization": "edgeGram", "minGrams": 2, "maxGrams": 15}],
                    "cognome": [{"type": "string", "analyzer": "lucene.italian"},
                                {"type": "autocomplete", "tokenization": "edgeGram", "minGrams": 2, "maxGrams": 15}],
                    "luogoResidenza": {"type": "document", "fields": {
                        "displayName": {"type": "string", "analyzer": "lucene.italian"},
                        "geoJson": {"type": "geo"},
                    }},
                },
            },
        },
    }
}

if __name__ == "__main__":
    plain = client_in_chiaro()
    enc = client_cifrante()
    db_plain = plain[config.DB_NAME]
    db_enc = enc[config.DB_NAME]

    versione = plain.server_info()["version"]
    print(f"MongoDB {versione}")
    if int(versione.split(".")[0]) < 9:
        # Su 8.2/8.3 prefix/suffix/substring esistono solo come *Preview (in 9.0 sono GA)
        for f in ENCRYPTED_FIELDS["fields"]:
            for q in f["queries"]:
                if q["queryType"] in ("prefix", "suffix", "substring"):
                    q["queryType"] += "Preview"
        print("Server < 9.0: uso prefixPreview / suffixPreview / substringPreview")

    titolo("1. Key vault (contiene le DEK cifrate con la master key)")
    plain[config.KEY_VAULT_DB].drop_collection(config.KEY_VAULT_COLL)
    # drop della collection cifrata + metadati QE (enxcol_.<nome>.esc / .ecoc) per rendere lo script rieseguibile
    db_plain.drop_collection(config.COLL_PERSONA_QE, encrypted_fields=ENCRYPTED_FIELDS)
    for c in (f"enxcol_.{config.COLL_PERSONA_QE}.esc", f"enxcol_.{config.COLL_PERSONA_QE}.ecoc"):
        db_plain.drop_collection(c)
    plain[config.KEY_VAULT_DB][config.KEY_VAULT_COLL].create_index(
        "keyAltNames", unique=True, partialFilterExpression={"keyAltNames": {"$exists": True}})
    print(f"Key vault pronto: {config.KEY_VAULT_NS}")

    titolo("2. Collection cifrata: schema dei campi cifrati")
    mostra(ENCRYPTED_FIELDS)
    ce = client_encryption(plain)
    ce.create_encrypted_collection(db_enc, config.COLL_PERSONA_QE, ENCRYPTED_FIELDS, kms_provider="local")
    print(f"\nCreata {config.COLL_PERSONA_QE}. Le DEK (una per campo) sono nel key vault: "
          f"{plain[config.KEY_VAULT_DB][config.KEY_VAULT_COLL].count_documents({})}")

    titolo(f"3. Copio {config.N_PERSONE_QE} persone passando dal client cifrante")
    sorgente = db_plain[config.COLL_PERSONA].find({}).limit(config.N_PERSONE_QE)
    batch, n = [], 0
    for doc in sorgente:
        p = doc["properties"]
        # null non è cifrabile: valorizzo i segni particolari mancanti
        if not p.get("segniParticolari"):
            p["segniParticolari"] = "nessuno"
        batch.append(doc)
        if len(batch) == 500:
            db_enc[config.COLL_PERSONA_QE].insert_many(batch)
            n += len(batch)
            batch = []
            print(f"  {n}...")
    if batch:
        db_enc[config.COLL_PERSONA_QE].insert_many(batch)
        n += len(batch)
    print(f"Inseriti {n} documenti")

    titolo("4. Indici sui campi NON cifrati della stessa collection")
    db_plain[config.COLL_PERSONA_QE].create_index([("properties.luogoResidenza.geoJson", GEOSPHERE)])
    print("2dsphere su properties.luogoResidenza.geoJson: OK")
    try:
        db_plain[config.COLL_PERSONA_QE].create_search_index(
            SearchIndexModel(definition=SEARCH_DEF_QE, name=config.SEARCH_INDEX_PERSONA_QE))
        print(f"Indice Search {config.SEARCH_INDEX_PERSONA_QE} creato (diventa interrogabile in pochi secondi)")
    except Exception as e:
        print(f"Indice Search non creato: {e}")
    print("\nSetup QE completato.")
