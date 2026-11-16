"""
Passi della demo web. Ogni passo: spiegazione + parametri + funzione che esegue
e restituisce un risultato strutturato (metriche, evidenza, tabelle, mappa, documenti).
"""
import re
import time
from collections import Counter
from datetime import datetime
from functools import lru_cache

from bson import decode, encode, json_util
from pymongo import MongoClient, monitoring

import config
from common import db, dentro_poligono, evidenzia, lettere_diverse, metri

IDX = config.SEARCH_INDEX_PERSONA
IDX_QE = config.SEARCH_INDEX_PERSONA_QE
PUNTO = config.PUNTO_ACQUARONE
POLI = config.POLIGONO_CENTRO_STORICO[0]
GEO = "properties.luogoResidenza.geoJson"
INDAGINE = "ff7f103e-8a54-4edb-878b-37c462b17eb5"
ID_BIAGIO = "50a70b49-7544-4e19-affe-b52b926864f2"
COLORI_REL = {"Residente": "#016BF8", "Domicilio": "#E0A800", "Frequenta": "#DB3030"}

REGISTRO = []
NOMI_INDAGINI = ["Operazione Lanterna", "Operazione Porto Antico", "Operazione Boccadasse", "Operazione Righi",
                 "Operazione Bisagno", "Operazione Polcevera", "Operazione Caricamento", "Operazione Sottoripa"]


