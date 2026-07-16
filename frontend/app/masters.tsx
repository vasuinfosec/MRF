import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, H1, H2, Label, Muted, Empty } from "@/src/components/ui";
import { theme } from "@/src/theme";

type Tab = "projects" | "vendors" | "units" | "brands" | "materials";
const TABS: { key: Tab; label: string }[] = [
  { key: "projects", label: "Projects" },
  { key: "vendors", label: "Vendors" },
  { key: "units", label: "Units" },
  { key: "brands", label: "Brands" },
  { key: "materials", label: "Materials" },
];

export default function Masters() {
  const router = useRouter();
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("projects");
  const [projects, setProjects] = useState<any[]>([]);
  const [vendors, setVendors] = useState<any[]>([]);
  const [masters, setMasters] = useState<any>({ unit: [], brand: [], material: [] });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  // Forms
  const [pf, setPf] = useState({ code: "", name: "", site: "", client: "" });
  const [vf, setVf] = useState({ name: "", address: "", gstin: "", contact: "", email: "" });
  const [mf, setMf] = useState("");

  const isAdmin = user?.role === "admin";
  const canVendor = isAdmin || user?.role === "purchase";

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [p, v, m] = await Promise.all([
        api<any[]>(isAdmin ? "/projects?all=1" : "/projects"),
        api<any[]>("/vendors"),
        api<any>("/masters"),
      ]);
      setProjects(p); setVendors(v); setMasters(m);
    } catch (_e) { /* noop */ }
    setBusy(false);
  }, [isAdmin]);

  useEffect(() => { if (user) load(); }, [user, load]);

  const addProject = async () => {
    setErr("");
    if (!pf.code.trim() || !pf.name.trim() || !pf.site.trim()) { setErr("Code, Name, Site are required."); return; }
    try {
      await api("/projects", { method: "POST", body: {
        code: pf.code.trim(), name: pf.name.trim(), site: pf.site.trim(),
        client: pf.client.trim(),
      } });
      setPf({ code: "", name: "", site: "", client: "" });
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const addVendor = async () => {
    setErr("");
    if (!vf.name.trim()) { setErr("Vendor name required."); return; }
    try {
      await api("/vendors", { method: "POST", body: {
        name: vf.name.trim(), address: vf.address.trim(),
        gstin: vf.gstin.trim(), contact: vf.contact.trim(), email: vf.email.trim(),
      } });
      setVf({ name: "", address: "", gstin: "", contact: "", email: "" });
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const addMaster = async (category: "unit" | "brand" | "material") => {
    setErr("");
    if (!mf.trim()) { setErr("Name required."); return; }
    try {
      await api("/masters", { method: "POST", body: { name: mf.trim(), category } });
      setMf("");
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const currentMasterKey: "unit" | "brand" | "material" | null =
    tab === "units" ? "unit" : tab === "brands" ? "brand" : tab === "materials" ? "material" : null;
  const currentMasterList = currentMasterKey ? (masters[currentMasterKey] || []) : [];

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity testID="back-btn" onPress={() => router.back()} style={{ padding: 8 }}>
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Master Data</Text>
        <View style={{ width: 38 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 80 }}>
        <H1>Masters</H1>
        <Muted>Create and manage projects, vendors, units, brands and materials.</Muted>

        {/* Tab bar */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chipRow} style={{ marginTop: 14, marginHorizontal: -16, paddingHorizontal: 16 }}>
          {TABS.map((t) => {
            const active = tab === t.key;
            return (
              <TouchableOpacity key={t.key} testID={`mtab-${t.key}`} onPress={() => setTab(t.key)}
                style={[styles.chip, {
                  borderColor: active ? theme.colors.primary : theme.colors.border,
                  backgroundColor: active ? theme.colors.primary : "#fff",
                }]}>
                <Text style={{ color: active ? "#fff" : theme.colors.text, fontSize: 12, fontWeight: "600" }}>{t.label}</Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>

        {err ? <Text testID="masters-err" style={{ color: theme.colors.danger, marginTop: 10 }}>{err}</Text> : null}

        {/* PROJECTS */}
        {tab === "projects" ? (
          <>
            {isAdmin ? (
              <Card style={{ marginTop: 14 }} testID="add-project-card">
                <H2>Add New Project</H2>
                <View style={{ marginTop: 10 }}>
                  <Label>PROJECT CODE</Label>
                  <TextInput testID="proj-code" value={pf.code} onChangeText={(v) => setPf({ ...pf, code: v })} placeholder="e.g. VIS-104" style={styles.inp} />
                  <View style={{ height: 10 }} />
                  <Label>PROJECT NAME</Label>
                  <TextInput testID="proj-name" value={pf.name} onChangeText={(v) => setPf({ ...pf, name: v })} placeholder="e.g. LMN Data Center Fire System" style={styles.inp} />
                  <View style={{ height: 10 }} />
                  <Label>DEFAULT SITE</Label>
                  <TextInput testID="proj-site" value={pf.site} onChangeText={(v) => setPf({ ...pf, site: v })} placeholder="e.g. Pune Hinjewadi" style={styles.inp} />
                  <View style={{ height: 10 }} />
                  <Label>CLIENT (OPTIONAL)</Label>
                  <TextInput testID="proj-client" value={pf.client} onChangeText={(v) => setPf({ ...pf, client: v })} placeholder="e.g. LMN Corp" style={styles.inp} />
                  <Btn testID="add-project-btn" title="+ Add Project" variant="action" onPress={addProject} style={{ marginTop: 12 }} />
                </View>
              </Card>
            ) : null}

            <H2 style={{ marginTop: 20 }}>All Projects ({projects.length})</H2>
            {projects.map((p) => (
              <Card key={p.project_id} style={{ marginTop: 8 }} testID={`p-${p.code}`}>
                <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontWeight: "700", color: theme.colors.primary }}>{p.code}</Text>
                    <Text style={{ marginTop: 2 }}>{p.name}</Text>
                    <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>{p.site}{p.client ? ` · ${p.client}` : ""}</Text>
                    <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>
                      {(p.site_engineers || []).length} engineer(s) · {(p.project_managers || []).length} PM(s) · {(p.sites || []).filter((s: any) => s.active !== false).length} sub-site(s)
                    </Text>
                  </View>
                </View>
              </Card>
            ))}
            {!projects.length ? <Empty msg="No projects yet." testID="p-empty" /> : null}
            <Muted style={{ marginTop: 10 }}>Manage sub-sites and team assignments from More → Projects.</Muted>
          </>
        ) : null}

        {/* VENDORS */}
        {tab === "vendors" ? (
          <>
            {canVendor ? (
              <Card style={{ marginTop: 14 }} testID="add-vendor-card">
                <H2>Add New Vendor</H2>
                <View style={{ marginTop: 10 }}>
                  <Label>VENDOR NAME</Label>
                  <TextInput testID="vend-name" value={vf.name} onChangeText={(v) => setVf({ ...vf, name: v })} placeholder="e.g. Legrand India" style={styles.inp} />
                  <View style={{ height: 10 }} />
                  <Label>ADDRESS</Label>
                  <TextInput testID="vend-addr" value={vf.address} onChangeText={(v) => setVf({ ...vf, address: v })} style={styles.inp} multiline />
                  <View style={{ height: 10 }} />
                  <Label>GSTIN</Label>
                  <TextInput testID="vend-gstin" value={vf.gstin} onChangeText={(v) => setVf({ ...vf, gstin: v })} placeholder="e.g. 27AAACL1234A1Z5" style={styles.inp} />
                  <View style={{ height: 10 }} />
                  <Label>CONTACT</Label>
                  <TextInput testID="vend-contact" value={vf.contact} onChangeText={(v) => setVf({ ...vf, contact: v })} keyboardType="phone-pad" style={styles.inp} />
                  <View style={{ height: 10 }} />
                  <Label>EMAIL</Label>
                  <TextInput testID="vend-email" value={vf.email} onChangeText={(v) => setVf({ ...vf, email: v })} keyboardType="email-address" autoCapitalize="none" style={styles.inp} />
                  <Btn testID="add-vendor-btn" title="+ Add Vendor" variant="action" onPress={addVendor} style={{ marginTop: 12 }} />
                </View>
              </Card>
            ) : null}

            <H2 style={{ marginTop: 20 }}>All Vendors ({vendors.length})</H2>
            {vendors.map((v) => (
              <Card key={v.vendor_id} style={{ marginTop: 8 }} testID={`v-${v.vendor_id}`}>
                <Text style={{ fontWeight: "700" }}>{v.name}</Text>
                <Text style={{ fontSize: 12, color: theme.colors.textMuted, marginTop: 2 }}>{v.gstin}</Text>
                {v.address ? <Text style={{ fontSize: 12, color: theme.colors.textMuted }}>{v.address}</Text> : null}
                {v.contact ? <Text style={{ fontSize: 12, color: theme.colors.textMuted }}>{v.contact}{v.email ? ` · ${v.email}` : ""}</Text> : null}
              </Card>
            ))}
            {!vendors.length ? <Empty msg="No vendors yet." testID="v-empty" /> : null}
          </>
        ) : null}

        {/* UNITS / BRANDS / MATERIALS */}
        {currentMasterKey ? (
          <>
            {isAdmin ? (
              <Card style={{ marginTop: 14 }} testID={`add-${currentMasterKey}-card`}>
                <H2>Add {TABS.find((t) => t.key === tab)?.label.slice(0, -1)}</H2>
                <View style={{ flexDirection: "row", gap: 8, marginTop: 10, alignItems: "flex-end" }}>
                  <View style={{ flex: 1 }}>
                    <Label>NAME</Label>
                    <TextInput testID={`m-input-${currentMasterKey}`} value={mf} onChangeText={setMf}
                      placeholder={
                        currentMasterKey === "unit" ? "e.g. Meter, Kg, Box" :
                        currentMasterKey === "brand" ? "e.g. Legrand, Schneider" :
                        "e.g. Emergency Light 3W"
                      }
                      style={styles.inp} />
                  </View>
                  <Btn testID={`m-add-${currentMasterKey}`} title="+ Add" variant="action" onPress={() => addMaster(currentMasterKey)} />
                </View>
              </Card>
            ) : null}

            <H2 style={{ marginTop: 20 }}>{TABS.find((t) => t.key === tab)?.label} ({currentMasterList.length})</H2>
            <Card style={{ marginTop: 8 }}>
              {currentMasterList.length ? currentMasterList.map((it: any, i: number) => (
                <View key={it.item_id || i} style={styles.masterRow} testID={`m-item-${it.name}`}>
                  <Text style={{ flex: 1, fontWeight: "500" }}>{it.name}</Text>
                </View>
              )) : <Muted>None yet.</Muted>}
            </Card>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 8, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  chipRow: { gap: 8, paddingRight: 16 },
  chip: { flexShrink: 0, height: 36, paddingHorizontal: 14, borderRadius: 999, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  inp: { borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, paddingHorizontal: 10, minHeight: 44, backgroundColor: "#fff", fontSize: 14, color: theme.colors.text },
  masterRow: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
});
