"""
00 - Generazione della base dati sintetica.

Modello dati (entità + relazioni):
  - personaFisica : entità con luogoResidenza EMBEDDED (solo la residenza attuale)
  - luogo         : entità Luogo (n per persona)
  - relazione     : archi idEntita1 -> idEntita2[] con codiceRelazione

Le coordinate di ogni luogo sono nel campo geoJson come GeoJSON Point [lon, lat]:
è ciò che abilita sia gli indici 2dsphere sia l'operatore geo di MongoDB Search.

Uso:
  python 00_genera_dati.py               # genera e carica su MongoDB
  python 00_genera_dati.py --dry-run     # scrive solo dei campioni JSON in ./campioni
"""
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from bson import json_util

import config

random.seed(42)
ORA = datetime(2026, 10, 1, tzinfo=timezone.utc)

# ----------------------------------------------------------------------------
# Dizionari
# ----------------------------------------------------------------------------
NOMI_M = ["Biagio", "Marco", "Luca", "Giuseppe", "Antonio", "Francesco", "Alessandro", "Andrea",
          "Giovanni", "Roberto", "Stefano", "Paolo", "Davide", "Simone", "Matteo", "Lorenzo",
          "Fabio", "Massimo", "Salvatore", "Vincenzo", "Gianluca", "Riccardo", "Emanuele", "Nicolò"]
NOMI_F = ["Maria", "Giulia", "Francesca", "Sara", "Chiara", "Laura", "Anna", "Valentina",
          "Elena", "Federica", "Silvia", "Martina", "Alessia", "Paola", "Roberta", "Ilaria"]
COGNOMI = ["Rossi", "Russo", "Ferrari", "Esposito", "Bianchi", "Romano", "Colombo", "Ricci",
           "Marino", "Greco", "Bruno", "Gallo", "Conti", "De Luca", "Costa", "Giordano",
           "Mancini", "Rizzo", "Lombardi", "Moretti", "Barbieri", "Fontana", "Santoro", "Mariani",
           "Rinaldi", "Caruso", "Ferrara", "Galli", "Martini", "Leone", "Longo", "Gentile",
           "Martinelli", "Vitale", "Parodi", "Ferrando", "Canepa", "Repetto", "Pastorino", "Bozzo",
           "Amalfi", "Cevasco", "Traverso", "Olivieri", "Queirolo", "Musso", "Lagomarsino"]
SOPRANNOMI = ["il Biondo", "Pippo", "lo Zio", "il Professore", "Gegè", "il Rosso", "Totò",
              "il Marinaio", "Baffo", "il Corto", "Nino", "la Volpe"]
SEGNI = ["tatuaggio drago braccio sinistro", "cicatrice sopracciglio destro",
         "tatuaggio ancora avambraccio destro", "zoppia lieve gamba sinistra",
         "neo evidente guancia sinistra", "tatuaggio scritta collo", "cicatrice mano destra",
         "orecchino sopracciglio", "tatuaggio rosa spalla destra", "dente d'oro incisivo"]
NAZIONALITA = ["Italiana"] * 8 + ["Albanese", "Rumena", "Marocchina", "Ecuadoriana", "Tunisina"]

