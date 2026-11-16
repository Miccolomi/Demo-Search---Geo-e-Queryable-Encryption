# Demo Search, Geo e Queryable Encryption

Applicazione web dimostrativa che mostra come **MongoDB Enterprise on-prem** possa sostituire un motore di ricerca esterno (ad esempio OpenSearch) per la **ricerca full text** e la **ricerca geospaziale**, e come proteggere i dati sensibili con **Queryable Encryption**, restando interrogabili.

I dati sono sintetici: persone, luoghi e relazioni sulla città di Genova, con un modello a entità e relazioni (`personaFisica`, `luogo`, `relazione`).

## Cosa mostra

| Tab | Contenuto |
|---|---|
| **Panoramica** | Modello dati, architettura, come è costruita la parte cifrata, documenti letti dal database |
| **Full text** | Ricerca con tolleranza agli errori, autocomplete, evidenziazione, filtri combinati, facet (filtri laterali con contatori) |
| **Geo** | Punto + raggio, poligono disegnato sulla mappa, i più vicini con la distanza, uso dell'indice |
| **Testo + Geo** | Testo e area geografica nella stessa query, ranking per prossimità, riepilogo di un'area |
| **Relazioni** | Ricerca geografica su tutti i luoghi collegati a una persona (non solo la residenza), documento denormalizzato costruito con `$lookup` |
| **Queryable Encryption** | Ricerche su campi cifrati (uguaglianza, intervallo, inizia per, finisce per, contiene), lo stesso documento visto con e senza chiavi |
| **★ Caso investigativo** | Un'unica aggregation che combina `$search`, `$lookup` sulle relazioni, indizi calcolati, `$facet` e lettura di dati cifrati |

Ogni passo mostra la spiegazione, la query eseguita, il tempo di risposta, i risultati e una riga **EVIDENZA** che dice cosa dimostra il risultato. Dove possibile c'è anche una verifica indipendente, per esempio un riconteggio o un calcolo geometrico fatto a parte.

## Architettura

```
App (Python, FastAPI)  ──►  Replica set MongoDB Enterprise (3 nodi)  ◄──►  MongoDB Search (mongot)
 driver + crypt_shared                                                       full text · geo · facet
 cifra / decifra i campi
```

- Le query arrivano solo ai nodi `mongod`; `$search` e `$searchMeta` vengono inoltrate a `mongot`, che mantiene gli indici aggiornati tramite change stream.
- La cifratura e la decifratura avvengono nel driver: il server non vede mai i dati sensibili in chiaro.

## Requisiti

- **MongoDB Enterprise 9.0 o superiore**, in replica set (Queryable Encryption non funziona su standalone), con **Feature Compatibility Version 9.0**. Se il cluster arriva da una versione precedente, va alzata esplicitamente:
  ```js
  db.adminCommand({ setFeatureCompatibilityVersion: "9.0", confirm: true })
  ```
- **MongoDB Search (`mongot`)** collegato al replica set. Per Enterprise si installa con il MongoDB Controllers for Kubernetes Operator.
- **Automatic Encryption Shared Library** (`mongo_crypt_v1.so` / `.dylib`) della stessa versione del server, dal Download Center di MongoDB Enterprise (pacchetto `crypt_shared`).
- **Python 3.10+**.

## Installazione

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export MONGODB_URI="mongodb://utente:password@host1:27017,host2:27017,host3:27017/admin?replicaSet=rs0&tls=true"
export CRYPT_SHARED_LIB_PATH="/percorso/mongo_crypt_v1.dylib"
# opzionale: export DB_NAME="demo_investigativa"

python check_ambiente.py      # versione, replica set, mongot, libreria di cifratura
```

## Preparazione dei dati

Da lanciare una volta, in quest'ordine:

```bash
python 00_genera_dati.py          # ~20.000 persone, ~36.000 luoghi, ~49.000 relazioni + indici 2dsphere
python 01_crea_indice_search.py   # indice MongoDB Search
python 02_prepara_caso.py         # i tre sospettati del "Caso investigativo"
python 03_qe_setup.py             # key vault, collection cifrata con tutte le persone (qualche minuto)
```

`03_qe_setup.py` crea una **chiave master locale** nel file `master-key.bin`. Conservala: senza quel file i dati cifrati non si possono più leggere. Il file è escluso da git e non va mai pubblicato.

`python 00_genera_dati.py --dry-run` non si collega al database: scrive solo alcuni documenti di esempio nella cartella `campioni/`.

## Avvio

```bash
python app.py                 # apre http://localhost:8000
PORT=9000 python app.py       # su un'altra porta
```

## File

| File | Ruolo |
|---|---|
| `app.py` | Server web (FastAPI) e API |
| `passi_web.py` | I passi della demo: spiegazioni, query, verifiche |
| `static/index.html` | La pagina (HTML + JavaScript, mappe con Leaflet) |
| `config.py` | Configurazione, sovrascrivibile con variabili d'ambiente |
| `common.py`, `qe_common.py` | Connessione, funzioni di calcolo, client per Queryable Encryption |
| `00_…03_*.py` | Preparazione dei dati |
| `check_ambiente.py` | Verifica dell'ambiente |

## Note

- **Sicurezza:** la chiave master in un file locale va bene solo per una demo. In produzione la chiave master sta in un KMS o HSM (on-prem via KMIP, oppure AWS KMS, Azure Key Vault, Google Cloud KMS); cambia solo la configurazione del driver.
- **Ricerca e dati cifrati:** MongoDB Search lavora solo sui campi in chiaro. Il tab "Caso investigativo" legge i campi cifrati nella stessa aggregation di `$search` usando un client con `bypassQueryAnalysis`: la query non viene analizzata dal driver, ma i risultati vengono comunque decifrati. Quel client serve solo in lettura; le ricerche sui campi cifrati usano il client Queryable Encryption standard.
- **Dati sintetici:** nomi, indirizzi, codici fiscali e matricole sono generati a caso; i codici fiscali hanno un formato plausibile ma non sono validi.
- **Mappe:** le tile sono caricate da Esri (World Street Map) e, se non disponibile, da OpenStreetMap: serve una connessione internet sul computer che apre la pagina.

## Licenza

Copyright 2026 Michele Farinacci. Distribuito con licenza [Apache 2.0](LICENSE).

Include [Leaflet](https://leafletjs.com) 1.9.4, con licenza BSD 2-Clause (`static/leaflet/LICENSE`). Vedi `NOTICE`.
