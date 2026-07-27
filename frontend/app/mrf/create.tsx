import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal, TextInput, Platform } from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import DateTimePicker from "@react-native-community/datetimepicker";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, H1, H2, Label, Muted } from "@/src/components/ui";
import { theme } from "@/src/theme";

// ---- Types ----
type Master = { item_id: string; name: string; category: string; parent_id?: string; value?: string };
type Project = { project_id: string; code: string; name: string; site: string; client?: string; customer_id?: string; sites?: any[]; system_categories?: string[] };
type Customer = { customer_id: string; name: string };
type LineItem = {
  item_line_id?: string;
  material_id?: string;
  description: string;
  unit: string;
  make?: string; make_id?: string;
  model?: string; model_id?: string;
  qty_requested: string;             // stored as string in UI, coerced numeric on submit
  billable: boolean;
  priority: "low" | "normal" | "high" | "urgent";
  remarks: string;
  specification?: string;            // kept for backwards compat but not exposed to SE
};

const PRIORITIES = [
  { key: "low", label: "Low" },
  { key: "normal", label: "Normal" },
  { key: "high", label: "High" },
  { key: "urgent", label: "Urgent" },
] as const;
const BILLABLE_OPTS = [
  { key: "billable", label: "Billable to client" },
  { key: "non_billable", label: "Non-billable (internal / warranty)" },
];

// UI helpers
const iso = (d: Date) => d.toISOString().slice(0, 10);
const today = () => new Date();
const addDays = (d: Date, n: number) => { const c = new Date(d); c.setDate(c.getDate() + n); return c; };
const empty = (): LineItem => ({
  material_id: undefined,
  description: "",
  unit: "",
  make: "", make_id: undefined,
  model: "", model_id: undefined,
  qty_requested: "1",
  billable: true,
  priority: "normal",
  remarks: "",
});

