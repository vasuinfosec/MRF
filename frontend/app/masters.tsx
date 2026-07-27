import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput, Modal } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, H1, H2, Label, Muted, Empty } from "@/src/components/ui";
import { theme } from "@/src/theme";
import ProjectTeamModal from "@/src/components/ProjectTeamModal";

type Tab = "projects" | "vendors" | "sites" | "units" | "brands" | "materials" | "models" | "gst" | "departments" | "thresholds" | "audit";
const TABS: { key: Tab; label: string; roles?: string[] }[] = [
  { key: "projects", label: "Projects" },
  { key: "vendors", label: "Vendors" },
  { key: "sites", label: "Sites" },
  { key: "units", label: "Units" },
  { key: "brands", label: "Brands/Makes" },
  { key: "models", label: "Models" },
  { key: "materials", label: "Materials" },
  { key: "gst", label: "GST Rates" },
  { key: "departments", label: "Departments" },
  { key: "thresholds", label: "PO Thresholds", roles: ["director", "admin"] },
  { key: "audit", label: "Master Audit", roles: ["director", "admin"] },
];

// System category shorthand map
const SYSTEM_SHORT: Record<string, string> = {
  "Fire Alarm": "FAS",
  "Fire Fighting": "FFT",
  "Gas Suppression": "GSS",
  "Water Mist": "WM",
  "CCTV": "CCTV",
  "Access Control": "ACS",
  "Structured Cabling": "SC",
  "Electrical": "ELE",
  "Other": "OTH",
};

