import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform, RefreshControl } from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { AppShell } from "@/src/components/AppShell";
import { useAuth } from "@/src/auth";
import { api, backendUrl, getDownloadToken } from "@/src/api";
import { Btn, Card, H1, Muted, Pill, Empty, Loader } from "@/src/components/ui";
import { theme, statusLabel } from "@/src/theme";
import { useResponsive } from "@/src/hooks/useResponsive";
import { DTable, DHead, DH, DRow, DC } from "@/src/components/DataTable";

// 17-status filter set + summarized groupings
const STATUS_FILTERS = [
  { key: "all", label: "All" },
  { key: "pending_action", label: "Pending Action" },  // computed client-side
  { key: "draft", label: "Draft" },
  { key: "under_pm_review", label: "Under PM Review", aliases: ["submitted", "under_review", "pm_review"] },
  { key: "under_gm_review", label: "Under GM Review" },
  { key: "under_director_review", label: "Under Director Review" },
  { key: "authorised", label: "Authorised", aliases: ["approved"] },
  { key: "rejected", label: "Rejected" },
  { key: "returned", label: "Returned" },
  { key: "purchase_pending", label: "Purchase Pending", aliases: ["sent_to_purchase"] },
  { key: "quotation_received", label: "Quotation Received" },
  { key: "po_pending", label: "PO Pending" },
  { key: "po_issued", label: "PO Issued", aliases: ["partially_ordered", "fully_ordered"] },
  { key: "partially_received", label: "Partially Received" },
  { key: "fully_received", label: "Fully Received", aliases: ["received"] },
  { key: "closed", label: "Closed" },
  { key: "cancelled", label: "Cancelled" },
];

function ownerRoleForStatus(status: string): string {
  const s = (status || "").toLowerCase();
  if (s === "draft" || s === "returned") return "site_engineer";
  if (["submitted", "pm_review", "under_review", "under_pm_review"].includes(s)) return "pm";
  if (s === "under_purchase_review" || s === "purchase_pending" || s === "sent_to_purchase" || s === "quotation_received" || s === "po_pending") return "purchase";
  if (s === "under_gm_review") return "gm";
  if (s === "under_director_review") return "director";
  if (["authorised", "approved"].includes(s)) return "purchase";
  return "";
}

function pendingForRole(role: string | undefined, status: string): boolean {
  const owner = ownerRoleForStatus(status);
  if (!role || !owner) return false;
  if (role === "admin" || role === "director") return true; // see all pending
  return role === owner;
}

