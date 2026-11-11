export async function getJSON(url, timeoutMs = 8000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const resp = await fetch(url, { cache: "no-store", signal: ctrl.signal });
    if (resp.status === 401) {
      const err = new Error("auth");
      err.status = 401;
      throw err;
    }
    if (!resp.ok) {
      const err = new Error("http " + resp.status);
      err.status = resp.status;
      throw err;
    }
    return await resp.json();
  } finally {
    clearTimeout(timer);
  }
}
