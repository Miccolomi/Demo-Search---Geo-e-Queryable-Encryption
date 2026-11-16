"""Verifica rapida: connessione, versione, replica set, mongot, shared library QE."""
import os

import config
from common import client

c = client()
info = c.server_info()
hello = c.admin.command("hello")
print(f"Connesso: MongoDB {info['version']}  modules={info.get('modules')}")
print(f"Replica set: {hello.get('setName')}  membri={hello.get('hosts')}")

try:
    p = c.admin.command({"getParameter": 1, "mongotHost": 1, "searchIndexManagementHostAndPort": 1})
    print(f"mongotHost={p.get('mongotHost')}  searchIndexManagement={p.get('searchIndexManagementHostAndPort')}")
except Exception as e:
    print(f"Parametri mongot non leggibili: {e}")

coll = c[config.DB_NAME]["__check_search"]
coll.insert_one({"x": 1})
try:
    list(coll.list_search_indexes())
    print("MongoDB Search: raggiungibile")
except Exception as e:
    print(f"MongoDB Search: NON raggiungibile -> {e}")
finally:
    coll.drop()

lib = config.CRYPT_SHARED_LIB_PATH
print(f"CRYPT_SHARED_LIB_PATH={lib or '(vuoto: serve mongocryptd nel PATH)'}"
      + ("" if not lib else f"  esiste={os.path.exists(lib)}"))
