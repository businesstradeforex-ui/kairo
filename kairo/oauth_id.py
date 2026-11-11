"""Google and Apple sign-in. Both stay disabled until their env vars are set.

Nothing here stores a client secret in the repo. Apple's client secret is a short-lived
JWT signed with the key you configure (APPLE_PRIVATE_KEY = PEM text or a file path).
"""
import json, os, time, urllib.parse, urllib.request
import webauth

def _get(url, data=None, headers=None, timeout=15):
    body = None if data is None else urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def google_start():
    if not webauth.providers()["google"]:
        raise RuntimeError("Google non configuré")
    state = webauth.new_oauth_state("google")
    q = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": webauth.public_base() + "/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    })
    return "https://accounts.google.com/o/oauth2/v2/auth?" + q

def google_finish(code, state):
    if not webauth.consume_oauth_state(state, "google"):
        raise ValueError("state OAuth invalide")
    tok = _get("https://oauth2.googleapis.com/token", {
        "code": code,
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "redirect_uri": webauth.public_base() + "/auth/google/callback",
        "grant_type": "authorization_code",
    })
    info = _get("https://openidconnect.googleapis.com/v1/userinfo", headers={
        "Authorization": "Bearer " + tok["access_token"],
    })
    if not info.get("email") or not info.get("email_verified", True):
        raise ValueError("e-mail Google non vérifié")
    return webauth.login_or_create_email(info["email"], "google", info.get("sub") or info["email"])

def apple_client_secret():
    """ES256 JWT, valid 5 minutes. cryptography only (no PyJWT)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    import base64
    pem = os.environ["APPLE_PRIVATE_KEY"]
    if not pem.strip().startswith("-----"):
        pem = open(pem, encoding="utf-8").read()
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    now = int(time.time())
    header = {"alg": "ES256", "kid": os.environ["APPLE_KEY_ID"]}
    payload = {
        "iss": os.environ["APPLE_TEAM_ID"],
        "iat": now,
        "exp": now + 300,
        "aud": "https://appleid.apple.com",
        "sub": os.environ["APPLE_CLIENT_ID"],
    }
    def b64(obj):
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    signing = (b64(header) + "." + b64(payload)).encode()
    sig = key.sign(signing, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(sig)
    raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return signing.decode() + "." + base64.urlsafe_b64encode(raw_sig).rstrip(b"=").decode()

def apple_start():
    if not webauth.providers()["apple"]:
        raise RuntimeError("Apple non configuré")
    state = webauth.new_oauth_state("apple")
    q = urllib.parse.urlencode({
        "client_id": os.environ["APPLE_CLIENT_ID"],
        "redirect_uri": webauth.public_base() + "/auth/apple/callback",
        "response_type": "code id_token",
        "response_mode": "form_post",
        "scope": "name email",
        "state": state,
    })
    return "https://appleid.apple.com/auth/authorize?" + q

def _jwt_payload(token):
    import base64
    part = token.split(".")[1]
    part += "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part))

def apple_finish(code, state, id_token=None, user_json=None):
    if not webauth.consume_oauth_state(state, "apple"):
        raise ValueError("state OAuth invalide")
    tok = _get("https://appleid.apple.com/auth/token", {
        "client_id": os.environ["APPLE_CLIENT_ID"],
        "client_secret": apple_client_secret(),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": webauth.public_base() + "/auth/apple/callback",
    })
    # Use only the id_token returned by Apple's token endpoint over HTTPS, never the
    # copy posted by the browser. aud and exp are checked; the TLS exchange is the trust anchor.
    claims = _jwt_payload(tok.get("id_token") or "")
    if claims.get("aud") != os.environ["APPLE_CLIENT_ID"]:
        raise ValueError("id_token Apple inattendu")
    if int(claims.get("exp") or 0) < int(time.time()):
        raise ValueError("id_token Apple expiré")
    email = claims.get("email")
    if not email and user_json:
        try:
            email = json.loads(user_json).get("email")
        except Exception:
            email = None
    if not email:
        raise ValueError("Apple n'a pas fourni d'e-mail (décochez « masquer » ou réessayez)")
    return webauth.login_or_create_email(email, "apple", claims.get("sub") or email)
