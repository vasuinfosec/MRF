import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api, backendUrl, getToken } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, H1, H2, Muted, Empty, Loader, Pill, Stat } from "@/src/components/ui";
import { theme } from "@/src/theme";

export default function Reports() {
  const router = useRouter();
  const { user } = useAuth();
  const [ageing, setAgeing] = useState<any[]>([]);
  const [dash, setDash] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (user) load(); }, [user]);
  const load = async () => {
    setBusy(true);
    try {
      const [a, d] = await Promise.all([api("/reports/mrf-ageing"), api("/reports/dashboard")]);
      setAgeing(a); setDash(d);
    } catch (_e) { /* noop */ }
    setBusy(false);
  };

  const exp = async (kind: "mrf" | "po") => {
    const t = await getToken();
    if (typeof window !== "undefined") window.open(`${backendUrl}/api/export/${kind}?token=${t}`, "_blank");
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }}>
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Reports</Text>
        <View style={{ width: 38 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: 16 }}>
        <H1>Analytics</H1>
        <Muted>Cross-project reporting.</Muted>

        {dash ? (
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 12 }}>
            <Stat testID="rep-billable" label="Billable Qty" value={dash.billable_value} tone="primary" />
            <Stat testID="rep-nonbillable" label="Non-Billable" value={dash.non_billable_value} />
            <Stat testID="rep-pending-bill" label="Pending Billing" value={dash.pending_billing_count} tone="action" />
            <Stat testID="rep-full-bill" label="Fully Billed" value={dash.fully_billed_count} tone="success" />
          </View>
        ) : null}

        <H2 style={{ marginTop: 20 }}>Excel Export</H2>
        <View style={{ marginTop: 8, gap: 8 }}>
          <Btn testID="export-mrf-btn" title="Export MRFs to Excel" variant="primary" onPress={() => exp("mrf")} />
          <Btn testID="export-po-btn" title="Export POs to Excel" variant="primary" onPress={() => exp("po")} />
        </View>

        <H2 style={{ marginTop: 20 }}>MRF Ageing</H2>
        {busy && !ageing.length ? <Loader /> : null}
        {ageing.length ? ageing.map((m) => (
          <Card key={m.mrf_id} style={{ marginTop: 8 }} testID={`ageing-${m.mrf_number.replace(/\//g,"-")}`}>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <View>
                <Text style={{ fontWeight: "700" }}>{m.mrf_number}</Text>
                <Text style={{ color: theme.colors.textMuted, fontSize: 12 }}>{m.site}</Text>
              </View>
              <View style={{ alignItems: "flex-end" }}>
                <Pill status={m.status} />
                <Text style={{ fontWeight: "800", fontSize: 18, color: m.days > 7 ? theme.colors.danger : theme.colors.primary, marginTop: 4 }}>
                  {m.days}d
                </Text>
              </View>
            </View>
          </Card>
        )) : <Empty msg="No ageing items." testID="ageing-empty" />}
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 8, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
});
