/**
 * Task 4 — Material Category Tree (Admin/Director only)
 *
 * Features:
 *   - Hierarchical tree with expand/collapse
 *   - Create at root or under any node
 *   - Rename / Move (change parent_id) / Deactivate
 *   - Cycle prevention & sibling-uniqueness enforced by backend
 *   - CSV template + bulk-import (path-based, e.g. "Fire Alarm/Detectors/Smoke")
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity, TextInput,
  RefreshControl, Alert, Platform, Modal,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { AppShell } from "@/src/components/AppShell";
import { api, backendUrl, getDownloadToken, getToken } from "@/src/api";
import { useAccessGuard } from "@/src/hooks/useAccessGuard";
import { Card, H2, Btn, Label, Muted, Empty, Loader } from "@/src/components/ui";
import { theme } from "@/src/theme";

type CategoryNode = {
  cat_id: string; name: string; parent_id: string | null;
  path: string; level: number; active: boolean;
  children?: CategoryNode[];
};

export default function CategoriesAdminScreen() {
  const { permitted, loading } = useAccessGuard();
  const router = useRouter();
  const [refreshing, setRefreshing] = useState(false);
  const [tree, setTree] = useState<CategoryNode[]>([]);
  const [flat, setFlat] = useState<CategoryNode[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [includeInactive, setIncludeInactive] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Add form (top-level or under selected parent)
  const [addName, setAddName] = useState("");
  const [addParent, setAddParent] = useState<string | null>(null);

  // Edit modal
  const [editing, setEditing] = useState<CategoryNode | null>(null);
  const [ef, setEf] = useState({ name: "", parent_id: "" as string | null, reason: "" });

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [t, f] = await Promise.all([
        api<CategoryNode[]>(`/categories?tree=1${includeInactive ? "&include_inactive=1" : ""}`).catch(() => []),
        api<CategoryNode[]>(`/categories?tree=0${includeInactive ? "&include_inactive=1" : ""}`).catch(() => []),
      ]);
      setTree(t || []); setFlat(f || []);
    } catch (e: any) { setErr(e?.message || "Failed to load"); }
  }, [includeInactive]);

  useEffect(() => { if (permitted) load(); }, [permitted, load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const addCategory = async () => {
    if (!addName.trim()) { setErr("Name required"); return; }
    try {
      await api("/categories", { method: "POST", body: {
        name: addName.trim(), parent_id: addParent,
      } });
      setAddName(""); setAddParent(null);
      if (addParent) setExpanded((s) => ({ ...s, [addParent]: true }));
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const startEdit = (n: CategoryNode) => {
    setEf({ name: n.name, parent_id: n.parent_id, reason: "" });
    setEditing(n);
  };

  const saveEdit = async () => {
    if (!editing) return;
    if (!ef.reason.trim()) { setErr("Reason required"); return; }
    try {
      const body: any = { reason: ef.reason.trim() };
      if (ef.name.trim() !== editing.name) body.name = ef.name.trim();
      if ((ef.parent_id || null) !== editing.parent_id) body.parent_id = ef.parent_id || null;
      if (Object.keys(body).length === 1) { setEditing(null); return; }
      await api(`/categories/${editing.cat_id}`, { method: "PUT", body });
      setEditing(null); load();
    } catch (e: any) { setErr(e.message); }
  };

  const deleteCategory = (n: CategoryNode) => {
    const doIt = async () => {
      try {
        await api(`/categories/${n.cat_id}?reason=${encodeURIComponent("Deactivated via Admin UI")}`, { method: "DELETE" });
        load();
      } catch (e: any) { setErr(e.message); }
    };
    if (Platform.OS === "web") { if (window.confirm(`Deactivate "${n.name}"?`)) doIt(); }
    else Alert.alert("Deactivate", `Deactivate "${n.name}"?`,
      [{ text: "Cancel" }, { text: "Deactivate", style: "destructive", onPress: doIt }]);
  };

  const downloadTemplate = async () => {
    if (Platform.OS !== "web") { Alert.alert("Template", "Use the web dashboard to download CSV templates."); return; }
    const t = await getDownloadToken();
    if (!t) { setErr("Could not mint download token"); return; }
    window.open(`${backendUrl}/api/categories/template.csv?token=${encodeURIComponent(t)}`, "_blank");
  };

  const importCsv = async () => {
    if (Platform.OS !== "web") { Alert.alert("Import", "CSV import is available on web."); return; }
    const input = document.createElement("input");
    input.type = "file"; input.accept = ".csv,text/csv";
    input.onchange = async (ev: any) => {
      const file = ev.target?.files?.[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      try {
        const tok = await getToken();
        const r = await fetch(`${backendUrl}/api/categories/import`, {
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
      } catch (e: any) { setErr(e.message || "Import failed"); }
    };
    input.click();
  };

  const rowsToRender = useMemo(() => {
    const rows: { node: CategoryNode; depth: number }[] = [];
    const walk = (nodes: CategoryNode[], depth: number) => {
      for (const n of nodes) {
        rows.push({ node: n, depth });
        if (expanded[n.cat_id] && n.children?.length) walk(n.children, depth + 1);
      }
    };
    walk(tree, 0);
    return rows;
  }, [tree, expanded]);

  if (loading || !permitted) return <AppShell title="Material Categories"><Loader /></AppShell>;

  return (
    <AppShell title="Material Categories" testID="cat-admin">
      <ScrollView
        contentContainerStyle={{ padding: 16, paddingBottom: 100 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        <Muted>Task 4 — Hierarchical category tree used everywhere materials are selected.</Muted>

        {err ? <Text style={{ color: theme.colors.danger, marginTop: 10 }}>{err}</Text> : null}

        <Card style={{ marginTop: 12 }} testID="cat-add-card">
          <H2>Add Category</H2>
          <Label>NAME</Label>
          <TextInput testID="cat-name" value={addName} onChangeText={setAddName}
            placeholder='e.g. "Detectors" or "Fire Alarm"' style={styles.inp} />
          <View style={{ height: 8 }} />
          <Label>PARENT (leave blank for root)</Label>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, paddingRight: 8 }}>
            <TouchableOpacity onPress={() => setAddParent(null)}
              style={[styles.chip, { borderColor: addParent === null ? theme.colors.primary : theme.colors.border, backgroundColor: addParent === null ? theme.colors.primary : "#fff" }]}>
              <Text style={{ color: addParent === null ? "#fff" : theme.colors.text, fontWeight: "600", fontSize: 12 }}>— Root —</Text>
            </TouchableOpacity>
            {flat.filter((c) => c.active).map((c) => (
              <TouchableOpacity key={c.cat_id} onPress={() => setAddParent(c.cat_id)}
                style={[styles.chip, { borderColor: addParent === c.cat_id ? theme.colors.primary : theme.colors.border, backgroundColor: addParent === c.cat_id ? theme.colors.primary : "#fff" }]}>
                <Text style={{ color: addParent === c.cat_id ? "#fff" : theme.colors.text, fontWeight: "600", fontSize: 12 }}>
                  {c.path}
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
          <View style={{ height: 12 }} />
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            <Btn testID="cat-add" title="Add Category" onPress={addCategory} />
            <Btn variant="outline" title="Template CSV" icon={<Ionicons name="download-outline" size={16} color={theme.colors.text} />} onPress={downloadTemplate} />
            <Btn variant="outline" title="Import CSV" icon={<Ionicons name="cloud-upload-outline" size={16} color={theme.colors.text} />} onPress={importCsv} />
          </View>
        </Card>

        <Card style={{ marginTop: 12 }} testID="cat-tree-card">
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <H2>Category tree</H2>
            <TouchableOpacity onPress={() => setIncludeInactive((v) => !v)} style={{ flexDirection: "row", alignItems: "center" }}>
              <Ionicons name={includeInactive ? "checkbox" : "square-outline"} size={18} color={theme.colors.primary} />
              <Text style={{ marginLeft: 6, color: theme.colors.text, fontSize: 12 }}>Show inactive</Text>
            </TouchableOpacity>
          </View>
          <View style={{ height: 8 }} />
          {rowsToRender.length === 0 ? (
            <Empty msg="No categories yet — add one above or import a CSV." />
          ) : rowsToRender.map(({ node, depth }) => {
            const hasChildren = !!node.children?.length;
            const isOpen = !!expanded[node.cat_id];
            return (
              <View key={node.cat_id} style={[styles.treeRow, { paddingLeft: 8 + depth * 20 }, !node.active && { opacity: 0.5 }]}>
                <TouchableOpacity onPress={() => hasChildren && setExpanded((s) => ({ ...s, [node.cat_id]: !isOpen }))}
                  style={{ padding: 4 }}>
                  <Ionicons name={hasChildren ? (isOpen ? "chevron-down" : "chevron-forward") : "ellipse-outline"} size={16} color={theme.colors.textMuted} />
                </TouchableOpacity>
                <Text style={{ flex: 1, color: theme.colors.text, fontWeight: node.level === 0 ? "700" : "500" }}>
                  {node.name}
                  {!node.active ? <Text style={{ color: theme.colors.danger, fontSize: 11 }}>  (inactive)</Text> : null}
                </Text>
                <TouchableOpacity testID={`edit-${node.cat_id}`} onPress={() => startEdit(node)} style={{ padding: 6 }}>
                  <Ionicons name="pencil" size={16} color={theme.colors.text} />
                </TouchableOpacity>
                {node.active && (
                  <TouchableOpacity onPress={() => deleteCategory(node)} style={{ padding: 6 }}>
                    <Ionicons name="trash-outline" size={16} color={theme.colors.danger} />
                  </TouchableOpacity>
                )}
              </View>
            );
          })}
        </Card>

        <View style={{ height: 20 }} />
        <Btn variant="ghost" title="Back to Masters" onPress={() => router.push("/masters")}
          icon={<Ionicons name="arrow-back" size={16} color={theme.colors.text} />} />
      </ScrollView>

      {/* Edit modal */}
      <Modal visible={!!editing} transparent animationType="fade" onRequestClose={() => setEditing(null)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <H2>Edit category</H2>
            <View style={{ height: 8 }} />
            <Label>NAME</Label>
            <TextInput testID="edit-name" value={ef.name} onChangeText={(v) => setEf({ ...ef, name: v })} style={styles.inp} />
            <View style={{ height: 8 }} />
            <Label>PARENT (leave blank for root)</Label>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}>
              <TouchableOpacity onPress={() => setEf({ ...ef, parent_id: null })}
                style={[styles.chip, { borderColor: ef.parent_id === null ? theme.colors.primary : theme.colors.border, backgroundColor: ef.parent_id === null ? theme.colors.primary : "#fff" }]}>
                <Text style={{ color: ef.parent_id === null ? "#fff" : theme.colors.text, fontSize: 12, fontWeight: "600" }}>— Root —</Text>
              </TouchableOpacity>
              {flat.filter((c) => c.active && c.cat_id !== editing?.cat_id).map((c) => (
                <TouchableOpacity key={c.cat_id} onPress={() => setEf({ ...ef, parent_id: c.cat_id })}
                  style={[styles.chip, { borderColor: ef.parent_id === c.cat_id ? theme.colors.primary : theme.colors.border, backgroundColor: ef.parent_id === c.cat_id ? theme.colors.primary : "#fff" }]}>
                  <Text style={{ color: ef.parent_id === c.cat_id ? "#fff" : theme.colors.text, fontSize: 12, fontWeight: "600" }}>{c.path}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <View style={{ height: 8 }} />
            <Label>REASON (required)</Label>
            <TextInput testID="edit-reason" value={ef.reason} onChangeText={(v) => setEf({ ...ef, reason: v })}
              placeholder="Why is this changing?" style={styles.inp} />
            <View style={{ height: 12 }} />
            <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 8 }}>
              <Btn variant="ghost" title="Cancel" onPress={() => setEditing(null)} />
              <Btn testID="edit-save" title="Save" onPress={saveEdit} />
            </View>
          </View>
        </View>
      </Modal>
    </AppShell>
  );
}

const styles = StyleSheet.create({
  inp: {
    borderWidth: 1, borderColor: theme.colors.borderStrong,
    borderRadius: theme.radius.md, paddingHorizontal: 12, paddingVertical: 10,
    fontSize: 14, backgroundColor: "#fff", color: theme.colors.text,
  },
  chip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1 },
  treeRow: {
    flexDirection: "row", alignItems: "center",
    borderBottomWidth: 1, borderBottomColor: theme.colors.border,
    paddingVertical: 8,
  },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.35)", justifyContent: "center", padding: 20 },
  modalCard: { backgroundColor: "#fff", borderRadius: 14, padding: 16 },
});
