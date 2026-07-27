import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal, TextInput } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, H1, H2, Input, Label, Muted } from "@/src/components/ui";
import { theme } from "@/src/theme";

export default function CreatePO() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();

  const [approvedMRFs, setApprovedMRFs] = useState<any[]>([]);
  const [vendors, setVendors] = useState<any[]>([]);
  const [projects, setProjects] = useState<any[]>([]);
  const [selected, setSelected] = useState<Record<string, { qty: number; rate: number; discount: number; gst: number; }>>({});
  const [vendorId, setVendorId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [deliverySite, setDeliverySite] = useState("");
  const [deliverySchedule, setDeliverySchedule] = useState("");
  const [paymentTerms, setPaymentTerms] = useState("30 days from invoice date");
  const [warranty, setWarranty] = useState("12 months from delivery");
  const [freight, setFreight] = useState("0");
  const [otherCharges, setOtherCharges] = useState("0");
  const [signatory, setSignatory] = useState(user?.name || "");
  const [picker, setPicker] = useState<null | "vendor" | "project">(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const [a, s, pa, v, p] = await Promise.all([
        api("/mrf?status=approved"), api("/mrf?status=sent_to_purchase"),
        api("/mrf?status=partially_ordered"), api("/vendors"), api("/projects"),
      ]);
      setApprovedMRFs([...a, ...s, ...pa]);
      setVendors(v); setProjects(p);
    })();
  }, []);

  const filteredMRFs = projectId ? approvedMRFs.filter((m) => m.project_id === projectId) : approvedMRFs;

  const toggle = (mrfId: string, item: any) => {
    const k = `${mrfId}:${item.item_line_id}`;
    setSelected((s) => {
      const n = { ...s };
      if (n[k]) delete n[k];
      else n[k] = { qty: (item.qty_approved || 0) - (item.qty_ordered || 0), rate: 0, discount: 0, gst: 18 };
      return n;
    });
  };
  const updateSel = (k: string, field: string, val: any) => {
    setSelected((s) => ({ ...s, [k]: { ...s[k], [field]: Number(val) || 0 } }));
  };

  const total = Object.entries(selected).reduce((sum, [_k, v]) => {
    const g = v.qty * v.rate;
    const ad = g - v.discount;
    return sum + ad + (ad * v.gst / 100);
  }, 0) + (Number(freight) || 0) + (Number(otherCharges) || 0);

  const submit = async () => {
    setErr(""); setBusy(true);
    if (!vendorId || !projectId || !Object.keys(selected).length) { setErr("Vendor, project and items required"); setBusy(false); return; }
    try {
      const items = Object.entries(selected).map(([k, v]) => {
        const [mrf_id, item_line_id] = k.split(":");
        const mrf = approvedMRFs.find((m) => m.mrf_id === mrf_id);
        const it = mrf?.items.find((i: any) => i.item_line_id === item_line_id);
        return {
          mrf_id, item_line_id,
          description: it?.description || "",
          specification: it?.specification || "",
          unit: it?.unit || "Nos",
          qty: v.qty, rate: v.rate, discount: v.discount, gst: v.gst,
        };
      });
      const po = await api<any>("/po", {
        method: "POST",
        body: {
          vendor_id: vendorId, project_id: projectId, delivery_site: deliverySite,
          items, delivery_schedule: deliverySchedule, payment_terms: paymentTerms,
          warranty_terms: warranty, freight: Number(freight) || 0,
          other_charges: Number(otherCharges) || 0, authorised_signatory: signatory,
        },
      });
      router.replace(`/po/${po.po_id}` as any);
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };

  const vendor = vendors.find((v) => v.vendor_id === vendorId);
  const project = projects.find((p) => p.project_id === projectId);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity testID="back-btn" onPress={() => router.back()} style={{ padding: 8 }}>
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Create Purchase Order</Text>
        <View style={{ width: 38 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 200 }}>
        <H1>New Purchase Order</H1>
        <Muted>Select approved items from one or more MRFs.</Muted>

        <Card style={{ marginTop: 16 }}>
          <Label>PROJECT (FILTER APPROVED MRFs)</Label>
          <TouchableOpacity testID="pick-project" onPress={() => setPicker("project")} style={styles.pick}>
            <Text>{project ? `${project.code} — ${project.name}` : "Select project"}</Text>
            <Ionicons name="chevron-down" size={18} color={theme.colors.textMuted} />
          </TouchableOpacity>

          <Label>VENDOR</Label>
          <TouchableOpacity testID="pick-vendor" onPress={() => setPicker("vendor")} style={styles.pick}>
            <Text>{vendor ? vendor.name : "Select vendor"}</Text>
            <Ionicons name="chevron-down" size={18} color={theme.colors.textMuted} />
          </TouchableOpacity>

          <Input testID="delivery-site" label="Delivery Site" value={deliverySite} onChangeText={setDeliverySite} />
          <Input testID="delivery-schedule" label="Delivery Schedule" value={deliverySchedule} onChangeText={setDeliverySchedule} placeholder="e.g. within 15 days" />
          <Input testID="payment-terms" label="Payment Terms" value={paymentTerms} onChangeText={setPaymentTerms} />
          <Input testID="warranty" label="Warranty" value={warranty} onChangeText={setWarranty} />
          <View style={{ flexDirection: "row", gap: 8 }}>
            <View style={{ flex: 1 }}><Input testID="freight" label="Freight (₹)" value={freight} onChangeText={setFreight} keyboardType="decimal-pad" /></View>
            <View style={{ flex: 1 }}><Input testID="other-charges" label="Other (₹)" value={otherCharges} onChangeText={setOtherCharges} keyboardType="decimal-pad" /></View>
          </View>
          <Input testID="signatory" label="Authorised Signatory" value={signatory} onChangeText={setSignatory} />
        </Card>

        <H2 style={{ marginTop: 20, marginBottom: 8 }}>Approved Items</H2>
        {filteredMRFs.length === 0 ? (
          <Card><Text style={{ color: theme.colors.textMuted }}>No approved MRFs available.</Text></Card>
        ) : null}
        {filteredMRFs.map((m) => (
          <Card key={m.mrf_id} style={{ marginBottom: 10 }} testID={`mrf-block-${m.mrf_number.replace(/\//g,"-")}`}>
            <Text style={styles.mrfNum}>{m.mrf_number}</Text>
            <Text style={styles.mrfSite}>{m.site}</Text>
            {m.items.filter((it: any) => it.status !== "rejected").map((it: any) => {
              const k = `${m.mrf_id}:${it.item_line_id}`;
              const sel = selected[k];
              const remaining = (it.qty_approved || 0) - (it.qty_ordered || 0);
              const disabled = remaining <= 0;
              return (
                <View key={it.item_line_id} style={styles.itemRow}>
                  <TouchableOpacity
                    testID={`select-item-${it.item_line_id}`}
                    onPress={() => !disabled && toggle(m.mrf_id, it)}
                    disabled={disabled}
                    style={styles.selectRow}
                  >
                    <View style={[styles.checkbox, { backgroundColor: sel ? theme.colors.primary : "#fff", borderColor: sel ? theme.colors.primary : theme.colors.borderStrong, opacity: disabled ? 0.4 : 1 }]}>
                      {sel ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
                    </View>
                    <View style={{ flex: 1, marginLeft: 8 }}>
                      <Text style={{ fontWeight: "600", color: theme.colors.text }}>{it.description}</Text>
                      <Text style={styles.itemMeta}>Approved: {it.qty_approved} · Remaining: {remaining} {it.unit}{disabled ? " · Fully ordered" : ""}</Text>
                    </View>
                  </TouchableOpacity>
                  {sel ? (
                    <View style={{ flexDirection: "row", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                      <MiniInp testID={`qty-${it.item_line_id}`} label="Qty" value={sel.qty} onChange={(v) => updateSel(k, "qty", v)} />
                      <MiniInp testID={`rate-${it.item_line_id}`} label="Rate" value={sel.rate} onChange={(v) => updateSel(k, "rate", v)} />
                      <MiniInp testID={`disc-${it.item_line_id}`} label="Disc" value={sel.discount} onChange={(v) => updateSel(k, "discount", v)} />
                      <MiniInp testID={`gst-${it.item_line_id}`} label="GST%" value={sel.gst} onChange={(v) => updateSel(k, "gst", v)} />
                    </View>
                  ) : null}
                </View>
              );
            })}
          </Card>
        ))}

        <Card style={{ marginTop: 12, backgroundColor: theme.colors.surface }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
            <Text style={{ fontWeight: "700" }}>Grand Total</Text>
            <Text style={{ fontWeight: "800", fontSize: 18, color: theme.colors.primary }} testID="po-total">₹ {new Intl.NumberFormat("en-IN").format(Math.round(total))}</Text>
          </View>
          <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 4 }}>{Object.keys(selected).length} item(s) selected</Text>
        </Card>

        {err ? <Text style={{ color: theme.colors.danger, marginTop: 10 }} testID="po-err">{err}</Text> : null}

        <Btn testID="submit-po-btn" title={busy ? "Creating…" : "Create Purchase Order"} variant="action" onPress={submit} disabled={busy} style={{ marginTop: 16 }} />
      </ScrollView>

      <Modal visible={!!picker} transparent animationType="fade" onRequestClose={() => setPicker(null)}>
        <TouchableOpacity style={styles.modalBg} activeOpacity={1} onPress={() => setPicker(null)}>
          <View style={[styles.modal, { marginBottom: insets.bottom + 16 }]} onStartShouldSetResponder={() => true}>
            <View style={styles.modalHead}>
              <Text style={{ fontWeight: "700", fontSize: 16 }}>Select {picker}</Text>
              <TouchableOpacity onPress={() => setPicker(null)}><Ionicons name="close" size={22} /></TouchableOpacity>
            </View>
            <ScrollView>
              {picker === "vendor" && vendors.map((v) => (
                <TouchableOpacity key={v.vendor_id} testID={`opt-v-${v.vendor_id}`}
                  style={styles.opt} onPress={() => { setVendorId(v.vendor_id); setPicker(null); }}>
                  <Text style={{ fontWeight: "600" }}>{v.name}</Text>
                  <Text style={{ color: theme.colors.textMuted, fontSize: 12 }}>{v.gstin}</Text>
                </TouchableOpacity>
              ))}
              {picker === "project" && projects.map((p) => (
                <TouchableOpacity key={p.project_id} testID={`opt-p-${p.code}`}
                  style={styles.opt} onPress={() => { setProjectId(p.project_id); setDeliverySite(p.site); setPicker(null); }}>
                  <Text style={{ fontWeight: "600" }}>{p.code} — {p.name}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        </TouchableOpacity>
      </Modal>
    </SafeAreaView>
  );
}

function MiniInp({ label, value, onChange, testID }: { label: string; value: number; onChange: (v: string) => void; testID?: string }) {
  return (
    <View style={{ flex: 1, minWidth: 70 }}>
      <Text style={{ fontSize: 9, color: theme.colors.textMuted, textTransform: "uppercase", letterSpacing: 1, marginBottom: 2 }}>{label}</Text>
      <TextInput
        testID={testID}
        value={String(value)}
        onChangeText={onChange}
        keyboardType="decimal-pad"
        style={{ borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 4, padding: 6, fontSize: 12, backgroundColor: "#fff" }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 8, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  pick: { borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, minHeight: 48, paddingHorizontal: 12, flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 12, backgroundColor: "#fff" },
  mrfNum: { fontSize: 15, fontWeight: "800", color: theme.colors.primary },
  mrfSite: { fontSize: 12, color: theme.colors.textMuted, marginBottom: 8 },
  itemRow: { paddingVertical: 8, borderTopWidth: 1, borderTopColor: theme.colors.border },
  selectRow: { flexDirection: "row", alignItems: "center" },
  checkbox: { width: 22, height: 22, borderWidth: 2, borderRadius: 4, alignItems: "center", justifyContent: "center" },
  itemMeta: { fontSize: 11, color: theme.colors.textMuted, marginTop: 2 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modal: { backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16, maxHeight: "70%", padding: 16 },
  modalHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: theme.colors.border, marginBottom: 8 },
  opt: { paddingVertical: 14, paddingHorizontal: 8, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
});