# Quartieri di Genova: (frazione, municipio, lat, lon, cap)
QUARTIERI = [
    ("Castelletto", "Centro Est", 44.4167, 8.9369, "16136"),
    ("Centro Storico", "Centro Est", 44.4085, 8.9325, "16123"),
    ("Molo", "Centro Est", 44.4065, 8.9285, "16128"),
    ("Foce", "Medio Levante", 44.3975, 8.9505, "16129"),
    ("Albaro", "Medio Levante", 44.3965, 8.9655, "16145"),
    ("San Fruttuoso", "Bassa Val Bisagno", 44.4125, 8.9615, "16143"),
    ("Marassi", "Bassa Val Bisagno", 44.4180, 8.9530, "16139"),
    ("Staglieno", "Media Val Bisagno", 44.4290, 8.9500, "16137"),
    ("Sampierdarena", "Centro Ovest", 44.4120, 8.8960, "16149"),
    ("Cornigliano", "Medio Ponente", 44.4170, 8.8700, "16152"),
    ("Sestri Ponente", "Medio Ponente", 44.4270, 8.8500, "16154"),
    ("Pegli", "Ponente", 44.4285, 8.8150, "16155"),
    ("Rivarolo", "Valpolcevera", 44.4440, 8.9010, "16159"),
    ("Quarto", "Levante", 44.3905, 9.0020, "16148"),
    ("Nervi", "Levante", 44.3835, 9.0330, "16167"),
]
VIE = ["Via Acquarone", "Via XX Settembre", "Via Balbi", "Via Garibaldi", "Via San Lorenzo",
       "Corso Italia", "Via Assarotti", "Corso Magenta", "Via Cantore", "Via Sestri",
       "Via Pegli", "Via Fereggiano", "Via Tolemaide", "Via Montevideo", "Via Nizza",
       "Corso Torino", "Via Pré", "Via del Campo", "Via Luccoli", "Salita San Nicolò",
       "Via Rivarolo", "Via Gianelli", "Via Oberdan", "Piazza Martinez", "Via Canevari"]
LUOGHI_NOTEVOLI = ["Bar del Porto", "Circolo Nautico", "Bar Centrale", "Sala Giochi Lucky",
                   "Officina Meccanica F.lli Parodi", "Ristorante La Lanterna", "Palestra Iron",
                   "Bar Sport", "Autolavaggio Express", "Pizzeria Da Gino", "Caffè degli Specchi",
                   "Circolo ARCI", "Agenzia Scommesse", "Tabaccheria n.12", "Market H24"]

INDAGINI = [str(uuid.UUID(int=random.getrandbits(128))) for _ in range(6)]
INDAGINI[0] = "ff7f103e-8a54-4edb-878b-37c462b17eb5"   # indagine di riferimento


GENDER = {
    "M": {"_id": "8990a044-681d-4ed0-8c75-791b84addcc4", "code": "M",
          "langDescriptions": [{"langCode": "it-IT", "name": "Maschio"}, {"langCode": "en-GB", "name": "Male"}]},
    "F": {"_id": "7d1b0f61-2b0e-4a7e-9c55-2b1f1c3a9e10", "code": "F",
          "langDescriptions": [{"langCode": "it-IT", "name": "Femmina"}, {"langCode": "en-GB", "name": "Female"}]},
}
STATI_CIVILI = [
    ("CONO", "Coniugato", "Conjugate"), ("CELI", "Celibe/Nubile", "Single"),
    ("DIVO", "Divorziato", "Divorced"), ("VEDO", "Vedovo", "Widowed"),
]
FONTE_MAN = {"nome": {"_id": "5ba6997a-1b42-4786-b78e-c3370fc67d23", "code": "MAN", "name": "Inserimento Manuale",
                      "isVisible": True, "langDescriptions": [{"langCode": "it-IT", "name": "Inserimento Manuale"}]},
             "dettaglio": "", "fonteCerta": False}
CATEGORIA_LUOGO = {"_id": "1367c025-420b-41f7-ad6b-fcaebee1fd23", "code": "Luogo", "name": "Luogo",
                   "langDescriptions": [{"langCode": "it_IT", "name": "Collegamento"},
                                        {"langCode": "en_GB", "name": "Connection"}],
                   "statoEntita": "CREATA"}


def uid() -> str:
    return str(uuid.UUID(int=random.getrandbits(128)))


def data_casuale(da: datetime, a: datetime) -> datetime:
    return da + timedelta(seconds=random.randint(0, int((a - da).total_seconds())))


