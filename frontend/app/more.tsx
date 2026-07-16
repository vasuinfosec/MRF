import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal } from "react-native";
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
          <Btn testID="reports-btn" title="Full Reports Dashboard" variant="primary" onPress={() => router.push("/reports")} />
          <Btn testID="import-btn" title="Excel Bulk Import" variant="outline" onPress={() => router.push("/import")} />
          <Btn testID="audit-log-btn" title="System Audit Trail" variant="outline" onPress={() => router.push("/audit")} />
        </View>
      </Card>

      <Card style={{ marginTop: 12 }} testID="projects-card">
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <H2>Projects ({projects.length})</H2>
        </View>
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
        <H2>Vendors ({vendors.length})</H2>
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
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <View style={{ flex: 1 }}><Btn title="Cancel" variant="outline" onPress={() => setTeamEdit(null)} /></View>
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
});
