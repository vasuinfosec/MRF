import { storage } from "@/src/utils/storage";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL || "";
const TOKEN_KEY = "vasu_session_token";

export async function getToken(): Promise<string | null> {
  return (await storage.secureGet(TOKEN_KEY, "" as string)) || null;
}
export async function setToken(t: string) { await storage.secureSet(TOKEN_KEY, t); }
export async function clearToken() { await storage.secureRemove(TOKEN_KEY); }

/**
 * SEC-003: Mint a short-lived, single-use download token for the CURRENT user.
 *
 * Browser file downloads (window.open / <a href="…?token=…">) cannot set
 * request headers, so the auth token has to travel in the URL. To avoid
 * leaking a 7-day session token via nginx access logs / Referer headers /
 * browser history, every download-triggering UI call mints a `dt_*` token
 * that:
 *   • lives 5 minutes,
 *   • is single-use (server marks it used atomically),
 *   • cannot be re-used on any other endpoint after that download completes.
 *
 * Returns null on failure — callers should surface a "download failed"
 * message and NOT fall back to the raw session token.
 */
export async function getDownloadToken(): Promise<string | null> {
  try {
    const r = await api<{ token: string; expires_in: number }>(
      "/auth/download-token", { method: "POST" }
    );
    return r.token || null;
  } catch {
    return null;
  }
}

export async function api<T = any>(
  path: string,
  opts: { method?: string; body?: any; token?: string | null } = {}
): Promise<T> {
  const token = opts.token !== undefined ? opts.token : await getToken();
  const res = await fetch(`${BASE}/api${path}`, {
    method: opts.method || "GET",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      const detail = j.detail || j.message;
      msg = typeof detail === "string"
        ? detail
        : detail?.message || detail?.error || msg;
    } catch (_e) { /* noop */ }
    throw new Error(msg);
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res.text() as any;
}

export const backendUrl = BASE;
