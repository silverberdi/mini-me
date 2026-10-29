export function createApiClient({ state }) {
  async function request(path, options = {}) {
    try { const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options, headers: { Accept: "application/json", ...(options.headers || {}) } }); let data = null; try { data = await response.json(); } catch { /* empty response */ } if (response.status === 401) { state.session = null; state.data.clear(); } return { ok: response.ok, status: response.status, data, error: data?.detail || response.statusText }; }
    catch (error) { if (error.name === "AbortError") return { ok: false, aborted: true, status: 0, error: "Lectura obsoleta" }; return { ok: false, offline: true, status: 0, error: "No se pudo conectar" }; }
  }
  return { get: (path, options = {}) => request(path, { ...options, method: "GET" }), post: (path, body, options = {}) => request(path, { ...options, method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json", ...(options.headers || {}) } }) };
}
