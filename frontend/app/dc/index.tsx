import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl, TextInput } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Muted, Btn, Loader, Card, Pill } from "@/src/components/ui";
import { theme, statusLabel } from "@/src/theme";

interface DC {
  dc_id: string; dc_number: string; date: string;
  dc_type: string; status: string;
  project_id: string; from_location: string; to_location: string;
  dispatch_date: string; vehicle_no?: string;
  items: any[];
}

export default function DCList() {
  const router = useRouter();
  const [rows, setRows] = useState<DC[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"all" | "outbound" | "inbound">("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<DC[]>("/dc");
      setRows(data || []);
    } catch {
      setRows([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    let r = rows;
    if (tab !== "all") r = r.filter((d) => d.dc_type === tab);
    if (q.trim()) {
      const s = q.trim().toLowerCase();
      r = r.filter((d) =>
        (d.dc_number + " " + (d.vehicle_no || "") + " " + (d.from_location || "") + " " + (d.to_location || "")).toLowerCase().includes(s)
      );
    }
    return r;
  }, [rows, q, tab]);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }} testID="back-btn">
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Delivery Challans</Text>
        <TouchableOpacity onPress={() => router.push("/dc/create")} style={{ padding: 8 }} testID="dc-new-btn">
          <Ionicons name="add" size={22} color={theme.colors.primary} />
        </TouchableOpacity>
      </View>

      <View style={styles.tabs}>
        {(["all", "outbound", "inbound"] as const).map((t) => (
          <TouchableOpacity key={t} onPress={() => setTab(t)}
            style={[styles.tab, tab === t ? styles.tabActive : null]} testID={`dc-tab-${t}`}>
            <Text style={[styles.tabText, tab === t ? styles.tabTextActive : null]}>{statusLabel(t)}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <View style={styles.searchBar}>
        <Ionicons name="search" size={16} color={theme.colors.textMuted} />
        <TextInput value={q} onChangeText={setQ} placeholder="Search by DC#, vehicle, location…" style={styles.searchInput} testID="dc-search" />
      </View>

      <ScrollView
        contentContainerStyle={{ padding: 12, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
      >
        {loading ? <Loader /> : null}
        {!loading && !filtered.length ? <Muted>No DCs yet. Tap + to create one.</Muted> : null}
        {filtered.map((d) => (
          <Card key={d.dc_id} style={styles.row}>
            <TouchableOpacity onPress={() => router.push(`/dc/${d.dc_id}`)} testID={`dc-row-${d.dc_id}`}>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Text style={styles.dcNo}>{d.dc_number}</Text>
                    <Pill status={d.dc_type || "outbound"} />
                    <Pill status={d.status || "issued"} />
                  </View>
                  <Muted>{d.from_location} → {d.to_location}</Muted>
                  <Muted>Dispatch: {d.dispatch_date}  ·  Vehicle: {d.vehicle_no || "—"}  ·  Items: {d.items?.length || 0}</Muted>
                </View>
                <Ionicons name="chevron-forward" size={20} color={theme.colors.textMuted} />
              </View>
            </TouchableOpacity>
          </Card>
        ))}
      </ScrollView>

      <View style={styles.fabRow}>
        <Btn title="Export All DCs (Excel)" variant="outline" onPress={async () => {
          const { getDownloadToken, backendUrl } = await import("@/src/api");
          const t = await getDownloadToken();
          if (!t) return;
          if (typeof window !== "undefined") window.open(`${backendUrl}/api/export/dc?token=${t}`, "_blank");
        }} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 4, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  tabs: { flexDirection: "row", padding: 8, gap: 6, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  tab: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, backgroundColor: "#fff", borderWidth: 1, borderColor: theme.colors.border },
  tabActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  tabText: { fontSize: 12, fontWeight: "700", color: theme.colors.text },
  tabTextActive: { color: "#fff" },
  searchBar: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#fff", margin: 12, marginBottom: 0, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6 },
  searchInput: { flex: 1, fontSize: 13, color: theme.colors.text },
  row: { marginBottom: 8 },
  dcNo: { fontSize: 15, fontWeight: "800", color: theme.colors.primary },
  fabRow: { padding: 12, borderTopWidth: 1, borderTopColor: theme.colors.border, backgroundColor: theme.colors.bg },
});
