/**
 * Task 4 — UOM Master & Conversion Rules (Admin/Director only)
 *
 * Two panels:
 *   1. Units of Measure — CRUD, base flag, kind (length/mass/count/…)
 *   2. Conversion Rules — from/to/factor + live "try it" convert widget
 *
 * CSV import + template download available for both panels.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity, TextInput,
  RefreshControl, Alert, Platform,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { AppShell } from "@/src/components/AppShell";
import { api, backendUrl, getDownloadToken } from "@/src/api";
import { useAccessGuard } from "@/src/hooks/useAccessGuard";
import { Card, H2, Btn, Label, Muted, Empty, Loader } from "@/src/components/ui";
import { theme } from "@/src/theme";

type Unit = { item_id: string; name: string; symbol?: string; kind?: string; is_base?: boolean; active: boolean };
type Conv = { conv_id: string; from_uom: string; to_uom: string; factor: number; notes?: string; created_by_name?: string };

export default function UomAdminScreen() {
  const { permitted, loading } = useAccessGuard();
  const router = useRouter();
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<"units" | "conversions">("units");
  const [units, setUnits] = useState<Unit[]>([]);
  const [convs, setConvs] = useState<Conv[]>([]);
  const [err, setErr] = useState<string | null>(null);

  // Add-unit form
  const [uf, setUf] = useState({ name: "", symbol: "", kind: "count", is_base: false });
  // Add-conversion form
  const [cf, setCf] = useState({ from_uom: "", to_uom: "", factor: "", notes: "" });
  // Convert-widget
  const [cw, setCw] = useState({ qty: "1", from_uom: "", to_uom: "", result: "" });

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [us, cs] = await Promise.all([
        api<Unit[]>("/uom/units").catch(() => []),
        api<Conv[]>("/uom/conversions").catch(() => []),
      ]);
      setUnits(us || []); setConvs(cs || []);
    } catch (e: any) { setErr(e?.message || "Failed to load"); }
  }, []);

  useEffect(() => { if (permitted) load(); }, [permitted, load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const addUnit = async () => {
    if (!uf.name.trim()) { setErr("Unit name required"); return; }
    try {
      await api("/uom/units", { method: "POST", body: { ...uf, name: uf.name.trim() } });
      setUf({ name: "", symbol: "", kind: "count", is_base: false });
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const deleteUnit = (u: Unit) => {
    const doIt = async () => {
      try {
        await api(`/uom/units/${u.item_id}?reason=${encodeURIComponent("Removed via Admin")}`, { method: "DELETE" });
        load();
      } catch (e: any) { setErr(e.message); }
    };
    if (Platform.OS === "web") { if (window.confirm(`Deactivate unit "${u.name}"?`)) doIt(); }
    else Alert.alert("Deactivate unit", `Remove "${u.name}"?`,
      [{ text: "Cancel" }, { text: "Deactivate", style: "destructive", onPress: doIt }]);
  };

  const addConv = async () => {
    if (!cf.from_uom || !cf.to_uom || !cf.factor) { setErr("From, To and Factor are required"); return; }
    try {
      await api("/uom/conversions", { method: "POST", body: {
        from_uom: cf.from_uom.trim(), to_uom: cf.to_uom.trim(),
        factor: Number(cf.factor), notes: cf.notes.trim(),
      } });
      setCf({ from_uom: "", to_uom: "", factor: "", notes: "" });
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const deleteConv = (c: Conv) => {
    const doIt = async () => {
      try {
        await api(`/uom/conversions/${c.conv_id}?reason=${encodeURIComponent("Removed via Admin")}`, { method: "DELETE" });
        load();
      } catch (e: any) { setErr(e.message); }
    };
    if (Platform.OS === "web") { if (window.confirm(`Remove ${c.from_uom} → ${c.to_uom}?`)) doIt(); }
    else Alert.alert("Remove rule", `Remove ${c.from_uom} → ${c.to_uom}?`,
      [{ text: "Cancel" }, { text: "Remove", style: "destructive", onPress: doIt }]);
  };

  const runConvert = async () => {
    setCw((s) => ({ ...s, result: "..." }));
    try {
      const r = await api<{ qty_out: number; factor: number }>(
        "/uom/convert",
        { method: "POST", body: { qty: Number(cw.qty), from_uom: cw.from_uom.trim(), to_uom: cw.to_uom.trim() } }
      );
      setCw((s) => ({ ...s, result: `${r.qty_out} ${cw.to_uom} (× ${r.factor})` }));
    } catch (e: any) { setCw((s) => ({ ...s, result: `Error: ${e.message}` })); }
  };

  // CSV Template download using short-lived token (works on web; native fallback = clipboard)
  const downloadTemplate = async (kind: "units" | "conversions") => {
    const path = kind === "units" ? "/uom/units/template.csv" : "/uom/conversions/template.csv";
    if (Platform.OS === "web") {
      const t = await getDownloadToken();
      if (!t) { setErr("Could not mint download token"); return; }
      window.open(`${backendUrl}/api${path}?token=${encodeURIComponent(t)}`, "_blank");
    } else {
      Alert.alert("Template", "CSV templates are available on the web dashboard.");
    }
  };

  // CSV import via file input on web
  const importCsv = async (kind: "units" | "conversions") => {
    if (Platform.OS !== "web") {
      Alert.alert("Import", "CSV import is available on the web dashboard for now.");
      return;
    }
    const input = document.createElement("input");
    input.type = "file"; input.accept = ".csv,text/csv";
    input.onchange = async (ev: any) => {
      const file = ev.target?.files?.[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      try {
        const tok = (await import("@/src/api")).getToken ? await (await import("@/src/api")).getToken() : null;
        const r = await fetch(`${backendUrl}/api/uom/${kind}/import`, {
          method: "POST",
          headers: tok ? { Authorization: `Bearer ${tok}` } : undefined,
          body: fd,
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
        const s = j.summary || {};
        Alert.alert("Import complete",
          `Created: ${s.created || 0}\nDuplicates: ${s.duplicates || 0}\nErrors: ${s.errors || 0}`);
        load();
      } catch (e: any) {
        setErr(e.message || "Import failed");
      }
    };
    input.click();
  };

  if (loading || !permitted) return <AppShell title="UOM & Conversions"><Loader /></AppShell>;

  return (
    <AppShell title="UOM & Conversions" testID="uom-admin">
      <ScrollView
        contentContainerStyle={{ padding: 16, paddingBottom: 100 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        <Muted>Task 4 — Units of Measure & conversion rules used by MRF, PO and Stock modules.</Muted>

        {/* Tabs */}
        <View style={styles.tabRow}>
          {(["units", "conversions"] as const).map((k) => (
            <TouchableOpacity key={k} testID={`tab-${k}`} onPress={() => setTab(k)}
              style={[styles.tab, {
                borderColor: tab === k ? theme.colors.primary : theme.colors.border,
                backgroundColor: tab === k ? theme.colors.primary : "#fff",
              }]}>
              <Text style={{ color: tab === k ? "#fff" : theme.colors.text, fontWeight: "700" }}>
                {k === "units" ? "Units" : "Conversion Rules"}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {err ? <Text style={{ color: theme.colors.danger, marginTop: 10 }}>{err}</Text> : null}

        {tab === "units" ? (
          <>
            <Card style={{ marginTop: 12 }} testID="unit-add-card">
              <H2>Add Unit</H2>
              <Label>NAME</Label>
              <TextInput testID="u-name" value={uf.name} onChangeText={(v) => setUf({ ...uf, name: v })}
                placeholder="e.g. Metre / Nos / Kilogram" style={styles.inp} />
              <View style={{ height: 8 }} />
              <Label>SYMBOL</Label>
              <TextInput testID="u-symbol" value={uf.symbol} onChangeText={(v) => setUf({ ...uf, symbol: v })}
                placeholder="e.g. m, kg, Nos" style={styles.inp} />
              <View style={{ height: 8 }} />
              <Label>KIND</Label>
              <View style={styles.chipRow}>
                {["count", "length", "mass", "volume", "area", "time"].map((k) => {
                  const active = uf.kind === k;
                  return (
                    <TouchableOpacity key={k} onPress={() => setUf({ ...uf, kind: k })}
                      style={[styles.chip, { borderColor: active ? theme.colors.primary : theme.colors.border, backgroundColor: active ? theme.colors.primary : "#fff" }]}>
                      <Text style={{ color: active ? "#fff" : theme.colors.text, fontSize: 12, fontWeight: "600" }}>{k}</Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
              <TouchableOpacity onPress={() => setUf({ ...uf, is_base: !uf.is_base })}
                style={{ flexDirection: "row", alignItems: "center", marginTop: 12 }}>
                <Ionicons name={uf.is_base ? "checkbox" : "square-outline"} size={20} color={theme.colors.primary} />
                <Text style={{ marginLeft: 8, color: theme.colors.text }}>Mark as base unit (for its kind)</Text>
              </TouchableOpacity>
              <View style={{ height: 12 }} />
              <View style={{ flexDirection: "row", gap: 8 }}>
                <Btn testID="u-add" title="Add unit" onPress={addUnit} />
                <Btn variant="outline" title="Template CSV" icon={<Ionicons name="download-outline" size={16} color={theme.colors.text} />} onPress={() => downloadTemplate("units")} />
                <Btn variant="outline" title="Import CSV" icon={<Ionicons name="cloud-upload-outline" size={16} color={theme.colors.text} />} onPress={() => importCsv("units")} />
              </View>
            </Card>

            <Card style={{ marginTop: 12 }} testID="unit-list-card">
              <H2>All units ({units.length})</H2>
              {units.length === 0 ? <Empty msg="No units yet — add one above or import a CSV." /> :
                units.map((u) => (
                  <View key={u.item_id} style={styles.row}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.rowTitle}>{u.name} <Text style={{ color: theme.colors.textMuted, fontWeight: "400" }}>({u.symbol})</Text></Text>
                      <Text style={styles.rowSub}>{u.kind}{u.is_base ? " · base" : ""}</Text>
                    </View>
                    <TouchableOpacity onPress={() => deleteUnit(u)} style={{ padding: 8 }}>
                      <Ionicons name="trash-outline" size={20} color={theme.colors.danger} />
                    </TouchableOpacity>
                  </View>
                ))}
            </Card>
          </>
        ) : (
          <>
            {/* Live convert */}
            <Card style={{ marginTop: 12 }} testID="convert-card">
              <H2>Quick convert</H2>
              <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
                <TextInput testID="cw-qty" value={cw.qty} onChangeText={(v) => setCw({ ...cw, qty: v })}
                  keyboardType="decimal-pad" placeholder="qty" style={[styles.inp, { flex: 1 }]} />
                <TextInput testID="cw-from" value={cw.from_uom} onChangeText={(v) => setCw({ ...cw, from_uom: v })}
                  placeholder="from (e.g. Metre)" style={[styles.inp, { flex: 1.5 }]} />
                <TextInput testID="cw-to" value={cw.to_uom} onChangeText={(v) => setCw({ ...cw, to_uom: v })}
                  placeholder="to (e.g. Centimetre)" style={[styles.inp, { flex: 1.5 }]} />
              </View>
              <View style={{ height: 8 }} />
              <Btn testID="cw-go" title="Convert" onPress={runConvert} />
              {cw.result ? <Text style={{ marginTop: 8, fontWeight: "600" }}>{cw.result}</Text> : null}
            </Card>

            {/* Add rule */}
            <Card style={{ marginTop: 12 }} testID="conv-add-card">
              <H2>Add conversion rule</H2>
              <Label>1 × FROM_UOM = FACTOR × TO_UOM</Label>
              <View style={{ flexDirection: "row", gap: 8 }}>
                <TextInput testID="cf-from" value={cf.from_uom} onChangeText={(v) => setCf({ ...cf, from_uom: v })}
                  placeholder="from (e.g. Metre)" style={[styles.inp, { flex: 1 }]} />
                <TextInput testID="cf-to" value={cf.to_uom} onChangeText={(v) => setCf({ ...cf, to_uom: v })}
                  placeholder="to (e.g. Centimetre)" style={[styles.inp, { flex: 1 }]} />
                <TextInput testID="cf-factor" value={cf.factor} onChangeText={(v) => setCf({ ...cf, factor: v })}
                  keyboardType="decimal-pad" placeholder="factor" style={[styles.inp, { flex: 0.8 }]} />
              </View>
              <View style={{ height: 8 }} />
              <TextInput testID="cf-notes" value={cf.notes} onChangeText={(v) => setCf({ ...cf, notes: v })}
                placeholder="Notes (optional)" style={styles.inp} />
              <View style={{ height: 12 }} />
              <View style={{ flexDirection: "row", gap: 8 }}>
                <Btn testID="cf-add" title="Add rule" onPress={addConv} />
                <Btn variant="outline" title="Template CSV" icon={<Ionicons name="download-outline" size={16} color={theme.colors.text} />} onPress={() => downloadTemplate("conversions")} />
                <Btn variant="outline" title="Import CSV" icon={<Ionicons name="cloud-upload-outline" size={16} color={theme.colors.text} />} onPress={() => importCsv("conversions")} />
              </View>
            </Card>

            <Card style={{ marginTop: 12 }} testID="conv-list-card">
              <H2>All rules ({convs.length})</H2>
              {convs.length === 0 ? <Empty msg="No conversion rules yet." /> :
                convs.map((c) => (
                  <View key={c.conv_id} style={styles.row}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.rowTitle}>1 {c.from_uom} = {c.factor} {c.to_uom}</Text>
                      {c.notes ? <Text style={styles.rowSub}>{c.notes}</Text> : null}
                    </View>
                    <TouchableOpacity onPress={() => deleteConv(c)} style={{ padding: 8 }}>
                      <Ionicons name="trash-outline" size={20} color={theme.colors.danger} />
                    </TouchableOpacity>
                  </View>
                ))}
            </Card>
          </>
        )}

        <View style={{ height: 20 }} />
        <Btn variant="ghost" title="Back to Masters" onPress={() => router.push("/masters")}
          icon={<Ionicons name="arrow-back" size={16} color={theme.colors.text} />} />
      </ScrollView>
    </AppShell>
  );
}

const styles = StyleSheet.create({
  tabRow: { flexDirection: "row", gap: 8, marginTop: 16, flexWrap: "wrap" },
  tab: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, borderWidth: 1 },
  chipRow: { flexDirection: "row", gap: 6, flexWrap: "wrap", marginTop: 4 },
  chip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1 },
  inp: {
    borderWidth: 1, borderColor: theme.colors.borderStrong,
    borderRadius: theme.radius.md, paddingHorizontal: 12, paddingVertical: 10,
    fontSize: 14, backgroundColor: "#fff", color: theme.colors.text,
  },
  row: {
    flexDirection: "row", alignItems: "center",
    borderBottomWidth: 1, borderBottomColor: theme.colors.border,
    paddingVertical: 10,
  },
  rowTitle: { fontWeight: "600", color: theme.colors.text, fontSize: 14 },
  rowSub: { color: theme.colors.textMuted, fontSize: 12, marginTop: 2 },
});
