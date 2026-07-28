import React, { useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform } from "react-native";
import { useRouter, usePathname } from "expo-router";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { theme } from "@/src/theme";
import { useAuth } from "@/src/auth";
import { useResponsive, CONTENT_MAX_WIDTH, SIDEBAR_WIDTH } from "@/src/hooks/useResponsive";
import { useKeyboardShortcuts } from "@/src/hooks/useKeyboardShortcuts";
import { useThemeMode } from "@/src/theme-context";
import { ShortcutsHelp } from "@/src/components/ShortcutsHelp";
import { isAccessAdmin } from "@/src/access";

type Tab = { key: string; label: string; icon: keyof typeof Ionicons.glyphMap; path: string; roles: string[] };
const TABS: Tab[] = [
  { key: "home", label: "Home", icon: "grid-outline", path: "/home", roles: ["director","pm","gm","purchase","admin","site_engineer","store"] },
  { key: "mrf", label: "MRF", icon: "document-text-outline", path: "/mrf", roles: ["director","pm","gm","purchase","admin","site_engineer","store"] },
  { key: "po", label: "PO", icon: "cart-outline", path: "/po", roles: ["director","pm","gm","purchase","admin","site_engineer","store"] },
  { key: "billing", label: "Billing", icon: "cash-outline", path: "/billing", roles: ["director","purchase","admin","gm"] },
  { key: "more", label: "More", icon: "menu-outline", path: "/more", roles: ["director","pm","gm","purchase","admin","site_engineer","store"] },
];

// Extra desktop-only entries that expose Admin/AI/Reports without a "More" hop.
type NavItem = { key: string; label: string; icon: keyof typeof Ionicons.glyphMap; path: string; roles?: string[] };
const DESKTOP_EXTRAS: NavItem[] = [
  { key: "masters", label: "Masters", icon: "server-outline", path: "/masters" },
  { key: "reports", label: "Reports", icon: "stats-chart-outline", path: "/reports" },
  { key: "assistant", label: "AI Assistant", icon: "sparkles-outline", path: "/assistant" },
  { key: "audit", label: "Audit", icon: "list-outline", path: "/audit", roles: ["admin", "director", "gm"] },
  { key: "access", label: "Access Control", icon: "shield-checkmark-outline", path: "/admin/access", roles: ["admin", "director"] },
];

