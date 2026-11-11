"""Encrypt connector secrets at rest (Fernet / AES-128-CBC + HMAC, via cryptography).

The key comes from KAIRO_SECRET_KEY, or from a chmod-600 file in the data directory.
That file is never committed. Ciphertexts are not valid JSON and are never returned by the API.
"""
import base64, hashlib, os
from cryptography.fernet import Fernet, InvalidToken
import common

def _key_bytes():
    raw = (os.environ.get("KAIRO_SECRET_KEY") or "").strip()
    if raw:
        try:
            pad = raw.encode()
            decoded = base64.urlsafe_b64decode(pad + b"===")
            if len(decoded) == 32 and raw.startswith(""):
                # A real Fernet key is urlsafe-base64 of 32 bytes (44 chars, ends with =).
                if len(raw) == 44:
                    return raw.encode()
        except Exception:
            pass
        return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    path = os.path.join(common.BASE, "secret.key")
    if not os.path.exists(path):
        key = Fernet.generate_key()
        old = os.umask(0o077)
        try:
            with open(path, "wb") as f:
                f.write(key)
        finally:
            os.umask(old)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return key
    return open(path, "rb").read().strip()

def ensure_key():
    """Create the on-disk key if KAIRO_SECRET_KEY is unset. Safe to call on first launch."""
    return _key_bytes()

def fernet():
    return Fernet(_key_bytes())

def encrypt(text):
    if text is None:
        return None
    return fernet().encrypt(text.encode("utf-8"))

def decrypt(blob):
    if not blob:
        return None
    try:
        return fernet().decrypt(bytes(blob)).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("secret illisible (clé de chiffrement différente)") from e