export default function CreateMRF() {
  const router = useRouter();
  const { user } = useAuth();
  const params = useLocalSearchParams<{ edit?: string }>();
  const insets = useSafeAreaInsets();
  const isEdit = !!params.edit;

  // Master data
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [masters, setMasters] = useState<{ unit: Master[]; brand: Master[]; material: Master[]; model: Master[] }>(
    { unit: [], brand: [], material: [], model: [] });
  const [loading, setLoading] = useState(true);

  // Form state
  const [customerId, setCustomerId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [site, setSite] = useState("");
  const [systemCat, setSystemCat] = useState("");
  const [requiredBy, setRequiredBy] = useState<string>(iso(addDays(today(), 7))); // default +7 days
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [remarks, setRemarks] = useState("");
  const [items, setItems] = useState<LineItem[]>([empty()]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  // Picker state
  const [picker, setPicker] = useState<{ type: string; index?: number } | null>(null);
  const [pickerSearch, setPickerSearch] = useState("");

  // Load masters + optionally existing MRF for edit
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cs, ps, mm, mats] = await Promise.all([
        api<Customer[]>("/customers"),
        api<Project[]>("/projects"),
        api<any>("/masters"),
        api<any[]>("/materials?status=approved"),   // Phase 4: only approved materials
      ]);
      setCustomers(cs);
      setProjects(ps);
      // Normalize new-format materials to the picker shape (name = description, includes UID)
      const matAsMaster = mats.map((m) => ({
        item_id: m.material_uid,            // used as key
        material_uid: m.material_uid,       // Phase 4 UID
        name: m.description,
        category: "material",
        value: m.unit || "",
        gst_rate: m.gst_rate,
        item_code: m.item_code,
      }));
      setMasters({
        unit: mm.unit || [], brand: mm.brand || [],
        material: matAsMaster, model: mm.model || [],
      });

      if (isEdit && params.edit) {
        const m = await api<any>(`/mrf/${params.edit}`);
        setCustomerId(m.customer_id || "");
        setProjectId(m.project_id || "");
        setSite(m.site || "");
        setSystemCat(m.system_category || "");
        setRequiredBy(m.required_by || iso(addDays(today(), 7)));
        setRemarks(m.remarks || "");
        setItems((m.items || []).map((it: any) => ({
          item_line_id: it.item_line_id,
          material_id: it.material_id,
          description: it.description || "",
          unit: it.unit || "",
          make: it.make || "", make_id: it.make_id,
          model: it.model || "", model_id: it.model_id,
          qty_requested: String(it.qty_requested ?? 1),
          billable: it.billable ?? true,
          priority: (it.priority as any) || "normal",
          remarks: it.remarks || "",
        })));
      }
    } catch (e: any) { setErr(e.message || "Failed to load"); }
    setLoading(false);
  }, [isEdit, params.edit]);
  useEffect(() => { load(); }, [load]);

  // Derived — projects for selected customer
  const projectsForCustomer = useMemo(() => {
    if (!customerId) return projects;
    return projects.filter((p) => p.customer_id === customerId);
  }, [projects, customerId]);
  const currentProject = projects.find((p) => p.project_id === projectId);
  const projectSites: string[] = useMemo(() => {
    if (!currentProject) return [];
    const subs = (currentProject.sites || []).filter((s: any) => s.active !== false).map((s: any) => s.name);
    return Array.from(new Set([currentProject.site, ...subs].filter(Boolean)));
  }, [currentProject]);
  const projectCategories: string[] = useMemo(() => {
    if (currentProject?.system_categories && currentProject.system_categories.length) return currentProject.system_categories;
    return ["Fire Alarm", "Fire Fighting", "Gas Suppression", "Water Mist", "CCTV", "Access Control", "Structured Cabling", "Electrical", "Other"];
  }, [currentProject]);

  // When customer changes → reset project/site if not compatible
  useEffect(() => {
    if (customerId && projectId) {
      const p = projects.find((x) => x.project_id === projectId);
      if (p && p.customer_id && p.customer_id !== customerId) {
        setProjectId(""); setSite(""); setSystemCat("");
      }
    }
  }, [customerId, projectId, projects]);

  const setItem = (i: number, patch: Partial<LineItem>) => {
    setItems((arr) => arr.map((it, idx) => (idx === i ? { ...it, ...patch } : it)));
  };
  const addItem = () => setItems((arr) => [...arr, empty()]);
  const removeItem = (i: number) => setItems((arr) => arr.length > 1 ? arr.filter((_, idx) => idx !== i) : arr);

  // When material chosen, auto-fill description + unit (and clear make/model unless preserved)
  const chooseMaterial = (i: number, m: any) => {
    const patch: Partial<LineItem> = {
      material_id: m.material_uid || m.item_id,  // Phase 4: prefer MAT-#### UID
      description: m.name,
    };
    if (m.value && !items[i].unit) patch.unit = m.value; // material master default unit
    setItem(i, patch);
    setPicker(null); setPickerSearch("");
  };

  const chooseMake = (i: number, brand: Master) => {
    // Changing make clears the model
    setItem(i, { make: brand.name, make_id: brand.item_id, model: "", model_id: undefined });
    setPicker(null); setPickerSearch("");
  };
  const chooseModel = (i: number, model: Master) => {
    setItem(i, { model: model.name, model_id: model.item_id });
    setPicker(null); setPickerSearch("");
  };

  const submit = async (asDraft: boolean) => {
    setErr("");
    if (!customerId) { setErr("Please select a Customer"); return; }
    if (!projectId) { setErr("Please select a Project"); return; }
    if (!site) { setErr("Please select a Site"); return; }
    if (!systemCat) { setErr("Please select a Material Category"); return; }
    if (!requiredBy) { setErr("Please pick a Required-by date"); return; }
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (!it.material_id || !it.description) { setErr(`Row ${i + 1}: pick a Material`); return; }
      if (!it.unit) { setErr(`Row ${i + 1}: unit is required`); return; }
      const q = Number(it.qty_requested);
      if (!(q > 0)) { setErr(`Row ${i + 1}: qty must be > 0`); return; }
    }
    setSaving(true);
    try {
      const payloadItems = items.map((it) => ({
        item_line_id: it.item_line_id,
        material_id: it.material_id,
        description: it.description,
        unit: it.unit,
        qty_requested: Number(it.qty_requested),
        make: it.make || "", make_id: it.make_id,
        model: it.model || "", model_id: it.model_id,
        billable: it.billable,
        priority: it.priority,
        remarks: it.remarks || "",
      }));
      let mrfId = params.edit;
      if (isEdit) {
        await api(`/mrf/${params.edit}`, { method: "PUT", body: {
          project_id: projectId, site, required_by: requiredBy,
          requesting_person: user?.name || "",
          system_category: systemCat, items: payloadItems, remarks,
        } });
      } else {
        const created = await api<any>("/mrf", { method: "POST", body: {
          project_id: projectId, site, required_by: requiredBy,
          requesting_person: user?.name || "",
          system_category: systemCat, items: payloadItems, remarks,
        } });
        mrfId = created.mrf_id;
      }
      if (!asDraft && mrfId) {
        await api(`/mrf/${mrfId}/submit`, { method: "POST" });
      }
      router.replace(`/mrf/${mrfId}` as any);
    } catch (e: any) { setErr(e.message || "Failed"); }
    setSaving(false);
  };

  // Picker options (searchable)
  const pickerOptions = useMemo(() => {
    if (!picker) return [];
    const q = pickerSearch.trim().toLowerCase();
    const filt = (arr: any[], key = "name") =>
      q ? arr.filter((x) => (x[key] || "").toLowerCase().includes(q)) : arr;
    switch (picker.type) {
      case "customer": return filt(customers.map((c) => ({ ...c, name: `${c.customer_id} · ${c.name}` })));
      case "project": return filt(projectsForCustomer.map((p) => ({ ...p, name: `${p.code} — ${p.name}` })));
      case "site": return projectSites.filter((s) => !q || s.toLowerCase().includes(q)).map((s) => ({ name: s }));
      case "category": return projectCategories.filter((s) => !q || s.toLowerCase().includes(q)).map((s) => ({ name: s }));
      case "material": return filt(masters.material);
      case "make": return filt(masters.brand);
      case "model": {
        const idx = picker.index ?? -1;
        const makeId = idx >= 0 ? items[idx].make_id : null;
        // Show models whose parent_id matches the selected make; if make has no children in master, show all models
        const all = filt(masters.model);
        const scoped = makeId ? all.filter((m) => m.parent_id === makeId) : all;
        return scoped.length ? scoped : all;
      }
      case "unit": return filt(masters.unit);
      case "priority": return PRIORITIES.filter((p) => !q || p.label.toLowerCase().includes(q));
      case "billable": return BILLABLE_OPTS;
      default: return [];
    }
  }, [picker, pickerSearch, customers, projectsForCustomer, projectSites, projectCategories, masters, items]);

  const closePicker = () => { setPicker(null); setPickerSearch(""); };

  const customerLabel = (() => {
    const c = customers.find((x) => x.customer_id === customerId);
    return c ? `${c.customer_id} · ${c.name}` : "Select customer";
  })();
  const projectLabel = currentProject ? `${currentProject.code} — ${currentProject.name}` : "Select project";

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity testID="back-btn" onPress={() => router.back()} style={{ padding: 8 }}>
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>{isEdit ? "Edit MRF" : "New MRF"}</Text>
        <View style={{ width: 38 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 200 }}>
        <H1>{isEdit ? "Edit Material Requisition" : "New Material Requisition"}</H1>
        <Muted>All fields use dropdowns from approved masters. Only Qty and Remarks are typed.</Muted>

        {loading ? <Muted>Loading masters…</Muted> : (
          <>
            {/* Header — Customer / Project / Site / Category / Required Date */}
            <Card style={{ marginTop: 16 }} testID="mrf-form-card">
              <Label>CUSTOMER *</Label>
              <PickerBox testID="pick-customer" value={customerLabel}
                onPress={() => { setPicker({ type: "customer" }); }} />

              <Label>PROJECT *</Label>
              <PickerBox testID="pick-project" value={customerId ? projectLabel : "Select a customer first"}
                disabled={!customerId}
                onPress={() => { setPicker({ type: "project" }); }} />

              <Label>SITE *</Label>
              <PickerBox testID="pick-site" value={site || (currentProject ? "Select site" : "Select project first")}
                disabled={!currentProject}
                onPress={() => setPicker({ type: "site" })} />

              <Label>MATERIAL CATEGORY (SYSTEM) *</Label>
              <PickerBox testID="pick-category" value={systemCat || "Select category"}
                disabled={!currentProject}
                onPress={() => setPicker({ type: "category" })} />

              <Label>REQUIRED BY *</Label>
              <TouchableOpacity testID="pick-date" onPress={() => setShowDatePicker(true)} style={pStyles.pick}>
                <Text style={{ color: theme.colors.text, fontSize: 15 }}>{requiredBy}</Text>
                <Ionicons name="calendar-outline" size={18} color={theme.colors.textMuted} />
              </TouchableOpacity>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4, marginBottom: 8 }}>
                {[
                  { label: "Today", d: today() },
                  { label: "+3d", d: addDays(today(), 3) },
                  { label: "+7d", d: addDays(today(), 7) },
                  { label: "+14d", d: addDays(today(), 14) },
                  { label: "+30d", d: addDays(today(), 30) },
                ].map((q) => (
                  <TouchableOpacity key={q.label} testID={`quick-${q.label}`} onPress={() => setRequiredBy(iso(q.d))}
                    style={[styles.chip, { borderColor: requiredBy === iso(q.d) ? theme.colors.primary : theme.colors.border }]}>
                    <Text style={{ fontSize: 12, color: requiredBy === iso(q.d) ? theme.colors.primary : theme.colors.text }}>{q.label}</Text>
                  </TouchableOpacity>
                ))}
              </View>

              <Label>REMARKS (OPTIONAL — free text)</Label>
              <TextInput testID="mrf-remarks" value={remarks} onChangeText={setRemarks}
                placeholder="Any notes for PM"
                style={styles.textArea} multiline />
            </Card>

            {/* Items */}
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 20 }}>
              <H2>Items ({items.length})</H2>
              <Btn testID="add-item-btn" title="+ Add Item" variant="outline" onPress={addItem} />
            </View>

            {items.map((it, i) => (
              <Card key={i} style={{ marginTop: 10 }} testID={`item-card-${i}`}>
                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                  <Text style={styles.itemHead}>ITEM {i + 1}</Text>
                  {items.length > 1 ? (
                    <TouchableOpacity testID={`remove-item-${i}`} onPress={() => removeItem(i)}>
                      <Ionicons name="trash-outline" size={18} color={theme.colors.danger} />
                    </TouchableOpacity>
                  ) : null}
                </View>

                <Label>MATERIAL *</Label>
                <PickerBox testID={`pick-material-${i}`}
                  value={it.description || (it.material_id ? "Loading…" : "Select material")}
                  onPress={() => setPicker({ type: "material", index: i })} />
                {it.material_id ? (
                  <Text style={styles.uid}>Material UID: {it.material_id}</Text>
                ) : null}

                <View style={{ flexDirection: "row", gap: 8 }}>
                  <View style={{ flex: 1 }}>
                    <Label>MAKE / BRAND</Label>
                    <PickerBox testID={`pick-make-${i}`} value={it.make || "Select make"}
                      onPress={() => setPicker({ type: "make", index: i })} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Label>MODEL</Label>
                    <PickerBox testID={`pick-model-${i}`}
                      value={it.model || (it.make ? "Select model" : "Pick make first")}
                      disabled={!it.make}
                      onPress={() => setPicker({ type: "model", index: i })} />
                  </View>
                </View>

                <View style={{ flexDirection: "row", gap: 8 }}>
                  <View style={{ flex: 1 }}>
                    <Label>UNIT *</Label>
                    <PickerBox testID={`pick-unit-${i}`} value={it.unit || "Select unit"}
                      onPress={() => setPicker({ type: "unit", index: i })} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Label>QTY REQUIRED *</Label>
                    <TextInput testID={`qty-${i}`} value={it.qty_requested}
                      onChangeText={(v) => setItem(i, { qty_requested: v.replace(/[^0-9.]/g, "") })}
                      keyboardType="decimal-pad"
                      placeholder="e.g. 10"
                      style={styles.inp} />
                  </View>
                </View>

                <View style={{ flexDirection: "row", gap: 8 }}>
                  <View style={{ flex: 1 }}>
                    <Label>PRIORITY *</Label>
                    <PickerBox testID={`pick-priority-${i}`} value={PRIORITIES.find((p) => p.key === it.priority)?.label || "Normal"}
                      onPress={() => setPicker({ type: "priority", index: i })} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Label>BILLING *</Label>
                    <PickerBox testID={`pick-billable-${i}`}
                      value={it.billable ? "Billable" : "Non-billable"}
                      onPress={() => setPicker({ type: "billable", index: i })} />
                  </View>
                </View>

                <Label>ITEM REMARKS (optional — free text)</Label>
                <TextInput testID={`remarks-${i}`} value={it.remarks}
                  onChangeText={(v) => setItem(i, { remarks: v })}
                  placeholder="Optional notes"
                  style={styles.textArea} multiline />
              </Card>
            ))}

            {err ? <Text style={{ color: theme.colors.danger, marginTop: 12 }} testID="mrf-err">{err}</Text> : null}

            <View style={{ marginTop: 20, gap: 8 }}>
              <Btn testID="save-draft-btn" title={saving ? "Saving…" : (isEdit ? "Save Changes" : "Save as Draft")} variant="outline" onPress={() => submit(true)} disabled={saving} />
              <Btn testID="submit-mrf-btn" title={saving ? "Submitting…" : "Submit for PM Review"} variant="action" onPress={() => submit(false)} disabled={saving} />
              <Muted>After you submit, the MRF will be routed to the assigned Project Manager. You cannot edit it once submitted unless it is returned.</Muted>
            </View>
          </>
        )}
      </ScrollView>

      {/* Native date picker — modal on iOS, spinner on Android, HTML input on Web */}
      {showDatePicker && Platform.OS !== "web" && (
        <DateTimePicker
          value={new Date(requiredBy || iso(today()))}
          mode="date"
          display={Platform.OS === "ios" ? "spinner" : "default"}
          minimumDate={today()}
          onChange={(_e, d) => {
            setShowDatePicker(false);
            if (d) setRequiredBy(iso(d));
          }}
        />
      )}
      {showDatePicker && Platform.OS === "web" && (
        <Modal visible transparent animationType="fade" onRequestClose={() => setShowDatePicker(false)}>
          <TouchableOpacity style={styles.modalBg} activeOpacity={1} onPress={() => setShowDatePicker(false)}>
            <View style={[styles.modal, { marginBottom: insets.bottom + 16 }]} onStartShouldSetResponder={() => true}>
              <View style={styles.modalHead}>
                <Text style={{ fontWeight: "700", fontSize: 16 }}>Pick Required-by Date</Text>
                <TouchableOpacity onPress={() => setShowDatePicker(false)}><Ionicons name="close" size={22} /></TouchableOpacity>
              </View>
              <TextInput
                testID="web-date-input"
                value={requiredBy}
                onChangeText={setRequiredBy}
                placeholder="YYYY-MM-DD"
                style={styles.inp}
                {...(Platform.OS === "web" ? ({ type: "date", min: iso(today()) } as any) : {})}
              />
              <View style={{ height: 8 }} />
              <Btn testID="web-date-done" title="Done" variant="action" onPress={() => setShowDatePicker(false)} />
            </View>
          </TouchableOpacity>
        </Modal>
      )}

      {/* Searchable Picker Modal */}
      <Modal visible={!!picker} transparent animationType="fade" onRequestClose={closePicker}>
        <TouchableOpacity style={styles.modalBg} activeOpacity={1} onPress={closePicker}>
          <View style={[styles.modal, { marginBottom: insets.bottom + 16 }]} onStartShouldSetResponder={() => true}>
            <View style={styles.modalHead}>
              <Text style={{ fontWeight: "700", fontSize: 16 }}>Select {picker?.type || ""}</Text>
              <TouchableOpacity onPress={closePicker}><Ionicons name="close" size={22} /></TouchableOpacity>
            </View>
            <TextInput
              testID="picker-search"
              placeholder="Search…"
              value={pickerSearch}
              onChangeText={setPickerSearch}
              style={styles.inp}
              autoFocus
            />
            <ScrollView style={{ maxHeight: 380 }}>
              {(pickerOptions as any[]).length === 0 ? (
                <View style={{ padding: 16 }}>
                  <Muted>No matches. Add options in the Masters screen (admin only).</Muted>
                </View>
              ) : null}
              {(pickerOptions as any[]).map((opt: any, idx: number) => {
                const t = picker?.type; const i = picker?.index ?? 0;
                const primary = opt.label || opt.name || String(opt);
                const key = opt.item_id || opt.customer_id || opt.project_id || opt.key || primary || idx;
                const onChoose = () => {
                  if (t === "customer") { setCustomerId(opt.customer_id); setProjectId(""); setSite(""); setSystemCat(""); closePicker(); }
                  else if (t === "project") { setProjectId(opt.project_id); setSite(""); setSystemCat(""); closePicker(); }
                  else if (t === "site") { setSite(opt.name); closePicker(); }
                  else if (t === "category") { setSystemCat(opt.name); closePicker(); }
                  else if (t === "material") { chooseMaterial(i, opt); }
                  else if (t === "make") { chooseMake(i, opt); }
                  else if (t === "model") { chooseModel(i, opt); }
                  else if (t === "unit") { setItem(i, { unit: opt.name }); closePicker(); }
                  else if (t === "priority") { setItem(i, { priority: opt.key }); closePicker(); }
                  else if (t === "billable") { setItem(i, { billable: opt.key === "billable" }); closePicker(); }
                };
                return (
                  <TouchableOpacity key={String(key)} testID={`opt-${t}-${idx}`} style={styles.opt} onPress={onChoose}>
                    <Text style={{ fontWeight: "600", color: theme.colors.text }}>{primary}</Text>
                    {opt.value ? <Text style={{ fontSize: 12, color: theme.colors.textMuted }}>{opt.value}</Text> : null}
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          </View>
        </TouchableOpacity>
      </Modal>
    </SafeAreaView>
  );
}

function PickerBox({ value, onPress, testID, disabled }: { value: string; onPress: () => void; testID?: string; disabled?: boolean }) {
  return (
    <TouchableOpacity testID={testID} onPress={disabled ? undefined : onPress}
      style={[pStyles.pick, disabled ? { opacity: 0.55, backgroundColor: theme.colors.surface } : null]}
      activeOpacity={disabled ? 1 : 0.85}>
      <Text style={{ color: disabled ? theme.colors.textMuted : theme.colors.text, fontSize: 15 }} numberOfLines={2}>{value}</Text>
      <Ionicons name="chevron-down" size={18} color={theme.colors.textMuted} />
    </TouchableOpacity>
  );
}

const pStyles = StyleSheet.create({
  pick: {
    borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: theme.radius.md,
    paddingHorizontal: 12, minHeight: 48, flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: theme.colors.bg, marginBottom: 8,
  },
});

const styles = StyleSheet.create({
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 8, paddingVertical: 8, backgroundColor: theme.colors.bg,
    borderBottomWidth: 1, borderBottomColor: theme.colors.border,
  },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  itemHead: { fontSize: 12, fontWeight: "700", color: theme.colors.primary, letterSpacing: 1 },
  uid: { fontSize: 11, color: theme.colors.textMuted, marginBottom: 6, marginTop: -4, letterSpacing: 0.3 },
  inp: { borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: theme.radius.md, paddingHorizontal: 12, paddingVertical: 10, backgroundColor: theme.colors.bg, color: theme.colors.text, marginBottom: 8 },
  textArea: { borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: theme.radius.md, paddingHorizontal: 12, paddingVertical: 10, backgroundColor: theme.colors.bg, color: theme.colors.text, minHeight: 60, marginBottom: 8 },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1, backgroundColor: "#fff" },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modal: { backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16, maxHeight: "80%", padding: 16 },
  modalHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: theme.colors.border, marginBottom: 8 },
  opt: { paddingVertical: 12, paddingHorizontal: 8, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
});
