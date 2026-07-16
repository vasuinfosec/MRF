import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal, TextInput } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AppShell } from "@/src/components/AppShell";
import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { Btn, Card, H1, H2, Muted, Label, Pill } from "@/src/components/ui";
import { theme } from "@/src/theme";

const ROLES = [
  { key: "site_engineer", label: "Site Engineer" },
  { key: "project_manager", label: "Project Manager" },
  { key: "purchase", label: "Purchase" },
  { key: "billing", label: "Billing" },
  { key: "admin", label: "Admin" },
];

export default function More() {
  const { user, logout, refresh } = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [users, setUsers] = useState<any[]>([]);
  const [vendors, setVendors] = useState<any[]>([]);
  const [projects, setProjects] = useState<any[]>([]);
  const [roleEdit, setRoleEdit] = useState<any>(null);
  const [teamEdit, setTeamEdit] = useState<any>(null);
  const [teamSe, setTeamSe] = useState<string[]>([]);
  const [teamPm, setTeamPm] = useState<string[]>([]);
  const [savingTeam, setSavingTeam] = useState(false);
  const [newSiteName, setNewSiteName] = useState("");
  const [newSiteLoc, setNewSiteLoc] = useState("");
  const [siteExpand, setSiteExpand] = useState<string | null>(null);

  useEffect(() => { load(); }, []);
  const load = async () => {
    try {
      const [u, v, p] = await Promise.all([
        api<any[]>("/users"), api<any[]>("/vendors"),
        api<any[]>(user?.role === "admin" ? "/projects?all=1" : "/projects"),
      ]);
      setUsers(u); setVendors(v); setProjects(p);
    } catch (_e) { /* noop */ }
  };

  const setRole = async (uid: string, role: string) => {
    await api("/users/role", { method: "POST", body: { user_id: uid, role } });
    setRoleEdit(null); load();
    if (uid === user?.user_id) refresh();
  };

  const openTeam = (p: any) => {
    setTeamEdit(p);
    setTeamSe(p.site_engineers || []);
    setTeamPm(p.project_managers || []);
  };
  const toggleTeam = (list: string[], setList: (v: string[]) => void, uid: string) => {
    setList(list.includes(uid) ? list.filter((x) => x !== uid) : [...list, uid]);
  };
  const saveTeam = async () => {
    setSavingTeam(true);
    try {
      await api(`/projects/${teamEdit.project_id}/team`, {
        method: "POST", body: { site_engineers: teamSe, project_managers: teamPm },
      });
      setTeamEdit(null); load();
    } catch (_e) { /* noop */ }
    setSavingTeam(false);
  };

  const refreshTeamProject = async (pid: string) => {
    const all = await api<any[]>("/projects?all=1");
    const updated = all.find((p) => p.project_id === pid);
    setTeamEdit(updated);
    setProjects(all);
  };

  const addSite = async () => {
    if (!newSiteName.trim() || !teamEdit) return;
    await api(`/projects/${teamEdit.project_id}/sites`, {
      method: "POST",
      body: { name: newSiteName.trim(), location: newSiteLoc.trim(), site_engineers: [] },
    });
    setNewSiteName(""); setNewSiteLoc("");
    await refreshTeamProject(teamEdit.project_id);
  };

  const toggleSiteEngineer = async (site: any, uid: string) => {
    const cur: string[] = site.site_engineers || [];
    const next = cur.includes(uid) ? cur.filter((x) => x !== uid) : [...cur, uid];
    await api(`/projects/${teamEdit.project_id}/sites/${site.site_id}`, {
      method: "PUT", body: { site_engineers: next },
    });
    await refreshTeamProject(teamEdit.project_id);
  };

  const removeSite = async (site_id: string) => {
    await api(`/projects/${teamEdit.project_id}/sites/${site_id}`, { method: "DELETE" });
    await refreshTeamProject(teamEdit.project_id);
  };

  const engineers = users.filter((u) => u.role === "site_engineer" || u.role === "admin");
  const pms = users.filter((u) => u.role === "project_manager" || u.role === "admin");

  const isAdmin = user?.role === "admin";

  return (
    <AppShell title="More" testID="more-screen">
      <H1>Settings & Masters</H1>
      <Muted>Profile, master data, and reports.</Muted>

      <Card style={{ marginTop: 16 }} testID="profile-card">
        <Label>SIGNED IN AS</Label>
        <Text style={{ fontSize: 16, fontWeight: "700", marginTop: 4 }}>{user?.name}</Text>
        <Text style={{ color: theme.colors.textMuted }}>{user?.email}</Text>
        <View style={{ marginTop: 8 }}><Pill status="approved" /></View>
        <Text style={{ marginTop: 4, fontSize: 12, color: theme.colors.textSecondary }}>Role: {user?.role}</Text>
        <Btn testID="logout-btn" title="Log Out" variant="outline" onPress={async () => { await logout(); router.replace("/login"); }} style={{ marginTop: 12 }} />
      </Card>

      <Card style={{ marginTop: 12 }} testID="reports-card">
        <H2>Reports & Tools</H2>
        <View style={{ marginTop: 8, gap: 8 }}>
          <Btn testID="masters-btn" title="Master Data (Projects, Vendors, Units, Brands, Materials)" variant="primary" onPress={() => router.push("/masters")} />
          <Btn testID="reports-btn" title="Reports Dashboard" variant="outline" onPress={() => router.push("/reports")} />
          <Btn testID="import-btn" title="Excel Bulk Import" variant="outline" onPress={() => router.push("/import")} />
          <Btn testID="audit-log-btn" title="System Audit Trail" variant="outline" onPress={() => router.push("/audit")} />
        </View>
      </Card>

      <Card style={{ marginTop: 12 }} testID="projects-card">
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <H2>Projects ({projects.length})</H2>
          {isAdmin ? (
            <TouchableOpacity testID="add-project-shortcut" onPress={() => router.push("/masters")} style={{ padding: 6 }}>
              <Ionicons name="add-circle-outline" size={22} color={theme.colors.primary} />
            </TouchableOpacity>
          ) : null}
        </View>
        {isAdmin ? <Muted>Tap a project to manage sub-sites and team. Tap + to create a new project.</Muted> : null}
        <View style={{ marginTop: 8 }}>
          {projects.map((p) => {
            const seCount = (p.site_engineers || []).length;
            const pmCount = (p.project_managers || []).length;
            return (
              <TouchableOpacity
                key={p.project_id}
                testID={`project-row-${p.code}`}
                onPress={() => isAdmin && openTeam(p)}
                disabled={!isAdmin}
                activeOpacity={isAdmin ? 0.6 : 1}
                style={styles.row}
              >
                <View style={{ flex: 1 }}>
                  <Text style={{ fontWeight: "700" }}>{p.code}</Text>
                  <Text style={{ color: theme.colors.textMuted, fontSize: 12 }}>{p.name} · {p.site}</Text>
                  <Text style={{ color: theme.colors.textMuted, fontSize: 11, marginTop: 2 }}>
                    {seCount} engineer(s) · {pmCount} PM(s)
                  </Text>
                </View>
                {isAdmin ? <Ionicons name="people-outline" size={20} color={theme.colors.primary} /> : null}
              </TouchableOpacity>
            );
          })}
        </View>
      </Card>

      <Card style={{ marginTop: 12 }} testID="vendors-card">
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <H2>Vendors ({vendors.length})</H2>
          {(isAdmin || user?.role === "purchase") ? (
            <TouchableOpacity testID="add-vendor-shortcut" onPress={() => router.push("/masters")} style={{ padding: 6 }}>
              <Ionicons name="add-circle-outline" size={22} color={theme.colors.primary} />
            </TouchableOpacity>
          ) : null}
        </View>
        <View style={{ marginTop: 8 }}>
          {vendors.map((v) => (
            <View key={v.vendor_id} style={styles.row}>
              <View><Text style={{ fontWeight: "700" }}>{v.name}</Text><Text style={{ color: theme.colors.textMuted, fontSize: 12 }}>{v.gstin}</Text></View>
            </View>
          ))}
        </View>
      </Card>

      {isAdmin ? (
        <Card style={{ marginTop: 12 }} testID="users-card">
          <H2>Users & Roles ({users.length})</H2>
          <View style={{ marginTop: 8 }}>
            {users.map((u) => (
              <View key={u.user_id} style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={{ fontWeight: "700" }}>{u.name}</Text>
                  <Text style={{ color: theme.colors.textMuted, fontSize: 12 }}>{u.email}</Text>
                </View>
                <TouchableOpacity testID={`edit-role-${u.email}`} onPress={() => setRoleEdit(u)} style={styles.rolePill}>
                  <Text style={{ fontSize: 11, fontWeight: "700", color: theme.colors.primary }}>{u.role}</Text>
                  <Ionicons name="chevron-forward" size={14} color={theme.colors.primary} />
                </TouchableOpacity>
              </View>
            ))}
          </View>
        </Card>
      ) : null}

      <Modal visible={!!roleEdit} transparent animationType="fade" onRequestClose={() => setRoleEdit(null)}>
        <View style={styles.modalBg}>
          <View style={[styles.modal, { marginBottom: insets.bottom + 16 }]}>
            <Text style={{ fontWeight: "800", fontSize: 16, marginBottom: 8 }}>Change Role — {roleEdit?.name}</Text>
            {ROLES.map((r) => (
              <TouchableOpacity key={r.key} testID={`set-role-${r.key}`} onPress={() => setRole(roleEdit.user_id, r.key)} style={styles.roleOpt}>
                <Text>{r.label}</Text>
                {roleEdit?.role === r.key ? <Ionicons name="checkmark" size={20} color={theme.colors.primary} /> : null}
              </TouchableOpacity>
            ))}
            <Btn title="Cancel" variant="outline" onPress={() => setRoleEdit(null)} style={{ marginTop: 8 }} />
          </View>
        </View>
      </Modal>

      {/* Team edit modal */}
      <Modal visible={!!teamEdit} transparent animationType="fade" onRequestClose={() => setTeamEdit(null)}>
        <View style={styles.modalBg}>
          <View style={[styles.modal, { marginBottom: insets.bottom + 16, maxHeight: "85%" }]}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
              <View style={{ flex: 1 }}>
                <Text style={{ fontWeight: "800", fontSize: 16 }}>Project Team</Text>
                <Text style={{ fontSize: 12, color: theme.colors.textMuted, marginTop: 2 }}>
                  {teamEdit?.code} — {teamEdit?.name}
                </Text>
              </View>
              <TouchableOpacity testID="close-team-btn" onPress={() => setTeamEdit(null)}>
                <Ionicons name="close" size={22} />
              </TouchableOpacity>
            </View>
            <ScrollView style={{ marginTop: 6 }}>
              <Text style={styles.teamHead}>Site Engineers</Text>
              {engineers.map((eu) => (
                <TouchableOpacity key={eu.user_id} testID={`toggle-se-${eu.email}`}
                  onPress={() => toggleTeam(teamSe, setTeamSe, eu.user_id)} style={styles.teamRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontWeight: "600" }}>{eu.name}</Text>
                    <Text style={{ fontSize: 11, color: theme.colors.textMuted }}>{eu.email} · {eu.role}</Text>
                  </View>
                  <View style={[styles.checkbox, { backgroundColor: teamSe.includes(eu.user_id) ? theme.colors.primary : "#fff", borderColor: teamSe.includes(eu.user_id) ? theme.colors.primary : theme.colors.borderStrong }]}>
                    {teamSe.includes(eu.user_id) ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
                  </View>
                </TouchableOpacity>
              ))}
              <Text style={[styles.teamHead, { marginTop: 12 }]}>Project Managers</Text>
              {pms.map((pu) => (
                <TouchableOpacity key={pu.user_id} testID={`toggle-pm-${pu.email}`}
                  onPress={() => toggleTeam(teamPm, setTeamPm, pu.user_id)} style={styles.teamRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontWeight: "600" }}>{pu.name}</Text>
                    <Text style={{ fontSize: 11, color: theme.colors.textMuted }}>{pu.email} · {pu.role}</Text>
                  </View>
                  <View style={[styles.checkbox, { backgroundColor: teamPm.includes(pu.user_id) ? theme.colors.primary : "#fff", borderColor: teamPm.includes(pu.user_id) ? theme.colors.primary : theme.colors.borderStrong }]}>
                    {teamPm.includes(pu.user_id) ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
                  </View>
                </TouchableOpacity>
              ))}
              <Text style={[styles.teamHead, { marginTop: 16 }]}>Sites</Text>
              {(teamEdit?.sites || []).filter((s: any) => s.active !== false).map((s: any) => (
                <View key={s.site_id} style={styles.siteBox} testID={`site-row-${s.site_id}`}>
                  <View style={{ flexDirection: "row", alignItems: "center" }}>
                    <TouchableOpacity onPress={() => setSiteExpand(siteExpand === s.site_id ? null : s.site_id)} style={{ flex: 1 }}>
                      <Text style={{ fontWeight: "700" }}>{s.name}</Text>
                      {s.location ? <Text style={{ fontSize: 11, color: theme.colors.textMuted }}>{s.location}</Text> : null}
                      <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>
                        {(s.site_engineers || []).length} engineer(s)
                      </Text>
                    </TouchableOpacity>
                    <TouchableOpacity testID={`remove-site-${s.site_id}`} onPress={() => removeSite(s.site_id)} style={{ padding: 6 }}>
                      <Ionicons name="trash-outline" size={16} color={theme.colors.danger} />
                    </TouchableOpacity>
                  </View>
                  {siteExpand === s.site_id ? (
                    <View style={{ marginTop: 8, paddingTop: 8, borderTopWidth: 1, borderTopColor: theme.colors.border }}>
                      {engineers.map((eu) => (
                        <TouchableOpacity key={eu.user_id} testID={`site-toggle-${s.site_id}-${eu.email}`}
                          onPress={() => toggleSiteEngineer(s, eu.user_id)}
                          style={styles.teamRow}>
                          <View style={{ flex: 1 }}>
                            <Text style={{ fontWeight: "600", fontSize: 13 }}>{eu.name}</Text>
                            <Text style={{ fontSize: 10, color: theme.colors.textMuted }}>{eu.email}</Text>
                          </View>
                          <View style={[styles.checkbox, {
                            backgroundColor: (s.site_engineers || []).includes(eu.user_id) ? theme.colors.primary : "#fff",
                            borderColor: (s.site_engineers || []).includes(eu.user_id) ? theme.colors.primary : theme.colors.borderStrong,
                          }]}>
                            {(s.site_engineers || []).includes(eu.user_id) ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
                          </View>
                        </TouchableOpacity>
                      ))}
                    </View>
                  ) : null}
                </View>
              ))}
              {/* Add site */}
              <View style={styles.addSite}>
                <TextInput testID="new-site-name" value={newSiteName} onChangeText={setNewSiteName}
                  placeholder="New site name (e.g. Tower A)" style={styles.inp} />
                <TextInput testID="new-site-loc" value={newSiteLoc} onChangeText={setNewSiteLoc}
                  placeholder="Location (optional)" style={[styles.inp, { marginTop: 6 }]} />
                <TouchableOpacity testID="add-site-btn" onPress={addSite} style={styles.addBtn}>
                  <Ionicons name="add-circle-outline" size={16} color="#fff" />
                  <Text style={{ color: "#fff", fontWeight: "700", marginLeft: 4, fontSize: 12 }}>Add Site</Text>
                </TouchableOpacity>
              </View>
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <View style={{ flex: 1 }}><Btn title="Close" variant="outline" onPress={() => setTeamEdit(null)} /></View>
              <View style={{ flex: 1 }}>
                <Btn testID="save-team-btn" title={savingTeam ? "Saving…" : "Save Team"} variant="action" onPress={saveTeam} disabled={savingTeam} />
              </View>
            </View>
          </View>
        </View>
      </Modal>
    </AppShell>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 8, borderTopWidth: 1, borderTopColor: theme.colors.border },
  rolePill: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: theme.colors.surface2, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modal: { backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 20 },
  checkbox: { width: 22, height: 22, borderWidth: 2, borderRadius: 4, alignItems: "center", justifyContent: "center" },
  teamHead: { fontSize: 11, fontWeight: "800", color: theme.colors.textMuted, textTransform: "uppercase", letterSpacing: 1.5, marginBottom: 4 },
  teamRow: { flexDirection: "row", alignItems: "center", paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  roleOpt: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 14, borderTopWidth: 1, borderTopColor: theme.colors.border },
  siteBox: { padding: 10, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 6, marginBottom: 8 },
  addSite: { padding: 10, borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, marginTop: 6, borderStyle: "dashed" },
  inp: { borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, minHeight: 40, paddingHorizontal: 10, backgroundColor: "#fff", fontSize: 13 },
  addBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: theme.colors.primary, paddingVertical: 10, borderRadius: 6, marginTop: 8 },
});
