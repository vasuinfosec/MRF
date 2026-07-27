import { useWindowDimensions, Platform } from "react-native";

/**
 * Web-polish breakpoints:
 *   mobile   :  < 768px      (phones — bottom tab bar, single column)
 *   tablet   :  768 – 1023px (iPad portrait — bottom tab bar, wider content)
 *   desktop  :  ≥ 1024px     (desktop — sidebar nav, table rows, hover states)
 *
 * On native (iOS / Android) we always report mobile so screens keep the
 * existing behaviour untouched.
 */
export type Breakpoint = "mobile" | "tablet" | "desktop";

export function useResponsive() {
  const { width } = useWindowDimensions();
  if (Platform.OS !== "web") {
    return { width, bp: "mobile" as Breakpoint, isMobile: true, isTablet: false, isDesktop: false };
  }
  const bp: Breakpoint = width >= 1024 ? "desktop" : width >= 768 ? "tablet" : "mobile";
  return {
    width,
    bp,
    isMobile: bp === "mobile",
    isTablet: bp === "tablet",
    isDesktop: bp === "desktop",
  };
}

// Design constants used across the web-polish layer
export const CONTENT_MAX_WIDTH = 1200;
export const SIDEBAR_WIDTH = 240;
