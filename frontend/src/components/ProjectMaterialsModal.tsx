import React, { useEffect, useState, useCallback, useMemo } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal, TextInput } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { theme } from "@/src/theme";
import { Btn, Label, Muted } from "@/src/components/ui";

type Props = {
  projectId: string;
  onClose: () => void;
  onChanged?: () => void;
};

type BoqOption = {
  boq_ref: string; description: string; unit: string;
  qty_remaining: number;
};

export default function ProjectMaterialsModal({ projectId, onClose, onChanged }: Props) {
  const insets = useSafeAreaInsets();
  const [project, setProject] = useState<any>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [materials, setMaterials] = useState<any[]>([]);
  const [boqOptions, setBoqOptions] = useState<BoqOption[]>([]);
  const [source, setSource] = useState<"manual" | "estimator">("manual");
  const [materialUid, setMaterialUid] = useState("");
  const [boqQty, setBoqQty] = useState("");
  const [boqRef, setBoqRef] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editQty, setEditQty] = useState("");

  const load = useCallback(async () => {
    try {
      const [all, mats, pm] = await Promise.all([
        api<any[]>("/projects?all=1"),
        api<any[]>("/materials?status=approved"),
        api<any[]>(`/projects/${projectId}/materials`),
      ]);
      setProject(all.find((x) => x.project_id === projectId));
      setMaterials(mats);
      setRows(pm);
      try {
        setBoqOptions(await api<BoqOption[]>(`/integrations/estimator/boq-options?project_id=${encodeURIComponent(projectId)}`));
      } catch { setBoqOptions([]); }
    } catch (e: any) { setErr(e.message || "Failed to load"); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const assignedUids = useMemo(() => new Set(rows.map((r) => r.material_uid)), [rows]);
  const availableMaterials = materials.filter((m) => !assignedUids.has(m.material_uid));

  const resetForm = () => { setMaterialUid(""); setBoqQty(""); setBoqRef(""); setSource("manual"); };

  const pickEstimatorLine = (opt: BoqOption) => {
    const mat = materials.find((m) => m.description.trim().toLowerCase() === opt.description.trim().toLowerCase());
    if (mat) setMaterialUid(mat.material_uid);
    setBoqQty(String(opt.qty_remaining));
    setBoqRef(opt.boq_ref);
  };

  const assign = async () => {
    setErr("");
    const qty = parseFloat(boqQty);
    if (!materialUid) { setErr("Select a material"); return; }
    if (!qty || qty <= 0) { setErr("Enter a valid BOQ quantity"); return; }
    setSaving(true);
    try {
      await api(`/projects/${projectId}/materials`, {
        method: "POST",
        body: { material_uid: materialUid, boq_qty: qty, source, boq_ref: boqRef || undefined },
      });
      resetForm();
      await load();
      if (onChanged) onChanged();
    } catch (e: any) { setErr(e.message || "Failed to assign"); }
    setSaving(false);
  };

  const startEdit = (row: any) => { setEditingId(row.pm_id); setEditQty(String(row.boq_qty)); };

  const saveEdit = async (row: any) => {
    const qty = parseFloat(editQty);
    if (!qty || qty <= 0) { setErr("Enter a valid BOQ quantity"); return; }
    try {
      await api(`/projects/${projectId}/materials/${row.pm_id}`, { method: "PUT", body: { boq_qty: qty } });
      setEditingId(null);
      await load();
      if (onChanged) onChanged();
    } catch (e: any) { setErr(e.message || "Failed to update"); }
  };

  const remove = async (row: any) => {
    setErr("");
    try {
      await api(`/projects/${projectId}/materials/${row.pm_id}`, { method: "DELETE" });
      await load();
      if (onChanged) onChanged();
    } catch (e: any) { setErr(e.message || "Failed to remove"); }
  };

  if (!project) return null;

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <View style={s.modalBg}>
        <View style={[s.modal, { marginBottom: insets.bottom + 16, maxHeight: "88%" }]}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <View style={{ flex: 1 }}>
              <Text style={{ fontWeight: "800", fontSize: 16 }}>Project Materials & BOQ</Text>
              <Text style={{ fontSize: 12, color: theme.colors.textMuted, marginTop: 2 }}>
                {project.code} — {project.name}
              </Text>
            </View>
            <TouchableOpacity testID="close-pm-btn" onPress={onClose}>
              <Ionicons name="close" size={22} />
            </TouchableOpacity>
          </View>
          {err ? <Text style={{ color: theme.colors.danger, fontSize: 12, marginBottom: 6 }}>{err}</Text> : null}
          <ScrollView style={{ marginTop: 6 }}>
            <Text style={s.head}>Assigned Materials</Text>
            {rows.length === 0 ? <Muted>No materials assigned yet.</Muted> : null}
            {rows.map((row) => {
              const mat = materials.find((m) => m.material_uid === row.material_uid);
              const low = row.balance <= 0;
              return (
                <View key={row.pm_id} style={s.matBox}>
                  <View style={{ flexDirection: "row", alignItems: "flex-start" }}>
                    <View style={{ flex: 1 }}>
                      <Text style={{ fontWeight: "700" }}>{mat?.description || row.material_uid}</Text>
                      <Text style={{ fontSize: 11, color: theme.colors.textMuted }}>
                        {row.material_uid} · Source: {row.source}{row.boq_ref ? ` (${row.boq_ref})` : ""}
                      </Text>
                      {editingId === row.pm_id ? (
                        <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 6 }}>
                          <TextInput testID={`edit-boq-${row.pm_id}`} value={editQty} onChangeText={setEditQty}
                            keyboardType="numeric" style={[s.inp, { flex: 1 }]} />
                          <TouchableOpacity onPress={() => saveEdit(row)}><Ionicons name="checkmark-circle" size={22} color={theme.colors.success} /></TouchableOpacity>
                          <TouchableOpacity onPress={() => setEditingId(null)}><Ionicons name="close-circle" size={22} color={theme.colors.textMuted} /></TouchableOpacity>
                        </View>
                      ) : (
                        <View style={{ flexDirection: "row", gap: 12, marginTop: 6 }}>
                          <Text style={{ fontSize: 12 }}>BOQ: <Text style={{ fontWeight: "700" }}>{row.boq_qty}</Text></Text>
                          <Text style={{ fontSize: 12 }}>Consumed: <Text style={{ fontWeight: "700" }}>{row.consumed_qty}</Text></Text>
                          <Text style={{ fontSize: 12, color: low ? theme.colors.danger : theme.colors.success }}>
                            Balance: <Text style={{ fontWeight: "700" }}>{row.balance}</Text>
                          </Text>
                        </View>
                      )}
                    </View>
                    {editingId === row.pm_id ? null : (
                      <View style={{ flexDirection: "row", gap: 4 }}>
                        <TouchableOpacity testID={`edit-pm-${row.pm_id}`} onPress={() => startEdit(row)} style={{ padding: 6 }}>
                          <Ionicons name="pencil-outline" size={16} color={theme.colors.text} />
                        </TouchableOpacity>
                        <TouchableOpacity testID={`remove-pm-${row.pm_id}`} onPress={() => remove(row)} style={{ padding: 6 }}>
                          <Ionicons name="trash-outline" size={16} color={theme.colors.danger} />
                        </TouchableOpacity>
                      </View>
                    )}
                  </View>
                </View>
              );
            })}

            <Text style={[s.head, { marginTop: 16 }]}>Assign New Material</Text>
            <View style={s.addBox}>
              <View style={{ flexDirection: "row", gap: 8, marginBottom: 8 }}>
                <TouchableOpacity onPress={() => setSource("manual")} style={[s.chip, source === "manual" && s.chipActive]}>
                  <Text style={[s.chipText, source === "manual" && s.chipTextActive]}>Manual Qty</Text>
                </TouchableOpacity>
                <TouchableOpacity onPress={() => setSource("estimator")} style={[s.chip, source === "estimator" && s.chipActive]}>
                  <Text style={[s.chipText, source === "estimator" && s.chipTextActive]}>From Estimator</Text>
                </TouchableOpacity>
              </View>

              {source === "estimator" ? (
                <>
                  <Label>APPROVED ESTIMATE BOQ LINE</Label>
                  {boqOptions.length === 0 ? <Muted>No estimator BOQ lines available for this project.</Muted> : null}
                  {boqOptions.map((opt) => (
                    <TouchableOpacity key={opt.boq_ref} onPress={() => pickEstimatorLine(opt)}
                      style={[s.boqRow, boqRef === opt.boq_ref && s.boqRowActive]}>
                      <Text style={{ fontSize: 12, fontWeight: "600" }}>{opt.boq_ref} · {opt.description}</Text>
                      <Text style={{ fontSize: 11, color: theme.colors.textMuted }}>Remaining {opt.qty_remaining} {opt.unit}</Text>
                    </TouchableOpacity>
                  ))}
                </>
              ) : (
                <>
                  <Label>MATERIAL</Label>
                  <ScrollView style={{ maxHeight: 140 }} nestedScrollEnabled>
                    {availableMaterials.map((m) => (
                      <TouchableOpacity key={m.material_uid} onPress={() => setMaterialUid(m.material_uid)}
                        style={[s.boqRow, materialUid === m.material_uid && s.boqRowActive]}>
                        <Text style={{ fontSize: 12, fontWeight: "600" }}>{m.description}</Text>
                        <Text style={{ fontSize: 11, color: theme.colors.textMuted }}>{m.material_uid}</Text>
                      </TouchableOpacity>
                    ))}
                  </ScrollView>
                </>
              )}

              <Label style={{ marginTop: 8 }}>BOQ QUANTITY</Label>
              <TextInput testID="new-pm-qty" value={boqQty} onChangeText={setBoqQty}
                keyboardType="numeric" placeholder="e.g. 500" style={s.inp} />

              <TouchableOpacity testID="assign-pm-btn" onPress={assign} style={s.addBtn} disabled={saving}>
                <Ionicons name="add-circle-outline" size={16} color="#fff" />
                <Text style={{ color: "#fff", fontWeight: "700", marginLeft: 4, fontSize: 12 }}>
                  {saving ? "Assigning…" : "Assign Material"}
                </Text>
              </TouchableOpacity>
            </View>
          </ScrollView>
          <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
            <View style={{ flex: 1 }}><Btn title="Close" variant="outline" onPress={onClose} /></View>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modal: { backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 20 },
  head: { fontSize: 11, fontWeight: "800", color: theme.colors.textMuted, textTransform: "uppercase", letterSpacing: 1.5, marginBottom: 4 },
  matBox: { padding: 10, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 6, marginBottom: 8 },
  addBox: { padding: 10, borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, marginTop: 6, borderStyle: "dashed" },
  inp: { borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, minHeight: 40, paddingHorizontal: 10, backgroundColor: "#fff", fontSize: 13 },
  addBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: theme.colors.primary, paddingVertical: 10, borderRadius: 6, marginTop: 10 },
  chip: { paddingVertical: 6, paddingHorizontal: 12, borderRadius: 16, borderWidth: 1, borderColor: theme.colors.borderStrong },
  chipActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  chipText: { fontSize: 12, fontWeight: "600", color: theme.colors.text },
  chipTextActive: { color: "#fff" },
  boqRow: { padding: 8, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 6, marginBottom: 4 },
  boqRowActive: { borderColor: theme.colors.primary, backgroundColor: theme.colors.primaryLight || "#eef2ff" },
});
