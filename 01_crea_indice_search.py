"""
01 - Creazione dell'indice MongoDB Search (mongot) su personaFisica.

Equivale al mapping OpenSearch, compreso il geo_point:
  OpenSearch  "coordinate": {"type": "geo_point"}
  MongoDB     "geoJson":    {"type": "geo"}
"""
import time

from pymongo.operations import SearchIndexModel

import config
from common import db, mostra, titolo

# Analyzer italiano per testo libero + autocomplete edgeGram per i nomi.
# "token" = campo keyword: filtri esatti e faccette.
CAMPO_NOME = [
    {"type": "string", "analyzer": "lucene.italian"},
    {"type": "autocomplete", "tokenization": "edgeGram", "minGrams": 2, "maxGrams": 15, "foldDiacritics": True},
    {"type": "token", "normalizer": "lowercase"},
]

DEFINIZIONE_PERSONA = {
    "mappings": {
        "dynamic": False,
        "fields": {
            "tipoEntita": {"type": "token"},
            "stato": {"type": "token"},
            "indagineTatticaId": {"type": "token"},
            "tags": {"type": "token"},
            "properties": {
                "type": "document",
                "fields": {
                    "nome": CAMPO_NOME,
                    "cognome": CAMPO_NOME,
                    "soprannomi": {"type": "string", "analyzer": "lucene.italian"},
                    "segniParticolari": {"type": "string", "analyzer": "lucene.italian"},
                    "nazionalita": {"type": "token"},
                    "dataNascita": {"type": "date"},
                    "gender": {"type": "document", "fields": {"code": {"type": "token"}}},
                    "luogoResidenza": {
                        "type": "document",
                        "fields": {
                            "displayName": {"type": "string", "analyzer": "lucene.italian"},
                            "frazione": {"type": "token"},
                            "citta": {"type": "token"},
                            "cap": {"type": "token"},
                            # ===> l'equivalente del geo_point di OpenSearch
                            "geoJson": {"type": "geo"},
                        },
                    },
                },
            },
        },
    }
}


def crea_indice(coll, nome, definizione, timeout_s=600):
    esistenti = {i["name"] for i in coll.list_search_indexes()}
    if nome in esistenti:
        print(f"Indice {nome} già presente: lo ricreo")
        coll.drop_search_index(nome)
        while nome in {i["name"] for i in coll.list_search_indexes()}:
            time.sleep(2)

    coll.create_search_index(SearchIndexModel(definition=definizione, name=nome))
    print(f"Indice {nome} creato, attendo che sia interrogabile", end="", flush=True)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        idx = next((i for i in coll.list_search_indexes(nome)), None)
        if idx and idx.get("queryable"):
            print(f"\nPronto in {time.time() - t0:.0f}s (status={idx.get('status')})")
            return
        print(".", end="", flush=True)
        time.sleep(3)
    raise TimeoutError(f"Indice {nome} non pronto dopo {timeout_s}s")


if __name__ == "__main__":
    d = db()
    titolo("Definizione indice MongoDB Search su personaFisica")
    mostra(DEFINIZIONE_PERSONA)
    crea_indice(d[config.COLL_PERSONA], config.SEARCH_INDEX_PERSONA, DEFINIZIONE_PERSONA)
