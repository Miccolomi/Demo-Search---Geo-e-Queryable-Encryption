"""
Configurazione della demo. Tutto si sovrascrive con variabili d'ambiente,
così non serve toccare il codice il giorno della demo.
"""
import os

# Connessione al replica set (QE richiede replica set o sharded, non standalone)
MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb://localhost:27017/?directConnection=true",
)

DB_NAME = os.getenv("DB_NAME", "demo_investigativa")

# Collection "in chiaro"
COLL_PERSONA = "personaFisica"
COLL_LUOGO = "luogo"
COLL_RELAZIONE = "relazione"
COLL_VISTA = "entitaVista"          # vista denormalizzata "stile OpenSearch" (opzionale)

# Queryable Encryption
COLL_PERSONA_QE = "personaFisicaQE"
KEY_VAULT_DB = "encryption"
KEY_VAULT_COLL = "__keyVault"
KEY_VAULT_NS = f"{KEY_VAULT_DB}.{KEY_VAULT_COLL}"
MASTER_KEY_FILE = os.getenv("MASTER_KEY_FILE", "master-key.bin")   # SOLO per demo: in prod KMIP/HSM
# Percorso della Automatic Encryption Shared Library (mongo_crypt_v1.so / .dylib / .dll),
# scaricabile dal Download Center di MongoDB Enterprise. Se vuoto si usa mongocryptd dal PATH.
CRYPT_SHARED_LIB_PATH = os.getenv("CRYPT_SHARED_LIB_PATH", "")

# Volumi
N_PERSONE = int(os.getenv("N_PERSONE", "20000"))
N_PERSONE_QE = int(os.getenv("N_PERSONE_QE", "100000"))   # tutte: serve al caso investigativo

# Nomi indici Search
SEARCH_INDEX_PERSONA = "persona_search"
SEARCH_INDEX_PERSONA_QE = "persona_qe_search"

# Punti di riferimento per le query (Genova)
# Via Acquarone 5 - residenza di "Biagio Amalfi", la persona di riferimento. GeoJSON = [lon, lat] !
PUNTO_ACQUARONE = [8.9368807, 44.4166842]
RAGGIO_METRI = 500

# Poligono approssimativo del Centro Storico di Genova (anello chiuso, [lon, lat])
POLIGONO_CENTRO_STORICO = [[
    [8.9255, 44.4050],
    [8.9405, 44.4050],
    [8.9420, 44.4130],
    [8.9270, 44.4140],
    [8.9255, 44.4050],
]]
