/**
 * Lightweight dark-mode toggle for the web.
 *
 * Strategy:
 *   - We do NOT refactor the giant static `theme` object (would touch 40+ files).
 *   - Instead we flip a `data-theme="dark"` attribute on <html>. A stylesheet
 *     shipped in +html.tsx swaps a handful of high-impact CSS custom properties
 *     and overrides card / surface / border / text colours globally.
 *   - Preference is persisted in localStorage under `vasu_theme`.
 *   - Falls back to `prefers-color-scheme` on first visit.
 *   - On native, the provider is a no-op (dark mode is web-only for now).
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Platform } from "react-native";

type Mode = "light" | "dark";
type Ctx = { mode: Mode; toggle: () => void; setMode: (m: Mode) => void };

const ThemeCtx = createContext<Ctx>({ mode: "light", toggle: () => {}, setMode: () => {} });
export const useThemeMode = () => useContext(ThemeCtx);

const STORAGE_KEY = "vasu_theme";

function readInitial(): Mode {
  if (Platform.OS !== "web" || typeof window === "undefined") return "light";
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "dark" || saved === "light") return saved;
  } catch {}
  try {
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) return "dark";
  } catch {}
  return "light";
}

function apply(mode: Mode) {
  if (Platform.OS !== "web" || typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", mode);
  // Also flip the browser chrome / status-bar colour for a native-feel install
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", mode === "dark" ? "#0B1220" : "#0F172A");
}

/**
 * Inject the CSS rules for dark mode + hover / focus / print polish at runtime.
 * We do this here (instead of relying on `+html.tsx`) because Expo Router's
 * dev server does not process `+html.tsx` — those rules only ship in a static
 * production export. Runtime injection makes the polish work everywhere
 * (dev server, production export, and even embedded iframe previews).
 */
const CSS = `
/* Desktop hover polish */
@media (hover: hover) and (pointer: fine) {
  [role="button"]:hover, a:hover,
  [data-testid$="-btn"]:hover,
  [data-testid^="side-"]:hover,
  [data-testid^="tab-"]:hover {
    filter: brightness(0.96);
    transition: filter 120ms ease-out, background-color 120ms ease-out;
  }
  [data-testid$="-card"]:hover,
  [data-testid^="mrf-item-"]:hover,
  [data-testid^="po-item-"]:hover {
    box-shadow: 0 6px 18px -8px rgba(15,23,42,0.18);
    transform: translateY(-1px);
    transition: box-shadow 160ms ease-out, transform 160ms ease-out;
  }
  [data-role="table-row"]:hover { background-color: #F1F5F9 !important; }
  input:focus-visible, textarea:focus-visible, select:focus-visible,
  button:focus-visible, [role="button"]:focus-visible {
    outline: 2px solid #2563EB; outline-offset: 2px; border-radius: 4px;
  }
}
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(15,23,42,0.25); border-radius: 6px; }
::-webkit-scrollbar-thumb:hover { background: rgba(15,23,42,0.45); }

/* ===================== DARK MODE ===================== */
html[data-theme="dark"] { color-scheme: dark; background:#0B1220; }
html[data-theme="dark"] body { background:#0B1220; color:#E2E8F0; }
html[data-theme="dark"] .r-backgroundColor-14lw9ot { background-color:#111827 !important; }
html[data-theme="dark"] .r-backgroundColor-11j01x2 { background-color:#0B1220 !important; }
html[data-theme="dark"] .r-backgroundColor-1jh0li6 { background-color:#1F2937 !important; }
html[data-theme="dark"] .r-borderColor-1wr2p1e,
html[data-theme="dark"] .r-borderTopColor-174iedc,
html[data-theme="dark"] .r-borderRightColor-13zh0bf,
html[data-theme="dark"] .r-borderBottomColor-eaxd7d { border-color:#1F2937 !important; }
html[data-theme="dark"] .r-color-15ijx5m { color:#E2E8F0 !important; }
html[data-theme="dark"] .r-color-1s7ct43 { color:#94A3B8 !important; }
/* Inline-style fallbacks — Btn variants set color via style prop */
html[data-theme="dark"] [style*="color: rgb(15, 23, 42)"],
html[data-theme="dark"] [style*="color:#0F172A"] { color:#E2E8F0 !important; }
html[data-theme="dark"] [style*="color: rgb(71, 85, 105)"] { color:#94A3B8 !important; }
html[data-theme="dark"] [style*="color: rgb(100, 116, 139)"] { color:#94A3B8 !important; }
html[data-theme="dark"] [style*="background-color: rgb(255, 255, 255)"] { background-color:#111827 !important; }
html[data-theme="dark"] [style*="border-color: rgb(203, 213, 225)"] { border-color:#334155 !important; }
html[data-theme="dark"] input, html[data-theme="dark"] textarea, html[data-theme="dark"] select {
  background-color:#0F172A !important; color:#E2E8F0 !important; border-color:#334155 !important;
}
html[data-theme="dark"] input::placeholder,
html[data-theme="dark"] textarea::placeholder { color:#64748B !important; }
html[data-theme="dark"] ::-webkit-scrollbar-thumb { background: rgba(203,213,225,0.25); }
html[data-theme="dark"] ::-webkit-scrollbar-thumb:hover { background: rgba(203,213,225,0.45); }

/* ===================== PRINT ===================== */
@media print {
  @page { margin: 12mm; }
  html, body, #root { position: static !important; inset: auto !important; overflow: visible !important; height: auto !important; background:#fff !important; color:#000 !important; }
  [id="app-sidebar"], [id="app-tabbar"],
  [data-testid="notif-icon"], [data-testid="theme-toggle"], [data-testid="shortcuts-btn"] { display: none !important; }
  [id="app-content"] { max-width: 100% !important; }
  * { color:#000 !important; background:#fff !important; box-shadow:none !important; }
  [data-testid$="-card"] { page-break-inside: avoid; break-inside: avoid; }
}
`;

function injectCss() {
  if (Platform.OS !== "web" || typeof document === "undefined") return;
  if (document.getElementById("vasu-web-polish")) return;
  const st = document.createElement("style");
  st.id = "vasu-web-polish";
  st.appendChild(document.createTextNode(CSS));
  document.head.appendChild(st);
}

export function ThemeModeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<Mode>(() => readInitial());

  useEffect(() => { injectCss(); apply(mode); }, [mode]);

  const setMode = useCallback((m: Mode) => {
    setModeState(m);
    if (Platform.OS === "web") {
      try { window.localStorage.setItem(STORAGE_KEY, m); } catch {}
    }
  }, []);
  const toggle = useCallback(() => setMode(mode === "dark" ? "light" : "dark"), [mode, setMode]);

  const value = useMemo(() => ({ mode, toggle, setMode }), [mode, toggle, setMode]);
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}
