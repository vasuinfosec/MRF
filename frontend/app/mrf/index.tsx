import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, RefreshControl } from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { AppShell } from "@/src/components/AppShell";
import { useAuth } from "@/src/auth";
import { api, backendUrl, getToken } from "@/src/api";
import { Btn, Card, H1, Muted, Pill, Empty, Loader, Label, Body } from "@/src/components/ui";
import { theme, statusLabel } from "@/src/theme";

const STATUS_FILTERS = ["all", "draft", "pm_review", "approved", "rejected", "returned", "sent_to_purchase", "partially_ordered", "fully_ordered", "received"];

export default function MRFList() {
  const { user } = useAuth();
  const params = useLocalSearchParams<{ status?: string }>();
  const router = useRouter();
  const [mrfs, setMrfs] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [projects, setProjects] = useState<any[]>([]);
  const [filter, setFilter] = useState<string>(params.status || "all");

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const q = filter !== "all" ? `?status=${filter}` : "";
      const [m, p] = await Promise.all([api(`/mrf${q}`), api("/projects")]);
      setMrfs(m); setProjects(p);
    } catch (_e) { /* noop */ }
    setBusy(false);
  }, [filter]);

  useEffect(() => { if (user) load(); }, [user, load, filter]);

  const projName = (id: string) => projects.find((p) => p.project_id === id)?.code || "—";

  const canCreate = user?.role === "site_engineer" || user?.role === "admin";

  const exportExcel = async () => {
    const t = await getToken();
    const url = `${backendUrl}/api/export/mrf?token=${t}`;
    if (typeof window !== "undefined") window.open(url, "_blank");
  };

  return (
    <AppShell title="Material Requisitions" testID="mrf-list-screen"
      right={<TouchableOpacity testID="export-mrf-btn" onPress={exportExcel} style={{ padding: 8 }}>
        <Ionicons name="download-outline" size={22} color={theme.colors.text} />
      </TouchableOpacity>}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <H1>MRFs</H1>
        {canCreate ? (
          <Btn testID="create-mrf-btn" title="+ New MRF" variant="action" onPress={() => router.push("/mrf/create")} />
        ) : null}
      </View>
      <Muted>Auto-numbered forms routed through approval workflow.</Muted>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow} style={{ marginTop: 12, marginHorizontal: -16, paddingHorizontal: 16 }}>
        {STATUS_FILTERS.map((f) => {
          const active = filter === f;
          return (
            <TouchableOpacity
              key={f}
              testID={`filter-${f}`}
              onPress={() => setFilter(f)}
              style={[styles.chip, {
                borderColor: active ? theme.colors.primary : theme.colors.border,
                backgroundColor: active ? theme.colors.primary : theme.colors.bg,
              }]}
            >
              <Text style={{ color: active ? "#fff" : theme.colors.text, fontSize: 12, fontWeight: "600" }}>
                {statusLabel(f)}
              </Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>

      {busy && !mrfs.length ? <Loader /> : null}

      <View style={{ marginTop: 16, gap: 10 }}>
        {mrfs.map((m) => (
          <TouchableOpacity
            key={m.mrf_id}
            testID={`mrf-item-${m.mrf_number.replace(/\//g, "-")}`}
            onPress={() => router.push(`/mrf/${m.mrf_id}` as any)}
            activeOpacity={0.7}
          >
            <Card>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.mrfNum}>{m.mrf_number}</Text>
                  <Text style={styles.mrfProj}>{projName(m.project_id)} · {m.site}</Text>
                  <Text style={styles.mrfMeta}>{m.system_category} · {m.items.length} item(s)</Text>
                </View>
                <Pill status={m.status} />
              </View>
              <View style={styles.mrfFoot}>
                <Text style={styles.mrfDate}>Required by: {m.required_by}</Text>
                <Text style={styles.mrfDate}>By {m.requesting_person}</Text>
              </View>
            </Card>
          </TouchableOpacity>
        ))}

        {!busy && !mrfs.length ? (
          <Empty msg="No MRFs found. Tap 'New MRF' to create one." testID="empty-mrf" />
        ) : null}
      </View>
    </AppShell>
  );
}

const styles = StyleSheet.create({
  chipRow: { gap: 8, paddingRight: 16 },
  chip: { flexShrink: 0, height: 36, paddingHorizontal: 14, borderRadius: 999, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  mrfNum: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  mrfProj: { fontSize: 13, color: theme.colors.textSecondary, marginTop: 2 },
  mrfMeta: { fontSize: 11, color: theme.colors.textMuted, marginTop: 4, textTransform: "uppercase", letterSpacing: 1 },
  mrfFoot: { flexDirection: "row", justifyContent: "space-between", marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: theme.colors.border },
  mrfDate: { fontSize: 11, color: theme.colors.textMuted },
});