export default function MRFList() {
  const { user } = useAuth();
  const params = useLocalSearchParams<{ status?: string; filter?: string }>();
  const router = useRouter();
  const { isDesktop } = useResponsive();
  const [mrfs, setMrfs] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [projects, setProjects] = useState<any[]>([]);
  const [filter, setFilter] = useState<string>(params.filter || params.status || "all");

  const load = useCallback(async () => {
    setBusy(true); setErr("");
    try {
      // Only pass status as a real server-side filter for real statuses.
      const knownServerFilter = STATUS_FILTERS.find((f) => f.key === filter)?.aliases?.length
        ? "" // aliases require client-side filter
        : (filter !== "all" && filter !== "pending_action" ? `?status=${filter}` : "");
      const [m, p] = await Promise.all([api<any[]>(`/mrf${knownServerFilter}`), api<any[]>("/projects")]);
      setMrfs(m); setProjects(p);
    } catch (e: any) {
      setErr(e?.message || "Failed to load MRFs");
    }
    setBusy(false);
  }, [filter]);

  useEffect(() => { if (user) load(); }, [user, load, filter]);

  const projName = (id: string) => projects.find((p) => p.project_id === id)?.code || "—";

  const canCreate = user?.role === "site_engineer" || user?.role === "pm" || user?.role === "director" || user?.role === "admin";

  const exportExcel = async () => {
    const t = await getDownloadToken();
    if (!t) return;
    const url = `${backendUrl}/api/export/mrf?token=${t}`;
    if (typeof window !== "undefined") window.open(url, "_blank");
  };

  const openMRF = (mrfId: string) => {
    // On web, open in a new tab so the user keeps their list open.
    if (Platform.OS === "web" && typeof window !== "undefined") {
      const win = window.open(`/mrf/${mrfId}`, "_blank");
      if (!win) router.push(`/mrf/${mrfId}` as any); // popup blocked → fallback
      return;
    }
    router.push(`/mrf/${mrfId}` as any);
  };

  // Client-side filter application (aliases + pending_action)
  const filtered = mrfs.filter((m) => {
    if (filter === "all") return true;
    if (filter === "pending_action") return pendingForRole(user?.role, m.status);
    const def = STATUS_FILTERS.find((f) => f.key === filter);
    if (def?.aliases?.length) return m.status === filter || def.aliases.includes(m.status);
    return m.status === filter;
  });

  const pendingCount = mrfs.filter((m) => pendingForRole(user?.role, m.status)).length;

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
      <Muted>
        {mrfs.length} MRF{mrfs.length === 1 ? "" : "s"} · {pendingCount} pending your action
      </Muted>

      <ScrollView horizontal showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.chipRow}
        style={{ marginTop: 12, marginHorizontal: -16, paddingHorizontal: 16 }}>
        {STATUS_FILTERS.map((f) => {
          const active = filter === f.key;
          // Show count for the pending filter
          const badge = f.key === "pending_action" ? pendingCount : null;
          return (
            <TouchableOpacity
              key={f.key}
              testID={`filter-${f.key}`}
              onPress={() => setFilter(f.key)}
              style={[styles.chip, {
                borderColor: active ? theme.colors.primary : theme.colors.border,
                backgroundColor: active ? theme.colors.primary : theme.colors.bg,
              }]}
            >
              <Text style={{ color: active ? "#fff" : theme.colors.text, fontSize: 12, fontWeight: "600" }}>
                {f.label}
              </Text>
              {typeof badge === "number" && badge > 0 ? (
                <View style={{ marginLeft: 6, backgroundColor: active ? "#fff" : theme.colors.danger, borderRadius: 10, paddingHorizontal: 6, minWidth: 20, alignItems: "center" }}>
                  <Text style={{ color: active ? theme.colors.primary : "#fff", fontSize: 10, fontWeight: "800" }}>{badge}</Text>
                </View>
              ) : null}
            </TouchableOpacity>
          );
        })}
      </ScrollView>

      {err ? (
        <Card style={{ marginTop: 16, backgroundColor: "#FEF2F2", borderColor: "#F87171", borderWidth: 1 }}>
          <Text style={{ color: theme.colors.danger, fontWeight: "600" }} testID="mrf-list-error">Failed to load</Text>
          <Text style={{ color: theme.colors.textMuted, fontSize: 12, marginTop: 4 }}>{err}</Text>
          <Btn testID="retry-btn" title="Retry" variant="outline" onPress={load} style={{ marginTop: 10 }} />
        </Card>
      ) : null}

      {busy && !mrfs.length ? <Loader /> : null}

      <ScrollView refreshControl={<RefreshControl refreshing={busy} onRefresh={load} />} style={{ marginTop: 16 }}>
        {isDesktop ? (
          <DTable>
            <DHead>
              <DH flex={1.2}>MRF #</DH>
              <DH flex={1.4}>Project · Site</DH>
              <DH flex={1.6}>Customer</DH>
              <DH flex={1}>System / Items</DH>
              <DH flex={1}>Required by</DH>
              <DH flex={0.9}>Requester</DH>
              <DH flex={1.2}>Status</DH>
            </DHead>
            {filtered.map((m) => (
              <DRow key={m.mrf_id}
                testID={`mrf-item-${m.mrf_number.replace(/\//g, "-")}`}
                onPress={() => openMRF(m.mrf_id)}>
                <DC flex={1.2}>
                  <Text style={styles.tcellStrong} testID={`mrfnum-${m.mrf_number.replace(/\//g, "-")}`}>{m.mrf_number}</Text>
                  {pendingForRole(user?.role, m.status) ? (
                    <Text style={styles.actionTag}>YOUR ACTION</Text>
                  ) : null}
                </DC>
                <DC flex={1.4}>{`${projName(m.project_id)} · ${m.site}`}</DC>
                <DC flex={1.6}>
                  {m.customer_id ? (
                    <Text style={styles.tcell} numberOfLines={1}>
                      <Text style={{ fontWeight: "700", color: theme.colors.primary }}>{m.customer_id}</Text>
                      {m.customer_name ? ` · ${m.customer_name}` : ""}
                    </Text>
                  ) : <Text style={[styles.tcell, { color: theme.colors.textMuted }]}>—</Text>}
                </DC>
                <DC flex={1}>{`${m.system_category} · ${m.items.length}`}</DC>
                <DC flex={1}>{m.required_by}</DC>
                <DC flex={0.9}>{m.requesting_person}</DC>
                <DC flex={1.2}><Pill status={m.status} /></DC>
              </DRow>
            ))}
            {!busy && !filtered.length && !err ? (
              <View style={{ paddingVertical: 24 }}>
                <Empty msg={filter === "all" ? "No MRFs found. Tap 'New MRF' to create one." : `No MRFs in status: ${statusLabel(filter)}`} testID="empty-mrf" />
              </View>
            ) : null}
          </DTable>
        ) : (
          <View style={{ gap: 10, paddingBottom: 60 }}>
            {filtered.map((m) => (
              <TouchableOpacity
                key={m.mrf_id}
                testID={`mrf-item-${m.mrf_number.replace(/\//g, "-")}`}
                onPress={() => openMRF(m.mrf_id)}
                activeOpacity={0.75}
              >
                <Card>
                  <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.mrfNum} testID={`mrfnum-${m.mrf_number.replace(/\//g, "-")}`}>{m.mrf_number}</Text>
                      <Text style={styles.mrfProj}>{projName(m.project_id)} · {m.site}</Text>
                      {m.customer_id ? (
                        <Text style={styles.mrfCust} numberOfLines={1}>
                          <Text style={{ fontWeight: "700", color: theme.colors.primary }}>{m.customer_id}</Text>
                          {m.customer_name ? ` · ${m.customer_name}` : ""}
                        </Text>
                      ) : null}
                      <Text style={styles.mrfMeta}>{m.system_category} · {m.items.length} item(s)</Text>
                    </View>
                    <View style={{ alignItems: "flex-end" }}>
                      <Pill status={m.status} />
                      {pendingForRole(user?.role, m.status) ? (
                        <View style={{ marginTop: 6, backgroundColor: theme.colors.danger, borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2 }}>
                          <Text style={{ color: "#fff", fontSize: 9, fontWeight: "800" }}>YOUR ACTION</Text>
                        </View>
                      ) : null}
                    </View>
                  </View>
                  <View style={styles.mrfFoot}>
                    <Text style={styles.mrfDate}>Required by: {m.required_by}</Text>
                    <Text style={styles.mrfDate}>By {m.requesting_person}</Text>
                  </View>
                  <View style={{ marginTop: 8, flexDirection: "row", justifyContent: "flex-end", alignItems: "center" }}>
                    <Text style={{ color: theme.colors.primary, fontSize: 11, fontWeight: "700" }}>OPEN</Text>
                    <Ionicons name={Platform.OS === "web" ? "open-outline" : "chevron-forward"} size={14} color={theme.colors.primary} style={{ marginLeft: 4 }} />
                  </View>
                </Card>
              </TouchableOpacity>
            ))}

            {!busy && !filtered.length && !err ? (
              <Empty msg={filter === "all" ? "No MRFs found. Tap 'New MRF' to create one." : `No MRFs in status: ${statusLabel(filter)}`} testID="empty-mrf" />
            ) : null}
          </View>
        )}
      </ScrollView>
    </AppShell>
  );
}

