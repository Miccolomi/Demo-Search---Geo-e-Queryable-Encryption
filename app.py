"""
Demo web: MongoDB on-prem al posto di OpenSearch, con Queryable Encryption.

  pip install -r requirements.txt
  python app.py            -> apre http://localhost:8000
"""
import json
import os
import threading
import time
import traceback
import webbrowser

from bson import json_util
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
from common import db
from passi_web import REGISTRO, ID_BIAGIO, indagini, plain_qe

app = FastAPI(title="Demo MongoDB on-prem")
BASE = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
TAB = [
    ("panoramica", "Panoramica"), ("fulltext", "Full text"), ("geo", "Geo"),
    ("testogeo", "Testo + Geo"), ("relazioni", "Relazioni"), ("qe", "Queryable Encryption"),
    ("caso", "★ Caso investigativo"),
]


def js(obj, status=200):
    """Serializza anche ObjectId, date, Binary (subtype 6 = dato cifrato)."""
    def accorcia(o):
        if isinstance(o, dict):
            if "$binary" in o:
                b = o["$binary"]
                return {"$binary": {"base64": b["base64"][:28] + "…", "subType": b["subType"]}}
            return {k: accorcia(v) for k, v in o.items()}
        if isinstance(o, list):
            return [accorcia(x) for x in o]
        return o
    dati = json.loads(json_util.dumps(obj, json_options=json_util.RELAXED_JSON_OPTIONS))
    return JSONResponse(accorcia(dati), status_code=status)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/stato")
def stato():
    d = db()
    c = d.client
    out = {"uri_host": ", ".join(f"{h}:{p}" for h, p in (c.nodes or [])) or "?"}
    try:
        info = c.server_info()
        hello = c.admin.command("hello")
        fcv = c.admin.command({"getParameter": 1, "featureCompatibilityVersion": 1})["featureCompatibilityVersion"]["version"]
        out.update(versione=info["version"], enterprise="enterprise" in info.get("modules", []), fcv=fcv,
                   replicaSet=hello.get("setName"), nodi=len(hello.get("hosts", [])))
        out["conteggi"] = {n: d[n].estimated_document_count()
                           for n in (config.COLL_PERSONA, config.COLL_LUOGO, config.COLL_RELAZIONE, config.COLL_PERSONA_QE)}
        out["hosts"] = hello.get("hosts", [])
        out["primary"] = hello.get("primary")
        out["chiavi"] = c[config.KEY_VAULT_DB][config.KEY_VAULT_COLL].count_documents({})
        try:
            out["mongot"] = c.admin.command({"getParameter": 1, "mongotHost": 1}).get("mongotHost")
        except Exception:
            out["mongot"] = None
        idx = {i["name"]: i.get("queryable", False) for i in d[config.COLL_PERSONA].list_search_indexes()}
        out["search"] = bool(idx.get(config.SEARCH_INDEX_PERSONA))
    except Exception as e:
        out["errore"] = str(e)
    lib = config.CRYPT_SHARED_LIB_PATH
    out["qe_lib"] = bool(lib) and os.path.exists(lib)
    return js(out)


@app.get("/api/opzioni")
def opzioni():
    d = db()
    return js({
        "indagini": [{"value": k, "label": f"{v['nome']} · {v['n']:,} persone".replace(",", ".")} for k, v in indagini().items()],
        "persone": persone_con_relazioni(d),
        "nazionalita": ["(non italiana)"] + sorted(d[config.COLL_PERSONA].distinct("properties.nazionalita")),
        "luoghi": sorted(x for x in d[config.COLL_LUOGO].distinct("properties.luogo.nomeLuogo") if x),
    })


def persone_con_relazioni(d):
    """Biagio Amalfi + le persone con più relazioni, con nome e indirizzo leggibili."""
    top = [x["_id"] for x in d[config.COLL_RELAZIONE].aggregate([
        {"$group": {"_id": "$idEntita1", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": 12}])]
    ids = [ID_BIAGIO] + [i for i in top if i != ID_BIAGIO]
    out = []
    for doc in d[config.COLL_PERSONA].find({"_id": {"$in": ids}}, {"properties.nome": 1, "properties.cognome": 1,
                                                                   "properties.luogoResidenza.displayName": 1}):
        pr = doc["properties"]
        parti = [x.strip() for x in pr["luogoResidenza"]["displayName"].split(",")] + ["", "", ""]
        out.append({"value": doc["_id"], "label": f"{pr['nome']} {pr['cognome']} – {parti[1]} {parti[0]}, {parti[2]}"})
    out.sort(key=lambda x: (x["value"] != ID_BIAGIO, x["label"]))
    return out


@app.get("/api/passi")
def passi():
    out = []
    for p in REGISTRO:
        params = []
        for x in p["params"]:
            x = dict(x)
            if callable(x["default"]):
                try:
                    x["default"] = x["default"]()
                except Exception:
                    x["default"] = ""
            params.append(x)
        out.append({k: v for k, v in p.items() if k != "fn"} | {"params": params})
    return js({"tab": TAB, "passi": out})


@app.get("/api/campioni")
def campioni():
    d = db()
    pers = d[config.COLL_PERSONA].find_one({"_id": ID_BIAGIO})
    rel = d[config.COLL_RELAZIONE].find_one({"idEntita1": ID_BIAGIO, "codiceRelazione": "PersonaFisica_Luogo_Residente"})
    luogo = d[config.COLL_LUOGO].find_one({"_id": rel["idEntita2"][0]}) if rel and rel.get("idEntita2") else d[config.COLL_LUOGO].find_one()
    return js({"personaFisica": pers, "relazione": rel, "luogo": luogo})


@app.post("/api/esegui/{tab}/{id}")
async def esegui(tab: str, id: str, req: Request):
    p = next((x for x in REGISTRO if x["tab"] == tab and x["id"] == id), None)
    if not p:
        return js({"errore": "passo non trovato"}, 404)
    params = await req.json()
    try:
        t0 = time.perf_counter()
        r = p["fn"](params)
        r["ms_totali"] = (time.perf_counter() - t0) * 1000
        return js(r)
    except Exception as e:
        traceback.print_exc()
        return js({"errore": f"{type(e).__name__}: {e}"}, 500)


if __name__ == "__main__":
    import uvicorn
    porta = int(os.getenv("PORT", "8000"))
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{porta}")).start()
    uvicorn.run(app, host="127.0.0.1", port=porta, log_level="warning")
