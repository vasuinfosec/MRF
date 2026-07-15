import { storage } from "@/src/utils/storage";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL || "";
const TOKEN_KEY = "vasu_session_token";

export async function getToken(): Promise<string | null> {
  return (await storage.secureGet(TOKEN_KEY, "" as string)) || null;
}
export async function setToken(t: string) { await storage.secureSet(TOKEN_KEY, t); }
export async function clearToken() { await storage.secureRemove(TOKEN_KEY); }

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
      msg = j.detail || j.message || msg;
    } catch (_e) { /* noop */ }
    throw new Error(msg);
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res.text() as any;
}

export const backendUrl = BASE;
