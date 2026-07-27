/**
 * Global keyboard-shortcut hook for the web dashboard.
 *
 * Bindings (all web-only):
 *   /            → focus the first search input on the page
 *   g h          → go to /home
 *   g m          → go to /mrf
 *   g p          → go to /po
 *   g b          → go to /billing
 *   g a          → go to /admin/access (Director/Admin)
 *   ?            → toggle the shortcuts help overlay
 *   Esc          → close open modals
 *
 * "g X" is a leader-key combo (like Vim / GitHub): press g, then a second
 * key within 1000 ms.
 */
import { useEffect } from "react";
import { Platform } from "react-native";
import { useRouter } from "expo-router";

export function useKeyboardShortcuts(setHelpOpen?: (v: boolean) => void) {
  const router = useRouter();

  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return;

    let leader = false;
    let leaderTimer: any = null;
    const clearLeader = () => { leader = false; if (leaderTimer) { clearTimeout(leaderTimer); leaderTimer = null; } };

    const inEditable = (t: EventTarget | null): boolean => {
      const el = t as HTMLElement | null;
      if (!el) return false;
      const tag = (el.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return true;
      if (el.isContentEditable) return true;
      return false;
    };

    const handler = (e: KeyboardEvent) => {
      // Never hijack when the user is typing
      if (inEditable(e.target)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      // Esc closes leader / modals
      if (e.key === "Escape") { clearLeader(); return; }

      // "?" toggles help
      if (e.key === "?" && setHelpOpen) {
        e.preventDefault();
        setHelpOpen(true);
        return;
      }

      // "/" focuses first search input
      if (e.key === "/" && !leader) {
        const search = document.querySelector<HTMLInputElement>(
          'input[placeholder*="Search" i], input[data-testid*="search" i]'
        );
        if (search) { e.preventDefault(); search.focus(); }
        return;
      }

      // Leader "g" begins a combo
      if (!leader && e.key.toLowerCase() === "g") {
        leader = true;
        leaderTimer = setTimeout(clearLeader, 1000);
        return;
      }

      if (leader) {
        const map: Record<string, string> = {
          h: "/home",
          m: "/mrf",
          p: "/po",
          b: "/billing",
          a: "/admin/access",
          s: "/masters",
          u: "/admin/uom",
          c: "/admin/categories",
        };
        const path = map[e.key.toLowerCase()];
        clearLeader();
        if (path) {
          e.preventDefault();
          router.push(path as any);
        }
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [router, setHelpOpen]);
}
