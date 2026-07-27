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
                [data-testid$="-btn"]:hover {
                  filter: brightness(0.96);
                  transition: filter 120ms ease-out;
                }
                input:focus, textarea:focus, select:focus {
                  outline: 2px solid #0F172A;
                  outline-offset: 1px;
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
