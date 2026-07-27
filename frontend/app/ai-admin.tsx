import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
  TouchableOpacity,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Card, H1, H2, Label, Muted } from "@/src/components/ui";
import { theme } from "@/src/theme";
import { useAuth } from "@/src/auth";

type SpendResp = {
  period_start_this_month: string;
  grand_total_inr_this_month: number;
  period_range: { month: string; spent_inr: number; calls: number }[];
  by_user: {
    user_id: string;
    name: string;
    role: string;
    spent_inr_this_month: number;
    limit_inr: number | null;
    unlimited: boolean;
    remaining_inr: number | null;
    calls_this_month: number;
  }[];
  by_model: { model: string; spent_inr: number; calls: number }[];
  budget_config: Record<string, number | null>;
  premium_allowed_roles: string[];
};

type SupplierRow = {
  vendor_id: string;
  vendor_name: string;
  total_orders: number;
  completed_orders: number;
  open_orders: number;
  total_ordered_value_inr: number;
  total_grns: number;
  rejected_grns: number;
  on_time_pct: number | null;
  avg_delay_days: number;
  last_order_date: string | null;
};

export default function AiAdminScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const canView = user?.role === "admin" || user?.role === "director";
  const [tab, setTab] = useState<"spend" | "suppliers">("spend");
  const [spend, setSpend] = useState<SpendResp | null>(null);
  const [suppliers, setSuppliers] = useState<SupplierRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const [s, sp] = await Promise.all([
        api<SpendResp>("/llm/admin/spend-monthly?months=6"),
        api<SupplierRow[]>("/llm/admin/supplier-performance?limit=100"),
      ]);
      setSpend(s);
      setSuppliers(sp);
    } catch (e: any) {
      setErr(e?.message || "Failed to load");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (canView) load();
  }, [canView, load]);

  if (!canView) {
    return (
      <SafeAreaView style={{ flex: 1, padding: 16 }}>
        <Muted>Admin or Director role required.</Muted>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }} testID="ai-admin-back">
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>AI Spend & Supplier Performance</Text>
        <View style={{ width: 38 }} />
      </View>

      <View style={styles.tabs}>
        <TouchableOpacity
          onPress={() => setTab("spend")}
          style={[styles.tab, tab === "spend" ? styles.tabActive : null]}
          testID="ai-admin-tab-spend"
        >
          <Ionicons name="cash-outline" size={14} color={tab === "spend" ? "#fff" : theme.colors.text} />
          <Text style={[styles.tabText, tab === "spend" ? styles.tabTextActive : null]}>
            Monthly AI Spend
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={() => setTab("suppliers")}
          style={[styles.tab, tab === "suppliers" ? styles.tabActive : null]}
          testID="ai-admin-tab-suppliers"
        >
          <Ionicons name="business-outline" size={14} color={tab === "suppliers" ? "#fff" : theme.colors.text} />
          <Text style={[styles.tabText, tab === "suppliers" ? styles.tabTextActive : null]}>
            Supplier Performance
          </Text>
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
        {loading ? <ActivityIndicator /> : null}
        {err ? <Text style={styles.err}>{err}</Text> : null}

        {!loading && tab === "spend" && spend ? (
          <View>
            <H1>AI Spend — {spend.period_start_this_month}</H1>
            <Muted>Wallet spent this calendar month across every user.</Muted>

            <Card style={{ marginTop: 12, backgroundColor: "#EEF2FF" }}>
              <Label>THIS MONTH GRAND TOTAL</Label>
              <Text style={styles.bigNum}>₹ {spend.grand_total_inr_this_month.toFixed(2)}</Text>
              <Muted>
                Non-director role cap: ₹200 / month · Director: unlimited · Premium (Sonnet 4.5) allowed only for {spend.premium_allowed_roles.join(", ")}.
              </Muted>
            </Card>

            <H2 style={{ marginTop: 16 }}>By user (this month)</H2>
            {spend.by_user.length === 0 ? (
              <Muted>No LLM spend yet this month.</Muted>
            ) : null}
            {spend.by_user.map((u) => {
              const pct =
                u.unlimited || !u.limit_inr
                  ? 0
                  : Math.min(100, (u.spent_inr_this_month / u.limit_inr) * 100);
              return (
                <Card key={u.user_id} style={{ marginTop: 8 }}>
                  <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                    <View style={{ flex: 1 }}>
                      <Text style={{ fontWeight: "700" }}>{u.name}</Text>
                      <Muted>
                        {u.role.toUpperCase()} · {u.calls_this_month} call(s)
                      </Muted>
                    </View>
                    <View style={{ alignItems: "flex-end" }}>
                      <Text style={{ fontWeight: "800", fontSize: 16 }}>
                        ₹ {u.spent_inr_this_month.toFixed(2)}
                      </Text>
                      <Muted>
                        {u.unlimited
                          ? "unlimited"
                          : `of ₹${u.limit_inr} · ₹${u.remaining_inr?.toFixed(2)} left`}
                      </Muted>
                    </View>
                  </View>
                  {!u.unlimited && u.limit_inr ? (
                    <View style={styles.barTrack}>
                      <View
                        style={[
                          styles.barFill,
                          {
                            width: `${pct}%`,
                            backgroundColor:
                              pct > 90 ? "#B91C1C" : pct > 70 ? "#B45309" : "#059669",
                          },
                        ]}
                      />
                    </View>
                  ) : null}
                </Card>
              );
            })}

            <H2 style={{ marginTop: 16 }}>By model (this month)</H2>
            {spend.by_model.map((m) => (
              <View key={m.model} style={styles.row}>
                <Text style={{ flex: 1, fontWeight: "700" }}>{m.model}</Text>
                <Text style={{ color: theme.colors.textMuted, marginRight: 12 }}>
                  {m.calls} call{m.calls === 1 ? "" : "s"}
                </Text>
                <Text style={{ fontWeight: "800" }}>₹ {m.spent_inr.toFixed(4)}</Text>
              </View>
            ))}

            <H2 style={{ marginTop: 16 }}>Trend — last 6 months</H2>
            {spend.period_range.map((p) => (
              <View key={p.month} style={styles.row}>
                <Text style={{ flex: 1 }}>{p.month}</Text>
                <Text style={{ color: theme.colors.textMuted, marginRight: 12 }}>{p.calls} calls</Text>
                <Text style={{ fontWeight: "700" }}>₹ {p.spent_inr.toFixed(2)}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {!loading && tab === "suppliers" ? (
          <View>
            <H1>Supplier Performance</H1>
            <Muted>Deterministic snapshot from POs and GRNs. No LLM cost, no complex scoring.</Muted>
            {suppliers.length === 0 ? <Muted style={{ marginTop: 12 }}>No supplier activity yet.</Muted> : null}
            {suppliers.map((s) => (
              <Card key={s.vendor_id} style={{ marginTop: 10 }}>
                <Text style={{ fontWeight: "800", fontSize: 14 }}>{s.vendor_name || s.vendor_id}</Text>
                <View style={styles.grid}>
                  <Metric label="Total POs" value={String(s.total_orders)} />
                  <Metric label="Completed" value={String(s.completed_orders)} />
                  <Metric label="Open" value={String(s.open_orders)} />
                  <Metric label="Rejected GRNs" value={String(s.rejected_grns)} />
                  <Metric
                    label="On-time %"
                    value={s.on_time_pct === null ? "—" : `${s.on_time_pct}%`}
                    color={s.on_time_pct === null ? undefined : s.on_time_pct >= 90 ? "#065F46" : s.on_time_pct >= 70 ? "#B45309" : "#B91C1C"}
                  />
                  <Metric label="Avg delay (d)" value={String(s.avg_delay_days)} />
                </View>
                <Muted style={{ marginTop: 6 }}>
                  Value ordered: ₹ {s.total_ordered_value_inr.toLocaleString("en-IN")} · Last order: {s.last_order_date || "—"}
                </Muted>
              </Card>
            ))}
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={styles.metricCell}>
      <Text style={[styles.metricValue, color ? { color } : null]}>{value}</Text>
      <Text style={styles.metricLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 4,
    paddingVertical: 8,
    backgroundColor: theme.colors.bg,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.border,
  },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  tabs: {
    flexDirection: "row",
    padding: 8,
    gap: 4,
    backgroundColor: theme.colors.bg,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.border,
  },
  tab: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  tabActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  tabText: { fontSize: 12, fontWeight: "700", color: theme.colors.text },
  tabTextActive: { color: "#fff" },
  bigNum: { fontSize: 28, fontWeight: "800", color: theme.colors.text, marginTop: 4 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: theme.colors.border,
  },
  barTrack: {
    marginTop: 8,
    height: 6,
    borderRadius: 3,
    backgroundColor: "#E5E7EB",
    overflow: "hidden",
  },
  barFill: { height: 6, borderRadius: 3 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 },
  metricCell: {
    minWidth: "31%",
    flexGrow: 1,
    backgroundColor: "#F7F8FC",
    padding: 6,
    borderRadius: 6,
    alignItems: "center",
  },
  metricValue: { fontSize: 15, fontWeight: "800", color: theme.colors.text },
  metricLabel: { fontSize: 10, color: theme.colors.textMuted, marginTop: 2 },
  err: {
    color: theme.colors.danger,
    backgroundColor: "#FEF2F2",
    padding: 8,
    borderRadius: 6,
    marginBottom: 8,
    fontSize: 12,
  },
});