@lru_cache
def indagini():
    """UUID indagineTatticaId -> nome leggibile (solo per la demo), ordinate per numero di persone."""
    out = {}
    for i, x in enumerate(db()[config.COLL_PERSONA].aggregate(
            [{"$group": {"_id": "$indagineTatticaId", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}])):
        out[x["_id"]] = dict(nome=NOMI_INDAGINI[i] if i < len(NOMI_INDAGINI) else f"Indagine {i + 1}", n=x["n"])
    return out


def nome_indagine(uuid):
    return indagini().get(uuid, {}).get("nome", uuid)


def passo(tab, id, titolo, cosa, perche, opensearch, params=(), auto=False, mappa=False, largo=False, scena=None, extra=None):
    def deco(fn):
        REGISTRO.append(dict(tab=tab, id=id, titolo=titolo, cosa=cosa, perche=perche, opensearch=opensearch,
                             params=list(params), auto=auto, mappa=mappa, largo=largo, scena=scena, extra=extra or [], fn=fn))
        return fn
    return deco


def P(nome, etichetta, tipo="text", default=None, **kw):
    return dict(nome=nome, etichetta=etichetta, tipo=tipo, default=default, **kw)


class Crono:
    """Somma i millisecondi delle operazioni sul database."""
    def __init__(self):
        self.ms = 0.0

    def __call__(self, fn, *a, **k):
        t0 = time.perf_counter()
        r = fn(*a, **k)
        self.ms += (time.perf_counter() - t0) * 1000
        return r


def coll(nome=config.COLL_PERSONA):
    return db()[nome]


def conta(stage, c=None):
    s = dict(stage)
    s["count"] = {"type": "total"}
    r = list((c or coll()).aggregate([{"$searchMeta": s}]))
    return r[0]["count"]["total"] if r else 0


def anello(pts):
    pts = [list(map(float, p)) for p in (pts or POLI)]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def via(display):
    parti = [x.strip() for x in (display or "").split(",")]
    return f"{parti[1]} {parti[0]}" if len(parti) > 1 else display


def M(etichetta, valore, nota=""):
    return dict(etichetta=etichetta, valore=valore, nota=nota)


def T(titolo, colonne, righe, vuoto="nessun risultato"):
    return dict(titolo=titolo, colonne=colonne, righe=righe, vuoto=vuoto)


def punto_persona(d, label=None, colore=None):
    c = d["coord"]
    return dict(lon=c[0], lat=c[1], label=label or f"{d.get('nome', '')} {d.get('cognome', '')}", colore=colore)


PROJ = {"_id": 0, "nome": "$properties.nome", "cognome": "$properties.cognome",
        "quartiere": "$properties.luogoResidenza.frazione",
        "indirizzo": "$properties.luogoResidenza.displayName",
        "coord": "$properties.luogoResidenza.geoJson.coordinates"}
SCORE = {"score": {"$round": [{"$meta": "searchScore"}, 2]}}


# =============================================================================
# FULL TEXT
# =============================================================================
@passo("fulltext", "A", "Ricerca tollerante agli errori di battitura",
       "Cerchiamo un nome scritto male. Prima senza tolleranza, poi con la tolleranza di N lettere per parola.",
       "Chi inserisce i dati sbaglia, e chi cerca sbaglia. Senza fuzzy la persona non si trova; con fuzzy sì. "
       "La colonna 'lettere diverse' mostra quanto ogni risultato è lontano da ciò che è stato scritto.",
       "query 'match' con 'fuzziness'.",
       [P("testo", "Testo cercato", default="Biaggio Amalfy"),
        P("maxEdits", "Lettere di tolleranza per parola", "select", 1, opzioni=[1, 2])])
def ft_a(p):
    c = Crono()
    testo, me = p["testo"], int(p["maxEdits"])
    base = {"index": IDX, "text": {"query": testo, "path": ["properties.nome", "properties.cognome"]}}
    fz = {"index": IDX, "text": {**base["text"], "fuzzy": {"maxEdits": me}}}
    q = [{"$search": fz}, {"$limit": 10}, {"$project": PROJ}]
    n0 = c(conta, base)
    n1 = c(conta, fz)
    senza = c(lambda: list(coll().aggregate([{"$search": base}, {"$limit": 10}, {"$project": PROJ}])))
    ris = c(lambda: list(coll().aggregate(q)))
    parole = testo.split()
    def riga(x):
        return {"nome trovato": x["nome"], "cognome trovato": x["cognome"], "quartiere": x["quartiere"],
                "lettere diverse da quanto scritto": sum(min(lettere_diverse(w, x["nome"]), lettere_diverse(w, x["cognome"])) for w in parole)}
    col = ["nome trovato", "cognome trovato", "lettere diverse da quanto scritto", "quartiere"]
    return dict(query=q, ms=c.ms,
                metriche=[M("Senza tolleranza", n0, f"cercando «{testo}»"), M(f"Con tolleranza {me}", n1, f"cercando «{testo}»")],
                evidenza=f"«{testo}» non esiste nei dati: senza tolleranza {n0} risultati. Con la tolleranza il database trova "
                         f"{n1} persone dal nome simile; la colonna 'lettere diverse' dice di quanto differiscono da ciò che è stato scritto.",
                tabelle=[T(f"1) SENZA tolleranza — hai cercato «{testo}»", col, [riga(x) for x in senza],
                           vuoto=f"Nessun risultato: nessuno nei dati si chiama esattamente «{testo}»."),
                         T(f"2) CON tolleranza {me} — stessa ricerca «{testo}»", col, [riga(x) for x in ris])])


@passo("fulltext", "B", "Suggerimenti mentre si scrive (autocomplete)",
       "Scrivi nella casella: a ogni lettera il database propone i cognomi che iniziano così, con il numero di persone.",
       "È la casella di ricerca che completa mentre scrivi. Il tempo di risposta resta di pochi millisecondi a ogni tasto.",
       "campo 'search_as_you_type' o edge n-gram.",
       [P("testo", "Scrivi un cognome (almeno 2 lettere)", default="amal", esempi=["amal", "mar", "fer", "co", "ga", "ros"])], auto=True)
def ft_b(p):
    c = Crono()
    t = (p.get("testo") or "").strip()
    if len(t) < 2:
        return dict(query=None, ms=0, metriche=[], evidenza="scrivi almeno 2 lettere", tabelle=[])
    q = [{"$search": {"index": IDX, "autocomplete": {"query": t, "path": "properties.cognome"}}},
         {"$group": {"_id": "$properties.cognome", "persone": {"$sum": 1}}}, {"$sort": {"persone": -1}}, {"$limit": 10}]
    ris = c(lambda: list(coll().aggregate(q)))
    return dict(query=q, ms=c.ms, metriche=[M("Cognomi suggeriti", len(ris)), M("Tempo", f"{c.ms:.0f} ms")],
                evidenza=f"con '{t}' il database suggerisce: {', '.join(x['_id'] for x in ris) or 'nessun cognome'}.",
                tabelle=[T("Suggerimenti", ["cognome", "persone"], [dict(cognome=x["_id"], persone=x["persone"]) for x in ris])])


@passo("fulltext", "C", "Testo libero sull'indirizzo, con le parole trovate evidenziate",
       "Cerchiamo parole dentro l'indirizzo. Confrontiamo chi le contiene tutte con chi ne contiene una sola.",
       "Lo score misura la pertinenza: chi contiene più parole sta sopra. Il database restituisce anche quali parole "
       "hanno fatto match, evidenziate in giallo, pronte per l'interfaccia.",
       "'match' + 'highlight'.",
       [P("testo", "Parole da cercare nell'indirizzo", default="acquarone castelletto")])
def ft_c(p):
    c = Crono()
    q = [{"$search": {"index": IDX, "text": {"query": p["testo"], "path": "properties.luogoResidenza.displayName"},
                      "highlight": {"path": "properties.luogoResidenza.displayName"}}},
         {"$limit": 400}, {"$project": {**PROJ, **SCORE, "hl": {"$meta": "searchHighlights"}}}]
    ris = c(lambda: list(coll().aggregate(q)))
    nparole = len(set(p["testo"].lower().split()))
    for x in ris:
        x["indirizzo (parole trovate)"] = evidenzia(x.pop("hl"))
        x["parole trovate"] = len({w.lower() for w in re.findall(r"«([^»]+)»", x["indirizzo (parole trovate)"])})
    tutte = [x for x in ris if x["parole trovate"] >= nparole]
    meno = [x for x in ris if x["parole trovate"] < nparole]
    col = ["parole trovate", "score", "nome", "cognome", "indirizzo (parole trovate)"]
    ev = (f"chi contiene tutte le parole ha score {min(x['score'] for x in tutte)}–{max(x['score'] for x in tutte)}; "
          f"chi ne contiene meno arriva al massimo a {max(x['score'] for x in meno)}."
          if tutte and meno else f"{len(ris)} risultati")
    return dict(query=q, ms=c.ms, metriche=[M("Con tutte le parole", len(tutte)), M("Con meno parole", len(meno))],
                evidenza=ev, tabelle=[T("Contengono tutte le parole (in cima)", col, tutte[:6]),
                                      T("Contengono meno parole (più in basso)", col, meno[:6])])


@passo("fulltext", "D", "Testo libero su segni particolari e soprannomi",
       "Cerchiamo chi ha certi segni particolari OPPURE un certo soprannome.",
       "Basta una condizione per essere trovati, ma chi le soddisfa entrambe è più pertinente: lo score lo mette in "
       "cima. Le colonne sì/– permettono di verificarlo.",
       "'bool' con due 'should' e 'minimum_should_match'.",
       [P("segni", "Segni particolari", default="tatuaggio drago"), P("soprannome", "Soprannome", default="biondo")])
def ft_d(p):
    c = Crono()
    cond = [{"text": {"query": p[k].strip(), "path": path}} for k, path in
            (("segni", "properties.segniParticolari"), ("soprannome", "properties.soprannomi")) if (p.get(k) or "").strip()]
    if not cond:
        return dict(query=None, ms=0, metriche=[], evidenza="compila almeno uno dei due campi", tabelle=[])
    q = [{"$search": {"index": IDX, "compound": {"should": cond, "minimumShouldMatch": 1}}},
         {"$limit": 300},
         {"$project": {**PROJ, **SCORE, "segni": "$properties.segniParticolari",
                       "soprannome": {"$first": "$properties.soprannomi"}}}]
    ris = c(lambda: list(coll().aggregate(q)))
    ws, wn = (p.get("segni") or "").lower().split(), (p.get("soprannome") or "").lower().split()
    for x in ris:
        x["segni ok"] = "sì" if ws and all(w in (x.get("segni") or "").lower() for w in ws) else "–"
        x["soprannome ok"] = "sì" if wn and all(w in (x.get("soprannome") or "").lower() for w in wn) else "–"
    ent = [x for x in ris if x["segni ok"] == "sì" and x["soprannome ok"] == "sì"]
    una = [x for x in ris if x not in ent]
    col = ["nome", "cognome", "segni", "segni ok", "soprannome", "soprannome ok", "score"]
    ev = (f"chi soddisfa entrambe ha score {min(x['score'] for x in ent)}; con una sola condizione lo score massimo è "
          f"{max(x['score'] for x in una)}." if ent and una else f"{len(ris)} risultati")
    return dict(query=q, ms=c.ms, metriche=[M("Entrambe le condizioni", len(ent)), M("Una sola", len(una))],
                evidenza=ev, tabelle=[T("Entrambe le condizioni", col, ent[:5]), T("Una sola condizione", col, una[:5])])


@passo("fulltext", "E", "Testo + filtro per indagine + intervallo di date",
       "Un cognome, ma solo per un'indagine e solo per i nati in un intervallo di anni. Nel database l'indagine è il "
       "campo indagineTatticaId (un identificativo): qui la mostriamo con un nome leggibile.",
       "Ogni documento appartiene a un'indagine e un operatore deve vedere solo la sua. Il filtro sta nella stessa "
       "query; le colonne indagine e nascita permettono di verificarlo riga per riga.",
       "'bool' con 'must' + 'filter' (term + range).",
       [P("cognome", "Cognome", default="rossi"), P("indagine", "Indagine", "select", INDAGINE, opzioni="@indagini"),
        P("da", "Nati dal", "number", 1970), P("a", "al", "number", 1989)])
def ft_e(p):
    c = Crono()
    da, a = int(p["da"]), int(p["a"])
    solo = {"index": IDX, "text": {"query": p["cognome"], "path": "properties.cognome"}}
    s = {"index": IDX, "compound": {"must": [{"text": solo["text"]}], "filter": [
        {"equals": {"path": "indagineTatticaId", "value": p["indagine"]}},
        {"range": {"path": "properties.dataNascita", "gte": datetime(da, 1, 1), "lt": datetime(a + 1, 1, 1)}}]}}
    q = [{"$search": s}, {"$limit": 10},
         {"$project": {**PROJ, "indagine": "$indagineTatticaId",
                       "nascita": {"$dateToString": {"date": "$properties.dataNascita", "format": "%Y-%m-%d"}}}}]
    s_ind = {"index": IDX, "compound": {"must": [{"text": solo["text"]}], "filter": [s["compound"]["filter"][0]]}}
    tot, ind, filt = c(conta, solo), c(conta, s_ind), c(conta, s)
    ris = c(lambda: list(coll().aggregate(q)))
    ok = all(x["indagine"] == p["indagine"] and str(da) <= x["nascita"][:4] <= str(a) for x in ris)
    for x in ris:
        x["indagine"] = nome_indagine(x["indagine"])
    return dict(query=q, ms=c.ms, metriche=[M(f"«{p['cognome']}» in tutto il database", tot, "nessun filtro"),
                                            M(f"… in {nome_indagine(p['indagine'])}", ind, "filtro indagine"),
                                            M(f"… e nati {da}–{a}", filt, "filtro indagine + date")],
                evidenza=f"{tot} → {ind} → {filt}: ogni filtro restringe il risultato. " + ("Ogni riga mostra l'indagine scelta e una data nell'intervallo."
                                                   if ok else "ATTENZIONE: controllo fallito"),
                tabelle=[T("Primi 10", ["nome", "cognome", "indagine", "nascita"], ris)])


FACCETTE = [
    ("quartiere", "Quartiere", "properties.luogoResidenza.frazione", "string"),
    ("nazionalita", "Nazionalità", "properties.nazionalita", "string"),
    ("genere", "Genere", "properties.gender.code", "string"),
    ("indagine", "Indagine", "indagineTatticaId", "string"),
    ("decennio", "Decennio di nascita", "properties.dataNascita", "date"),
]
DECENNI = [datetime(y, 1, 1) for y in range(1940, 2020, 10)]
GENERI = {"M": "Maschio", "F": "Femmina"}


def filtro_faccetta(chiave, path, tipo, valori):
    if tipo == "date":
        rng = [{"range": {"path": path, "gte": datetime(int(v), 1, 1), "lt": datetime(int(v) + 10, 1, 1)}} for v in valori]
        return {"compound": {"should": rng, "minimumShouldMatch": 1}}
    return {"in": {"path": path, "value": list(valori)}}


def operatore(testo, filtri):
    must = ([{"text": {"query": testo, "path": ["properties.cognome", "properties.nome"], "fuzzy": {"maxEdits": 1}}}]
            if testo else [{"exists": {"path": "properties.cognome"}}])
    flt = [filtro_faccetta(k, path, tipo, filtri[k]) for k, _, path, tipo in FACCETTE if filtri.get(k)]
    return {"compound": {"must": must, **({"filter": flt} if flt else {})}}


def definizione(k, path, tipo):
    if tipo == "date":
        return {"type": "date", "path": path, "boundaries": DECENNI, "default": "altro"}
    return {"type": "string", "path": path, "numBuckets": 20}


@passo("fulltext", "F", "Filtri laterali con contatori (facet)",
       "Una ricerca come sui siti di e-commerce: scrivi (o lascia vuoto) e spunta i filtri a sinistra. Accanto a ogni "
       "valore c'è il numero di persone che resterebbero spuntandolo. In gergo tecnico questi contatori si chiamano facet.",
       "L'operatore vede subito come si distribuiscono i risultati e restringe con un clic. Risultati e contatori "
       "arrivano dallo stesso indice e si aggiornano insieme a ogni clic.",
       "'aggregations' di tipo 'terms' e 'date_histogram' accanto alla query.",
       [P("testo", "Cerca per nome o cognome (vuoto = tutti)", default="", esempi=["rossi", "amalfi", "parodi", "maria"]),
        P("filtri", "", "faccette", {})], auto=True)
def ft_f(p):
    c = Crono()
    testo = (p.get("testo") or "").strip()
    filtri = {k: v for k, v in (p.get("filtri") or {}).items() if v}
    op = operatore(testo, filtri)
    q_ris = [{"$search": {"index": IDX, **op}}, {"$limit": 15},
             {"$project": {**PROJ, "genere": "$properties.gender.code", "nazionalità": "$properties.nazionalita",
                           "nascita": {"$dateToString": {"date": "$properties.dataNascita", "format": "%Y"}},
                           "indagine": "$indagineTatticaId"}}]
    totale = c(conta, {"index": IDX, **op})
    ris = c(lambda: list(coll().aggregate(q_ris)))
    ind = {k: v["nome"] for k, v in indagini().items()}
    for x in ris:
        x["indagine"] = ind.get(x.get("indagine"), x.get("indagine"))
        x["genere"] = GENERI.get(x.get("genere"), x.get("genere"))
    # contatori: per ogni filtro si applicano tutti gli ALTRI filtri (così i valori dello stesso gruppo restano visibili)
    gruppi, q_meta = [], None
    for k, titolo, path, tipo in FACCETTE:
        altri = {kk: vv for kk, vv in filtri.items() if kk != k}
        qm = [{"$searchMeta": {"index": IDX, "facet": {"operator": operatore(testo, altri),
                                                       "facets": {k: definizione(k, path, tipo)}}}}]
        if q_meta is None:
            q_meta = qm
        meta = c(lambda: list(coll().aggregate(qm)))
        valori = []
        for bkt in (meta[0]["facet"][k]["buckets"] if meta else []):
            if tipo == "date":
                if bkt["_id"] == "altro" or not bkt["count"]:
                    continue
                v = str(bkt["_id"].year)
                label = f"{v}–{str(bkt['_id'].year + 9)[2:]}"
            else:
                v = bkt["_id"]
                label = (GENERI.get(v) if k == "genere" else ind.get(v) if k == "indagine" else v) or v
            valori.append(dict(valore=v, label=label, n=bkt["count"], selezionato=v in filtri.get(k, [])))
        if tipo == "date":
            valori.sort(key=lambda x: x["valore"])
        gruppi.append(dict(chiave=k, titolo=titolo, valori=valori))
    sel = [f"{t}: {', '.join(next((x['label'] for g in gruppi if g['chiave'] == k for x in g['valori'] if x['valore'] == v), v) for v in filtri[k])}"
           for k, t, _, _ in FACCETTE if filtri.get(k)]
    ev = (f"{totale} persone" + (f" per «{testo}»" if testo else "") + (f", con filtri — {'; '.join(sel)}" if sel else ", nessun filtro") +
          ". Il numero accanto a ogni casella dice quante persone resterebbero spuntandola: lo calcola il database, a ogni clic.")
    return dict(query=[{"risultati": q_ris}, {"contatori (uno per gruppo di filtri)": q_meta}], ms=c.ms,
                metriche=[M("Persone trovate", totale), M("Filtri attivi", sum(len(v) for v in filtri.values()))],
                evidenza=ev, faccette=gruppi,
                tabelle=[T(f"Primi {len(ris)} di {totale}", ["nome", "cognome", "genere", "nascita", "nazionalità", "quartiere", "indagine"], ris)])


# =============================================================================
# GEO NATIVO
# =============================================================================
def persone_geo(filtro, c, limite=5000):
    docs = c(lambda: list(coll().find(filtro, {"_id": 0, "properties.nome": 1, "properties.cognome": 1,
                                               "properties.nazionalita": 1, "indagineTatticaId": 1,
                                               "properties.luogoResidenza.displayName": 1,
                                               "properties.luogoResidenza.frazione": 1, GEO: 1}).limit(limite)))
    out = []
    for d in docs:
        pr = d["properties"]
        out.append(dict(nome=pr["nome"], cognome=pr["cognome"], quartiere=pr["luogoResidenza"]["frazione"],
                        indirizzo=via(pr["luogoResidenza"]["displayName"]), nazionalità=pr.get("nazionalita"),
                        indagine=nome_indagine(d.get("indagineTatticaId")), coord=pr["luogoResidenza"]["geoJson"]["coordinates"]))
    return out


@passo("geo", "A", "Punto + raggio",
       "Clicca sulla mappa per scegliere il punto e imposta il raggio: troviamo chi risiede dentro il cerchio.",
       "È la ricerca per distanza che in OpenSearch si fa con il geo_point: qui è un operatore nativo del database con un indice "
       "geografico, senza motore di ricerca. La distanza di ogni risultato è ricalcolata a parte.",
       "filtro 'geo_distance' su campo geo_point.",
       [P("punto", "Punto (clic sulla mappa)", "punto", PUNTO), P("raggio", "Raggio (metri)", "range", 300, min=50, max=2000, step=50)])
def geo_a(p):
    c = Crono()
    pt, r = p["punto"], float(p["raggio"])
    q = {GEO: {"$geoWithin": {"$centerSphere": [pt, r / 6378100.0]}}}
    docs = persone_geo(q, c)
    for d in docs:
        d["metri"] = round(metri(pt, d["coord"]))
    lontani = sorted(docs, key=lambda d: -d["metri"])
    mx = lontani[0]["metri"] if docs else 0
    return dict(query=q, ms=c.ms, metriche=[M("Persone nel cerchio", len(docs)), M("La più lontana", f"{mx} m", f"raggio {r:.0f} m")],
                evidenza=(f"{len(docs)} persone; la più lontana è a {mx} m, quindi tutte entro i {r:.0f} m." if mx <= r + 1
                          else f"ATTENZIONE: la più lontana è a {mx} m, oltre il raggio di {r:.0f} m."),
                tabelle=[T("Le più lontane dal punto (la verifica del limite)", ["nome", "cognome", "indirizzo", "quartiere", "metri"], lontani[:8])],
                mappa=dict(punti=[punto_persona(d, f"{d['nome']} {d['cognome']} – {d['metri']} m") for d in docs],
                           cerchio=dict(centro=pt, raggio=r), centro=pt))


@passo("geo", "B", "Poligono: chi è dentro un'area disegnata",
       "Disegna un poligono sulla mappa (o usa quello del Centro Storico): troviamo chi risiede dentro.",
       "È il caso 'n punti che definiscono un'area'. Ogni risultato viene ricontrollato con un calcolo geometrico "
       "indipendente.",
       "filtro 'geo_polygon' / 'geo_shape'.",
       [P("poligono", "Poligono (disegna sulla mappa)", "poligono", POLI)])
def geo_b(p):
    c = Crono()
    an = anello(p["poligono"])
    q = {GEO: {"$geoWithin": {"$geometry": {"type": "Polygon", "coordinates": [an]}}}}
    docs = persone_geo(q, c)
    ver = sum(dentro_poligono(d["coord"], an) for d in docs)
    return dict(query=q, ms=c.ms, metriche=[M("Persone trovate", len(docs)), M("Confermate dentro", ver, "calcolo indipendente")],
                evidenza=f"{len(docs)} persone trovate dal database, {ver} confermate dentro il poligono dal calcolo indipendente.",
                tabelle=[T("Esempi", ["nome", "cognome", "indirizzo", "quartiere"], docs[:8])],
                mappa=dict(punti=[punto_persona(d) for d in docs], poligono=an))


@passo("geo", "C", "I più vicini, con la distanza in metri",
       "Clicca un punto sulla mappa: le N persone che abitano più vicino, ordinate per distanza.",
       "È la prima domanda di chi indaga su un indirizzo. Il database ordina e restituisce la distanza; sulla mappa i "
       "punti sono numerati.",
       "ordinamento '_geo_distance'.",
       [P("punto", "Punto (clic sulla mappa)", "punto", PUNTO), P("n", "Quanti", "number", 10)])
def geo_c(p):
    c = Crono()
    q = [{"$geoNear": {"near": {"type": "Point", "coordinates": p["punto"]}, "key": GEO,
                       "distanceField": "distanzaMetri", "spherical": True}},
         {"$limit": int(p["n"])},
         {"$project": {**PROJ, "metri": {"$round": ["$distanzaMetri", 0]}}}]
    ris = c(lambda: list(coll().aggregate(q)))
    for i, x in enumerate(ris, 1):
        x["posizione"], x["indirizzo"] = i, via(x["indirizzo"])
    return dict(query=q, ms=c.ms, metriche=[M("Il più vicino", f"{ris[0]['metri']:.0f} m" if ris else "-"),
                                            M(f"Il {len(ris)}°", f"{ris[-1]['metri']:.0f} m" if ris else "-")],
                evidenza="distanze crescenti dall'alto in basso: l'ordinamento lo fa il database.",
                tabelle=[T("Ordinati per distanza", ["posizione", "metri", "nome", "cognome", "indirizzo"], ris)],
                mappa=dict(punti=[punto_persona(x, f"{x['posizione']}. {x['nome']} {x['cognome']} – {x['metri']:.0f} m") for x in ris],
                           centro=p["punto"], numerati=True))


@passo("geo", "D", "Geo + altri filtri: quanti documenti legge davvero",
       "Raggio + nazionalità + indagine nella stessa query. Poi chiediamo al database quanti documenti ha letto.",
       "Grazie all'indice geografico il database legge solo i documenti dell'area, non tutta la collection: è questo "
       "che lo tiene veloce quando i dati crescono.",
       "'bool' con 'filter' geo_distance + term.",
       [P("punto", "Punto (clic sulla mappa)", "punto", PUNTO), P("raggio", "Raggio (metri)", "range", 1500, min=100, max=3000, step=100),
        P("nazionalita", "Nazionalità", "select", "(non italiana)", opzioni="@nazionalita"),
        P("indagine", "Indagine", "select", INDAGINE, opzioni="@indagini")])
def geo_d(p):
    c = Crono()
    naz = {"$ne": "Italiana"} if p["nazionalita"] == "(non italiana)" else p["nazionalita"]
    q = {GEO: {"$geoWithin": {"$centerSphere": [p["punto"], float(p["raggio"]) / 6378100.0]}},
         "properties.nazionalita": naz, "indagineTatticaId": p["indagine"]}
    docs = persone_geo(q, c)
    st = coll().find(q).explain()["executionStats"]
    tot = coll().estimated_document_count()
    return dict(query=q, ms=c.ms, metriche=[M("Risultati", len(docs)), M("Documenti letti", st["totalDocsExamined"]),
                                            M("Documenti in collection", tot)],
                evidenza=f"{len(docs)} risultati leggendo {st['totalDocsExamined']} documenti su {tot}: l'indice esclude "
                         f"a priori tutto ciò che è fuori dall'area.",
                tabelle=[T("Esempi", ["nome", "cognome", "nazionalità", "indagine", "quartiere"], docs[:8])],
                mappa=dict(punti=[punto_persona(d, f"{d['nome']} {d['cognome']} – {d['nazionalità']}") for d in docs],
                           cerchio=dict(centro=p["punto"], raggio=float(p["raggio"])), centro=p["punto"]))


# =============================================================================
# TESTO + GEO
# =============================================================================
def con_metri(ris, pt):
    for x in ris:
        x["metri"] = round(metri(pt, x["coord"]))
        if "indirizzo" in x:
            x["indirizzo"] = via(x["indirizzo"])
    return ris


@passo("testogeo", "A", "Cognome con errore + entro un raggio",
       "Un cognome scritto male, ma solo tra chi abita entro il raggio scelto sulla mappa.",
       "Testo e area geografica nella stessa query e nello stesso indice. La distanza di ogni risultato e la mappa "
       "permettono di verificare che nessuno sia fuori dal cerchio.",
       "'bool' con 'must' match fuzzy + 'filter' geo_distance.",
       [P("cognome", "Cognome (anche sbagliato)", default="Amalfy"), P("punto", "Punto (clic sulla mappa)", "punto", PUNTO),
        P("raggio", "Raggio (metri)", "range", 1000, min=100, max=3000, step=100)])
def tg_a(p):
    c = Crono()
    txt = {"text": {"query": p["cognome"], "path": "properties.cognome", "fuzzy": {"maxEdits": 1}}}
    s = {"index": IDX, "compound": {"must": [txt], "filter": [{"geoWithin": {"path": GEO, "circle": {
        "center": {"type": "Point", "coordinates": p["punto"]}, "radius": float(p["raggio"])}}}]}}
    q = [{"$search": s}, {"$limit": 2000}, {"$project": PROJ}]
    tutti, area = c(conta, {"index": IDX, **txt}), c(conta, s)
    ris = con_metri(c(lambda: list(coll().aggregate(q))), p["punto"])
    mx = max((x["metri"] for x in ris), default=0)
    return dict(query=q, ms=c.ms, metriche=[M("In tutta Genova", tutti), M("Nel raggio", area), M("Il più lontano", f"{mx} m")],
                evidenza=(f"da {tutti} a {area}: il più lontano è a {mx} m, entro i {float(p['raggio']):.0f} m richiesti."
                          if mx <= float(p["raggio"]) + 1 else f"ATTENZIONE: il più lontano è a {mx} m, oltre il raggio."),
                tabelle=[T("I più lontani dal punto", ["nome", "cognome", "quartiere", "metri"], sorted(ris, key=lambda x: -x["metri"])[:8])],
                mappa=dict(punti=[punto_persona(x, f"{x['nome']} {x['cognome']} – {x['metri']} m") for x in ris],
                           cerchio=dict(centro=p["punto"], raggio=float(p["raggio"])), centro=p["punto"]))


@passo("testogeo", "B", "Autocomplete dentro un'area disegnata",
       "Disegna un'area sulla mappa e scrivi nella casella: i suggerimenti arrivano mentre scrivi, solo dall'area.",
       "Suggerimenti mentre scrivi, limitati all'area selezionata, in una sola query. Sulla mappa si vedono i punti "
       "aggiornarsi a ogni lettera.",
       "search_as_you_type + filtro 'geo_polygon'.",
       [P("poligono", "Area (disegna sulla mappa)", "poligono", POLI), P("testo", "Scrivi un cognome", default="ros", esempi=["ros", "mar", "fer", "co", "ga", "amal"])], auto=True)
def tg_b(p):
    c = Crono()
    t = (p.get("testo") or "").strip()
    an = anello(p["poligono"])
    if len(t) < 2:
        return dict(query=None, ms=0, metriche=[], evidenza="scrivi almeno 2 lettere", tabelle=[], mappa=dict(punti=[], poligono=an))
    ac = {"autocomplete": {"query": t, "path": "properties.cognome"}}
    s = {"index": IDX, "compound": {"must": [ac], "filter": [{"geoWithin": {"path": GEO, "geometry": {
        "type": "Polygon", "coordinates": [an]}}}]}}
    q = [{"$search": s}, {"$limit": 2000}, {"$project": PROJ}]
    tutti = c(conta, {"index": IDX, **ac})
    ris = c(lambda: list(coll().aggregate(q)))
    ver = sum(dentro_poligono(x["coord"], an) for x in ris)
    cog = Counter(x["cognome"] for x in ris)
    return dict(query=q, ms=c.ms, metriche=[M("In tutta Genova", tutti), M("Nell'area", len(ris)), M("Confermati dentro", ver)],
                evidenza=f"'{t}': {tutti} in tutta Genova, {len(ris)} nell'area, {ver} confermati dentro il poligono.",
                tabelle=[T("Cognomi suggeriti nell'area", ["cognome", "persone"], [dict(cognome=k, persone=v) for k, v in cog.most_common(8)])],
                mappa=dict(punti=[punto_persona(x) for x in ris], poligono=an))


@passo("testogeo", "C", "Più vicino = più in alto in classifica",
       "Lo stesso cognome cercato due volte: senza e con un criterio che premia chi abita vicino al punto scelto.",
       "Qui la distanza non esclude nessuno: entra nello score. Confrontando le due tabelle si vede che con la "
       "vicinanza le distanze crescono dall'alto in basso.",
       "ordinamento per '_geo_distance' o function_score con decay.",
       [P("cognome", "Cognome", default="parodi"), P("punto", "Punto (clic sulla mappa)", "punto", PUNTO)])
def tg_c(p):
    c = Crono()
    txt = {"text": {"query": p["cognome"], "path": "properties.cognome"}}
    q = [{"$search": {"index": IDX, "compound": {"must": [txt], "should": [{"near": {"path": GEO, "origin": {
        "type": "Point", "coordinates": p["punto"]}, "pivot": 1000}}]}}}, {"$limit": 10}, {"$project": {**PROJ, **SCORE}}]
    con = con_metri(c(lambda: list(coll().aggregate(q))), p["punto"])
    senza = con_metri(c(lambda: list(coll().aggregate([{"$search": {"index": IDX, **txt}}, {"$limit": 10},
                                                         {"$project": {**PROJ, **SCORE}}]))), p["punto"])
    for lst in (con, senza):
        for i, x in enumerate(lst, 1):
            x["posizione"] = i
    col = ["posizione", "nome", "cognome", "quartiere", "metri", "score"]
    ordinati = all(con[i]["metri"] <= con[i + 1]["metri"] + 150 for i in range(len(con) - 1))
    chiave = lambda x: (x["nome"], x["cognome"], x["metri"])
    nuovi = len({chiave(x) for x in con} - {chiave(x) for x in senza})
    return dict(query=q, ms=c.ms,
                metriche=[M("Distanza media SENZA", f"{sum(x['metri'] for x in senza) // max(len(senza), 1)} m"),
                          M("Distanza media CON", f"{sum(x['metri'] for x in con) // max(len(con), 1)} m"),
                          M("Persone diverse tra le due liste", f"{nuovi} su {len(con)}")],
                evidenza=(f"le due liste sono diverse ({nuovi} persone su {len(con)} cambiano). "
                          + ("CON la vicinanza le distanze crescono dall'alto in basso e lo score scende: i più vicini salgono in cima."
                             if ordinati else "ATTENZIONE: con la vicinanza le distanze non risultano ordinate.")),
                tabelle=[T("SENZA vicinanza: ordine qualsiasi", col, senza), T("CON vicinanza: i più vicini in cima", col, con)],
                mappa=dict(punti=[punto_persona(x, f"{x['posizione']}. {x['nome']} {x['cognome']} – {x['metri']} m") for x in con],
                           centro=p["punto"], numerati=True))


@passo("testogeo", "D", "Riepilogo dell'area selezionata",
       "Scegli punto e raggio: in una sola chiamata MongoDB Search dice quante persone ci sono nell'area, divise per "
       "quartiere e per nazionalità (facet). Per dimostrare che i numeri sono giusti li calcoliamo una seconda volta "
       "in un modo completamente diverso, con la query geo nativa del tab Geo ($geoWithin): i totali devono coincidere.",
       "Quando l'operatore seleziona un'area sulla mappa vuole subito un riepilogo: quanti sono, in quali quartieri, "
       "di quale nazionalità. Sono gli stessi contatori laterali del passo Full text F, ma calcolati su un'area.",
       "query geo_distance + 'aggregations'.",
       [P("punto", "Punto (clic sulla mappa)", "punto", PUNTO), P("raggio", "Raggio (metri)", "range", 2000, min=200, max=4000, step=100)])
def tg_d(p):
    c = Crono()
    q = [{"$searchMeta": {"index": IDX, "facet": {
        "operator": {"geoWithin": {"path": GEO, "circle": {"center": {"type": "Point", "coordinates": p["punto"]},
                                                           "radius": float(p["raggio"])}}},
        "facets": {"perQuartiere": {"type": "string", "path": "properties.luogoResidenza.frazione"},
                   "perNazionalita": {"type": "string", "path": "properties.nazionalita"}}}}}]
    meta = c(lambda: list(coll().aggregate(q))[0])
    ver = Counter(d["properties"]["luogoResidenza"]["frazione"] for d in coll().find(
        {GEO: {"$geoWithin": {"$centerSphere": [p["punto"], float(p["raggio"]) / 6378100.0]}}},
        {"properties.luogoResidenza.frazione": 1}))
    righe = [{"quartiere": b["_id"], "persone nell'area": b["count"], "ricontate con geo nativo": ver.get(b["_id"], 0)}
             for b in meta["facet"]["perQuartiere"]["buckets"]]
    diff = sum(abs(r["persone nell'area"] - r["ricontate con geo nativo"]) for r in righe)
    tot_s, tot_g = meta["count"]["lowerBound"], sum(ver.values())
    righe.append({"quartiere": "TOTALE", "persone nell'area": tot_s, "ricontate con geo nativo": tot_g})
    ev = ("due calcoli indipendenti danno lo stesso risultato, quartiere per quartiere e nel totale." if diff == 0 else
          f"coincide con la query geo nativa a meno di {diff} persone su {sum(ver.values())}: punti sul bordo del cerchio.")
    return dict(query=q, ms=c.ms, metriche=[M("Totale con MongoDB Search", tot_s, "facet"),
                                            M("Totale con query geo nativa", tot_g, "$geoWithin, il ricontrollo")], evidenza=ev,
                tabelle=[T("Per quartiere (con riconteggio)", ["quartiere", "persone nell'area", "ricontate con geo nativo"], righe),
                         T("Per nazionalità", ["nazionalità", "persone"],
                           [{"nazionalità": b["_id"], "persone": b["count"]} for b in meta["facet"]["perNazionalita"]["buckets"]])],
                mappa=dict(punti=[], cerchio=dict(centro=p["punto"], raggio=float(p["raggio"])), centro=p["punto"]))


# =============================================================================
# RELAZIONI
# =============================================================================
def breve(codice):
    return codice.replace("PersonaFisica_Luogo_", "")


@passo("relazioni", "A", "Chi ha o ha avuto un legame con un'area",
       "Disegna un'area. Partiamo dai Luoghi dentro l'area, seguiamo le Relazioni (join) e arriviamo alle Persone. "
       "Confrontiamo con la ricerca sulla sola residenza attuale embedded.",
       "Il documento persona contiene solo la residenza attuale. La domanda investigativa è più ampia: residenze "
       "passate, domicili, luoghi frequentati. Per ogni persona in più si vede dove abita oggi e che legame ha.",
       "non risolvibile con il documento attuale: servirebbe denormalizzare tutti i luoghi e tenerli sincronizzati.",
       [P("poligono", "Area (disegna sulla mappa)", "poligono", POLI)])
def rel_a(p):
    c = Crono()
    an = anello(p["poligono"])
    geom = {"type": "Polygon", "coordinates": [an]}
    q = [{"$match": {"properties.luogo.geoJson": {"$geoWithin": {"$geometry": geom}}}},
         {"$lookup": {"from": config.COLL_RELAZIONE, "localField": "_id", "foreignField": "idEntita2", "as": "rel"}},
         {"$unwind": "$rel"},
         {"$lookup": {"from": config.COLL_PERSONA, "localField": "rel.idEntita1", "foreignField": "_id", "as": "p"}},
         {"$unwind": "$p"},
         {"$group": {"_id": "$p._id", "nome": {"$first": "$p.properties.nome"}, "cognome": {"$first": "$p.properties.cognome"},
                     "residenza": {"$first": "$p.properties.luogoResidenza.displayName"},
                     "coordRes": {"$first": "$p.properties.luogoResidenza.geoJson.coordinates"},
                     "legami": {"$push": {"tipo": "$rel.codiceRelazione", "fine": "$rel.datiRelazione.elencoProprieta.dataFine",
                                          "luogo": "$properties.luogo.displayName", "coord": "$properties.luogo.geoJson.coordinates"}}}}]
    tutti = c(lambda: list(coll(config.COLL_LUOGO).aggregate(q)))
    solo = c(coll().count_documents, {GEO: {"$geoWithin": {"$geometry": geom}}})
    piu = [x for x in tutti if not dentro_poligono(x["coordRes"], an)]
    tipo = lambda l: breve(l["tipo"]) + (" (passata)" if l["fine"] else "")
    tipi = Counter(tipo(l) for x in piu for l in x["legami"])
    righe = [{"persona": f"{x['nome']} {x['cognome']}", "abita oggi in": via(x["residenza"]),
              "legame con l'area": tipo(x["legami"][0]), "luogo nell'area": via(x["legami"][0]["luogo"])} for x in piu[:10]]
    punti = [dict(lon=l["coord"][0], lat=l["coord"][1], colore=COLORI_REL.get(breve(l["tipo"]), "#00684A"),
                  label=f"{x['nome']} {x['cognome']} – {tipo(l)}") for x in piu[:600] for l in x["legami"]]
    return dict(query=q, ms=c.ms, metriche=[M("Solo residenza embedded", solo), M("Con tutte le relazioni", len(tutti)),
                                            M("Persone in più", len(piu), "oggi abitano fuori area")],
                evidenza=f"{len(piu)} persone abitano oggi fuori dall'area ma hanno un legame con essa: con la sola residenza "
                         f"embedded non si troverebbero.",
                tabelle=[T("Perché sono in più: tipo di legame", ["legame", "quante volte"],
                           [{"legame": k, "quante volte": v} for k, v in tipi.most_common()]),
                         T("Esempi", ["persona", "abita oggi in", "legame con l'area", "luogo nell'area"], righe)],
                mappa=dict(punti=punti, poligono=an, legenda=[dict(colore=v, label=k) for k, v in COLORI_REL.items()]))


@passo("relazioni", "B", "Chi frequenta un certo luogo",
       "Scegli un luogo: seguiamo solo le relazioni di tipo 'Frequenta' e arriviamo alle persone.",
       "La stessa navigazione Luogo → Relazione → Persona risponde a domande diverse cambiando solo il filtro. Ogni "
       "riga mostra il tipo e l'id della relazione che la collega al luogo.",
       "servirebbe un secondo indice dei luoghi con le persone collegate.",
       [P("luogo", "Luogo", "select", "Bar del Porto", opzioni="@luoghi")], mappa=True)
def rel_b(p):
    c = Crono()
    q = [{"$match": {"properties.luogo.nomeLuogo": p["luogo"]}},
         {"$lookup": {"from": config.COLL_RELAZIONE, "localField": "_id", "foreignField": "idEntita2",
                      "pipeline": [{"$match": {"codiceRelazione": "PersonaFisica_Luogo_Frequenta"}}], "as": "rel"}},
         {"$unwind": "$rel"},
         {"$lookup": {"from": config.COLL_PERSONA, "localField": "rel.idEntita1", "foreignField": "_id", "as": "p"}},
         {"$unwind": "$p"},
         {"$project": {"_id": 0, "luogo": "$properties.luogo.displayName", "coordLuogo": "$properties.luogo.geoJson.coordinates",
                       "relazione": "$rel.codiceRelazione", "idRelazione": "$rel._id", "nome": "$p.properties.nome",
                       "cognome": "$p.properties.cognome", "quartiere": "$p.properties.luogoResidenza.frazione",
                       "coord": "$p.properties.luogoResidenza.geoJson.coordinates"}}]
    ris = c(lambda: list(coll(config.COLL_LUOGO).aggregate(q)))
    for x in ris:
        x["relazione"], x["id relazione"] = breve(x["relazione"]), x["idRelazione"][:8] + "…"
    qs = Counter(x["quartiere"] for x in ris)
    return dict(query=q, ms=c.ms, metriche=[M("Frequentatori", len(ris)), M("Quartieri di provenienza", len(qs))],
                evidenza=f"{len(ris)} persone collegate a '{p['luogo']}' da una relazione 'Frequenta', ognuna verificabile per id.",
                tabelle=[T("Frequentatori", ["nome", "cognome", "relazione", "id relazione", "quartiere"], ris[:10]),
                         T("Da dove vengono", ["quartiere", "frequentatori"], [dict(quartiere=k, frequentatori=v) for k, v in qs.most_common(8)])],
                mappa=dict(punti=[punto_persona(x, f"{x['nome']} {x['cognome']} – abita a {x['quartiere']}") for x in ris],
                           centro=ris[0]["coordLuogo"] if ris else None, etichettaCentro=p["luogo"]))


@passo("relazioni", "C", "Il documento 'stile OpenSearch' costruito con due join",
       "Prendiamo una persona e costruiamo il documento con le sue relazioni di primo grado (il campo "
       "relazioniPrimoGrado), quello che in un'architettura con OpenSearch una pipeline esterna scrive nell'indice. $lookup è la join di MongoDB: prima persona → relazione (idEntita1), poi relazione → "
       "luogo (idEntita2). Senza la casella 'salva' il documento è solo il risultato della query, mostrato a video; "
       "con la casella viene scritto nella collection entitaVista e riletto da lì.",
       "Oggi questo documento lo costruisce una pipeline esterna e lo scrive in OpenSearch. MongoDB lo costruisce dal "
       "dato vivo: al volo, oppure salvato con $merge e tenuto aggiornato con i change stream.",
       "pipeline esterna che legge MongoDB e scrive l'indice delle entità.",
       [P("id", "Persona", "select", ID_BIAGIO, opzioni="@persone"),
        P("salva", "Salva il risultato nella collection entitaVista ($merge)", "checkbox", False)])
def rel_c(p):
    c = Crono()
    q = [{"$match": {"_id": p["id"]}},
         {"$lookup": {"from": config.COLL_RELAZIONE, "localField": "_id", "foreignField": "idEntita1", "pipeline": [
             {"$lookup": {"from": config.COLL_LUOGO, "localField": "idEntita2", "foreignField": "_id", "as": "l"}},
             {"$unwind": "$l"},
             {"$project": {"_id": 0, "codiceRelazione": 1, "relazioneId": "$_id", "id": "$l._id", "tipoEntita": "$l.tipoEntita",
                           "datiRelazione": 1, "properties": {"luogo": "$l.properties.luogo"}}}],
             "as": "relazioniPrimoGrado.Luogo"}},
         {"$project": {"fonti": 0, "properties.gender": 0, "properties.statoCivile": 0}}]
    doc = c(lambda: next(iter(coll().aggregate(q)), None))
    if not doc:
        return dict(query=q, ms=c.ms, metriche=[], evidenza="persona non trovata", tabelle=[])
    orig = coll().find_one({"_id": p["id"]}, {"fonti": 0, "properties.gender": 0, "properties.statoCivile": 0})
    rel = doc["relazioniPrimoGrado"]["Luogo"]
    salvato = None
    if p.get("salva"):
        c(lambda: list(coll().aggregate(q[:2] + [{"$merge": {"into": config.COLL_VISTA, "whenMatched": "replace",
                                                               "whenNotMatched": "insert"}}])))
        salvato = db()[config.COLL_VISTA].find_one({"_id": p["id"]}, {"_id": 1, "properties.nome": 1, "properties.cognome": 1,
                                                                       "relazioniPrimoGrado.Luogo.codiceRelazione": 1})
    righe = [{"relazione": breve(x["codiceRelazione"]), "luogo": via(x["properties"]["luogo"]["displayName"]),
              "quartiere": x["properties"]["luogo"].get("frazione", "")} for x in rel]
    docs = [dict(titolo="Prima: il documento in personaFisica", doc=orig),
            dict(titolo="Dopo: risultato della query (solo a video)", doc=doc, evidenzia=["relazioniPrimoGrado"],
                 nota="In giallo la parte aggiunta dalle due join.")]
    if salvato:
        docs.append(dict(titolo=f"Riletto dalla collection {config.COLL_VISTA} (salvato con $merge)", doc=salvato, evidenzia=["relazioniPrimoGrado"],
                         nota="Questo documento ora esiste nel database: è letto dalla collection, non ricostruito."))
    return dict(query=q, ms=c.ms, metriche=[M("Relazioni trovate (join 1)", len(rel)), M("Luoghi agganciati (join 2)", len(rel)),
                                            M("Salvato in entitaVista", "sì" if salvato else "no")],
                evidenza=(f"partendo da 1 documento con la sola residenza attuale, due join aggiungono {len(rel)} luoghi collegati. "
                          + (f"Il documento è stato salvato in {config.COLL_VISTA} e riletto dalla collection."
                             if salvato else "Non è stato salvato niente: è il risultato della query. Spunta 'salva' per scriverlo in una collection.")),
                tabelle=[T("Cosa hanno aggiunto le join", ["relazione", "luogo", "quartiere"], righe)], documenti=docs)


# =============================================================================
# QUERYABLE ENCRYPTION
# =============================================================================
class Spia(monitoring.CommandListener):
    """Registra i comandi inviati al server sulla collection cifrata."""
    def __init__(self):
        self.comandi = []

    def started(self, e):
        if e.command_name in ("find", "aggregate") and e.command.get(e.command_name) == config.COLL_PERSONA_QE:
            cmd = decode(encode(e.command))
            self.comandi.append({k: cmd[k] for k in ("find", "aggregate", "filter", "pipeline") if k in cmd})
            self.comandi = self.comandi[-5:]

    def succeeded(self, e):
        pass

    def failed(self, e):
        pass


SPIA = Spia()


@lru_cache
def enc():
    from pymongo.encryption_options import AutoEncryptionOpts
    from qe_common import kms_providers
    opts = dict(kms_providers=kms_providers(), key_vault_namespace=config.KEY_VAULT_NS)
    if config.CRYPT_SHARED_LIB_PATH:
        opts.update(crypt_shared_lib_path=config.CRYPT_SHARED_LIB_PATH, crypt_shared_lib_required=True)
    return MongoClient(config.MONGODB_URI, auto_encryption_opts=AutoEncryptionOpts(**opts),
                       event_listeners=[SPIA])[config.DB_NAME][config.COLL_PERSONA_QE]


def plain_qe():
    return db()[config.COLL_PERSONA_QE]


CAMPI = {"_id": 1, "properties.nome": 1, "properties.cognome": 1, "properties.codiceFiscale": 1,
         "properties.dataNascita": 1, "properties.matricolaSidet": 1, "properties.segniParticolari": 1}


@lru_cache
def rif():
    return enc().find_one({"_id": ID_BIAGIO}, CAMPI) or enc().find_one({}, CAMPI)


def piatto_qe(d):
    p = d["properties"]
    dn = p.get("dataNascita")
    return {"nome": p.get("nome"), "cognome": p.get("cognome"), "codice fiscale": p.get("codiceFiscale"),
            "nascita": dn.strftime("%Y-%m-%d") if isinstance(dn, datetime) else dn,
            "matricola": p.get("matricolaSidet"), "segni particolari": p.get("segniParticolari")}


def comando_al_server(valore_in_chiaro):
    """L'ultimo comando inviato al server, se il driver lo espone già cifrato."""
    if not SPIA.comandi:
        return None
    cmd = SPIA.comandi[-1]
    testo = json_util.dumps(cmd)
    if valore_in_chiaro and str(valore_in_chiaro) in testo:
        return None
    return cmd


def qe_trova(filtro, col, valore, titolo_metrica):
    c = Crono()
    SPIA.comandi.clear()
    docs = c(lambda: [piatto_qe(d) for d in enc().find(filtro, CAMPI).limit(10)])
    cmd = comando_al_server(valore)
    n = c(enc().count_documents, filtro)
    documenti = [dict(titolo="La query che arriva al server", doc=cmd,
                      nota="Il valore cercato viaggia cifrato: il server non lo vede mai.")] if cmd else []
    return dict(query=filtro, ms=c.ms, metriche=[M(titolo_metrica, n)],
                evidenza=f"{n} documenti trovati con una query su un campo cifrato; i risultati sono in chiaro solo perché "
                         f"li legge l'applicazione che ha le chiavi.",
                tabelle=[T("Risultati (letti dall'applicazione autorizzata)", ["nome", "cognome"] + col, docs)], documenti=documenti)


def _rif(campo, f=lambda v: v):
    def g():
        try:
            return f(rif()["properties"][campo])
        except Exception:
            return ""
    return g


QE_OS = "il campo sarebbe indicizzato in chiaro."


@passo("qe", "A", "Ricerca esatta su un campo cifrato: codice fiscale",
       "Cerchiamo una persona per codice fiscale. Nel database il codice fiscale è cifrato.",
       "Il driver cifra anche il valore cercato: il server confronta dati cifrati con dati cifrati. Nel riquadro "
       "'La query che arriva al server' si vede che il codice fiscale non c'è.",
       QE_OS, [P("cf", "Codice fiscale", default=_rif("codiceFiscale"))])
def qe_a(p):
    return qe_trova({"properties.codiceFiscale": p["cf"]}, ["codice fiscale"], p["cf"], "Trovati")


@passo("qe", "B", "Intervallo su un campo cifrato: data di nascita",
       "Tutte le persone nate in un intervallo di anni. La data di nascita è cifrata.",
       "Non solo uguaglianza: anche i confronti maggiore/minore funzionano su un campo cifrato.",
       QE_OS, [P("da", "Nati dal", "number", 1980), P("a", "al", "number", 1989)])
def qe_b(p):
    f = {"properties.dataNascita": {"$gte": datetime(int(p["da"]), 1, 1), "$lt": datetime(int(p["a"]) + 1, 1, 1)}}
    return qe_trova(f, ["nascita"], None, "Trovati")


@passo("qe", "C", "Inizia per… su un campo cifrato: matricola",
       "Matricole che iniziano con le lettere/cifre indicate (da 3 a 10 caratteri).",
       "Ricerca parziale su un identificativo cifrato: GA da MongoDB 9.0.",
       QE_OS, [P("prefisso", "Inizia per", default=_rif("matricolaSidet", lambda v: v[:6]))])
def qe_c(p):
    f = {"$expr": {"$encStrStartsWith": {"input": "$properties.matricolaSidet", "prefix": p["prefisso"]}}}
    return qe_trova(f, ["matricola"], p["prefisso"], "Trovati")


@passo("qe", "D", "Finisce per… su un campo cifrato: matricola",
       "Matricole che finiscono con le cifre indicate (da 3 a 10 caratteri).",
       "Tipico quando si conoscono solo le ultime cifre di un documento o di un identificativo.",
       QE_OS, [P("suffisso", "Finisce per", default=_rif("matricolaSidet", lambda v: v[-4:]))])
def qe_d(p):
    f = {"$expr": {"$encStrEndsWith": {"input": "$properties.matricolaSidet", "suffix": p["suffisso"]}}}
    return qe_trova(f, ["matricola"], p["suffisso"], "Trovati")


@passo("qe", "E", "Contiene… su un campo cifrato: segni particolari",
       "Persone i cui segni particolari contengono una parola (da 3 a 6 caratteri). Il campo è cifrato.",
       "Ricerca dentro un testo descrittivo sensibile, senza esporlo in chiaro.",
       QE_OS, [P("testo", "Contiene (3–6 caratteri)", default="drago")])
def qe_e(p):
    f = {"$expr": {"$encStrContains": {"input": "$properties.segniParticolari", "substring": p["testo"]}}}
    return qe_trova(f, ["segni particolari"], p["testo"], "Trovati")


@passo("qe", "F", "Lo stesso documento visto con e senza chiavi",
       "Leggiamo lo stesso documento due volte: dall'applicazione autorizzata e da un client senza chiavi.",
       "Chi amministra il database, chi legge i log o un backup vede solo dati cifrati (Binary subtype 6). Il server "
       "non ha mai avuto le chiavi.",
       "i dati sensibili sono copiati in chiaro anche nell'indice.",
       [P("id", "Id del documento", default=lambda: rif()["_id"] if rif() else ID_BIAGIO)])
def qe_f(p):
    c = Crono()
    con = c(enc().find_one, {"_id": p["id"]}, CAMPI)
    senza = c(plain_qe().find_one, {"_id": p["id"]}, {**CAMPI, "__safeContent__": 1})
    if senza and "__safeContent__" in senza:
        senza["__safeContent__"] = f"[{len(senza['__safeContent__'])} tag crittografici]"
    return dict(query={"_id": p["id"]}, ms=c.ms, metriche=[],
                evidenza="stesso documento: leggibile per l'applicazione, illeggibile per il server.", tabelle=[],
                documenti=[dict(titolo="Applicazione autorizzata (ha le chiavi)", doc=con),
                           dict(titolo="Client senza chiavi (DBA, server, log, backup)", doc=senza)])


@passo("qe", "G", "Ricerca full text e geo + dati cifrati",
       "Nella collection cifrata cerchiamo un cognome entro un raggio, poi l'applicazione autorizzata rilegge i "
       "documenti trovati.",
       "Nome, cognome e residenza sono in chiaro e indicizzati da MongoDB Search; i campi sensibili dello stesso "
       "documento tornano leggibili solo a chi ha le chiavi. Sono due passaggi: ricerca, poi lettura.",
       "tutto il documento, compresi i dati sensibili, starebbe in chiaro nell'indice.",
       [P("testo", "Cognome (inizio)", default="amal"), P("punto", "Punto (clic sulla mappa)", "punto", PUNTO),
        P("raggio", "Raggio (metri)", "range", 3000, min=500, max=6000, step=500)])
def qe_g(p):
    c = Crono()
    q = [{"$search": {"index": IDX_QE, "compound": {
            "must": [{"autocomplete": {"query": p["testo"], "path": "properties.cognome"}}],
            "filter": [{"geoWithin": {"path": GEO, "circle": {"center": {"type": "Point", "coordinates": p["punto"]},
                                                               "radius": float(p["raggio"])}}}]}}},
         {"$limit": 10}, {"$project": {"_id": 1, "coord": "$properties.luogoResidenza.geoJson.coordinates"}}]
    trovati = c(lambda: list(plain_qe().aggregate(q)))
    coord = {x["_id"]: x["coord"] for x in trovati}
    docs = c(lambda: list(enc().find({"_id": {"$in": list(coord)}}, CAMPI)))
    righe = [piatto_qe(d) for d in docs]
    return dict(query=q, ms=c.ms, metriche=[M("1. Search: _id trovati", len(trovati)), M("2. Riletti e decifrati", len(docs))],
                evidenza="la ricerca usa i campi in chiaro; codice fiscale e matricola diventano leggibili solo nella "
                         "rilettura fatta dall'applicazione autorizzata.",
                tabelle=[T("Risultati decifrati", ["nome", "cognome", "codice fiscale", "nascita", "matricola"], righe)],
                mappa=dict(punti=[dict(lon=coord[d["_id"]][0], lat=coord[d["_id"]][1],
                                       label=f"{d['properties']['nome']} {d['properties']['cognome']}") for d in docs if d["_id"] in coord],
                           cerchio=dict(centro=p["punto"], raggio=float(p["raggio"])), centro=p["punto"]))


# =============================================================================
# CASO INVESTIGATIVO: tutto insieme in una sola aggregation
# =============================================================================
@lru_cache
def client_lettore():
    """
    Client con cifratura automatica e bypassQueryAnalysis: non analizza le query (quindi $search è ammesso)
    ma decifra automaticamente i campi cifrati presenti nelle risposte.
    """
    from pymongo.encryption_options import AutoEncryptionOpts
    from qe_common import kms_providers
    opts = dict(kms_providers=kms_providers(), key_vault_namespace=config.KEY_VAULT_NS, bypass_query_analysis=True)
    if config.CRYPT_SHARED_LIB_PATH:
        opts.update(crypt_shared_lib_path=config.CRYPT_SHARED_LIB_PATH)
    return MongoClient(config.MONGODB_URI, auto_encryption_opts=AutoEncryptionOpts(**opts))


@lru_cache
def decifratore():
    from bson.binary import STANDARD
    from bson.codec_options import CodecOptions
    from pymongo.encryption import ClientEncryption
    from qe_common import kms_providers
    return ClientEncryption(kms_providers(), config.KEY_VAULT_NS, db().client, CodecOptions(uuid_representation=STANDARD))


def cifrato(v):
    from bson.binary import Binary
    return isinstance(v, Binary) and v.subtype == 6


def distanza_expr(lon, lat):
    """Distanza in metri (formula dell'emisenoverso) calcolata dentro l'aggregation."""
    rad = lambda e: {"$degreesToRadians": e}
    plon = {"$arrayElemAt": ["$properties.luogoResidenza.geoJson.coordinates", 0]}
    plat = {"$arrayElemAt": ["$properties.luogoResidenza.geoJson.coordinates", 1]}
    dlat, dlon = rad({"$subtract": [plat, lat]}), rad({"$subtract": [plon, lon]})
    a = {"$add": [{"$pow": [{"$sin": {"$divide": [dlat, 2]}}, 2]},
                  {"$multiply": [{"$cos": rad(lat)}, {"$cos": rad(plat)}, {"$pow": [{"$sin": {"$divide": [dlon, 2]}}, 2]}]}]}
    return {"$round": [{"$multiply": [2 * 6371008.8, {"$asin": {"$sqrt": a}}]}, 0]}


CASO_EXTRA = [
    dict(titolo="La query, in cinque parti", html="""
<ol>
<li><b>Ricerca (MongoDB Search, <code>$search</code>).</b> Cognome con tolleranza agli errori (fino a 2 lettere: «Rosi» trova Rossi e
Rosso), solo nell'indagine scelta. Il tatuaggio e la vicinanza al locale alzano il punteggio, ma non escludono nessuno.</li>
<li><b>Join con le relazioni (<code>$lookup</code> su <code>relazione</code>).</b> Per ogni candidato verifica se esiste una relazione
«Frequenta» con il locale.</li>
<li><b>Indizi calcolati dal database (<code>$addFields</code>).</b> Distanza in metri tra la residenza e il locale, presenza del
segno particolare, relazione con il locale, e il numero di indizi soddisfatti.</li>
<li><b>Due risultati in parallelo (<code>$facet</code>).</b> I numeri dell'imbuto e i sospettati ordinati per numero di indizi.</li>
<li><b>Il fascicolo (<code>$lookup</code> sulla collection cifrata).</b> Per i primi sospettati legge codice fiscale, data di nascita e
matricola da <code>personaFisicaQE</code>: il server li restituisce cifrati, il driver li decifra.</li>
</ol>
<p>Una sola chiamata al database, sul dato vivo. Oggi lo stesso risultato richiede OpenSearch per testo e geo, MongoDB per le
relazioni, un accesso separato ai dati sensibili e la ricomposizione nell'applicazione.</p>"""),
    dict(titolo="Come leggiamo il fascicolo cifrato nella stessa query", html="""
<p>Il driver con Queryable Encryption fa due cose: <b>cifra le query in uscita</b> e <b>decifra i risultati in arrivo</b>.</p>
<p>La ricerca full text (<code>$search</code>) non è compatibile con la prima, e senza accorgimenti il driver la blocca.</p>
<p>Con l'opzione <b><code>bypassQueryAnalysis</code></b> il driver <b>salta la prima e mantiene la seconda</b>: la ricerca parte, e i dati
cifrati che tornano nel risultato vengono decifrati nell'applicazione.</p>
<p><b>Il limite:</b> si cerca solo sui campi in chiaro (cognome, segni particolari, residenza). I campi cifrati (codice fiscale, data di
nascita, matricola) in questa query si <b>leggono</b>, non si <b>cercano</b>. Per cercarli si usano le query del tab Queryable Encryption.</p>
<p style="background:#E3FCF7;border-radius:8px;padding:10px 14px"><b>In una frase:</b> ricerca sui dati in chiaro, dati sensibili
cifrati sul server e leggibili solo dall'applicazione, tutto in una query.</p>
<p>Nell'applicazione ci sono quindi due client: uno per le ricerche sui campi cifrati, uno di sola lettura per la query combinata.</p>
<details><summary>Dettagli tecnici</summary>
<table><tr><th></th><th>Client QE normale (tab QE)</th><th>Client con bypassQueryAnalysis (questo tab)</th></tr>
<tr><td>Cifra la query in uscita</td><td>sì</td><td>no</td></tr>
<tr><td>Accetta <code>$search</code></td><td>no (errore <code>mongotQuery is not allowed</code>)</td><td>sì</td></tr>
<tr><td>Cerca sui campi cifrati</td><td>sì</td><td>no (servirebbe cifrare il valore a mano)</td></tr>
<tr><td>Decifra i risultati</td><td>sì</td><td>sì</td></tr>
<tr><td>Le chiavi arrivano al server</td><td>mai</td><td>mai</td></tr></table>
<p style="margin-top:12px"><b>La configurazione del driver (Python).</b> È tutto ciò che distingue i due client: è identica,
tranne l'ultima riga.</p>
<pre>AutoEncryptionOpts(
    kms_providers=...,                             # dove sta la chiave master (oggi un file locale, in produzione il KMS)
    key_vault_namespace="encryption.__keyVault",   # dove stanno le chiavi dei campi
    bypass_query_analysis=True)                    # salta l'analisi delle query, ma continua a decifrare i risultati</pre>
</details>"""),
]


@passo("caso", "A", "Dal testimone al fascicolo, in una sola query",
       "Un testimone ha visto un uomo con un tatuaggio a forma di drago vicino a un locale e ha sentito un cognome "
       "simile a quello indicato. Una sola aggregation: ricerca con tolleranza sul cognome, filtro indagine, tatuaggio "
       "nei segni particolari, vicinanza al locale, join sulle relazioni (chi frequenta il locale), distanza calcolata, "
       "e, per i primi sospettati, il fascicolo dalla collection cifrata.",
       "È il lavoro che oggi richiede più sistemi (OpenSearch per la ricerca, MongoDB per le relazioni, un altro "
       "passaggio per i dati sensibili). Qui è una query sola, sul dato vivo; i dati sensibili restano cifrati sul "
       "server e diventano leggibili solo nell'applicazione autorizzata.",
       "query OpenSearch per testo e geo, poi chiamate a MongoDB per le relazioni, poi un altro accesso per i dati "
       "sensibili, e il tutto ricomposto nell'applicazione.",
       [P("cognome", "Cognome sentito dal testimone", default="Rosi"),
        P("segni", "Segno particolare", default="drago"),
        P("luogo", "Locale dove è stato visto", "select", "Bar del Porto", opzioni="@luoghi"),
        P("raggio", "Abita entro (metri dal locale)", "range", 1000, min=200, max=3000, step=100),
        P("indagine", "Indagine", "select", INDAGINE, opzioni="@indagini")], mappa=True, largo=True,
       scena="«Ho visto un uomo con un tatuaggio a forma di drago vicino al Bar del Porto. Qualcuno l'ha chiamato… "
             "Rosi, mi pare.» — Indagine: Operazione Lanterna.",
       extra=CASO_EXTRA)
def caso_a(p):
    c = Crono()
    luogo = coll(config.COLL_LUOGO).find_one({"properties.luogo.nomeLuogo": p["luogo"]})
    lon, lat = luogo["properties"]["luogo"]["geoJson"]["coordinates"]
    raggio, segni = float(p["raggio"]), p["segni"].strip()
    sospettato = {"nome": "$properties.nome", "cognome": "$properties.cognome",
                  "soprannome": {"$first": "$properties.soprannomi"}, "segni": "$properties.segniParticolari",
                  "quartiere": "$properties.luogoResidenza.frazione", "indirizzo": "$properties.luogoResidenza.displayName",
                  "coord": "$properties.luogoResidenza.geoJson.coordinates", "distanza": 1, "tatuaggio": 1, "vicino": 1,
                  "frequenta": 1, "indizi": 1, "score": {"$round": ["$score", 2]}, "fascicolo": {"$first": "$fascicolo"}}
    q = [
        # 1. MongoDB Search: cognome con tolleranza + indagine; tatuaggio e vicinanza alzano il punteggio
        {"$search": {"index": IDX, "compound": {
            "must": [{"text": {"query": p["cognome"], "path": "properties.cognome", "fuzzy": {"maxEdits": 2}}}],
            "filter": [{"equals": {"path": "indagineTatticaId", "value": p["indagine"]}}],
            "should": [{"text": {"query": segni, "path": "properties.segniParticolari"}},
                       {"near": {"path": GEO, "origin": {"type": "Point", "coordinates": [lon, lat]}, "pivot": raggio}}]}}},
        {"$addFields": {"score": {"$meta": "searchScore"}}},
        # 2. JOIN con le relazioni: questa persona frequenta il locale?
        {"$lookup": {"from": config.COLL_RELAZIONE, "let": {"pid": "$_id"}, "as": "legame", "pipeline": [
            {"$match": {"$expr": {"$and": [{"$eq": ["$idEntita1", "$$pid"]}, {"$in": [luogo["_id"], "$idEntita2"]}]}}},
            {"$project": {"codiceRelazione": 1}}]}},
        # 3. gli indizi, calcolati dal database
        {"$addFields": {"distanza": distanza_expr(lon, lat),
                        "tatuaggio": {"$regexMatch": {"input": {"$ifNull": ["$properties.segniParticolari", ""]},
                                                      "regex": re.escape(segni), "options": "i"}},
                        "frequenta": {"$gt": [{"$size": "$legame"}, 0]}}},
        {"$addFields": {"vicino": {"$lte": ["$distanza", raggio]}}},
        {"$addFields": {"indizi": {"$add": [1, {"$cond": ["$tatuaggio", 1, 0]}, {"$cond": ["$vicino", 1, 0]},
                                            {"$cond": ["$frequenta", 1, 0]}]}}},
        # 4. in parallelo: imbuto e sospettati con il fascicolo cifrato
        {"$facet": {
            "imbuto": [{"$group": {"_id": None, "cognome": {"$sum": 1},
                                   "tatuaggio": {"$sum": {"$cond": ["$tatuaggio", 1, 0]}},
                                   "tatuaggioVicino": {"$sum": {"$cond": [{"$and": ["$tatuaggio", "$vicino"]}, 1, 0]}},
                                   "tutti": {"$sum": {"$cond": [{"$and": ["$tatuaggio", "$vicino", "$frequenta"]}, 1, 0]}}}}],
            "sospettati": [
                {"$sort": {"indizi": -1, "score": -1}}, {"$limit": 6},
                # 5. JOIN con la collection CIFRATA: il fascicolo (codice fiscale, nascita, matricola)
                {"$lookup": {"from": config.COLL_PERSONA_QE, "localField": "_id", "foreignField": "_id", "as": "fascicolo",
                             "pipeline": [{"$project": {"_id": 0, "codiceFiscale": "$properties.codiceFiscale",
                                                        "dataNascita": "$properties.dataNascita",
                                                        "matricola": "$properties.matricolaSidet"}}]}},
                {"$project": sospettato}]}}]

    modo = "decifrato automaticamente dal driver (bypassQueryAnalysis)"
    try:
        out = c(lambda: list(client_lettore()[config.DB_NAME][config.COLL_PERSONA].aggregate(q)))[0]
    except Exception as e:
        modo = f"client in chiaro ({type(e).__name__}): fascicolo non decifrabile"
        out = c(lambda: list(coll().aggregate(q)))[0]
    # piano B: se qualche campo è ancora cifrato, lo decifro esplicitamente con le chiavi
    for s in out["sospettati"]:
        f = s.get("fascicolo") or {}
        for k, v in list(f.items()):
            if cifrato(v):
                try:
                    f[k] = decifratore().decrypt(v)
                    modo = "decifrato esplicitamente dall'applicazione (ClientEncryption.decrypt)"
                except Exception:
                    f[k] = "(cifrato)"
    vista_server = None
    if out["sospettati"]:
        vista_server = plain_qe().find_one({"_id": out["sospettati"][0].get("_id")}, {"_id": 0, "properties.codiceFiscale": 1,
                                                                                      "properties.dataNascita": 1, "properties.matricolaSidet": 1}) \
            if out["sospettati"][0].get("_id") else None

    imb = (out["imbuto"] or [{}])[0]
    nel_db = coll().estimated_document_count()
    in_ind = c(conta, {"index": IDX, "compound": {"must": [{"exists": {"path": "properties.cognome"}}],
                                                  "filter": [{"equals": {"path": "indagineTatticaId", "value": p["indagine"]}}]}})
    imbuto = [dict(label="Persone nel database", n=nel_db),
              dict(label=f"… in {nome_indagine(p['indagine'])}", n=in_ind),
              dict(label=f"… con cognome simile a «{p['cognome']}»", n=imb.get("cognome", 0)),
              dict(label=f"… con «{segni}» nei segni particolari", n=imb.get("tatuaggio", 0)),
              dict(label=f"… che abitano entro {raggio:.0f} m dal locale", n=imb.get("tatuaggioVicino", 0)),
              dict(label=f"… che frequentano «{p['luogo']}»", n=imb.get("tutti", 0))]

    schede = []
    for i, s in enumerate(out["sospettati"], 1):
        f = s.get("fascicolo")
        dn = f.get("dataNascita") if f else None
        schede.append(dict(
            titolo=f"{i}. {s['nome']} {s['cognome']}" + (f" detto «{s['soprannome']}»" if s.get("soprannome") else ""),
            sottotitolo=f"{via(s['indirizzo'])}, {s['quartiere']}",
            punteggio=f"{s['indizi']}/4",
            indizi=[dict(ok=True, testo=f"cognome simile a «{p['cognome']}»: {s['cognome']}"),
                    dict(ok=bool(s["tatuaggio"]), testo=f"segni particolari: {s.get('segni') or '—'}"),
                    dict(ok=bool(s["vicino"]), testo=f"abita a {s['distanza']:.0f} m dal locale"),
                    dict(ok=bool(s["frequenta"]), testo=f"relazione «Frequenta» con {p['luogo']}" if s["frequenta"]
                         else f"nessuna relazione con {p['luogo']}")],
            fascicolo=None if not f else {"Codice fiscale": f.get("codiceFiscale"),
                                          "Data di nascita": dn.strftime("%d/%m/%Y") if isinstance(dn, datetime) else dn,
                                          "Matricola": f.get("matricola")}))
    pts = [dict(lon=s["coord"][0], lat=s["coord"][1], label=f"{i}. {s['nome']} {s['cognome']} – {s['indizi']}/4 indizi")
           for i, s in enumerate(out["sospettati"], 1)]
    top = out["sospettati"][0] if out["sospettati"] else None
    ev = (f"in una sola query: {imb.get('cognome', 0)} persone con cognome simile, {imb.get('tutti', 0)} soddisfano tutti gli "
          f"indizi. " + (f"Primo sospettato: {top['nome']} {top['cognome']} ({top['indizi']}/4). " if top else "")
          + f"Fascicolo: {modo}.")
    return dict(query=q, ms=c.ms, metriche=[M("Query eseguite", 1, "una sola aggregation"), M("Sospettati mostrati", len(schede))],
                evidenza=ev, imbuto=imbuto, schede=schede,
                tabelle=[],
                documenti=[dict(titolo="Lo stesso fascicolo del 1° sospettato, come lo vede il server", doc=vista_server,
                                nota="Sul server e nel risultato della query questi campi sono cifrati: li decifra solo l'applicazione.")]
                if vista_server else [],
                mappa=dict(punti=pts, numerati=True, cerchio=dict(centro=[lon, lat], raggio=raggio),
                           centro=[lon, lat], etichettaCentro=p["luogo"]))
