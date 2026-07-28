// @ts-nocheck
import { ScrollViewStyleReset } from "expo-router/html";
import type { PropsWithChildren } from "react";

export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="en" style={{ height: "100%" }}>
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, shrink-to-fit=no, viewport-fit=cover"
        />

        {/* PWA / desktop-install polish */}
        <title>ViL AI Prompt Control · Vasu Infosec</title>
        <meta name="description" content="Vasu Infosec — Material Requisition & Purchase Order System with AI Purchase Manager and role-based approvals." />
        <meta name="theme-color" content="#0F172A" />
        <meta name="application-name" content="ViL AI Prompt Control" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="apple-mobile-web-app-title" content="ViL AI" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="format-detection" content="telephone=no" />
        <link rel="manifest" href="/manifest.webmanifest" />
        <link rel="apple-touch-icon" href="/assets/images/icon.png" />
        <link rel="icon" type="image/png" sizes="512x512" href="/assets/images/icon.png" />

        {/*
          Disable body scrolling on web so ScrollView components work correctly.
          Also add desktop-friendly hover states and text-selection tuning.
        */}
        <ScrollViewStyleReset />
        <style
          dangerouslySetInnerHTML={{
            __html: `
              body > div:first-child { position: fixed !important; top: 0; left: 0; right: 0; bottom: 0; }
              [role="tablist"] [role="tab"] * { overflow: visible !important; }
              [role="heading"], [role="heading"] * { overflow: visible !important; }

              /* Desktop hover polish — subtle so it doesn't break mobile touch */
              @media (hover: hover) and (pointer: fine) {
                [role="button"]:hover,
                a:hover,
                [data-testid$="-btn"]:hover,
                [data-testid^="side-"]:hover,
                [data-testid^="tab-"]:hover {
                  filter: brightness(0.96);
                  transition: filter 120ms ease-out, background-color 120ms ease-out;
                }
                /* Card hover — subtle lift */
                [data-testid$="-card"]:hover,
                [data-testid^="mrf-item-"]:hover,
                [data-testid^="po-item-"]:hover {
                  box-shadow: 0 6px 18px -8px rgba(15,23,42,0.18);
                  transform: translateY(-1px);
                  transition: box-shadow 160ms ease-out, transform 160ms ease-out;
                }
                /* Table rows */
                [data-role="table-row"]:hover {
                  background-color: #F1F5F9 !important;
                }
                /* Focus rings */
                input:focus-visible, textarea:focus-visible, select:focus-visible,
                button:focus-visible, [role="button"]:focus-visible {
                  outline: 2px solid #2563EB;
                  outline-offset: 2px;
                  border-radius: 4px;
                }
              }

              /* Scrollbar polish on desktop */
              ::-webkit-scrollbar { width: 10px; height: 10px; }
              ::-webkit-scrollbar-track { background: transparent; }
              ::-webkit-scrollbar-thumb { background: rgba(15,23,42,0.25); border-radius: 6px; }
              ::-webkit-scrollbar-thumb:hover { background: rgba(15,23,42,0.45); }

              /* Prevent iOS from auto-zooming form inputs */
              input, textarea, select { font-size: 16px !important; }

              /* Loading fallback while the JS bundle warms up */
              #root:empty::before {
                content: "Loading ViL AI Prompt Control…";
                position: fixed; inset: 0;
                display: flex; align-items: center; justify-content: center;
                color: #64748B; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                background: #F8FAFC;
              }

              /* ===================== DARK MODE (web-only lightweight overlay) =====================
                 React Native Web compiles inline styles to hashed classes such as
                 r-backgroundColor-14lw9ot (= #FFFFFF).  We target those specific
                 hashes so brand accents (primary blue #002FA7, action orange, etc.)
                 remain untouched.
              */
              html[data-theme="dark"] { color-scheme: dark; background:#0B1220; }
              html[data-theme="dark"] body { background:#0B1220; color:#E2E8F0; }
              html[data-theme="dark"] #root:empty::before { color:#94A3B8; background:#0B1220; }

              /* --- Surfaces (backgrounds) --- */
              html[data-theme="dark"] .r-backgroundColor-14lw9ot { background-color:#111827 !important; } /* #FFFFFF → dark card */
              html[data-theme="dark"] .r-backgroundColor-11j01x2 { background-color:#0B1220 !important; } /* #F8FAFC → dark bg */
              html[data-theme="dark"] .r-backgroundColor-1jh0li6 { background-color:#1F2937 !important; } /* #F1F5F9 → dark surface2 */

              /* --- Borders (all four sides + shorthand) --- */
              html[data-theme="dark"] .r-borderColor-1wr2p1e,
              html[data-theme="dark"] .r-borderTopColor-174iedc,
              html[data-theme="dark"] .r-borderRightColor-13zh0bf,
              html[data-theme="dark"] .r-borderBottomColor-eaxd7d,
              html[data-theme="dark"] .r-borderLeftColor-2yi16 { border-color:#1F2937 !important; }

              /* --- Text --- */
              html[data-theme="dark"] .r-color-15ijx5m { color:#E2E8F0 !important; } /* #0F172A body text */
              html[data-theme="dark"] .r-color-1s7ct43 { color:#94A3B8 !important; } /* muted */
              /* textSecondary #475569 is used as inline color too */
              html[data-theme="dark"] div[style*="color: rgb(71, 85, 105)"],
              html[data-theme="dark"] [style*="color: rgb(71, 85, 105)"] { color:#94A3B8 !important; }
              html[data-theme="dark"] div[style*="color: rgb(15, 23, 42)"],
              html[data-theme="dark"] [style*="color: rgb(15, 23, 42)"] { color:#E2E8F0 !important; }
              html[data-theme="dark"] div[style*="color: rgb(100, 116, 139)"],
              html[data-theme="dark"] [style*="color: rgb(100, 116, 139)"] { color:#94A3B8 !important; }
              /* Fallback for RN-Web dynamic style attr for backgrounds */
              html[data-theme="dark"] div[style*="background-color: rgb(255, 255, 255)"],
              html[data-theme="dark"] [style*="background-color: rgb(255, 255, 255)"] { background-color:#111827 !important; }

              /* --- Inputs / textareas --- */
              html[data-theme="dark"] input,
              html[data-theme="dark"] textarea,
              html[data-theme="dark"] select {
                background-color:#0F172A !important;
                color:#E2E8F0 !important;
                border-color:#334155 !important;
              }
              html[data-theme="dark"] input::placeholder,
              html[data-theme="dark"] textarea::placeholder { color:#64748B !important; }

              /* Dark scrollbars */
              html[data-theme="dark"] ::-webkit-scrollbar-thumb { background: rgba(203,213,225,0.25); }
              html[data-theme="dark"] ::-webkit-scrollbar-thumb:hover { background: rgba(203,213,225,0.45); }

              /* ===================== PRINT ===================== */
              @media print {
                @page { margin: 12mm; }
                html, body, #root, body > div:first-child { position: static !important; inset: auto !important; overflow: visible !important; height: auto !important; background:#fff !important; color:#000 !important; }
                /* Hide chrome */
                [nativeID="app-sidebar"],
                [id="app-sidebar"],
                [nativeID="app-tabbar"],
                [id="app-tabbar"],
                [data-testid="notif-icon"],
                [data-testid="theme-toggle"],
                [data-testid="shortcuts-btn"],
                [data-testid$="-btn"],
                [role="button"][data-testid*="back"] { display: none !important; }
                /* Expand content */
                [nativeID="app-content"], [id="app-content"] { max-width: 100% !important; }
                /* Force light theme in print */
                * { color:#000 !important; background:#fff !important; box-shadow:none !important; }
                /* Add page breaks between top-level cards for long docs */
                [data-testid$="-card"] { page-break-inside: avoid; break-inside: avoid; }
              }
            `,
          }}
        />
      </head>
      <body
        style={{
          margin: 0,
          height: "100%",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {children}
      </body>
    </html>
  );
}
