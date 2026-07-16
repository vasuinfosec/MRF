import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, RefreshControl, ScrollView, TouchableOpacity } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { theme } from "@/src/theme";
import { AppShell } from "@/src/components/AppShell";
import { Btn, Card, H1, H2, Muted, Stat, Loader, Label, Body, Row } from "@/src/components/ui";

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [stats, setStats] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const s = await api("/reports/dashboard");
      setStats(s);
    } catch (_e) { /* noop */ }
    setBusy(false);
  }, []);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => { if (user) load(); }, [user, load]);

  if (!user) return null;

  const role = user.role;

  return (
    <AppShell title="Vasu Infosec" testID="home-screen">
      <View>
        <H1>Welcome, {user.name.split(" ")[0]}</H1>
        <Muted>{roleWelcome(role)}</Muted>
      </View>

      {!stats && busy ? <Loader /> : null}

      {stats ? (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 12, marginTop: 16 }}>
          <Stat testID="stat-total-mrf" label="Total MRFs" value={stats.total_mrf} />
          <Stat testID="stat-pending-pm" label="Pending PM" value={stats.pending_pm} tone="action" />
          <Stat testID="stat-pending-purchase" label="Pending Purchase" value={stats.pending_purchase} />
          <Stat testID="stat-total-po" label="Purchase Orders" value={stats.total_po} tone="success" />
          <Stat testID="stat-pending-billing" label="Pending Billing" value={stats.pending_billing_count} tone="action" />
          <Stat testID="stat-po-value" label="PO Value (₹)" value={fmt(stats.po_value)} />
        </View>
      ) : null}

      {stats?.ageing ? (
        <Card style={{ marginTop: 16 }} testID="ageing-card">
          <H2>MRF Ageing</H2>
          <Row style={{ marginTop: 12, gap: 8 }}>
            {Object.entries(stats.ageing).map(([k, v]) => (
              <View key={k} style={styles.age}>
                <Text style={styles.ageVal}>{v as any}</Text>
                <Text style={styles.ageLabel}>{k} days</Text>
              </View>
            ))}
          </Row>
        </Card>
      ) : null}

      <Card style={{ marginTop: 16 }} testID="quick-actions">
        <H2>Quick Actions</H2>
        <View style={{ marginTop: 12, gap: 8 }}>
          {(role === "site_engineer" || role === "pm" || role === "director" || role === "admin") ? (
            <Btn testID="quick-create-mrf" title="+ Create New MRF" variant="action" onPress={() => router.push("/mrf/create")} />
          ) : null}
          <Btn testID="quick-view-mrf" title="View MRF List" variant="outline" onPress={() => router.push("/mrf")} />
          {(role === "pm" || role === "gm" || role === "director" || role === "admin") ? (
            <Btn testID="quick-approvals" title="Pending Authorisations" variant="primary" onPress={() => router.push("/mrf?status=pm_review")} />
          ) : null}
          {(role === "purchase" || role === "director" || role === "admin") ? (
            <Btn testID="quick-po-create" title="Create Purchase Order" variant="primary" onPress={() => router.push("/po/create")} />
          ) : null}
          {(role === "gm" || role === "director" || role === "admin") ? (
            <Btn testID="quick-po-approvals" title="POs Awaiting My Approval" variant="primary" onPress={() => router.push("/po?filter=pending_approval")} />
          ) : null}
          {(role === "purchase" || role === "gm" || role === "director" || role === "admin") ? (
            <Btn testID="quick-billing" title="Billing Dashboard" variant="primary" onPress={() => router.push("/billing")} />
          ) : null}
          <Btn testID="quick-reports" title="Reports" variant="outline" onPress={() => router.push("/reports")} />
          <Btn testID="quick-grn" title="Goods Received Notes" variant="outline" onPress={() => router.push("/grn")} />
          <Btn testID="quick-dc" title="Delivery Challans" variant="outline" onPress={() => router.push("/dc")} />
          <Btn testID="quick-cs" title="Comparative Statements" variant="outline" onPress={() => router.push("/comparative-statement")} />
        </View>
      </Card>

      <Card style={{ marginTop: 16, backgroundColor: theme.colors.surface }} testID="role-info-card">
        <Label>YOUR ROLE ACCESS</Label>
        <Body style={{ marginTop: 6 }}>{roleAccess(role)}</Body>
      </Card>
    </AppShell>
  );
}

function roleWelcome(role: string) {
  return ({
    director: "Full override authority · approve high-value POs · edit thresholds.",
    pm: "Review site engineer MRFs · authorise · assign purchase.",
    gm: "Approve mid-value POs · authorise MRFs · portfolio oversight.",
    purchase: "Issue POs · manage vendors · record invoices · low-value POs auto-issued.",
    admin: "Manage users, projects, masters and thresholds. No approval authority.",
    site_engineer: "Draft & submit MRFs for your project · record goods received.",
    store: "Record goods received at your site.",
  } as Record<string, string>)[role] || "";
}

function roleAccess(role: string) {
  return ({
    director: "All permissions · Approve POs > Director threshold · Edit thresholds · Full audit",
    pm: "Authorise MRFs on your projects · Track project material · Escalate to purchase",
    gm: "Approve POs > GM threshold · Authorise MRFs · Portfolio reports",
    purchase: "Issue POs (auto below GM threshold) · Manage vendors · Record invoices & receipts",
    admin: "Users · Projects · Vendors · Materials · Thresholds · No MRF/PO approval authority",
    site_engineer: "Create Draft MRF · Submit for PM review · Record GRN on your site",
    store: "Record GRN at your site · View site MRFs/POs (read-only)",
  } as Record<string, string>)[role] || "";
}

function fmt(n: number) {
  return new Intl.NumberFormat("en-IN").format(Math.round(n));
}

const styles = StyleSheet.create({
  age: { flex: 1, minWidth: 70, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 6, padding: 10, alignItems: "center" },
  ageVal: { fontSize: 22, fontWeight: "800", color: theme.colors.primary },
  ageLabel: { fontSize: 10, textTransform: "uppercase", color: theme.colors.textMuted, marginTop: 2, letterSpacing: 1 },
});
