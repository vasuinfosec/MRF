import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { AppShell } from "@/src/components/AppShell";
import { useAuth } from "@/src/auth";
import { api, backendUrl, getToken } from "@/src/api";
import { Btn, Card, H1, Muted, Pill, Empty, Loader } from "@/src/components/ui";
import { theme } from "@/src/theme";

export default function POList() {
  const { user } = useAuth();
  const router = useRouter();
  const [pos, setPos] = useState<any[]>([]);
  const [vendors, setVendors] = useState<any[]>([]);
  const [projects, setProjects] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [p, v, pr] = await Promise.all([api("/po"), api("/vendors"), api("/projects")]);
      setPos(p); setVendors(v); setProjects(pr);
    } catch (_e) { /* noop */ }
    setBusy(false);
  }, []);

  useEffect(() => { if (user) load(); }, [user, load]);

  const vName = (id: string) => vendors.find((v) => v.vendor_id === id)?.name || id;
  const pName = (id: string) => projects.find((p) => p.project_id === id)?.code || id;

  const canCreate = user?.role === "purchase" || user?.role === "admin";

  const exportExcel = async () => {
    const t = await getToken();
    if (typeof window !== "undefined") window.open(`${backendUrl}/api/export/po?token=${t}`, "_blank");
  };

  return (
    <AppShell title="Purchase Orders" testID="po-list-screen"
      right={<TouchableOpacity testID="export-po-btn" onPress={exportExcel} style={{ padding: 8 }}>
        <Ionicons name="download-outline" size={22} color={theme.colors.text} />
      </TouchableOpacity>}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <H1>Orders</H1>
        {canCreate ? (
          <Btn testID="create-po-btn" title="+ New PO" variant="action" onPress={() => router.push("/po/create")} />
        ) : null}
      </View>
      <Muted>Convert approved MRFs to purchase orders.</Muted>

      {busy && !pos.length ? <Loader /> : null}

      <View style={{ marginTop: 16, gap: 10 }}>
        {pos.map((p) => (
          <TouchableOpacity key={p.po_id} testID={`po-item-${p.po_number.replace(/\//g, "-")}`}
            onPress={() => router.push(`/po/${p.po_id}` as any)} activeOpacity={0.7}>
            <Card>
              <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.poNum}>{p.po_number}</Text>
                  <Text style={styles.poVendor}>{vName(p.vendor_id)}</Text>
                  <Text style={styles.poMeta}>Project {pName(p.project_id)} · {p.items?.length || 0} items · MRF {p.mrf_refs?.length || 0}</Text>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <Pill status={p.status === "issued" ? "sent_to_purchase" : p.status} />
                  <Text style={styles.poTotal}>₹ {new Intl.NumberFormat("en-IN").format(p.total || 0)}</Text>
                </View>
              </View>
            </Card>
          </TouchableOpacity>
        ))}
        {!busy && !pos.length ? <Empty msg="No purchase orders yet." testID="empty-po" /> : null}
      </View>
    </AppShell>
  );
}

const styles = StyleSheet.create({
  poNum: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  poVendor: { fontSize: 13, color: theme.colors.textSecondary, marginTop: 2 },
  poMeta: { fontSize: 11, color: theme.colors.textMuted, marginTop: 4, textTransform: "uppercase", letterSpacing: 1 },
  poTotal: { fontSize: 15, fontWeight: "800", color: theme.colors.primary, marginTop: 6 },
});
