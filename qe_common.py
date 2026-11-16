"""Setup condiviso per Queryable Encryption (client cifrante + ClientEncryption)."""
import os

from bson.codec_options import CodecOptions
from bson.binary import STANDARD
from pymongo import MongoClient
from pymongo.encryption import ClientEncryption
from pymongo.encryption_options import AutoEncryptionOpts

import config


def master_key() -> bytes:
    """Chiave master LOCALE da 96 byte. Solo per demo: in produzione KMIP / HSM."""
    if not os.path.exists(config.MASTER_KEY_FILE):
        with open(config.MASTER_KEY_FILE, "wb") as f:
            f.write(os.urandom(96))
        print(f"Generata nuova master key in {config.MASTER_KEY_FILE}")
    with open(config.MASTER_KEY_FILE, "rb") as f:
        return f.read()


def kms_providers():
    return {"local": {"key": master_key()}}
    # Produzione on-prem, ad esempio:
    # return {"kmip": {"endpoint": "kmip.example.local:5696"}}   + kms_tls_options con i certificati


def client_cifrante() -> MongoClient:
    """Client con cifratura automatica: cifra in scrittura e in query, decifra in lettura."""
    opts = dict(kms_providers=kms_providers(), key_vault_namespace=config.KEY_VAULT_NS)
    if config.CRYPT_SHARED_LIB_PATH:
        opts.update(crypt_shared_lib_path=config.CRYPT_SHARED_LIB_PATH, crypt_shared_lib_required=True)
    return MongoClient(config.MONGODB_URI, auto_encryption_opts=AutoEncryptionOpts(**opts))


def client_in_chiaro() -> MongoClient:
    """Client SENZA chiavi: vede quello che vede il server / un DBA / un backup."""
    return MongoClient(config.MONGODB_URI)


def client_encryption(key_vault_client: MongoClient) -> ClientEncryption:
    return ClientEncryption(kms_providers(), config.KEY_VAULT_NS, key_vault_client,
                            CodecOptions(uuid_representation=STANDARD))
