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
import ProjectTeamModal from "@/src/components/ProjectTeamModal";

const ROLES = [
  { key: "director", label: "Director" },
  { key: "gm", label: "General Manager" },
  { key: "pm", label: "Project Manager" },
  { key: "purchase", label: "Purchase" },
  { key: "site_engineer", label: "Site Engineer" },
  { key: "store", label: "Stores" },
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
  const [teamPid, setTeamPid] = useState<string | null>(null);

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
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
          <Btn testID="masters-btn" title="Master Data (Projects, Vendors, Sites, Units, Brands, Materials)" variant="primary" onPress={() => router.push("/masters")} />
          <Btn testID="reports-btn" title="Reports Dashboard" variant="outline" onPress={() => router.push("/reports")} />
          {(user?.role === "admin" || user?.role === "director") ? (
            <Btn testID="access-control-btn" title="Access Control (Invitations & Roles)" variant="primary" onPress={() => router.push("/admin/access")} />
          ) : null}
          {(user?.role === "admin" || user?.role === "director") ? (
            <Btn testID="ai-admin-btn" title="AI Spend & Supplier Performance" variant="outline" onPress={() => router.push("/ai-admin")} />
          ) : null}
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
        {isAdmin ? <Muted>Tap Assign Team to manage engineers, PMs and sub-sites.</Muted> : null}
        <View style={{ marginTop: 8 }}>
          {projects.map((p) => {
            const seCount = (p.site_engineers || []).length;
            const pmCount = (p.project_managers || []).length;
            return (
              <View key={p.project_id} style={styles.row} testID={`project-row-${p.code}`}>
                <View style={{ flex: 1 }}>
                  <Text style={{ fontWeight: "700" }}>{p.code}</Text>
                  <Text style={{ color: theme.colors.textMuted, fontSize: 12 }}>{p.name} · {p.site}</Text>
                  <Text style={{ color: theme.colors.textMuted, fontSize: 11, marginTop: 2 }}>
                    {seCount} engineer(s) · {pmCount} PM(s)
                  </Text>
                </View>
                {isAdmin ? (
                  <TouchableOpacity testID={`assign-${p.code}`} onPress={() => setTeamPid(p.project_id)} style={styles.assignBtn}>
                    <Ionicons name="people-outline" size={14} color="#fff" />
                    <Text style={{ color: "#fff", fontSize: 11, fontWeight: "700", marginLeft: 4 }}>Assign</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
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

      {teamPid ? (
        <ProjectTeamModal projectId={teamPid} onClose={() => setTeamPid(null)} onChanged={load} />
      ) : null}
    </AppShell>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 8, borderTopWidth: 1, borderTopColor: theme.colors.border },
  rolePill: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: theme.colors.surface2, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999 },
  assignBtn: { flexDirection: "row", alignItems: "center", backgroundColor: theme.colors.primary, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modal: { backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 20 },
  roleOpt: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 14, borderTopWidth: 1, borderTopColor: theme.colors.border },
});
