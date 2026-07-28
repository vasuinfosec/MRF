import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, ScrollView, RefreshControl, TouchableOpacity, StyleSheet, Modal, Alert, TextInput, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { AppShell } from "@/src/components/AppShell";
import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useAccessGuard } from "@/src/hooks/useAccessGuard";
import { Card, H1, H2, Muted, Loader, Empty, Btn, Label } from "@/src/components/ui";
import { theme } from "@/src/theme";
import { ACCESS_ADMIN_EMAIL } from "@/src/access";

const ROLES = ["site_engineer", "pm", "purchase", "gm", "director", "store"];

type U = {
  user_id: string;
  email: string;
  name: string;
  role: string;
  roles?: string[];
  is_active: boolean;
};

export default function UsersAndRoles() {
  const { permitted, loading } = useAccessGuard(["admin"], [ACCESS_ADMIN_EMAIL]);
  const { user: me } = useAuth();
  const [refreshing, setRefreshing] = useState(false);
  const [rows, setRows] = useState<U[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<"active" | "inactive" | "all">("active");
  const [editing, setEditing] = useState<U | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setErr(null);
    try { setRows(await api<U[]>("/users")); }
    catch (e: any) { setErr(e?.message || "Failed to load"); }
  }, []);
  useEffect(() => { if (permitted) load(); }, [permitted, load]);

  const shown = useMemo(() => {
    const query = q.trim().toLowerCase();
    return rows.filter((u) => {
      if (filter === "active" && !u.is_active) return false;
      if (filter === "inactive" && u.is_active) return false;
      if (!query) return true;
      return (u.email || "").toLowerCase().includes(query) || (u.name || "").toLowerCase().includes(query);
    });
  }, [rows, q, filter]);

  const openEdit = (u: U) => {
    const cur = new Set(u.roles && u.roles.length ? u.roles : (u.role ? [u.role] : []));
    setPicked(cur);
    setEditing(u);
  };
  const toggleRole = (r: string) => {
    const n = new Set(picked);
    if (n.has(r)) n.delete(r); else n.add(r);
    setPicked(n);
  };
  const save = async () => {
    if (!editing) return;
    if (picked.size === 0) { Alert.alert("Pick at least one role"); return; }
    setBusy(true);
    try {
      await api(`/admin/access/users/${editing.user_id}/roles`, {
        method: "POST", body: { roles: Array.from(picked) },
      });
      setEditing(null);
      await load();
    } catch (e: any) {
      const msg = friendlyError(e?.message);
      Alert.alert("Cannot update roles", msg);
    } finally { setBusy(false); }
  };

  const deactivate = (u: U) => {
    if (u.user_id === me?.user_id) { Alert.alert("Not allowed", "You cannot deactivate your own account."); return; }
    if (Platform.OS === "ios") {
      Alert.prompt(
        "Deactivate user",
        `Reason for deactivating ${u.email}?`,
        async (reason) => {
          if (!reason) return;
          try {
            await api(`/admin/access/users/${u.user_id}/deactivate`, { method: "POST", body: { reason } });
            await load();
          } catch (e: any) {
            Alert.alert("Cannot deactivate", friendlyError(e?.message));
          }
        }
      );
      return;
    }

    // Alert.prompt is iOS-only. Fall back to a two-step confirmation.
    Alert.alert(
      "Deactivate user",
      `Deactivate ${u.email}? All their sessions will be terminated.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Deactivate", style: "destructive", onPress: async () => {
            try {
              await api(`/admin/access/users/${u.user_id}/deactivate`, {
                method: "POST", body: { reason: "Deactivated via Admin Console" },
              });
              await load();
            } catch (e: any) { Alert.alert("Cannot deactivate", friendlyError(e?.message)); }
          },
        },
      ]
    );
  };

  if (loading || !permitted) return <AppShell title="Users & Roles"><Loader /></AppShell>;

  return (
    <AppShell title="Users & Roles" testID="users-roles-screen">
      <ScrollView
        contentContainerStyle={{ paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      >
        <H1>Users & Roles</H1>
        <Muted>Multi-role assignment · guardrails prevent self-elevation and last-Director removal.</Muted>

        {err ? (
          <Card style={{ marginTop: 12, borderColor: theme.colors.danger }}>
            <Text style={{ color: theme.colors.danger }}>{err}</Text>
          </Card>
        ) : null}

        <View style={styles.searchWrap}>
          <Ionicons name="search-outline" size={16} color={theme.colors.textMuted} />
          <TextInput
            testID="user-search"
            value={q}
            onChangeText={setQ}
            placeholder="Search name or email"
            placeholderTextColor={theme.colors.textMuted}
            style={styles.searchInput}
            autoCapitalize="none"
          />
        </View>

        <View style={styles.filterRow}>
          {(["active", "inactive", "all"] as const).map((f) => (
            <TouchableOpacity key={f} testID={`filter-${f}`} onPress={() => setFilter(f)}
              style={[styles.filterChip, filter === f && styles.filterChipActive]}>
              <Text style={[styles.filterChipText, filter === f && styles.filterChipTextActive]}>{f}</Text>
            </TouchableOpacity>
          ))}
          <Text style={{ marginLeft: "auto", color: theme.colors.textMuted, fontSize: 12 }}>{shown.length} shown</Text>
        </View>

        {shown.length === 0 ? (
          <Empty title="No users match" />
        ) : shown.map((u) => (
          <View key={u.user_id} style={styles.row} testID={`user-${u.user_id}`}>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Text style={styles.name}>{u.name || u.email}</Text>
                {u.user_id === me?.user_id ? <Text style={styles.youTag}>YOU</Text> : null}
                {!u.is_active ? <Text style={styles.inactiveTag}>INACTIVE</Text> : null}
              </View>
              <Text style={styles.email}>{u.email}</Text>
              <View style={styles.roleChipsRow}>
                {(u.roles && u.roles.length ? u.roles : (u.role ? [u.role] : [])).map((r) => (
                  <View key={r} style={styles.rolePill}>
                    <Text style={styles.rolePillText}>{r}</Text>
                  </View>
                ))}
              </View>
            </View>
            <View style={{ gap: 6 }}>
              <TouchableOpacity testID={`edit-roles-${u.user_id}`} onPress={() => openEdit(u)} style={styles.iconBtn}>
                <Ionicons name="options-outline" size={18} color={theme.colors.primary} />
              </TouchableOpacity>
              {u.is_active && u.user_id !== me?.user_id ? (
                <TouchableOpacity testID={`deactivate-${u.user_id}`} onPress={() => deactivate(u)} style={styles.iconBtn}>
                  <Ionicons name="ban-outline" size={18} color={theme.colors.danger} />
                </TouchableOpacity>
              ) : null}
            </View>
          </View>
        ))}
      </ScrollView>

      <Modal visible={!!editing} transparent animationType="slide" onRequestClose={() => setEditing(null)}>
        <View style={styles.modalBg}>
          <View style={styles.modal}>
            <H2>Manage roles</H2>
            <Muted>{editing?.email}</Muted>
            {editing?.user_id === me?.user_id ? (
              <View style={styles.warn}>
                <Ionicons name="warning-outline" size={16} color={theme.colors.action} />
                <Text style={styles.warnText}>You cannot modify your own roles.</Text>
              </View>
            ) : null}
            <Label style={{ marginTop: 12 }}>Roles (multi-select)</Label>
            <View style={styles.roleGrid}>
              {ROLES.map((r) => {
                const on = picked.has(r);
                return (
                  <TouchableOpacity key={r} testID={`role-${r}`} onPress={() => toggleRole(r)}
                    disabled={editing?.user_id === me?.user_id}
                    style={[styles.roleChip, on && styles.roleChipActive]}>
                    <Ionicons name={on ? "checkmark-circle" : "ellipse-outline"} size={14} color={on ? "#fff" : theme.colors.textMuted} />
                    <Text style={[styles.roleChipText, on && styles.roleChipTextActive]}>{r}</Text>
                  </TouchableOpacity>
                );
              })}
            </View>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <Btn title="Cancel" variant="outline" onPress={() => setEditing(null)} style={{ flex: 1 }} />
              <Btn
                testID="save-roles"
                title={busy ? "Saving…" : "Save"}
                onPress={save}
                disabled={busy || editing?.user_id === me?.user_id || picked.size === 0}
                style={{ flex: 2 }}
              />
            </View>
          </View>
        </View>
      </Modal>
    </AppShell>
  );
}

function friendlyError(msg?: string): string {
  if (!msg) return "Something went wrong.";
  const m = msg.toLowerCase();
  if (m.includes("last_director_protected")) return "Refusing to remove the last active Director. Add another Director first.";
  if (m.includes("cannot modify your own")) return "You cannot modify your own account.";
  if (m.includes("cannot activate or elevate yourself")) return "You cannot activate or elevate yourself.";
  if (m.includes("cannot deactivate yourself")) return "You cannot deactivate yourself.";
  return msg;
}

const styles = StyleSheet.create({
  searchWrap: {
    flexDirection: "row", alignItems: "center", gap: 8,
    borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: theme.radius.md,
    paddingHorizontal: 12, paddingVertical: 4, marginTop: 12, backgroundColor: theme.colors.bg,
  },
  searchInput: { flex: 1, color: theme.colors.text, fontSize: 14, minHeight: 44 },
  filterRow: { flexDirection: "row", gap: 6, alignItems: "center", marginTop: 10, marginBottom: 6 },
  filterChip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: theme.colors.borderStrong },
  filterChipActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  filterChipText: { fontSize: 12, textTransform: "capitalize", color: theme.colors.text, fontWeight: "600" },
  filterChipTextActive: { color: "#fff" },
  row: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 14, borderWidth: 1, borderColor: theme.colors.border,
    borderRadius: theme.radius.md, marginBottom: 8, backgroundColor: theme.colors.bg,
  },
  name: { fontWeight: "700", color: theme.colors.text, fontSize: 14 },
  email: { color: theme.colors.textMuted, fontSize: 12, marginTop: 2 },
  youTag: { fontSize: 9, fontWeight: "800", color: "#fff", backgroundColor: theme.colors.primary, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  inactiveTag: { fontSize: 9, fontWeight: "800", color: "#fff", backgroundColor: theme.colors.danger, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  roleChipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 6 },
  rolePill: { backgroundColor: theme.colors.surface2, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  rolePillText: { fontSize: 10, fontWeight: "700", color: theme.colors.primary, letterSpacing: 0.6 },
  iconBtn: { padding: 8 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modal: { backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 20 },
  warn: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 12, backgroundColor: theme.colors.surface2, padding: 10, borderRadius: 8 },
  warnText: { color: theme.colors.action, fontSize: 12, fontWeight: "600" },
  roleGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 4, marginBottom: 16 },
  roleChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999,
    borderWidth: 1, borderColor: theme.colors.borderStrong, backgroundColor: theme.colors.bg,
  },
  roleChipActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  roleChipText: { color: theme.colors.text, fontWeight: "600", fontSize: 12 },
  roleChipTextActive: { color: "#fff" },
});
