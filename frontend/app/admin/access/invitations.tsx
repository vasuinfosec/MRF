import React, { useCallback, useEffect, useState } from "react";
import { View, Text, ScrollView, RefreshControl, TouchableOpacity, StyleSheet, Modal, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { AppShell } from "@/src/components/AppShell";
import { api } from "@/src/api";
import { useAccessGuard } from "@/src/hooks/useAccessGuard";
import { Card, H1, H2, Muted, Loader, Empty, Btn, Label, Input, Pill } from "@/src/components/ui";
import { theme } from "@/src/theme";
import { ACCESS_ADMIN_EMAIL } from "@/src/access";

const ROLES = ["site_engineer", "pm", "purchase", "gm", "director", "store"];

type Inv = {
  invitation_id: string;
  email: string;
  role: string;
  note?: string;
  issued_at?: string;
  expires_at?: string;
  consumed?: boolean;
  consumed_at?: string;
  from_request_id?: string;
};

export default function Invitations() {
  const { permitted, loading } = useAccessGuard(["admin"], [ACCESS_ADMIN_EMAIL]);
  const [refreshing, setRefreshing] = useState(false);
  const [rows, setRows] = useState<Inv[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Inv | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<string>("pm");
  const [hours, setHours] = useState<string>("72");
  const [note, setNote] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setErr(null);
    try { setRows(await api<Inv[]>("/admin/access/invitations")); }
    catch (e: any) { setErr(e?.message || "Failed to load"); }
  }, []);
  useEffect(() => { if (permitted) load(); }, [permitted, load]);

  const resetForm = () => {
    setCreating(false);
    setEditing(null);
    setEmail("");
    setRole("pm");
    setHours("72");
    setNote("");
  };

  const openCreate = () => {
    resetForm();
    setCreating(true);
  };

  const openEdit = (inv: Inv) => {
    setCreating(false);
    setEditing(inv);
    setEmail(inv.email);
    setRole(inv.role);
    setHours("72");
    setNote(inv.note || "");
  };

  const save = async () => {
    if (!email.includes("@")) { Alert.alert("Invalid", "Enter a valid email."); return; }
    setBusy(true);
    try {
      await api(
        editing
          ? `/admin/access/invitations/${editing.invitation_id}`
          : "/admin/access/invitations",
        {
        method: editing ? "PUT" : "POST",
        body: { email: email.trim().toLowerCase(), role, expires_in_hours: Number(hours) || 72, note },
      });
      resetForm();
      await load();
    } catch (e: any) {
      Alert.alert("Failed", e?.message || "Could not save email access.");
    } finally { setBusy(false); }
  };

  const revoke = (iid: string, email: string) => {
    Alert.alert(
      "Revoke invitation?",
      `${email} will no longer be able to sign in with this invitation.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Revoke", style: "destructive", onPress: async () => {
            try {
              await api(`/admin/access/invitations/${iid}`, { method: "DELETE" });
              await load();
            } catch (e: any) {
              Alert.alert("Failed", e?.message || "Could not revoke.");
            }
          },
        },
      ]
    );
  };

  if (loading || !permitted) return <AppShell title="Invitations"><Loader /></AppShell>;

  const open = rows.filter((r) => !r.consumed && !isExpired(r.expires_at));
  const consumed = rows.filter((r) => r.consumed);
  const expired = rows.filter((r) => !r.consumed && isExpired(r.expires_at));

  return (
    <AppShell title="Invitations" testID="invitations-screen">
      <ScrollView
        contentContainerStyle={{ paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      >
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <View style={{ flex: 1 }}>
            <H1>Google Login Access</H1>
            <Muted>Only emails added here can sign in, with the assigned role.</Muted>
          </View>
          <TouchableOpacity testID="new-invitation-btn" onPress={openCreate} style={styles.newBtn}>
            <Ionicons name="add" size={22} color="#fff" />
          </TouchableOpacity>
        </View>

        {err ? (
          <Card style={{ marginTop: 12, borderColor: theme.colors.danger }}>
            <Text style={{ color: theme.colors.danger }}>{err}</Text>
          </Card>
        ) : null}

        <Section title={`Open (${open.length})`}>
          {open.length === 0 ? <Empty title="No open invitations" /> : open.map((i) => (
            <InviteRow key={i.invitation_id} inv={i} onEdit={() => openEdit(i)} onRevoke={() => revoke(i.invitation_id, i.email)} />
          ))}
        </Section>

        {consumed.length > 0 ? (
          <Section title={`Consumed (${consumed.length})`}>
            {consumed.map((i) => <InviteRow key={i.invitation_id} inv={i} />)}
          </Section>
        ) : null}

        {expired.length > 0 ? (
          <Section title={`Expired (${expired.length})`}>
            {expired.map((i) => <InviteRow key={i.invitation_id} inv={i} onEdit={() => openEdit(i)} onRevoke={() => revoke(i.invitation_id, i.email)} />)}
          </Section>
        ) : null}
      </ScrollView>

      <Modal visible={creating || !!editing} transparent animationType="slide" onRequestClose={resetForm}>
        <View style={styles.modalBg}>
          <View style={styles.modal}>
            <H2>{editing ? "Update Email Access" : "Add Email Access"}</H2>
            <Input label="Email" value={email} onChangeText={setEmail} placeholder="user@vasuinfosec.com" autoCapitalize="none" keyboardType="email-address" />
            <Label>Role</Label>
            <View style={styles.roleGrid}>
              {ROLES.map((r) => (
                <TouchableOpacity key={r} testID={`role-${r}`} onPress={() => setRole(r)}
                  style={[styles.roleChip, role === r && styles.roleChipActive]}>
                  <Text style={[styles.roleChipText, role === r && styles.roleChipTextActive]}>{r}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <Input label="Expires in (hours)" value={hours} onChangeText={setHours} keyboardType="numeric" />
            <Input label="Note (optional)" value={note} onChangeText={setNote} placeholder="e.g. new hire, replacement for X" />
            <View style={{ flexDirection: "row", gap: 8 }}>
              <Btn title="Cancel" variant="outline" onPress={resetForm} style={{ flex: 1 }} />
              <Btn testID="create-invitation-confirm" title={busy ? "Saving…" : "Save Access"} onPress={save} disabled={busy} style={{ flex: 2 }} />
            </View>
          </View>
        </View>
      </Modal>
    </AppShell>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={{ marginTop: 16 }}>
      <H2>{title}</H2>
      <View style={{ marginTop: 8 }}>{children}</View>
    </View>
  );
}

function InviteRow({ inv, onEdit, onRevoke }: { inv: Inv; onEdit?: () => void; onRevoke?: () => void }) {
  const state = inv.consumed ? "approved" : isExpired(inv.expires_at) ? "rejected" : "pm_review";
  return (
    <View style={styles.row}>
      <View style={{ flex: 1 }}>
        <Text style={styles.email}>{inv.email}</Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 }}>
          <View style={styles.rolePill}><Text style={styles.rolePillText}>{inv.role}</Text></View>
          <Pill status={state} />
        </View>
        {inv.note ? <Text style={styles.note}>{inv.note}</Text> : null}
        <Text style={styles.meta}>
          issued {rel(inv.issued_at)} · expires {rel(inv.expires_at)}
        </Text>
      </View>
      <View style={{ flexDirection: "row" }}>
        {onEdit ? (
          <TouchableOpacity onPress={onEdit} style={styles.iconBtn} testID={`edit-${inv.invitation_id}`}>
            <Ionicons name="pencil-outline" size={18} color={theme.colors.primary} />
          </TouchableOpacity>
        ) : null}
        {onRevoke ? (
          <TouchableOpacity onPress={onRevoke} style={styles.iconBtn} testID={`revoke-${inv.invitation_id}`}>
            <Ionicons name="trash-outline" size={18} color={theme.colors.danger} />
          </TouchableOpacity>
        ) : null}
      </View>
    </View>
  );
}

function isExpired(iso?: string): boolean {
  if (!iso) return false;
  try { return new Date(iso).getTime() < Date.now(); } catch { return false; }
}
function rel(iso?: string): string {
  if (!iso) return "-";
  try {
    const t = new Date(iso).getTime();
    const now = Date.now();
    const diff = t - now;
    const abs = Math.abs(diff);
    const m = Math.floor(abs / 60000);
    if (m < 60) return `${diff < 0 ? m + "m ago" : "in " + m + "m"}`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${diff < 0 ? h + "h ago" : "in " + h + "h"}`;
    const d = Math.floor(h / 24);
    return `${diff < 0 ? d + "d ago" : "in " + d + "d"}`;
  } catch { return iso; }
}

const styles = StyleSheet.create({
  newBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.colors.primary, alignItems: "center", justifyContent: "center" },
  row: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 14, borderWidth: 1, borderColor: theme.colors.border,
    borderRadius: theme.radius.md, marginBottom: 8, backgroundColor: theme.colors.bg,
  },
  email: { fontWeight: "700", color: theme.colors.text, fontSize: 14 },
  note: { color: theme.colors.textSecondary, fontSize: 12, marginTop: 4 },
  meta: { color: theme.colors.textMuted, fontSize: 11, marginTop: 4 },
  rolePill: { backgroundColor: theme.colors.surface2, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  rolePillText: { fontSize: 10, fontWeight: "700", color: theme.colors.primary, letterSpacing: 0.6 },
  iconBtn: { padding: 8 },
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
