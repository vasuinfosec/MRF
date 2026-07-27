import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput, Alert, Modal } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Btn, Card, H2, Label, Muted } from "@/src/components/ui";
import { theme } from "@/src/theme";

interface DCItem {
  description: string; unit: string; qty: number;
  material_uid?: string; variant_uid?: string;
  make?: string; model?: string; remarks?: string;
  mrf_id?: string; po_id?: string; grn_id?: string; item_line_id?: string;
}

interface Project { project_id: string; code: string; name: string; site?: string; customer_id?: string; }
interface PO { po_id: string; po_number: string; project_id: string; vendor_id: string; customer_id?: string; items: any[]; }
interface GRN { grn_id: string; grn_number: string; po_id: string; project_id: string; items: any[]; }

export default function DCCreate() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [pos, setPOs] = useState<PO[]>([]);
  const [grns, setGRNs] = useState<GRN[]>([]);
  const [dcType, setDCType] = useState<"outbound" | "inbound">("outbound");
  const [projectId, setProjectId] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [poId, setPOId] = useState("");
  const [grnId, setGRNId] = useState("");
  const [fromLoc, setFromLoc] = useState("");
  const [toLoc, setToLoc] = useState("");
  const [dispatchDate, setDispatchDate] = useState(new Date().toISOString().slice(0, 10));
  const [vehicleNo, setVehicleNo] = useState("");
  const [driverName, setDriverName] = useState("");
  const [driverContact, setDriverContact] = useState("");
  const [transporter, setTransporter] = useState("");
  const [eWayBill, setEWayBill] = useState("");
  const [remarks, setRemarks] = useState("");
  const [signatory, setSignatory] = useState("");
  const [vendorDCRef, setVendorDCRef] = useState("");
  const [items, setItems] = useState<DCItem[]>([]);
  const [pickSource, setPickSource] = useState<null | "po" | "grn">(null);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const p = await api<Project[]>("/projects"); setProjects(p || []);
      const po = await api<PO[]>("/po"); setPOs(po || []);
      const g = await api<GRN[]>("/grns"); setGRNs(g || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  const addBlankItem = () => setItems((s) => [...s, { description: "", unit: "nos", qty: 1 }]);
  const updItem = (i: number, key: keyof DCItem, val: any) =>
    setItems((s) => s.map((it, idx) => (idx === i ? { ...it, [key]: val } : it)));
  const rmItem = (i: number) => setItems((s) => s.filter((_, idx) => idx !== i));

  const pickFromPO = (po: PO) => {
    setPOId(po.po_id);
    setProjectId(po.project_id);
    setCustomerId(po.customer_id || "");
    setItems(po.items.map((it: any) => ({
      description: it.description,
      unit: it.unit,
      qty: it.qty,
      material_uid: it.material_uid,
      variant_uid: it.variant_uid,
      make: it.make, model: it.model,
      po_id: po.po_id, mrf_id: it.mrf_id, item_line_id: it.item_line_id,
    })));
    setPickSource(null);
  };

  const pickFromGRN = (g: GRN) => {
    setGRNId(g.grn_id);
    setPOId(g.po_id || "");
    setProjectId(g.project_id);
    setItems(g.items.map((it: any) => ({
      description: it.description,
      unit: it.unit,
      qty: it.qty,
      material_uid: it.material_uid,
      variant_uid: it.variant_uid,
      make: it.make, model: it.model,
      grn_id: g.grn_id, po_id: g.po_id,
    })));
    setPickSource(null);
  };

  const save = async () => {
    setErr("");
    if (!projectId) { setErr("Project is required."); return; }
    if (!fromLoc.trim() || !toLoc.trim()) { setErr("From & To locations required."); return; }
    if (!dispatchDate.trim()) { setErr("Dispatch date required."); return; }
    if (!items.length) { setErr("Add at least one item."); return; }
    setSaving(true);
    try {
      const dc = await api<{ dc_id: string; dc_number: string }>("/dc", {
        method: "POST", body: {
          dc_type: dcType,
          project_id: projectId,
          customer_id: customerId || undefined,
          po_id: poId || undefined,
          grn_id: grnId || undefined,
          from_location: fromLoc,
          to_location: toLoc,
          dispatch_date: dispatchDate,
          vehicle_no: vehicleNo, driver_name: driverName, driver_contact: driverContact,
          transporter, e_way_bill_no: eWayBill,
          remarks, authorised_signatory: signatory, vendor_dc_ref: vendorDCRef,
          items,
        },
      });
      Alert.alert("Delivery Challan Created", dc.dc_number);
      router.replace(`/dc/${dc.dc_id}`);
    } catch (e: any) {
      setErr(e?.message || "Failed to create DC.");
    }
    setSaving(false);
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }} testID="back-btn">
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>New Delivery Challan</Text>
        <View style={{ width: 38 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 80 }}>
        <H2>Type & References</H2>
        <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
          {(["outbound", "inbound"] as const).map((t) => (
            <TouchableOpacity key={t}
              onPress={() => setDCType(t)}
              style={[styles.pill, dcType === t ? styles.pillActive : null]}>
              <Text style={[styles.pillTxt, dcType === t ? styles.pillTxtActive : null]}>{t.toUpperCase()}</Text>
            </TouchableOpacity>
          ))}
        </View>
        <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
          <Btn title="Pick from PO" variant="outline" onPress={() => setPickSource("po")} />
          <Btn title="Pick from GRN" variant="outline" onPress={() => setPickSource("grn")} />
        </View>
        {poId ? <Muted>Linked PO: {pos.find((p) => p.po_id === poId)?.po_number}</Muted> : null}
        {grnId ? <Muted>Linked GRN: {grns.find((g) => g.grn_id === grnId)?.grn_number}</Muted> : null}

        <H2 style={{ marginTop: 16 }}>Project & Route</H2>
        <Card style={{ marginTop: 8 }}>
          <Label>Project</Label>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 4 }}>
            {projects.map((p) => (
              <TouchableOpacity key={p.project_id}
                onPress={() => { setProjectId(p.project_id); setCustomerId(p.customer_id || ""); }}
                style={[styles.chip, projectId === p.project_id ? styles.chipActive : null]}>
                <Text style={[styles.chipTxt, projectId === p.project_id ? styles.chipTxtActive : null]}>{p.code}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
          <Label style={{ marginTop: 8 }}>From location</Label>
          <TextInput value={fromLoc} onChangeText={setFromLoc} placeholder="e.g. Pune warehouse" style={styles.input} testID="dc-from" />
          <Label style={{ marginTop: 8 }}>To location</Label>
          <TextInput value={toLoc} onChangeText={setToLoc} placeholder="e.g. Bandra Site" style={styles.input} testID="dc-to" />
          <Label style={{ marginTop: 8 }}>Dispatch date (YYYY-MM-DD)</Label>
          <TextInput value={dispatchDate} onChangeText={setDispatchDate} placeholder="2026-01-31" style={styles.input} testID="dc-date" />
        </Card>

        <H2 style={{ marginTop: 16 }}>Transport</H2>
        <Card style={{ marginTop: 8 }}>
          <Label>Vehicle No.</Label>
          <TextInput value={vehicleNo} onChangeText={setVehicleNo} placeholder="e.g. MH14 AB 1234" style={styles.input} testID="dc-vehicle" />
          <Label style={{ marginTop: 8 }}>Driver Name</Label>
          <TextInput value={driverName} onChangeText={setDriverName} style={styles.input} testID="dc-driver" />
          <Label style={{ marginTop: 8 }}>Driver Contact</Label>
          <TextInput value={driverContact} onChangeText={setDriverContact} keyboardType="phone-pad" style={styles.input} />
          <Label style={{ marginTop: 8 }}>Transporter</Label>
          <TextInput value={transporter} onChangeText={setTransporter} style={styles.input} />
          <Label style={{ marginTop: 8 }}>E-Way Bill No.</Label>
          <TextInput value={eWayBill} onChangeText={setEWayBill} style={styles.input} />
          {dcType === "inbound" ? (
            <>
              <Label style={{ marginTop: 8 }}>Vendor DC Ref</Label>
              <TextInput value={vendorDCRef} onChangeText={setVendorDCRef} placeholder="Vendor's DC number" style={styles.input} />
            </>
          ) : null}
        </Card>

        <H2 style={{ marginTop: 16 }}>Items ({items.length})</H2>
        {items.map((it, idx) => (
          <Card key={idx} style={{ marginTop: 8 }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text style={{ fontWeight: "700", color: theme.colors.textMuted }}>Item {idx + 1}</Text>
              <TouchableOpacity onPress={() => rmItem(idx)}>
                <Ionicons name="trash-outline" size={16} color={theme.colors.danger} />
              </TouchableOpacity>
            </View>
            <TextInput value={it.description} onChangeText={(v) => updItem(idx, "description", v)} placeholder="Description" style={styles.input} testID={`dc-item-desc-${idx}`} />
            <View style={{ flexDirection: "row", gap: 6, marginTop: 6 }}>
              <TextInput value={String(it.qty)} onChangeText={(v) => updItem(idx, "qty", parseFloat(v) || 0)} placeholder="Qty" keyboardType="decimal-pad" style={[styles.input, { flex: 1 }]} testID={`dc-item-qty-${idx}`} />
              <TextInput value={it.unit} onChangeText={(v) => updItem(idx, "unit", v)} placeholder="Unit" style={[styles.input, { flex: 1 }]} />
            </View>
            {(it.material_uid || it.variant_uid) ? (
              <View style={{ flexDirection: "row", gap: 6, marginTop: 6 }}>
                {it.material_uid ? <Text style={styles.matChip}>MAT {it.material_uid}</Text> : null}
                {it.variant_uid ? <Text style={styles.varChip}>VAR {it.variant_uid}</Text> : null}
              </View>
            ) : null}
          </Card>
        ))}
        <Btn title="+ Add Item" variant="outline" onPress={addBlankItem} />

        <H2 style={{ marginTop: 16 }}>Meta</H2>
        <Card style={{ marginTop: 8 }}>
          <Label>Remarks</Label>
          <TextInput value={remarks} onChangeText={setRemarks} multiline style={[styles.input, { minHeight: 60 }]} />
          <Label style={{ marginTop: 8 }}>Authorised Signatory</Label>
          <TextInput value={signatory} onChangeText={setSignatory} placeholder="Name / designation" style={styles.input} />
        </Card>

        {err ? <Text style={styles.err}>{err}</Text> : null}

        <View style={{ marginTop: 16 }}>
          <Btn testID="dc-save-btn" title={saving ? "Saving…" : "Create Delivery Challan"}
            variant="primary" onPress={save} disabled={saving} />
        </View>
      </ScrollView>

      {/* Pick source modal */}
      <Modal visible={pickSource !== null} transparent animationType="fade" onRequestClose={() => setPickSource(null)}>
        <TouchableOpacity style={styles.modalBg} activeOpacity={1} onPress={() => setPickSource(null)}>
          <View style={styles.modalCard} onStartShouldSetResponder={() => true}>
            <Text style={{ fontSize: 16, fontWeight: "800" }}>{pickSource === "po" ? "Pick a Purchase Order" : "Pick a GRN"}</Text>
            <ScrollView style={{ maxHeight: 400, marginTop: 8 }}>
              {pickSource === "po" && pos.map((p) => (
                <TouchableOpacity key={p.po_id} onPress={() => pickFromPO(p)} style={styles.modalRow}>
                  <Text style={{ fontWeight: "700" }}>{p.po_number}</Text>
                  <Muted>Items: {p.items?.length || 0}</Muted>
                </TouchableOpacity>
              ))}
              {pickSource === "grn" && grns.map((g) => (
                <TouchableOpacity key={g.grn_id} onPress={() => pickFromGRN(g)} style={styles.modalRow}>
                  <Text style={{ fontWeight: "700" }}>{g.grn_number}</Text>
                  <Muted>Items: {g.items?.length || 0}</Muted>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        </TouchableOpacity>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 4, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: "#fff" },
  pillActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  pillTxt: { color: theme.colors.text, fontSize: 12, fontWeight: "800" },
  pillTxtActive: { color: "#fff" },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: "#fff", marginRight: 6 },
  chipActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  chipTxt: { color: theme.colors.text, fontSize: 12, fontWeight: "700" },
  chipTxtActive: { color: "#fff" },
  input: { borderWidth: 1, borderColor: theme.colors.border, backgroundColor: "#fff", borderRadius: 6, padding: 8, fontSize: 13 },
  matChip: { backgroundColor: "#EEF2FF", color: "#3730A3", fontSize: 11, fontWeight: "700", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  varChip: { backgroundColor: "#ECFCCB", color: "#3F6212", fontSize: 11, fontWeight: "700", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  err: { color: theme.colors.danger, backgroundColor: "#FEF2F2", padding: 10, borderRadius: 6, marginTop: 10, fontSize: 12 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "center", padding: 16 },
  modalCard: { backgroundColor: "#fff", borderRadius: 12, padding: 16 },
  modalRow: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
});
