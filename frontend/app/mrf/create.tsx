import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal, Platform } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, H1, H2, Input, Label, Muted, Body } from "@/src/components/ui";
import { theme } from "@/src/theme";

const SYSTEMS = ["Fire Alarm", "Fire Fighting", "Gas Suppression", "Water Mist", "CCTV", "Access Control", "Structured Cabling", "Electrical", "Other"];

export default function CreateMRF() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();

  const [projects, setProjects] = useState<any[]>([]);
  const [masters, setMasters] = useState<any>({ unit: [], brand: [], material: [] });
  const [projectId, setProjectId] = useState("");
  const [site, setSite] = useState("");
  const [requiredBy, setRequiredBy] = useState("");
  const [reqPerson, setReqPerson] = useState(user?.name || "");
  const [systemCat, setSystemCat] = useState("Fire Alarm");
  const [remarks, setRemarks] = useState("");
  const [items, setItems] = useState<any[]>([blankItem()]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [picker, setPicker] = useState<{ type: string; index?: number } | null>(null);

  function blankItem() {
    return {
      description: "", specification: "", part_number: "", unit: "Nos",
      qty_requested: 1, purpose: "", drawing_ref: "", billable: true,
      boq_ref: "", remarks: "",
    };
  }

  useEffect(() => {
    (async () => {
      const [p, m] = await Promise.all([api("/projects"), api("/masters")]);
      setProjects(p); setMasters(m);
      if (p[0]) { setProjectId(p[0].project_id); setSite(p[0].site); }
    })();
  }, []);

  const addItem = () => setItems([...items, blankItem()]);
  const removeItem = (i: number) => setItems(items.filter((_, idx) => idx !== i));
  const updateItem = (i: number, k: string, v: any) => {
    setItems(items.map((it, idx) => (idx === i ? { ...it, [k]: v } : it)));
  };

  const submit = async (asDraft = false) => {
    setErr("");
    if (!projectId) { setErr("Select project"); return; }
    if (!site) { setErr("Site required"); return; }
    if (!requiredBy) { setErr("Required-by date required"); return; }
    if (!items.length || items.some((i) => !i.description)) { setErr("All items must have a description"); return; }
    setSaving(true);
    try {
      const cleanItems = items.map((i) => ({
        ...i,
        qty_requested: Number(i.qty_requested) || 0,
      }));
      const mrf = await api<any>("/mrf", {
        method: "POST",
        body: {
          project_id: projectId,
          site, required_by: requiredBy, requesting_person: reqPerson,
          system_category: systemCat, items: cleanItems, remarks,
        },
      });
      if (!asDraft) {
        await api(`/mrf/${mrf.mrf_id}/submit`, { method: "POST" });
      }
      router.replace(`/mrf/${mrf.mrf_id}` as any);
    } catch (e: any) { setErr(e.message); }
    setSaving(false);
  };

  const currentProject = projects.find((p) => p.project_id === projectId);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity testID="back-btn" onPress={() => router.back()} style={{ padding: 8 }}>
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Create MRF</Text>
        <View style={{ width: 38 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 200 }}>
        <H1>New Material Requisition</H1>
        <Muted>Fill in details. Auto-numbered on save.</Muted>

        <Card style={{ marginTop: 16 }} testID="mrf-form-card">
          <Label>PROJECT</Label>
          <PickerBox testID="picker-project" value={currentProject ? `${currentProject.code} — ${currentProject.name}` : "Select project"}
                    onPress={() => setPicker({ type: "project" })} />

          <Input testID="site-input" label="Site / Location" value={site} onChangeText={setSite} />
          <Input testID="required-by-input" label="Required by (YYYY-MM-DD)" value={requiredBy} onChangeText={setRequiredBy} placeholder="2026-03-15" />
          <Input testID="requester-input" label="Requesting Person" value={reqPerson} onChangeText={setReqPerson} />

          <Label>SYSTEM / CATEGORY</Label>
          <PickerBox testID="picker-system" value={systemCat} onPress={() => setPicker({ type: "system" })} />

          <Input testID="remarks-input" label="Remarks (optional)" value={remarks} onChangeText={setRemarks} multiline />
        </Card>

        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 20 }}>
          <H2>Items ({items.length})</H2>
          <Btn testID="add-item-btn" title="+ Add Item" variant="outline" onPress={addItem} />
        </View>

        {items.map((it, i) => (
          <Card key={i} style={{ marginTop: 10 }} testID={`item-card-${i}`}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
              <Text style={styles.itemHead}>Item {i + 1}</Text>
              {items.length > 1 ? (
                <TouchableOpacity testID={`remove-item-${i}`} onPress={() => removeItem(i)}>
                  <Ionicons name="trash-outline" size={18} color={theme.colors.danger} />
                </TouchableOpacity>
              ) : null}
            </View>
            <Input testID={`item-desc-${i}`} label="Description *" value={it.description} onChangeText={(v) => updateItem(i, "description", v)} />
            <Input testID={`item-spec-${i}`} label="Specification / Brand" value={it.specification} onChangeText={(v) => updateItem(i, "specification", v)} />
            <View style={{ flexDirection: "row", gap: 8 }}>
              <View style={{ flex: 1 }}>
                <Input testID={`item-part-${i}`} label="Part Number" value={it.part_number} onChangeText={(v) => updateItem(i, "part_number", v)} />
              </View>
              <View style={{ flex: 1 }}>
                <Label>UNIT</Label>
                <PickerBox testID={`picker-unit-${i}`} value={it.unit} onPress={() => setPicker({ type: "unit", index: i })} />
              </View>
            </View>
            <Input testID={`item-qty-${i}`} label="Quantity Requested" value={String(it.qty_requested)} onChangeText={(v) => updateItem(i, "qty_requested", v)} keyboardType="decimal-pad" />
            <Input testID={`item-purpose-${i}`} label="Purpose / Work Area" value={it.purpose} onChangeText={(v) => updateItem(i, "purpose", v)} />
            <Input testID={`item-drawing-${i}`} label="Drawing / Reference No." value={it.drawing_ref} onChangeText={(v) => updateItem(i, "drawing_ref", v)} />
            <Input testID={`item-boq-${i}`} label="Client BOQ Reference" value={it.boq_ref} onChangeText={(v) => updateItem(i, "boq_ref", v)} />
            <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 12 }}>
              <TouchableOpacity testID={`item-billable-${i}`} onPress={() => updateItem(i, "billable", !it.billable)} style={styles.checkRow}>
                <View style={[styles.checkbox, { backgroundColor: it.billable ? theme.colors.primary : "#fff", borderColor: it.billable ? theme.colors.primary : theme.colors.borderStrong }]}>
                  {it.billable ? <Ionicons name="checkmark" size={16} color="#fff" /> : null}
                </View>
                <Text style={{ marginLeft: 8, color: theme.colors.text }}>Billable to client</Text>
              </TouchableOpacity>
            </View>
            <Input testID={`item-remarks-${i}`} label="Remarks" value={it.remarks} onChangeText={(v) => updateItem(i, "remarks", v)} />
          </Card>
        ))}

        {err ? <Text style={{ color: theme.colors.danger, marginTop: 12 }} testID="mrf-err">{err}</Text> : null}

        <View style={{ marginTop: 20, gap: 8 }}>
          <Btn testID="submit-mrf-btn" title={saving ? "Submitting…" : "Submit for Approval"} variant="action" onPress={() => submit(false)} disabled={saving} />
          <Btn testID="save-draft-btn" title="Save as Draft" variant="outline" onPress={() => submit(true)} disabled={saving} />
        </View>
      </ScrollView>

      {/* Picker Modal */}
      <Modal visible={!!picker} transparent animationType="fade" onRequestClose={() => setPicker(null)}>
        <TouchableOpacity style={styles.modalBg} activeOpacity={1} onPress={() => setPicker(null)}>
          <View style={[styles.modal, { marginBottom: insets.bottom + 16 }]} onStartShouldSetResponder={() => true}>
            <View style={styles.modalHead}>
              <Text style={{ fontWeight: "700", fontSize: 16 }}>Select {picker?.type}</Text>
              <TouchableOpacity onPress={() => setPicker(null)}><Ionicons name="close" size={22} /></TouchableOpacity>
            </View>
            <ScrollView>
              {picker?.type === "project" && projects.map((p) => (
                <TouchableOpacity key={p.project_id} testID={`opt-${p.code}`} style={styles.opt}
                  onPress={() => { setProjectId(p.project_id); setSite(p.site); setPicker(null); }}>
                  <Text style={{ fontWeight: "600" }}>{p.code} — {p.name}</Text>
                  <Text style={{ color: theme.colors.textMuted, fontSize: 12 }}>{p.site}</Text>
                </TouchableOpacity>
              ))}
              {picker?.type === "system" && SYSTEMS.map((s) => (
                <TouchableOpacity key={s} testID={`opt-sys-${s}`} style={styles.opt} onPress={() => { setSystemCat(s); setPicker(null); }}>
                  <Text>{s}</Text>
                </TouchableOpacity>
              ))}
              {picker?.type === "unit" && (masters.unit || []).map((u: any) => (
                <TouchableOpacity key={u.item_id} testID={`opt-unit-${u.name}`} style={styles.opt}
                  onPress={() => { if (picker.index !== undefined) updateItem(picker.index, "unit", u.name); setPicker(null); }}>
                  <Text>{u.name}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        </TouchableOpacity>
      </Modal>
    </SafeAreaView>
  );
}

function PickerBox({ value, onPress, testID }: { value: string; onPress: () => void; testID?: string }) {
  return (
    <TouchableOpacity testID={testID} onPress={onPress} style={pStyles.pick}>
      <Text style={{ color: theme.colors.text, fontSize: 15 }}>{value}</Text>
      <Ionicons name="chevron-down" size={18} color={theme.colors.textMuted} />
    </TouchableOpacity>
  );
}

const pStyles = StyleSheet.create({
  pick: {
    borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: theme.radius.md,
    paddingHorizontal: 12, minHeight: 48, flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: theme.colors.bg, marginBottom: 12,
  },
});

const styles = StyleSheet.create({
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 8, paddingVertical: 8, backgroundColor: theme.colors.bg,
    borderBottomWidth: 1, borderBottomColor: theme.colors.border,
  },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  itemHead: { fontSize: 14, fontWeight: "700", color: theme.colors.primary, textTransform: "uppercase", letterSpacing: 1 },
  checkRow: { flexDirection: "row", alignItems: "center" },
  checkbox: { width: 22, height: 22, borderWidth: 2, borderRadius: 4, alignItems: "center", justifyContent: "center" },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modal: { backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16, maxHeight: "70%", padding: 16 },
  modalHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: theme.colors.border, marginBottom: 8 },
  opt: { paddingVertical: 14, paddingHorizontal: 8, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
});
