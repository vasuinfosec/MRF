import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { Platform } from "react-native";
import { api, setToken, clearToken, getToken } from "@/src/api";

export type User = {
  user_id: string;
  email: string;
  name: string;
  picture?: string;
  role: string;
  is_active: boolean;
};

type Ctx = {
  user: User | null;
  loading: boolean;
  login: (email: string, role: string, name?: string) => Promise<void>;
  loginWithSessionId: (sessionId: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  setRoleLocal: (role: string) => void;
};

const AuthCtx = createContext<Ctx>({} as Ctx);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const t = await getToken();
      if (!t) { setUser(null); return; }
      const u = await api<User>("/auth/me");
      setUser(u);
    } catch (_e) {
      await clearToken();
      setUser(null);
    }
  }, []);

  useEffect(() => {
    (async () => {
      // On web, check for session_id in URL first (Emergent auth callback)
      if (Platform.OS === "web" && typeof window !== "undefined") {
        const hash = window.location.hash || "";
        const search = window.location.search || "";
        const m = hash.match(/session_id=([^&]+)/) || search.match(/session_id=([^&]+)/);
        if (m) {
          try {
            const r = await api<{ session_token: string; user: User }>("/auth/session", {
              method: "POST", body: { session_id: m[1] }, token: null,
            });
            await setToken(r.session_token);
            setUser(r.user);
            window.history.replaceState(null, "", window.location.pathname);
          } catch (e) { console.warn("session err", e); }
        }
      }
      await refresh();
      setLoading(false);
    })();
  }, [refresh]);

  const login = async (email: string, role: string, name?: string) => {
    // Deployment health-check gate: dev-login is a demo-only flow. In release
    // builds the backend returns 404 (ACCESS_SECURITY_V2), so we fail fast
    // here with a friendlier error instead of surfacing the raw 404.
    if (!__DEV__) {
      throw new Error("Demo login is disabled in production builds. Please use Google Sign-in.");
    }
    const r = await api<{ session_token: string; user: User }>("/auth/dev-login", {
      method: "POST", body: { email, role, name }, token: null,
    });
    await setToken(r.session_token);
    setUser(r.user);
  };

  const loginWithSessionId = async (session_id: string) => {
    const r = await api<{ session_token: string; user: User }>("/auth/session", {
      method: "POST", body: { session_id }, token: null,
    });
    await setToken(r.session_token);
    setUser(r.user);
  };

  const logout = async () => {
    try { await api("/auth/logout", { method: "POST" }); } catch (_e) { /* noop */ }
    await clearToken();
    setUser(null);
  };

  const setRoleLocal = (role: string) => setUser((u) => (u ? { ...u, role } : u));

  return (
    <AuthCtx.Provider value={{ user, loading, login, loginWithSessionId, logout, refresh, setRoleLocal }}>
      {children}
    </AuthCtx.Provider>
  );
}
