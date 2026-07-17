import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api, backendUrl, getDownloadToken } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, H1, H2, Muted, Empty, Loader, Pill, Stat } from "@/src/components/ui";
import { theme } from "@/src/theme";

export default function Reports() {
  const router = useRouter();
  const { user } = useAuth();
  const [ageing, setAgeing] = useState<any[]>([]);
  const [variance, setVariance] = useState<any[]>([]);
  const [projects, setProjects] = useState<any[]>([]);
  const [vendors, setVendors] = useState<any[]>([]);
  const [dash, setDash] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (user) load(); }, [user]);
  const load = async () => {
    setBusy(true);
    try {
      const [a, d, v, p, vn] = await Promise.all([
        api("/reports/mrf-ageing"),
        api("/reports/dashboard"),
        api("/reports/grn-variance"),
        api("/projects"),
        api("/vendors"),
      ]);
      setAgeing(a); setDash(d); setVariance(v); setProjects(p); setVendors(vn);
    } catch (_e) { /* noop */ }
    setBusy(false);
  };

  const pName = (id: string) => projects.find((p) => p.project_id === id)?.code || "—";
  const vName = (id: string) => vendors.find((v) => v.vendor_id === id)?.name || "—";

  const exp = async (kind: "mrf" | "po") => {
    const t = await getDownloadToken();
    if (!t) return;
    if (typeof window !== "undefined") window.open(`${backendUrl}/api/export/${kind}?token=${t}`, "_blank");
  };

  const expTally = async (kind: "purchase" | "invoice") => {
    const t = await getDownloadToken();
    if (!t) return;
    if (typeof window !== "undefined") window.open(`${backendUrl}/api/export/tally?kind=${kind}&token=${t}`, "_blank");
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

        <H2 style={{ marginTop: 20 }}>Bulk Export</H2>
        <Muted>Line-item level exports with Customer ID, MAT/VAR UIDs, taxes and audit-logged downloads.</Muted>
        <View style={{ marginTop: 8, gap: 8 }}>
          <Btn testID="export-mrf-btn" title="⬇ Export All MRFs (Excel)" variant="primary" onPress={() => exp("mrf")} />
          <Btn testID="export-po-btn" title="⬇ Export All POs (Excel)" variant="primary" onPress={() => exp("po")} />
        </View>

        <H2 style={{ marginTop: 20 }}>Tally-Compatible Voucher Export</H2>
        <Muted>Purchase-voucher rows with Vasu GSTIN, Customer ID, MAT/VAR UIDs, HSN, and CGST/SGST/IGST split — ready for Tally XML import.</Muted>
        <View style={{ marginTop: 8, gap: 8 }}>
          <Btn testID="export-tally-purchase-btn" title="Tally: Purchase Voucher (from POs)" variant="action" onPress={() => expTally("purchase")} />
          <Btn testID="export-tally-invoice-btn" title="Tally: Purchase Voucher (from Vendor Invoices)" variant="action" onPress={() => expTally("invoice")} />
        </View>

        <H2 style={{ marginTop: 20 }}>GRN vs PO Variance</H2>
        <Muted>Sorted by highest absolute variance. Negative invoice variance = under-invoiced.</Muted>
        {variance.length ? variance.map((v) => (
          <Card key={v.po_id} style={{ marginTop: 8 }} testID={`variance-${v.po_number.replace(/\//g, "-")}`}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
              <View style={{ flex: 1 }}>
                <Text style={{ fontWeight: "700" }}>{v.po_number}</Text>
                <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>
                  {pName(v.project_id)} · {vName(v.vendor_id)}
                </Text>
                <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>
                  {v.short_lines} of {v.line_count} line(s) short · Date {v.date}
                </Text>
              </View>
              <Pill status={v.status === "issued" ? "sent_to_purchase" : v.status} />
            </View>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
              <VStat label="Ordered" v={v.value_ordered} />
              <VStat label="Received" v={v.value_received} />
              <VStat label="Variance" v={v.variance} tone={v.variance !== 0 ? "warn" : "ok"} />
              <VStat label="Invoiced" v={v.invoice_total} />
              <VStat label="Inv. Var" v={v.invoice_variance} tone={Math.abs(v.invoice_variance) > 0.5 ? "warn" : "ok"} />
            </View>
          </Card>
        )) : <Empty msg="No POs to compare yet." testID="variance-empty" />}

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

function VStat({ label, v, tone }: { label: string; v: number; tone?: "warn" | "ok" }) {
  const fmt = new Intl.NumberFormat("en-IN").format(Math.round(v || 0));
  const color = tone === "warn" ? theme.colors.danger : tone === "ok" ? theme.colors.success : theme.colors.text;
  return (
    <View style={{ minWidth: 70, flex: 1, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 4, padding: 6 }}>
      <Text style={{ fontSize: 9, color: theme.colors.textMuted, textTransform: "uppercase", letterSpacing: 1 }}>{label}</Text>
      <Text style={{ fontSize: 12, fontWeight: "700", marginTop: 2, color }}>₹ {fmt}</Text>
    </View>
  );
}
const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 8, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
});