# ----------------------------------------------------------------------------
# Costruttori dei documenti
# ----------------------------------------------------------------------------
def oggetto_luogo(quartiere=None, via=None, civico=None, lat=None, lon=None, nome_luogo=""):
    fraz, mun, qlat, qlon, cap = quartiere or random.choice(QUARTIERI)
    via = via or random.choice(VIE)
    civico = civico or str(random.randint(1, 180))
    lat = lat if lat is not None else round(qlat + random.uniform(-0.004, 0.004), 7)
    lon = lon if lon is not None else round(qlon + random.uniform(-0.005, 0.005), 7)
    display = f"{civico}, {via}, {fraz}, {mun}, Genova, Liguria, {cap}, Italia"
    if nome_luogo:
        display = f"{nome_luogo}, {display}"
    return {
        "inputName": f"{via} {civico},{cap} {fraz} Genova (Genova) Italia",
        "tipoIndirizzo": "",
        "nomeLuogo": nome_luogo,
        "displayName": display,
        "indirizzo": via,
        "numeroCivico": civico,
        "numeroInterno": "",
        "frazione": fraz,
        "citta": "Genova",
        "cap": cap,
        "provincia": "Genova",
        "regione": "Liguria",
        "nazione": "Italia",
        "codiceNazione": "it",
        "longitudine": lon,
        "latitudine": lat,
        "extraTags": {},
        "boundingBox": {
            "latitudineMin": round(lat - 0.00005, 7), "latitudineMax": round(lat + 0.00005, 7),
            "longitudineMin": round(lon - 0.00005, 7), "longitudineMax": round(lon + 0.00005, 7),
        },
        # Coordinate in GeoJSON. Attenzione all'ordine: [lon, lat]
        "geoJson": {"type": "Point", "coordinates": [lon, lat]},
    }


def doc_luogo(luogo_obj, indagine, creato):
    return {
        "_id": uid(),
        "tipoEntita": "Luogo",
        "versione": "1",
        "properties": {"luogo": luogo_obj},
        "labels": [],
        "principale": False,
        "indagineTatticaId": indagine,
        "creationDate": creato,
        "creationUser": "CC_User1",
        "modificationDate": creato,
        "modificationUser": "searchuser",
        "stato": "MODIFICATA",
        "trackingId": uid(),
        "imported": False,
        "tags": ["LuogoValidato"],
    }


def doc_relazione(id_persona, id_luogo, codice, indagine, creato, data_inizio, data_fine):
    return {
        "_id": uid(),
        "idEntita1": id_persona,
        "tipoEntita1": "PersonaFisica",
        "idEntita2": [id_luogo],
        "tipoEntita2": "Luogo",
        "codiceRelazione": codice,
        "categoria": CATEGORIA_LUOGO,
        "datiRelazione": {"elencoProprieta": {"dataInizio": data_inizio, "dataFine": data_fine}},
        "labels": [],
        "indagineTatticaId": indagine,
        "creationDate": creato,
        "creationUser": "CC_User1",
        "modificationDate": creato,
        "stato": "CREATA",
        "trackingId": uid(),
        "imported": False,
    }


