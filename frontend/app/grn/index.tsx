import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl, TextInput } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Muted, Btn, Loader, Card } from "@/src/components/ui";
import { theme } from "@/src/theme";

interface GRN {
  grn_id: string;
  grn_number: string;
  date: string;
  po_number: string;
  vendor_id: string;
  project_id: string;
  mrf_refs: string[];
  received_by_name: string;
  items: any[];
  status?: string;
  vehicle_no?: string;
  vendor_dc_ref?: string;
}

export default function GRNList() {
  const router = useRouter();
  const [rows, setRows] = useState<GRN[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<GRN[]>("/grns");
      setRows(data || []);
    } catch {
      setRows([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    if (!q.trim()) return rows;
    const s = q.trim().toLowerCase();
    return rows.filter((g) =>
      (g.grn_number + " " + (g.po_number || "") + " " + (g.received_by_name || "")).toLowerCase().includes(s)
    );
  }, [rows, q]);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }} testID="back-btn">
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Goods Received Notes</Text>
        <TouchableOpacity onPress={load} style={{ padding: 8 }}>
          <Ionicons name="refresh" size={22} color={theme.colors.text} />
        </TouchableOpacity>
      </View>

      <View style={styles.searchBar}>
        <Ionicons name="search" size={16} color={theme.colors.textMuted} />
        <TextInput
          value={q}
          onChangeText={setQ}
          placeholder="Search by GRN#, PO#, receiver…"
          style={styles.searchInput}
          testID="grn-search"
        />
      </View>

      <ScrollView
        contentContainerStyle={{ padding: 12, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
      >
        {loading ? <Loader /> : null}
        {!loading && !filtered.length ? <Muted>No GRNs found.</Muted> : null}
        {filtered.map((g) => (
          <Card key={g.grn_id} style={styles.row}>
            <TouchableOpacity onPress={() => router.push(`/grn/${g.grn_id}`)} testID={`grn-row-${g.grn_id}`}>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.grnNo}>{g.grn_number}</Text>
                  <Muted>{new Date(g.date).toLocaleDateString()}  ·  PO {g.po_number || "—"}</Muted>
                  <Muted>Items: {g.items?.length || 0}  ·  Received by: {g.received_by_name || "—"}</Muted>
                  {g.vendor_dc_ref ? <Muted>Vendor DC: {g.vendor_dc_ref}</Muted> : null}
                </View>
                <Ionicons name="chevron-forward" size={20} color={theme.colors.textMuted} />
              </View>
            </TouchableOpacity>
          </Card>
        ))}
      </ScrollView>

      <View style={styles.fabRow}>
        <Btn title="Export All GRNs (Excel)" variant="outline" onPress={async () => {
          const { getToken, backendUrl } = await import("@/src/api");
          const t = await getToken();
          if (typeof window !== "undefined") window.open(`${backendUrl}/api/export/grn?token=${t}`, "_blank");
        }} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 4, paddingVertical: 8, backgroundColor: theme.colors.bg,
    borderBottomWidth: 1, borderBottomColor: theme.colors.border,
  },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  searchBar: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#fff", margin: 12, marginBottom: 0,
    borderWidth: 1, borderColor: theme.colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 6,
  },
  searchInput: { flex: 1, fontSize: 13, color: theme.colors.text },
  row: { marginBottom: 8 },
  grnNo: { fontSize: 15, fontWeight: "800", color: theme.colors.primary },
  fabRow: { padding: 12, borderTopWidth: 1, borderTopColor: theme.colors.border, backgroundColor: theme.colors.bg },
});