export default function Masters() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("projects");
  const [projects, setProjects] = useState<any[]>([]);
  const [vendors, setVendors] = useState<any[]>([]);
  const [masters, setMasters] = useState<any>({ unit: [], brand: [], material: [], model: [], gst: [], department: [] });
  const [systems, setSystems] = useState<string[]>([]);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [teamPid, setTeamPid] = useState<string | null>(null);

  // Add-Project form
  const [pf, setPf] = useState({ code: "", name: "", site: "", client: "", customer_id: "", system_categories: [] as string[] });
  // Edit-Project modal
  const [pEdit, setPEdit] = useState<any>(null);
  // Add-Vendor form
  const [vf, setVf] = useState({ name: "", address: "", gstin: "", contact: "", email: "" });
  // Edit-Vendor modal
  const [vEdit, setVEdit] = useState<any>(null);
  // Add-master form
  const [mf, setMf] = useState("");

  // Task 3A.2 / Task 4: roles[] is authoritative for current access checks;
  // the scalar role remains only as a compatibility fallback for legacy users.
  const actorRoles = user?.roles?.length ? user.roles : user?.role ? [user.role] : [];
  const isAdmin = actorRoles.includes("admin");
  const isDirectorOrAdmin = isAdmin || actorRoles.includes("director");
  const canVendor = isAdmin || actorRoles.includes("purchase");

  // Filter tabs by role
  const visibleTabs = TABS.filter((t) => !t.roles || t.roles.some((role) => actorRoles.includes(role)));

  // PO threshold state
  const [thresholds, setThresholds] = useState<{ gm: string; director: string }>({ gm: "50000", director: "500000" });
  const [thrSaving, setThrSaving] = useState(false);
  const [thrMsg, setThrMsg] = useState("");
  const loadThresholds = useCallback(async () => {
    try {
      const t = await api<{ gm: number; director: number }>("/settings/thresholds");
      setThresholds({ gm: String(t.gm), director: String(t.director) });
    } catch (_e) { /* noop */ }
  }, []);
  const saveThresholds = async () => {
    setThrSaving(true); setThrMsg("");
    try {
      await api("/settings/thresholds", { method: "PUT", body: {
        gm: Number(thresholds.gm), director: Number(thresholds.director),
      } });
      setThrMsg("Thresholds updated.");
    } catch (e: any) { setThrMsg(e.message || "Failed"); }
    setThrSaving(false);
  };

  const load = useCallback(async () => {
    try {
      const [p, v, m, sy] = await Promise.all([
        api<any[]>(isAdmin ? "/projects?all=1" : "/projects"),
        api<any[]>("/vendors"),
        api<any>("/masters"),
        api<string[]>("/systems"),
      ]);
      setProjects(p); setVendors(v); setMasters(m); setSystems(sy);
    } catch (_e) { /* noop */ }
  }, [isAdmin]);

  useEffect(() => { if (user) load(); }, [user, load]);
  useEffect(() => { if (tab === "thresholds" && isDirectorOrAdmin) loadThresholds(); }, [tab, isDirectorOrAdmin, loadThresholds]);

  // Clear tab-scoped state when switching
  useEffect(() => { setErr(""); setQ(""); }, [tab]);

  const toggleSystem = (s: string) => {
    setPf((prev) => ({
      ...prev,
      system_categories: prev.system_categories.includes(s)
        ? prev.system_categories.filter((x) => x !== s)
        : [...prev.system_categories, s],
    }));
  };

  const addProject = async () => {
    setErr("");
    if (!pf.code.trim() || !pf.name.trim() || !pf.site.trim()) { setErr("Code, Name, Site are required."); return; }
    try {
      await api("/projects", { method: "POST", body: {
        code: pf.code.trim(), name: pf.name.trim(), site: pf.site.trim(),
        client: pf.client.trim(),
        customer_id: pf.customer_id?.trim() || null,
        system_categories: pf.system_categories,
      } });
      setPf({ code: "", name: "", site: "", client: "", customer_id: "", system_categories: [] });
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const saveProjectEdit = async () => {
    if (!pEdit) return;
    const reason = pEdit._reason?.trim();
    if (!reason) { setErr("Please enter a reason for this change (required)."); return; }
    try {
      await api(`/projects/${pEdit.project_id}`, { method: "PUT", body: {
        code: pEdit.code, name: pEdit.name, site: pEdit.site,
        client: pEdit.client, customer_id: pEdit.customer_id || null,
        system_categories: pEdit.system_categories || [],
        reason,
      } });
      setPEdit(null); load();
    } catch (e: any) { setErr(e.message); }
  };

  const deactivateProject = async (project_id: string) => {
    await api(`/projects/${project_id}?reason=Deactivated%20via%20UI`, { method: "DELETE" });
    load();
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

  const saveVendorEdit = async () => {
    if (!vEdit) return;
    const reason = vEdit._reason?.trim();
    if (!reason) { setErr("Please enter a reason for this change (required)."); return; }
    try {
      await api(`/vendors/${vEdit.vendor_id}`, { method: "PUT", body: {
        name: vEdit.name, address: vEdit.address, gstin: vEdit.gstin,
        contact: vEdit.contact, email: vEdit.email, reason,
      } });
      setVEdit(null); load();
    } catch (e: any) { setErr(e.message); }
  };

  const deactivateVendor = async (vendor_id: string) => {
    await api(`/vendors/${vendor_id}?reason=Deactivated%20via%20UI`, { method: "DELETE" });
    load();
  };

  const [mfValue, setMfValue] = useState("");   // used for GST rate (percentage)

  const addMaster = async (category: string) => {
    setErr("");
    if (!mf.trim()) { setErr("Name required."); return; }
    try {
      const body: any = { name: mf.trim(), category };
      if (category === "gst" && mfValue.trim()) body.value = mfValue.trim();
      await api("/masters", { method: "POST", body });
      setMf(""); setMfValue(""); load();
    } catch (e: any) { setErr(e.message); }
  };

  const currentMasterKey: "unit" | "brand" | "material" | "model" | "gst" | "department" | null =
    tab === "units" ? "unit"
    : tab === "brands" ? "brand"
    : tab === "materials" ? "material"
    : tab === "models" ? "model"
    : tab === "gst" ? "gst"
    : tab === "departments" ? "department"
    : null;
  const masterList = currentMasterKey ? (masters[currentMasterKey] || []) : [];

  const filteredProjects = q ? projects.filter((p) =>
    (p.code + " " + p.name + " " + (p.site || "") + " " + (p.client || "")).toLowerCase().includes(q.toLowerCase())
  ) : projects;
  const filteredVendors = q ? vendors.filter((v) =>
    (v.name + " " + (v.gstin || "") + " " + (v.address || "")).toLowerCase().includes(q.toLowerCase())
  ) : vendors;
  const filteredMasters = q ? masterList.filter((m: any) => m.name.toLowerCase().includes(q.toLowerCase())) : masterList;

  // Flatten sub-sites across projects
  const allSites = projects.flatMap((p) => (p.sites || []).filter((s: any) => s.active !== false).map((s: any) => ({ ...s, project: p })));
  const filteredSites = q ? allSites.filter((s) =>
    (s.name + " " + (s.location || "") + " " + s.project.code + " " + s.project.name).toLowerCase().includes(q.toLowerCase())
  ) : allSites;

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
        <Muted>Customers · Projects · Vendors · Materials · GST · Departments · Users · Thresholds.</Muted>

        {isAdmin ? (
          <TouchableOpacity
            testID="open-material-master"
            onPress={() => router.push("/material-master")}
            style={styles.cta}
            activeOpacity={0.85}
          >
            <View style={{ flex: 1 }}>
              <Text style={styles.ctaTitle}>Material Master & UOM Controls →</Text>
              <Text style={styles.ctaSub}>Category-linked materials, approved units, conversions and traceability.</Text>
            </View>
            <Ionicons name="cube-outline" size={26} color={theme.colors.primary} />
          </TouchableOpacity>
        ) : null}

        {/* Customer master CTA */}
        <TouchableOpacity
          testID="open-customers"
          onPress={() => router.push("/customers")}
          style={styles.cta}
          activeOpacity={0.85}
        >
          <View style={{ flex: 1 }}>
            <Text style={styles.ctaTitle}>Customer Master →</Text>
            <Text style={styles.ctaSub}>Permanent Customer ID, GSTIN, Customer POs. Used everywhere.</Text>
          </View>
          <Ionicons name="people-outline" size={26} color={theme.colors.primary} />
        </TouchableOpacity>

        <ScrollView horizontal showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chipRow} style={{ marginTop: 14, marginHorizontal: -16, paddingHorizontal: 16 }}>
          {visibleTabs.map((t) => {
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

        {/* Search */}
        <View style={styles.search}>
          <Ionicons name="search-outline" size={16} color={theme.colors.textMuted} />
          <TextInput
            testID="masters-search"
            value={q}
            onChangeText={setQ}
            placeholder={`Search ${TABS.find((t) => t.key === tab)?.label.toLowerCase()}…`}
            style={{ flex: 1, marginLeft: 8, fontSize: 14, color: theme.colors.text, paddingVertical: 0 }}
          />
          {q ? (
            <TouchableOpacity onPress={() => setQ("")}><Ionicons name="close-circle" size={16} color={theme.colors.textMuted} /></TouchableOpacity>
          ) : null}
        </View>

        {err ? <Text testID="masters-err" style={{ color: theme.colors.danger, marginTop: 10 }}>{err}</Text> : null}

        {/* PROJECTS */}
        {tab === "projects" ? (
          <>
            {isAdmin ? (
              <Card style={{ marginTop: 12 }} testID="add-project-card">
                <H2>Add New Project</H2>
                <View style={{ marginTop: 10 }}>
                  <Label>PROJECT CODE</Label>
                  <TextInput testID="proj-code" value={pf.code} onChangeText={(v) => setPf({ ...pf, code: v })} placeholder="e.g. VIS-104" style={styles.inp} />
                  <View style={{ height: 10 }} />
                  <Label>PROJECT NAME</Label>
                  <TextInput testID="proj-name" value={pf.name} onChangeText={(v) => setPf({ ...pf, name: v })} placeholder="e.g. LMN Data Center" style={styles.inp} />
                  <View style={{ height: 10 }} />
                  <Label>DEFAULT SITE</Label>
                  <TextInput testID="proj-site" value={pf.site} onChangeText={(v) => setPf({ ...pf, site: v })} placeholder="e.g. Pune Hinjewadi" style={styles.inp} />
                  <View style={{ height: 10 }} />
                  <Label>CLIENT NAME (legacy)</Label>
                  <TextInput testID="proj-client" value={pf.client} onChangeText={(v) => setPf({ ...pf, client: v })} placeholder="e.g. LMN Corp (kept for display; prefer Customer ID below)" style={styles.inp} />
                  <View style={{ height: 10 }} />
                  <Label>CUSTOMER ID (link to Customer master)</Label>
                  <TextInput testID="proj-customer-id" value={pf.customer_id}
                    onChangeText={(v) => setPf({ ...pf, customer_id: v.replace(/[^A-Za-z0-9_-]/g, "") })}
                    autoCapitalize="characters"
                    placeholder="e.g. VASU-CUST-001 (create Customer first)"
                    style={styles.inp} />
                  <TouchableOpacity onPress={() => router.push("/customers")} testID="proj-open-cust"><Text style={{ color: theme.colors.primary, fontSize: 12, marginTop: 4 }}>+ Open Customer Master →</Text></TouchableOpacity>
                  <View style={{ height: 12 }} />
                  <Label>SYSTEM CATEGORIES</Label>
                  <Muted style={{ marginBottom: 6 }}>Which systems does this project cover? Tap to toggle.</Muted>
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                    {systems.map((s) => {
                      const active = pf.system_categories.includes(s);
                      return (
                        <TouchableOpacity key={s} testID={`sys-${SYSTEM_SHORT[s] || s}`}
                          onPress={() => toggleSystem(s)}
                          style={[styles.sysChip, active ? { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary } : {}]}>
                          <Text style={{ fontWeight: "700", fontSize: 10, color: active ? "#fff" : theme.colors.textSecondary, letterSpacing: 0.5 }}>{SYSTEM_SHORT[s] || s}</Text>
                          <Text style={{ fontSize: 10, color: active ? "#fff" : theme.colors.textMuted, marginLeft: 4 }}>{s}</Text>
                        </TouchableOpacity>
                      );
                    })}
                  </View>
                  <Btn testID="add-project-btn" title="+ Add Project" variant="action" onPress={addProject} style={{ marginTop: 12 }} />
                </View>
              </Card>
            ) : null}

            <H2 style={{ marginTop: 20 }}>All Projects ({filteredProjects.length})</H2>
            {filteredProjects.map((p) => (
              <Card key={p.project_id} style={{ marginTop: 8, opacity: p.active === false ? 0.5 : 1 }} testID={`p-${p.code}`}>
                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontWeight: "700", color: theme.colors.primary }}>{p.code}{p.active === false ? " (inactive)" : ""}</Text>
                    <Text style={{ marginTop: 2 }}>{p.name}</Text>
                    <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>{p.site}{p.customer_id ? ` · Customer: ${p.customer_id}` : (p.client ? ` · ${p.client}` : "")}</Text>
                    <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>
                      {(p.site_engineers || []).length} engineer(s) · {(p.project_managers || []).length} PM(s) · {(p.sites || []).filter((x: any) => x.active !== false).length} sub-site(s)
                    </Text>
                    {(p.system_categories || []).length ? (
                      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                        {p.system_categories.map((s: string) => (
                          <View key={s} style={styles.sysTag}>
                            <Text style={{ fontSize: 9, fontWeight: "800", color: theme.colors.primary, letterSpacing: 0.5 }}>{SYSTEM_SHORT[s] || s}</Text>
                          </View>
                        ))}
                      </View>
                    ) : null}
                  </View>
                  {isAdmin ? (
                    <View style={{ flexDirection: "row", gap: 4 }}>
                      <TouchableOpacity testID={`edit-${p.code}`} onPress={() => setPEdit({ ...p, system_categories: p.system_categories || [] })} style={styles.iconBtn}>
                        <Ionicons name="pencil-outline" size={16} color={theme.colors.text} />
                      </TouchableOpacity>
                      <TouchableOpacity testID={`deactivate-${p.code}`} onPress={() => deactivateProject(p.project_id)} style={styles.iconBtn}>
                        <Ionicons name="trash-outline" size={16} color={theme.colors.danger} />
                      </TouchableOpacity>
                    </View>
                  ) : null}
                </View>
                {isAdmin ? (
                  <Btn testID={`assign-team-${p.code}`} title="Assign Team & Sites" variant="outline" onPress={() => setTeamPid(p.project_id)} style={{ marginTop: 10 }} />
                ) : null}
              </Card>
            ))}
            {!filteredProjects.length ? <Empty msg="No projects match." testID="p-empty" /> : null}
          </>
        ) : null}

        {/* VENDORS */}
        {tab === "vendors" ? (
          <>
            {canVendor ? (
              <Card style={{ marginTop: 12 }} testID="add-vendor-card">
                <H2>Add New Vendor</H2>
                <View style={{ marginTop: 10 }}>
                  <Label>VENDOR NAME</Label>
                  <TextInput testID="vend-name" value={vf.name} onChangeText={(v) => setVf({ ...vf, name: v })} placeholder="e.g. Legrand India" style={styles.inp} />
                  <View style={{ height: 10 }} />
                  <Label>ADDRESS</Label>
                  <TextInput testID="vend-addr" value={vf.address} onChangeText={(v) => setVf({ ...vf, address: v })} style={styles.inp} multiline />
                  <View style={{ height: 10 }} />
                  <Label>GSTIN</Label>
                  <TextInput testID="vend-gstin" value={vf.gstin} onChangeText={(v) => setVf({ ...vf, gstin: v })} style={styles.inp} />
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

            <H2 style={{ marginTop: 20 }}>All Vendors ({filteredVendors.length})</H2>
            {filteredVendors.map((v) => (
              <Card key={v.vendor_id} style={{ marginTop: 8, opacity: v.active === false ? 0.5 : 1 }} testID={`v-${v.vendor_id}`}>
                <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontWeight: "700" }}>{v.name}{v.active === false ? " (inactive)" : ""}</Text>
                    <Text style={{ fontSize: 12, color: theme.colors.textMuted, marginTop: 2 }}>{v.gstin}</Text>
                    {v.address ? <Text style={{ fontSize: 12, color: theme.colors.textMuted }}>{v.address}</Text> : null}
                    {v.contact ? <Text style={{ fontSize: 12, color: theme.colors.textMuted }}>{v.contact}{v.email ? ` · ${v.email}` : ""}</Text> : null}
                  </View>
                  {canVendor ? (
                    <View style={{ flexDirection: "row", gap: 4 }}>
                      <TouchableOpacity testID={`v-edit-${v.vendor_id}`} onPress={() => setVEdit({ ...v })} style={styles.iconBtn}>
                        <Ionicons name="pencil-outline" size={16} color={theme.colors.text} />
                      </TouchableOpacity>
                      <TouchableOpacity testID={`v-deactivate-${v.vendor_id}`} onPress={() => deactivateVendor(v.vendor_id)} style={styles.iconBtn}>
                        <Ionicons name="trash-outline" size={16} color={theme.colors.danger} />
                      </TouchableOpacity>
                    </View>
                  ) : null}
                </View>
              </Card>
            ))}
            {!filteredVendors.length ? <Empty msg="No vendors match." testID="v-empty" /> : null}
          </>
        ) : null}

        {/* SITES */}
        {tab === "sites" ? (
          <>
            <Muted style={{ marginTop: 12 }}>Sub-sites are managed under each project&apos;s team. Tap a row to open its project team.</Muted>
            <H2 style={{ marginTop: 20 }}>All Sub-Sites ({filteredSites.length})</H2>
            {filteredSites.map((s: any) => (
              <TouchableOpacity key={s.site_id} testID={`site-row-${s.site_id}`}
                onPress={() => isAdmin && setTeamPid(s.project.project_id)}
                disabled={!isAdmin}
                activeOpacity={isAdmin ? 0.6 : 1}>
                <Card style={{ marginTop: 8 }}>
                  <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                    <View style={{ flex: 1 }}>
                      <Text style={{ fontWeight: "700" }}>{s.name}</Text>
                      {s.location ? <Text style={{ fontSize: 12, color: theme.colors.textMuted }}>{s.location}</Text> : null}
                      <Text style={{ fontSize: 11, color: theme.colors.primary, marginTop: 2 }}>{s.project.code} — {s.project.name}</Text>
                      <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>
                        {(s.site_engineers || []).length} engineer(s)
                      </Text>
                    </View>
                    {isAdmin ? <Ionicons name="chevron-forward" size={18} color={theme.colors.textMuted} /> : null}
                  </View>
                </Card>
              </TouchableOpacity>
            ))}
            {!filteredSites.length ? <Empty msg="No sub-sites yet. Add one from a project's team page." testID="s-empty" /> : null}
          </>
        ) : null}

        {/* PO THRESHOLDS */}
        {tab === "thresholds" && isDirectorOrAdmin ? (
          <>
            <Card style={{ marginTop: 12 }} testID="thresholds-card">
              <H2>Purchase Order Approval Thresholds</H2>
              <Muted style={{ marginTop: 6 }}>
                POs at or below ₹{new Intl.NumberFormat("en-IN").format(Number(thresholds.gm) || 0)} are auto-issued by Purchase.
                {"\n"}Between GM threshold and Director threshold require GM approval.
                {"\n"}Above Director threshold require Director approval.
              </Muted>
              <View style={{ height: 12 }} />
              <Label>GM APPROVAL THRESHOLD (₹)</Label>
              <TextInput
                testID="thr-gm"
                value={thresholds.gm}
                onChangeText={(v) => setThresholds((s) => ({ ...s, gm: v.replace(/[^0-9.]/g, "") }))}
                placeholder="50000"
                keyboardType="numeric"
                style={styles.inp}
              />
              <View style={{ height: 10 }} />
              <Label>DIRECTOR APPROVAL THRESHOLD (₹)</Label>
              <TextInput
                testID="thr-director"
                value={thresholds.director}
                onChangeText={(v) => setThresholds((s) => ({ ...s, director: v.replace(/[^0-9.]/g, "") }))}
                placeholder="500000"
                keyboardType="numeric"
                style={styles.inp}
              />
              {thrMsg ? (
                <Text testID="thr-msg" style={{ marginTop: 8, color: thrMsg.includes("updated") ? theme.colors.success : theme.colors.danger }}>
                  {thrMsg}
                </Text>
              ) : null}
              <Btn testID="thr-save" title={thrSaving ? "Saving…" : "Save Thresholds"} variant="action" onPress={saveThresholds} style={{ marginTop: 14 }} disabled={thrSaving} />
            </Card>
          </>
        ) : null}

        {/* MASTERS: UNITS/BRANDS/MATERIALS/MODELS/GST/DEPARTMENTS */}
        {currentMasterKey ? (          <>
            {isAdmin ? (
              <Card style={{ marginTop: 12 }} testID={`add-${currentMasterKey}-card`}>
                <H2>Add {TABS.find((t) => t.key === tab)?.label.replace(/s$/, "")}</H2>
                <View style={{ flexDirection: "row", gap: 8, marginTop: 10, alignItems: "flex-end" }}>
                  <View style={{ flex: 1 }}>
                    <Label>NAME</Label>
                    <TextInput testID={`m-input-${currentMasterKey}`} value={mf} onChangeText={setMf}
                      placeholder={
                        currentMasterKey === "unit" ? "e.g. Meter, Kg, Box" :
                        currentMasterKey === "brand" ? "e.g. Legrand, Schneider" :
                        currentMasterKey === "model" ? "e.g. XC-500 (specify brand in name)" :
                        currentMasterKey === "gst" ? "e.g. GST 18% Standard" :
                        currentMasterKey === "department" ? "e.g. Purchase, Accounts" :
                        "e.g. Emergency Light 3W"
                      }
                      style={styles.inp} />
                  </View>
                  {currentMasterKey === "gst" ? (
                    <View style={{ width: 100 }}>
                      <Label>RATE %</Label>
                      <TextInput testID="m-input-gst-val" value={mfValue} onChangeText={setMfValue}
                        placeholder="18" keyboardType="numeric" style={styles.inp} />
                    </View>
                  ) : null}
                  <Btn testID={`m-add-${currentMasterKey}`} title="+ Add" variant="action" onPress={() => addMaster(currentMasterKey)} />
                </View>
              </Card>
            ) : null}

            <H2 style={{ marginTop: 20 }}>{TABS.find((t) => t.key === tab)?.label} ({filteredMasters.length})</H2>
            <Card style={{ marginTop: 8 }}>
              {filteredMasters.length ? filteredMasters.map((it: any, i: number) => (
                <View key={it.item_id || i} style={styles.masterRow} testID={`m-item-${it.name}`}>
                  <Text style={{ flex: 1, fontWeight: "500" }}>
                    {it.name}
                    {it.value ? <Text style={{ color: theme.colors.textMuted, fontWeight: "400" }}>  ·  {it.value}{currentMasterKey === "gst" ? "%" : ""}</Text> : null}
                  </Text>
                </View>
              )) : <Muted>None match.</Muted>}
            </Card>
          </>
        ) : null}

        {/* MASTER AUDIT */}
        {tab === "audit" && isDirectorOrAdmin ? (
          <MasterAuditSection />
        ) : null}
      </ScrollView>

      {/* Team modal */}
      {teamPid ? (
        <ProjectTeamModal projectId={teamPid} onClose={() => setTeamPid(null)} onChanged={load} />
      ) : null}

      {/* Edit-project modal */}
      <Modal visible={!!pEdit} transparent animationType="fade" onRequestClose={() => setPEdit(null)}>
        <View style={styles.modalBg}>
          <View style={[styles.modal, { paddingBottom: 16 + insets.bottom, maxHeight: "88%" }]}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <Text style={{ fontWeight: "800", fontSize: 16 }}>Edit Project</Text>
              <TouchableOpacity onPress={() => setPEdit(null)}><Ionicons name="close" size={22} /></TouchableOpacity>
            </View>
            {pEdit ? (
              <ScrollView>
                <Label>CODE</Label>
                <TextInput testID="pe-code" value={pEdit.code || ""} onChangeText={(v) => setPEdit({ ...pEdit, code: v })} style={styles.inp} />
                <View style={{ height: 8 }} />
                <Label>NAME</Label>
                <TextInput testID="pe-name" value={pEdit.name || ""} onChangeText={(v) => setPEdit({ ...pEdit, name: v })} style={styles.inp} />
                <View style={{ height: 8 }} />
                <Label>DEFAULT SITE</Label>
                <TextInput testID="pe-site" value={pEdit.site || ""} onChangeText={(v) => setPEdit({ ...pEdit, site: v })} style={styles.inp} />
                <View style={{ height: 8 }} />
                <Label>CLIENT (legacy free-text)</Label>
                <TextInput testID="pe-client" value={pEdit.client || ""} onChangeText={(v) => setPEdit({ ...pEdit, client: v })} style={styles.inp} />
                <View style={{ height: 8 }} />
                <Label>CUSTOMER ID (from Customer master)</Label>
                <TextInput testID="pe-customer-id" value={pEdit.customer_id || ""}
                  onChangeText={(v) => setPEdit({ ...pEdit, customer_id: v.replace(/[^A-Za-z0-9_-]/g, "") })}
                  autoCapitalize="characters"
                  placeholder="e.g. VASU-CUST-001 · leave blank if not linked"
                  style={styles.inp} />
                <View style={{ height: 10 }} />
                <Label>SYSTEM CATEGORIES</Label>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                  {systems.map((s) => {
                    const active = (pEdit.system_categories || []).includes(s);
                    return (
                      <TouchableOpacity key={s} testID={`pe-sys-${SYSTEM_SHORT[s] || s}`}
                        onPress={() => setPEdit({
                          ...pEdit,
                          system_categories: active
                            ? (pEdit.system_categories || []).filter((x: string) => x !== s)
                            : [...(pEdit.system_categories || []), s],
                        })}
                        style={[styles.sysChip, active ? { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary } : {}]}>
                        <Text style={{ fontWeight: "700", fontSize: 10, color: active ? "#fff" : theme.colors.textSecondary, letterSpacing: 0.5 }}>{SYSTEM_SHORT[s] || s}</Text>
                        <Text style={{ fontSize: 10, color: active ? "#fff" : theme.colors.textMuted, marginLeft: 4 }}>{s}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
                <View style={{ height: 12 }} />
                <Label>REASON FOR CHANGE * (mandatory audit)</Label>
                <TextInput testID="pe-reason" value={pEdit._reason || ""}
                  onChangeText={(v) => setPEdit({ ...pEdit, _reason: v })}
                  placeholder="e.g. Correct client name per contract"
                  style={[styles.inp, { backgroundColor: "#fffbea", minHeight: 60 }]}
                  multiline />
              </ScrollView>
            ) : null}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <View style={{ flex: 1 }}><Btn title="Cancel" variant="outline" onPress={() => setPEdit(null)} /></View>
              <View style={{ flex: 1 }}><Btn testID="pe-save" title="Save" variant="action" onPress={saveProjectEdit} /></View>
            </View>
          </View>
        </View>
      </Modal>

      {/* Edit-vendor modal */}
      <Modal visible={!!vEdit} transparent animationType="fade" onRequestClose={() => setVEdit(null)}>
        <View style={styles.modalBg}>
          <View style={[styles.modal, { paddingBottom: 16 + insets.bottom, maxHeight: "88%" }]}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <Text style={{ fontWeight: "800", fontSize: 16 }}>Edit Vendor</Text>
              <TouchableOpacity onPress={() => setVEdit(null)}><Ionicons name="close" size={22} /></TouchableOpacity>
            </View>
            {vEdit ? (
              <ScrollView>
                <Label>NAME</Label>
                <TextInput testID="ve-name" value={vEdit.name || ""} onChangeText={(v) => setVEdit({ ...vEdit, name: v })} style={styles.inp} />
                <View style={{ height: 8 }} />
                <Label>ADDRESS</Label>
                <TextInput testID="ve-addr" value={vEdit.address || ""} onChangeText={(v) => setVEdit({ ...vEdit, address: v })} style={styles.inp} multiline />
                <View style={{ height: 8 }} />
                <Label>GSTIN</Label>
                <TextInput testID="ve-gstin" value={vEdit.gstin || ""} onChangeText={(v) => setVEdit({ ...vEdit, gstin: v })} style={styles.inp} />
                <View style={{ height: 8 }} />
                <Label>CONTACT</Label>
                <TextInput testID="ve-contact" value={vEdit.contact || ""} onChangeText={(v) => setVEdit({ ...vEdit, contact: v })} style={styles.inp} />
                <View style={{ height: 8 }} />
                <Label>EMAIL</Label>
                <TextInput testID="ve-email" value={vEdit.email || ""} onChangeText={(v) => setVEdit({ ...vEdit, email: v })} style={styles.inp} autoCapitalize="none" />
                <View style={{ height: 12 }} />
                <Label>REASON FOR CHANGE * (mandatory audit)</Label>
                <TextInput testID="ve-reason" value={vEdit._reason || ""}
                  onChangeText={(v) => setVEdit({ ...vEdit, _reason: v })}
                  placeholder="e.g. Update GSTIN after re-registration"
                  style={[styles.inp, { backgroundColor: "#fffbea", minHeight: 60 }]}
                  multiline />
              </ScrollView>
            ) : null}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <View style={{ flex: 1 }}><Btn title="Cancel" variant="outline" onPress={() => setVEdit(null)} /></View>
              <View style={{ flex: 1 }}><Btn testID="ve-save" title="Save" variant="action" onPress={saveVendorEdit} /></View>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 8, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  chipRow: { gap: 8, paddingRight: 16 },
  chip: { flexShrink: 0, height: 36, paddingHorizontal: 14, borderRadius: 999, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  search: { flexDirection: "row", alignItems: "center", borderWidth: 1, borderColor: theme.colors.border, backgroundColor: "#fff", borderRadius: 8, paddingHorizontal: 12, height: 40, marginTop: 12 },
  inp: { borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, paddingHorizontal: 10, minHeight: 44, backgroundColor: "#fff", fontSize: 14, color: theme.colors.text },
  masterRow: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  iconBtn: { width: 32, height: 32, alignItems: "center", justifyContent: "center", borderRadius: 6, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: "#fff" },
  sysChip: { flexDirection: "row", alignItems: "center", paddingHorizontal: 8, paddingVertical: 6, borderRadius: 6, borderWidth: 1, borderColor: theme.colors.borderStrong, backgroundColor: "#fff" },
  sysTag: { backgroundColor: "rgba(0,47,167,0.08)", paddingHorizontal: 6, paddingVertical: 3, borderRadius: 3 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modal: { backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 20 },
  cta: {
    marginTop: 14, flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: "rgba(0,47,167,0.06)",
    borderWidth: 1, borderColor: "rgba(0,47,167,0.25)",
    borderRadius: 12, padding: 14,
  },
  ctaTitle: { fontSize: 15, fontWeight: "700", color: theme.colors.primary },
  ctaSub: { fontSize: 12, color: theme.colors.textMuted, marginTop: 2 },
  auditRow: {
    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.colors.border,
  },
});

function MasterAuditSection() {
  const [rows, setRows] = React.useState<any[]>([]);
  const [entity, setEntity] = React.useState<string>("");
  const [loading, setLoading] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const q = entity ? `?entity=${encodeURIComponent(entity)}` : "";
      const d = await api<any[]>(`/master-audit${q}`);
      setRows(d);
    } catch { setRows([]); }
    setLoading(false);
  }, [entity]);

  React.useEffect(() => { load(); }, [load]);

  const filters = [
    { key: "", label: "All" },
    { key: "customer", label: "Customer" },
    { key: "customer_po", label: "Customer PO" },
    { key: "project", label: "Project" },
    { key: "vendor", label: "Vendor" },
    { key: "master.gst", label: "GST" },
    { key: "master.department", label: "Dept" },
    { key: "master.brand", label: "Brand" },
    { key: "master.model", label: "Model" },
    { key: "master.material", label: "Material" },
    { key: "master.unit", label: "Unit" },
  ];

  return (
    <>
      <H2 style={{ marginTop: 20 }}>Master Data Audit Log</H2>
      <Muted>Every master-data change (who, when, why, before/after).</Muted>

      <ScrollView horizontal showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ gap: 6, marginTop: 10 }}>
        {filters.map((f) => {
          const active = entity === f.key;
          return (
            <TouchableOpacity key={f.key || "all"} onPress={() => setEntity(f.key)}
              testID={`audit-filter-${f.key || "all"}`}
              style={[styles.chip, {
                borderColor: active ? theme.colors.primary : theme.colors.border,
                backgroundColor: active ? theme.colors.primary : "#fff",
                height: 30, paddingHorizontal: 10,
              }]}>
              <Text style={{ color: active ? "#fff" : theme.colors.text, fontSize: 12 }}>{f.label}</Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>

      <Card style={{ marginTop: 10 }}>
        {loading ? <Muted>Loading…</Muted> : rows.length === 0 ? (
          <Muted>No audit entries yet.</Muted>
        ) : rows.map((r) => (
          <View key={r.audit_id} style={styles.auditRow} testID={`audit-${r.audit_id}`}>
            <Text style={{ fontWeight: "700", color: theme.colors.text }}>
              {r.entity} · {r.entity_id}
            </Text>
            <Text style={{ color: theme.colors.textMuted, fontSize: 12, marginTop: 2 }}>
              {String(r.timestamp || "").slice(0, 19).replace("T", " ")} · {r.user_name} ({r.user_role}) · {r.action}
            </Text>
            {r.reason ? <Text style={{ fontSize: 13, marginTop: 4 }}>💬 {r.reason}</Text> : null}
            {r.old_value ? <Text style={{ fontSize: 11, color: "#b45309", marginTop: 4 }} numberOfLines={2}>OLD: {JSON.stringify(r.old_value)}</Text> : null}
            {r.new_value ? <Text style={{ fontSize: 11, color: "#166534", marginTop: 2 }} numberOfLines={2}>NEW: {JSON.stringify(r.new_value)}</Text> : null}
          </View>
        ))}
      </Card>
    </>
  );
}
