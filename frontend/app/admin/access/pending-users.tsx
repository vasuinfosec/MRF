import React, { useCallback, useEffect, useState } from "react";
import { View, Text, ScrollView, RefreshControl, TouchableOpacity, StyleSheet, Modal, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { AppShell } from "@/src/components/AppShell";
import { api } from "@/src/api";
import { useAccessGuard } from "@/src/hooks/useAccessGuard";
import { Card, H1, H2, Muted, Loader, Empty, Btn, Label } from "@/src/components/ui";
import { theme } from "@/src/theme";
import { ACCESS_ADMIN_EMAIL } from "@/src/access";

const ROLES = ["site_engineer", "pm", "purchase", "gm", "director", "store"];

type PU = {
  user_id: string;
  email: string;
  name?: string;
  role?: string | null;
  roles?: string[];
  is_active?: boolean;
  invited_role?: string;
  pending_since?: string;
  created_at?: string;
};

export default function PendingUsers() {
  const { permitted, loading } = useAccessGuard(["admin"], [ACCESS_ADMIN_EMAIL]);
  const [refreshing, setRefreshing] = useState(false);
  const [rows, setRows] = useState<PU[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [modal, setModal] = useState<PU | null>(null);
  const [role, setRole] = useState<string>("pm");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setErr(null);
    try { setRows(await api<PU[]>("/admin/access/pending-users")); }
    catch (e: any) { setErr(e?.message || "Failed to load"); }
  }, []);
  useEffect(() => { if (permitted) load(); }, [permitted, load]);

  const openModal = (u: PU) => { setModal(u); setRole(u.invited_role || "pm"); };

  const activate = async () => {
    if (!modal) return;
    setBusy(true);
    try {
      await api(`/admin/access/users/${modal.user_id}/activate`, {
        method: "POST", body: { role },
      });
      setModal(null);
      Alert.alert("Activated", `${modal.email} is now active as ${role}.`);
      await load();
    } catch (e: any) {
      Alert.alert("Failed", e?.message || "Could not activate.");
    } finally { setBusy(false); }
  };

  if (loading || !permitted) return <AppShell title="Pending Activation"><Loader /></AppShell>;

  return (
    <AppShell title="Pending Activation" testID="pending-users-screen">
      <ScrollView
        contentContainerStyle={{ paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      >
        <H1>Pending Activation</H1>
        <Muted>Invited users who signed in and are awaiting role activation.</Muted>

        {err ? (
          <Card style={{ marginTop: 12, borderColor: theme.colors.danger }}>
            <Text style={{ color: theme.colors.danger }}>{err}</Text>
          </Card>
        ) : null}

        <View style={{ marginTop: 12 }}>
          {rows.length === 0 ? (
            <Empty title="Nobody waiting" subtitle="Users who complete an invitation flow will appear here." />
          ) : rows.map((u) => (
            <View key={u.user_id} style={styles.row} testID={`pu-${u.user_id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.email}>{u.email}</Text>
                {u.name ? <Text style={styles.name}>{u.name}</Text> : null}
                <Text style={styles.meta}>
                  waiting since {rel(u.pending_since || u.created_at)}
                  {u.invited_role ? ` · invited as ${u.invited_role}` : ""}
                </Text>
              </View>
              <TouchableOpacity
                testID={`activate-${u.user_id}`}
                onPress={() => openModal(u)}
                style={styles.activateBtn}
              >
                <Ionicons name="checkmark" size={16} color="#fff" />
                <Text style={styles.activateBtnText}>Activate</Text>
              </TouchableOpacity>
            </View>
          ))}
        </View>
      </ScrollView>

      <Modal visible={!!modal} transparent animationType="slide" onRequestClose={() => setModal(null)}>
        <View style={styles.modalBg}>
          <View style={styles.modal}>
            <H2>Activate user</H2>
            <Muted>{modal?.email}</Muted>
            <Label style={{ marginTop: 12 }}>Assign role</Label>
            <View style={styles.roleGrid}>
              {ROLES.map((r) => (
                <TouchableOpacity key={r} testID={`role-${r}`} onPress={() => setRole(r)}
                  style={[styles.roleChip, role === r && styles.roleChipActive]}>
                  <Text style={[styles.roleChipText, role === r && styles.roleChipTextActive]}>{r}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <Btn title="Cancel" variant="outline" onPress={() => setModal(null)} style={{ flex: 1 }} />
              <Btn testID="activate-confirm" title={busy ? "Activating…" : "Activate"} onPress={activate} disabled={busy} style={{ flex: 2 }} />
            </View>
          </View>
        </View>
      </Modal>
    </AppShell>
  );
}

function rel(iso?: string): string {
  if (!iso) return "-";
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    return `${d}d ago`;
  } catch { return iso; }
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 14, borderWidth: 1, borderColor: theme.colors.border,
    borderRadius: theme.radius.md, marginBottom: 8, backgroundColor: theme.colors.bg,
  },
  email: { fontWeight: "700", color: theme.colors.text, fontSize: 14 },
  name: { color: theme.colors.textSecondary, fontSize: 12, marginTop: 2 },
  meta: { color: theme.colors.textMuted, fontSize: 11, marginTop: 2 },
  activateBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: theme.colors.success, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8,
  },
  activateBtnText: { color: "#fff", fontWeight: "700", fontSize: 12 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modal: { backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 20 },
  roleGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 4, marginBottom: 16 },
  roleChip: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999,
    borderWidth: 1, borderColor: theme.colors.borderStrong, backgroundColor: theme.colors.bg,
  },
  roleChipActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  roleChipText: { color: theme.colors.text, fontWeight: "600", fontSize: 12 },
  roleChipTextActive: { color: "#fff" },
});
