import React, { useCallback, useEffect, useState } from "react";
import { View, Text, ScrollView, RefreshControl, TouchableOpacity, StyleSheet, Modal, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { AppShell } from "@/src/components/AppShell";
import { api } from "@/src/api";
import { useAccessGuard } from "@/src/hooks/useAccessGuard";
import { Card, H1, H2, Muted, Loader, Empty, Btn, Label, Input } from "@/src/components/ui";
import { theme } from "@/src/theme";
import { ACCESS_ADMIN_EMAIL } from "@/src/access";

const ROLES = ["site_engineer", "pm", "purchase", "gm", "director", "store"];

type Req = {
  request_id: string;
  email: string;
  name?: string;
  attempt_count?: number;
  first_attempt_at?: string;
  last_attempt_at?: string;
  promoted_to_invitation?: string;
};

export default function PendingRequests() {
  const { permitted, loading } = useAccessGuard(["admin"], [ACCESS_ADMIN_EMAIL]);
  const [refreshing, setRefreshing] = useState(false);
  const [rows, setRows] = useState<Req[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [modal, setModal] = useState<Req | null>(null);
  const [role, setRole] = useState<string>("pm");
  const [note, setNote] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setErr(null);
    try { setRows(await api<Req[]>("/admin/access/pending-requests")); }
    catch (e: any) { setErr(e?.message || "Failed to load"); }
  }, []);
  useEffect(() => { if (permitted) load(); }, [permitted, load]);

  const invite = async () => {
    if (!modal) return;
    setBusy(true);
    try {
      await api(`/admin/access/pending-requests/${modal.request_id}/invite`, {
        method: "POST", body: { role, expires_in_hours: 72, note },
      });
      setModal(null); setNote("");
      Alert.alert("Invitation issued", `${modal.email} can now sign in as ${role}.`);
      await load();
    } catch (e: any) {
      Alert.alert("Failed", e?.message || "Could not create invitation.");
    } finally { setBusy(false); }
  };

  if (loading || !permitted) return <AppShell title="Pending Requests"><Loader /></AppShell>;

  return (
    <AppShell title="Pending Requests" testID="pending-requests-screen">
      <ScrollView
        contentContainerStyle={{ paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      >
        <H1>Pending Access Requests</H1>
        <Muted>Uninvited sign-in attempts. Promote to invitation to grant access.</Muted>

        {err ? (
          <Card style={{ marginTop: 12, borderColor: theme.colors.danger }}>
            <Text style={{ color: theme.colors.danger }}>{err}</Text>
          </Card>
        ) : null}

        <View style={{ marginTop: 12 }}>
          {rows.length === 0 ? (
            <Empty title="No pending requests" subtitle="Uninvited sign-in attempts will appear here." />
          ) : rows.map((r) => (
            <View key={r.request_id} style={styles.row} testID={`req-${r.request_id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.email}>{r.email}</Text>
                {r.name ? <Text style={styles.name}>{r.name}</Text> : null}
                <Text style={styles.meta}>
                  {r.attempt_count || 1} attempt(s) · last {relTime(r.last_attempt_at)}
                </Text>
                {r.promoted_to_invitation ? (
                  <Text style={[styles.meta, { color: theme.colors.success, marginTop: 4 }]}>
                    ✓ Invitation issued
                  </Text>
                ) : null}
              </View>
              {r.promoted_to_invitation ? null : (
                <TouchableOpacity
                  testID={`invite-${r.request_id}`}
                  onPress={() => { setModal(r); setRole("pm"); setNote(""); }}
                  style={styles.inviteBtn}
                >
                  <Ionicons name="paper-plane-outline" size={14} color="#fff" />
                  <Text style={styles.inviteBtnText}>Invite</Text>
                </TouchableOpacity>
              )}
            </View>
          ))}
        </View>
      </ScrollView>

      <Modal visible={!!modal} transparent animationType="slide" onRequestClose={() => setModal(null)}>
        <View style={styles.modalBg}>
          <View style={styles.modal}>
            <H2>Invite as…</H2>
            <Muted>{modal?.email}</Muted>

            <Label style={{ marginTop: 16 }}>Assign role</Label>
            <View style={styles.roleGrid}>
              {ROLES.map((r) => (
                <TouchableOpacity
                  key={r}
                  testID={`pick-role-${r}`}
                  onPress={() => setRole(r)}
                  style={[styles.roleChip, role === r && styles.roleChipActive]}
                >
                  <Text style={[styles.roleChipText, role === r && styles.roleChipTextActive]}>{r}</Text>
                </TouchableOpacity>
              ))}
            </View>

            <Input label="Note (optional)" value={note} onChangeText={setNote} placeholder="e.g. new hire, Sales team" />

            <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
              <Btn title="Cancel" variant="outline" onPress={() => setModal(null)} style={{ flex: 1 }} />
              <Btn testID="invite-confirm" title={busy ? "Sending…" : "Send Invitation"} onPress={invite} disabled={busy} style={{ flex: 2 }} />
            </View>
          </View>
        </View>
      </Modal>
    </AppShell>
  );
}

function relTime(iso?: string): string {
  if (!iso) return "-";
  try {
    const then = new Date(iso).getTime();
    const diff = Math.max(0, Date.now() - then);
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
  inviteBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: theme.colors.primary, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8,
  },
  inviteBtnText: { color: "#fff", fontWeight: "700", fontSize: 12 },
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
