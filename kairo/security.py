"""HTTP hardening: headers, CSRF comparison, in-memory rate limits.

Rate limits reset when the process restarts. Login lockout itself is stored in the
database (see webauth) so a restart does not clear it.
"""
import hmac, os, threading, time

def production():
    return os.environ.get("KAIRO_ENV", "production").lower() not in ("development", "dev", "test")

def safe_error(exc):
    if production():
        return "erreur interne"
    return f"{type(exc).__name__}: {exc}"[:300]

def consteq(a, b):
    a = "" if a is None else str(a)
    b = "" if b is None else str(b)
    return hmac.compare_digest(a.encode(), b.encode()) if len(a) == len(b) else hmac.compare_digest(
        __import__("hashlib").sha256(a.encode()).digest(),
        __import__("hashlib").sha256(b.encode()).digest(),
    )

def security_headers(secure=False):
    csp = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self' https://accounts.google.com https://appleid.apple.com"
    )
    h = {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        "X-Robots-Tag": "noindex, nofollow",
        "Cache-Control": "no-store",
    }
    if secure:
        h["Strict-Transport-Security"] = "max-age=15552000; includeSubDomains"
    return h

class RateLimiter:
    def __init__(self):
        self._hits = {}
        self._lock = threading.Lock()

    def hit(self, key, limit, window_s):
        now = time.time()
        with self._lock:
            arr = [t for t in self._hits.get(key, []) if now - t < window_s]
            if len(arr) >= limit:
                self._hits[key] = arr
                return max(1, int(window_s - (now - arr[0])) + 1)
            arr.append(now)
            self._hits[key] = arr[-limit * 2:]
            return 0

    def reset(self):
        with self._lock:
            self._hits.clear()

LIMITER = RateLimiter()