export function AppShell({ children, title, right, testID }: { children: React.ReactNode; title: string; right?: React.ReactNode; testID?: string }) {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const pathname = usePathname();
  const { user } = useAuth();
  const { isDesktop } = useResponsive();
  const { mode, toggle } = useThemeMode();
  const [helpOpen, setHelpOpen] = useState(false);

  useKeyboardShortcuts(setHelpOpen);

  const tabs = TABS.filter((t) => !user || t.roles.includes(user.role));
  const extras = DESKTOP_EXTRAS.filter(
    (t) =>
      (!t.roles || (user && t.roles.includes(user.role))) &&
      (t.key !== "access" || isAccessAdmin(user))
  );

  const isActive = (path: string) => {
    // Home is only active on exact match; other tabs match on prefix.
    if (path === "/home") return pathname === "/home";
    return pathname.startsWith(path);
  };

  const headerRight = (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
      {right}
      {Platform.OS === "web" ? (
        <TouchableOpacity testID="theme-toggle" onPress={toggle} style={s.iconBtn} accessibilityLabel="Toggle dark mode">
          <Ionicons name={mode === "dark" ? "sunny-outline" : "moon-outline"} size={20} color={theme.colors.text} />
        </TouchableOpacity>
      ) : null}
      {Platform.OS === "web" && isDesktop ? (
        <TouchableOpacity testID="shortcuts-btn" onPress={() => setHelpOpen(true)} style={s.iconBtn} accessibilityLabel="Keyboard shortcuts">
          <Ionicons name="keypad-outline" size={20} color={theme.colors.text} />
        </TouchableOpacity>
      ) : null}
      <TouchableOpacity testID="notif-icon" onPress={() => router.push("/notifications")} style={s.iconBtn}>
        <Ionicons name="notifications-outline" size={22} color={theme.colors.text} />
      </TouchableOpacity>
    </View>
  );

  const brand = (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
      <View style={s.logo}><Text style={s.logoText}>V</Text></View>
      <View>
        <Text style={s.title}>{title}</Text>
        {user ? <Text style={s.subtitle}>{user.name} · {roleLabel(user.role)}</Text> : null}
      </View>
    </View>
  );

  // ---------- Desktop layout: sidebar + top bar + centered content ----------
  if (isDesktop) {
    return (
      <SafeAreaView style={s.wrap} edges={["top"]} testID={testID}>
        <View style={s.desktopRow}>
          {/* Sidebar */}
          <View style={s.sidebar} nativeID="app-sidebar">
            <View style={s.sidebarBrand}>{brand}</View>
            <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingVertical: 8 }}>
              {[...tabs, ...extras].map((t) => {
                const active = isActive(t.path);
                return (
                  <TouchableOpacity
                    key={t.key}
                    testID={`side-${t.key}`}
                    onPress={() => router.push(t.path as any)}
                    style={[s.sideItem, active && s.sideItemActive]}
                  >
                    <Ionicons name={t.icon} size={18} color={active ? "#fff" : theme.colors.text} />
                    <Text style={[s.sideLabel, { color: active ? "#fff" : theme.colors.text, fontWeight: active ? "700" : "500" }]}>
                      {t.label}
                    </Text>
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
            <View style={s.sidebarFoot}>
              <Text style={s.footHint}>Press <Text style={s.footKbd}>?</Text> for shortcuts</Text>
            </View>
          </View>

          {/* Main column */}
          <View style={{ flex: 1 }}>
            <View style={[s.header, s.desktopHeader]}>
              <Text style={s.desktopTitle}>{title}</Text>
              {headerRight}
            </View>
            <ScrollView
              style={{ flex: 1 }}
              contentContainerStyle={s.desktopScrollInner}
              nativeID="app-scroll"
            >
              <View style={s.desktopContainer} nativeID="app-content">
                {children}
              </View>
            </ScrollView>
          </View>
        </View>
        <ShortcutsHelp visible={helpOpen} onClose={() => setHelpOpen(false)} />
      </SafeAreaView>
    );
  }

  // ---------- Mobile / tablet layout: original header + bottom tabs ----------
  return (
    <SafeAreaView style={s.wrap} edges={["top"]} testID={testID}>
      <View style={s.header}>
        {brand}
        {headerRight}
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 96 + insets.bottom }}>
        <View style={s.tabletContainer}>{children}</View>
      </ScrollView>

      <View style={[s.tabBar, { paddingBottom: insets.bottom || 8 }]} nativeID="app-tabbar">
        {tabs.map((t) => {
          const active = isActive(t.path);
          return (
            <TouchableOpacity
              key={t.key}
              testID={`tab-${t.key}`}
              onPress={() => router.push(t.path as any)}
              style={s.tab}
            >
              <Ionicons name={t.icon} size={22} color={active ? theme.colors.primary : theme.colors.textMuted} />
              <Text style={[s.tabLabel, { color: active ? theme.colors.primary : theme.colors.textMuted, fontWeight: active ? "700" : "500" }]}>
                {t.label}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>
      <ShortcutsHelp visible={helpOpen} onClose={() => setHelpOpen(false)} />
    </SafeAreaView>
  );
}

export function roleLabel(role: string) {
  return ({
    director: "Director",
    pm: "Project Manager",
    gm: "General Manager",
    purchase: "Purchase",
    admin: "Admin",
    site_engineer: "Site Engineer",
    store: "Stores",
    project_manager: "Project Manager",
    billing: "Purchase",
  } as Record<string, string>)[role] || role;
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.colors.surface },
  header: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: theme.colors.bg,
    borderBottomWidth: 1, borderBottomColor: theme.colors.border,
  },
  logo: { width: 36, height: 36, borderRadius: 6, backgroundColor: theme.colors.primary, alignItems: "center", justifyContent: "center" },
  logoText: { color: "#fff", fontSize: 18, fontWeight: "800" },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text, letterSpacing: -0.3 },
  subtitle: { fontSize: 11, color: theme.colors.textMuted, marginTop: 1 },
  iconBtn: { width: 40, height: 40, borderRadius: 6, alignItems: "center", justifyContent: "center" },

  // Bottom tab bar (mobile/tablet)
  tabBar: {
    position: "absolute", bottom: 0, left: 0, right: 0,
    flexDirection: "row",
    backgroundColor: theme.colors.bg,
    borderTopWidth: 1, borderTopColor: theme.colors.border,
    paddingTop: 6,
  },
  tab: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 6 },
  tabLabel: { fontSize: 10, marginTop: 2, letterSpacing: 0.4 },

  // Tablet centering container (kept flexible)
  tabletContainer: { alignSelf: "center", width: "100%", maxWidth: 900 },

  // Desktop layout
  desktopRow: { flex: 1, flexDirection: "row" },
  sidebar: {
    width: SIDEBAR_WIDTH,
    backgroundColor: theme.colors.bg,
    borderRightWidth: 1, borderRightColor: theme.colors.border,
    paddingVertical: 12, paddingHorizontal: 8,
  },
  sidebarBrand: { paddingHorizontal: 8, paddingVertical: 8, marginBottom: 4 },
  sideItem: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 10, paddingHorizontal: 10,
    borderRadius: 6, marginBottom: 2,
  },
  sideItemActive: { backgroundColor: theme.colors.primary },
  sideLabel: { fontSize: 14 },
  sidebarFoot: { paddingTop: 12, borderTopWidth: 1, borderTopColor: theme.colors.border, alignItems: "center" },
  footHint: { fontSize: 10, color: theme.colors.textMuted },
  footKbd: {
    fontFamily: "monospace", color: theme.colors.text, fontWeight: "700",
    backgroundColor: "#F1F5F9", borderRadius: 3, paddingHorizontal: 5,
  },

  desktopHeader: { paddingHorizontal: 24 },
  desktopTitle: { fontSize: 18, fontWeight: "800", color: theme.colors.text, letterSpacing: -0.3 },
  desktopScrollInner: { padding: 24, paddingBottom: 40, alignItems: "center" },
  desktopContainer: { width: "100%", maxWidth: CONTENT_MAX_WIDTH },
});