const styles = StyleSheet.create({
  chipRow: { gap: 8, paddingRight: 16 },
  chip: { flexShrink: 0, height: 36, paddingHorizontal: 14, borderRadius: 999, borderWidth: 1, alignItems: "center", justifyContent: "center", flexDirection: "row" },
  mrfNum: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  mrfProj: { fontSize: 13, color: theme.colors.textSecondary, marginTop: 2 },
  mrfCust: { fontSize: 11, color: theme.colors.textMuted, marginTop: 2, letterSpacing: 0.3 },
  mrfMeta: { fontSize: 11, color: theme.colors.textMuted, marginTop: 4, textTransform: "uppercase", letterSpacing: 1 },
  mrfFoot: { flexDirection: "row", justifyContent: "space-between", marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: theme.colors.border },
  mrfDate: { fontSize: 11, color: theme.colors.textMuted },

  // Desktop table view (shared primitives from DataTable.tsx)
  tcell: { fontSize: 13, color: theme.colors.text },
  tcellStrong: { fontSize: 13, fontWeight: "700", color: theme.colors.text },
  actionTag: { marginTop: 4, alignSelf: "flex-start", backgroundColor: theme.colors.danger, color: "#fff", fontSize: 9, fontWeight: "800", paddingHorizontal: 5, paddingVertical: 2, borderRadius: 4 },
});
