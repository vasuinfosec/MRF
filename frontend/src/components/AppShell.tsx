import React from "react";
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from "react-native";
import { useRouter, usePathname } from "expo-router";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { theme } from "@/src/theme";
import { useAuth } from "@/src/auth";

type Tab = { key: string; label: string; icon: keyof typeof Ionicons.glyphMap; path: string; roles: string[] };
const TABS: Tab[] = [
  { key: "home", label: "Home", icon: "grid-outline", path: "/home", roles: ["director","pm","gm","purchase","admin"] },
  { key: "mrf", label: "MRF", icon: "document-text-outline", path: "/mrf", roles: ["director","pm","gm","purchase","admin"] },
  { key: "po", label: "PO", icon: "cart-outline", path: "/po", roles: ["director","pm","gm","purchase","admin"] },
  { key: "billing", label: "Billing", icon: "cash-outline", path: "/billing", roles: ["director","purchase","admin","gm"] },
  { key: "more", label: "More", icon: "menu-outline", path: "/more", roles: ["director","pm","gm","purchase","admin"] },
];

export function AppShell({ children, title, right, testID }: { children: React.ReactNode; title: string; right?: React.ReactNode; testID?: string }) {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const pathname = usePathname();
  const { user } = useAuth();

  const tabs = TABS.filter((t) => !user || t.roles.includes(user.role));
  const currentTab = tabs.find((t) => pathname.startsWith(t.path))?.key || "home";

  return (
    <SafeAreaView style={s.wrap} edges={["top"]} testID={testID}>
      <View style={s.header}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
          <View style={s.logo}><Text style={s.logoText}>V</Text></View>
          <View>
            <Text style={s.title}>{title}</Text>
            {user ? <Text style={s.subtitle}>{user.name} · {roleLabel(user.role)}</Text> : null}
          </View>
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          {right}
          <TouchableOpacity testID="notif-icon" onPress={() => router.push("/notifications")} style={s.iconBtn}>
            <Ionicons name="notifications-outline" size={22} color={theme.colors.text} />
          </TouchableOpacity>
        </View>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 96 + insets.bottom }}>
        {children}
      </ScrollView>

      <View style={[s.tabBar, { paddingBottom: insets.bottom || 8 }]}>
        {tabs.map((t) => {
          const active = currentTab === t.key;
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
    // legacy fallbacks
    site_engineer: "Project Manager",
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
  tabBar: {
    position: "absolute", bottom: 0, left: 0, right: 0,
    flexDirection: "row",
    backgroundColor: theme.colors.bg,
    borderTopWidth: 1, borderTopColor: theme.colors.border,
    paddingTop: 6,
  },
  tab: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 6 },
  tabLabel: { fontSize: 10, marginTop: 2, letterSpacing: 0.4 },
});