def codice_fiscale_finto(nome, cognome, nascita, sesso):
    """Formato plausibile, NON valido (niente checksum reale): basta per la demo."""
    def cons(s):
        c = [ch for ch in s.upper() if ch.isalpha() and ch not in "AEIOU"]
        v = [ch for ch in s.upper() if ch in "AEIOU"]
        return (c + v + ["X", "X", "X"])[:3]
    mesi = "ABCDEHLMPRST"
    giorno = nascita.day + (40 if sesso == "F" else 0)
    return ("".join(cons(cognome)) + "".join(cons(nome)) + f"{nascita.year % 100:02d}"
            + mesi[nascita.month - 1] + f"{giorno:02d}" + "D969" + random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ"))


def doc_persona(nome, cognome, sesso, luogo_residenza, indagine, creato, _id=None):
    nascita = data_casuale(datetime(1940, 1, 1, tzinfo=timezone.utc), datetime(2005, 12, 31, tzinfo=timezone.utc))
    nascita = nascita.replace(hour=0, minute=0, second=0)
    sc = random.choice(STATI_CIVILI)
    return {
        "_id": _id or uid(),
        "tipoEntita": "PersonaFisica",
        "versione": "1",
        "fonti": [FONTE_MAN],
        "properties": {
            "coloreCapelli": random.choice([None, "castani", "neri", "biondi", "grigi"]),
            "dataDecesso": None,
            "gender": GENDER[sesso],
            "dataNascita": nascita,
            "cognome": cognome,
            "matricolaSidet": f"SDT{random.randint(1000000, 9999999)}",
            "nazionalita": random.choice(NAZIONALITA),
            "segniParticolari": random.choice(SEGNI) if random.random() < 0.6 else None,
            "nome": nome,
            "luogoNascita": None,
            "statoCivile": {"_id": uid(), "code": sc[0],
                            "langDescriptions": [{"langCode": "it-IT", "name": sc[1]},
                                                 {"langCode": "en-GB", "name": sc[2]}]},
            "codiceFiscale": codice_fiscale_finto(nome, cognome, nascita, sesso),
            "soprannomi": random.sample(SOPRANNOMI, 1) if random.random() < 0.15 else None,
            "dataIdentificazioneSidet": None,
            "immagine": None,
            "coloreOcchi": random.choice([None, "castani", "azzurri", "verdi"]),
            # Residenza ATTUALE embedded (copia del Luogo collegato con relazione Residente aperta)
            "luogoResidenza": luogo_residenza,
            "altezza": random.choice([None, random.randint(155, 195)]),
        },
        "labels": [],
        "principale": False,
        "indagineTatticaId": indagine,
        "creationDate": creato,
        "creationUser": "CC_User1",
        "modificationDate": creato,
        "modificationUser": "searchuser",
        "stato": random.choice(["CREATA", "MODIFICATA"]),
        "trackingId": uid(),
        "imported": False,
        "tags": [],
    }


# ----------------------------------------------------------------------------
# Generazione
# ----------------------------------------------------------------------------
def genera(n_persone: int):
    persone, luoghi, relazioni = [], [], []

    # Luoghi "notevoli" condivisi (bar, circoli...): molte persone li frequentano
    notevoli = []
    for nome_l in LUOGHI_NOTEVOLI:
        q = random.choice(QUARTIERI[:9])
        lo = oggetto_luogo(quartiere=q, nome_luogo=nome_l)
        d = doc_luogo(lo, INDAGINI[0], ORA)
        notevoli.append(d)
        luoghi.append(d)

    for i in range(n_persone):
        indagine = INDAGINI[0] if random.random() < 0.3 else random.choice(INDAGINI)
        creato = data_casuale(datetime(2024, 1, 1, tzinfo=timezone.utc), ORA)

        if i == 0:
            # La persona di riferimento della demo (Biagio Amalfi, Via Acquarone 5)
            sesso, nome, cognome = "M", "Biagio", "Amalfi"
            res = oggetto_luogo(quartiere=QUARTIERI[0], via="Via Acquarone", civico="5",
                                lat=44.4166842, lon=8.9368807)
            pid = "50a70b49-7544-4e19-affe-b52b926864f2"
        else:
            sesso = "M" if random.random() < 0.55 else "F"
            nome = random.choice(NOMI_M if sesso == "M" else NOMI_F)
            cognome = random.choice(COGNOMI)
            res = oggetto_luogo()
            pid = None

        p = doc_persona(nome, cognome, sesso, res, indagine, creato, _id=pid)
        persone.append(p)

        # 1) residenza attuale -> Luogo + Relazione aperta
        l_res = doc_luogo(res, indagine, creato)
        luoghi.append(l_res)
        relazioni.append(doc_relazione(p["_id"], l_res["_id"], "PersonaFisica_Luogo_Residente",
                                       indagine, creato, data_casuale(datetime(2015, 1, 1, tzinfo=timezone.utc), creato), None))

        # 2) 0..2 residenze/domicili storici (chiusi): NON sono nel documento persona
        for _ in range(random.choice([0, 0, 1, 1, 2])):
            lo = oggetto_luogo()
            ld = doc_luogo(lo, indagine, creato)
            luoghi.append(ld)
            inizio = data_casuale(datetime(2000, 1, 1, tzinfo=timezone.utc), datetime(2014, 12, 31, tzinfo=timezone.utc))
            relazioni.append(doc_relazione(p["_id"], ld["_id"],
                                           random.choice(["PersonaFisica_Luogo_Residente", "PersonaFisica_Luogo_Domicilio"]),
                                           indagine, creato, inizio, inizio + timedelta(days=random.randint(200, 3000))))

        # 3) 0..2 luoghi frequentati (condivisi)
        for ln in random.sample(notevoli, random.choice([0, 0, 0, 1, 1, 2])):
            relazioni.append(doc_relazione(p["_id"], ln["_id"], "PersonaFisica_Luogo_Frequenta",
                                           indagine, creato, None, None))

    # Qualche omonimo / parente di Amalfi per far vedere fuzzy e autocomplete
    for nome in ["Mario", "Lucia", "Giovanni"]:
        res = oggetto_luogo(quartiere=QUARTIERI[0])
        p = doc_persona(nome, "Amalfi", "F" if nome == "Lucia" else "M", res, INDAGINI[0], ORA)
        persone.append(p)
        l_res = doc_luogo(res, INDAGINI[0], ORA)
        luoghi.append(l_res)
        relazioni.append(doc_relazione(p["_id"], l_res["_id"], "PersonaFisica_Luogo_Residente",
                                       INDAGINI[0], ORA, ORA - timedelta(days=900), None))

    return persone, luoghi, relazioni


def scrivi_campioni(persone, luoghi, relazioni):
    os.makedirs("campioni", exist_ok=True)
    for nome, docs in [("personaFisica", persone[:3]), ("luogo", luoghi[:3]), ("relazione", relazioni[:3])]:
        with open(f"campioni/{nome}.json", "w", encoding="utf-8") as f:
            f.write(json_util.dumps(docs, indent=2, ensure_ascii=False,
                                    json_options=json_util.RELAXED_JSON_OPTIONS))
    print("Campioni scritti in ./campioni")


def carica(persone, luoghi, relazioni):
    from pymongo import ASCENDING, GEOSPHERE
    from common import client
    db = client()[config.DB_NAME]

    for c in [config.COLL_PERSONA, config.COLL_LUOGO, config.COLL_RELAZIONE, config.COLL_VISTA]:
        db.drop_collection(c)

    def batch_insert(coll, docs, size=2000):
        for i in range(0, len(docs), size):
            coll.insert_many(docs[i:i + size], ordered=False)

    print(f"Inserisco {len(persone)} persone, {len(luoghi)} luoghi, {len(relazioni)} relazioni...")
    batch_insert(db[config.COLL_PERSONA], persone)
    batch_insert(db[config.COLL_LUOGO], luoghi)
    batch_insert(db[config.COLL_RELAZIONE], relazioni)

    print("Creo indici 2dsphere e indici sulle relazioni...")
    db[config.COLL_PERSONA].create_index([("properties.luogoResidenza.geoJson", GEOSPHERE)], name="residenza_2dsphere")
    db[config.COLL_LUOGO].create_index([("properties.luogo.geoJson", GEOSPHERE)], name="luogo_2dsphere")
    db[config.COLL_RELAZIONE].create_index([("idEntita1", ASCENDING), ("codiceRelazione", ASCENDING)], name="da_entita")
    db[config.COLL_RELAZIONE].create_index([("idEntita2", ASCENDING), ("codiceRelazione", ASCENDING)], name="a_entita")

    for c in [config.COLL_PERSONA, config.COLL_LUOGO, config.COLL_RELAZIONE]:
        print(f"  {c:15s} {db[c].estimated_document_count():>8} documenti")
    print("Fatto.")


if __name__ == "__main__":
    p, l, r = genera(config.N_PERSONE)
    scrivi_campioni(p, l, r)
    if "--dry-run" in sys.argv:
        print(f"[dry-run] generati {len(p)} persone, {len(l)} luoghi, {len(r)} relazioni (nessun caricamento)")
    else:
        carica(p, l, r)
