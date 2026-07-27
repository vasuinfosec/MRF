import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput, Modal, Alert } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, H1, H2, Label, Muted, Empty } from "@/src/components/ui";
import { theme } from "@/src/theme";
import { useResponsive } from "@/src/hooks/useResponsive";
import { DTable, DHead, DH, DRow, DC } from "@/src/components/DataTable";

type Customer = {
  customer_id: string;
  name: string;
  gstin?: string;
  pan?: string;
  billing_address?: string;
  shipping_address?: string;
  contact_person?: string;
  phone?: string;
  email?: string;
  remarks?: string;
  active: boolean;
  po_count?: number;
};

type CPO = {
  cpo_id: string;
  customer_id: string;
  po_number: string;
  po_date?: string;
  value?: number;
  validity_till?: string;
  attachment_name?: string;
  remarks?: string;
  active: boolean;
};

const INR = (n: number) => new Intl.NumberFormat("en-IN").format(n || 0);

export default function CustomersScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { isDesktop } = useResponsive();
  const [rows, setRows] = useState<Customer[]>([]);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");

  const canWrite = user?.role === "admin" || user?.role === "director";

  const empty: Customer = {
    customer_id: "", name: "", gstin: "", pan: "",
    billing_address: "", shipping_address: "", contact_person: "",
    phone: "", email: "", remarks: "", active: true,
  };
  const [nf, setNf] = useState<Customer>(empty);
  const [edit, setEdit] = useState<Customer | null>(null);
  const [editReason, setEditReason] = useState("");
  const [editingIdChange, setEditingIdChange] = useState(false);

  const [posOpen, setPosOpen] = useState<Customer | null>(null);
  const [pos, setPos] = useState<CPO[]>([]);
  const emptyCPO: CPO = { cpo_id: "", customer_id: "", po_number: "", po_date: "", value: 0, validity_till: "", attachment_name: "", remarks: "", active: true };
  const [nfCPO, setNfCPO] = useState<CPO>(emptyCPO);

  const load = useCallback(async () => {
    try {
      const d = await api<Customer[]>("/customers?include_inactive=1");
      setRows(d);
    } catch (e: any) { setErr(e.message || "Failed"); }
  }, []);

  useEffect(() => { if (user) load(); }, [user, load]);

  const filtered = q
    ? rows.filter((c) => (c.customer_id + " " + c.name + " " + (c.gstin || "")).toLowerCase().includes(q.toLowerCase()))
    : rows;

  const createCustomer = async () => {
    setErr(""); setMsg("");
    if (!nf.customer_id.trim() || !nf.name.trim()) { setErr("Customer ID and Name are required."); return; }
    try {
      await api("/customers", { method: "POST", body: nf });
      setNf(empty);
      setMsg("Customer created.");
      load();
    } catch (e: any) { setErr(e.message || "Failed"); }
  };

  const openEdit = (c: Customer) => {
    setEdit({ ...c });
    setEditReason("");
    setEditingIdChange(false);
  };

  const saveEdit = async () => {
    if (!edit) return;
    setErr("");
    if (!editReason.trim()) { setErr("Please enter a reason for this change (required for audit)."); return; }
    try {
      const body: any = {
        name: edit.name, gstin: edit.gstin, pan: edit.pan,
        billing_address: edit.billing_address, shipping_address: edit.shipping_address,
        contact_person: edit.contact_person, phone: edit.phone, email: edit.email,
        remarks: edit.remarks, active: edit.active,
        reason: editReason.trim(),
      };
      if (editingIdChange && edit.customer_id) body.customer_id = edit.customer_id;
      const original = rows.find((r) => r.customer_id === (editingIdChange ? edit.customer_id : rows.find((x)=>x.name===edit.name)?.customer_id));
      const cidToUpdate = original?.customer_id || edit.customer_id;
      await api(`/customers/${cidToUpdate}`, { method: "PUT", body });
      setEdit(null); setEditReason(""); setEditingIdChange(false);
      setMsg("Customer updated.");
      load();
    } catch (e: any) { setErr(e.message || "Failed"); }
  };

  const deactivate = (c: Customer) => {
    Alert.alert("Deactivate Customer?", `${c.customer_id} · ${c.name}`, [
      { text: "Cancel", style: "cancel" },
      { text: "Deactivate", style: "destructive", onPress: async () => {
        try { await api(`/customers/${c.customer_id}?reason=Deactivated%20by%20admin`, { method: "DELETE" }); load(); }
        catch (e: any) { setErr(e.message || "Failed"); }
      }},
    ]);
  };

  const openPOs = async (c: Customer) => {
    setPosOpen(c);
    try {
      const detail = await api<any>(`/customers/${c.customer_id}`);
      setPos(detail.customer_pos || []);
    } catch { setPos([]); }
  };

  const addPO = async () => {
    if (!posOpen) return;
    setErr("");
    if (!nfCPO.po_number.trim()) { setErr("PO number required"); return; }
    try {
      const body: any = { ...nfCPO };
      if (body.value) body.value = Number(body.value);
      await api(`/customers/${posOpen.customer_id}/pos`, { method: "POST", body });
      setNfCPO(emptyCPO);
      openPOs(posOpen);
      load();
    } catch (e: any) { setErr(e.message || "Failed"); }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }} testID="back-btn">
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Customer Master</Text>
        <View style={{ width: 38 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 80 }}>
        <H1>Customers</H1>
        <Muted>Permanent alphanumeric Customer ID · used everywhere (projects, MRF, PO, invoices, exports).</Muted>

        <TextInput
          testID="cust-search"
          placeholder="Search by ID, name or GSTIN…"
          value={q}
          onChangeText={setQ}
          style={styles.input}
        />

        {err ? <Text testID="cust-err" style={styles.err}>{err}</Text> : null}
        {msg ? <Text testID="cust-msg" style={styles.msg}>{msg}</Text> : null}

        {canWrite ? (
          <Card style={{ marginTop: 8 }} testID="cust-new">
            <H2>+ Add Customer</H2>
            <Label>CUSTOMER ID *</Label>
            <TextInput
              testID="cust-cid"
              placeholder="e.g. VASU-CUST-001 or your legacy ID"
              value={nf.customer_id}
              onChangeText={(v) => setNf({ ...nf, customer_id: v.replace(/[^A-Za-z0-9_-]/g, "") })}
              style={styles.input}
              autoCapitalize="characters"
            />
            <Muted>Alphanumeric, dashes/underscores allowed. Editable later.</Muted>
            <Label>NAME *</Label>
            <TextInput testID="cust-name" value={nf.name} onChangeText={(v) => setNf({ ...nf, name: v })} style={styles.input} />
            <Label>GSTIN</Label>
            <TextInput testID="cust-gstin" value={nf.gstin} onChangeText={(v) => setNf({ ...nf, gstin: v.toUpperCase() })} style={styles.input} autoCapitalize="characters" />
            <Label>PAN</Label>
            <TextInput testID="cust-pan" value={nf.pan} onChangeText={(v) => setNf({ ...nf, pan: v.toUpperCase() })} style={styles.input} autoCapitalize="characters" />
            <Label>BILLING ADDRESS</Label>
            <TextInput testID="cust-billing" value={nf.billing_address} onChangeText={(v) => setNf({ ...nf, billing_address: v })} style={styles.input} multiline />
            <Label>SHIPPING ADDRESS</Label>
            <TextInput testID="cust-shipping" value={nf.shipping_address} onChangeText={(v) => setNf({ ...nf, shipping_address: v })} style={styles.input} multiline />
            <View style={{ flexDirection: "row", gap: 8 }}>
              <View style={{ flex: 1 }}>
                <Label>CONTACT PERSON</Label>
                <TextInput testID="cust-contact" value={nf.contact_person} onChangeText={(v) => setNf({ ...nf, contact_person: v })} style={styles.input} />
              </View>
              <View style={{ flex: 1 }}>
                <Label>PHONE</Label>
                <TextInput testID="cust-phone" value={nf.phone} onChangeText={(v) => setNf({ ...nf, phone: v })} style={styles.input} keyboardType="phone-pad" />
              </View>
            </View>
            <Label>EMAIL</Label>
            <TextInput testID="cust-email" value={nf.email} onChangeText={(v) => setNf({ ...nf, email: v })} style={styles.input} keyboardType="email-address" autoCapitalize="none" />
            <Btn testID="cust-create" title="Create Customer" variant="action" onPress={createCustomer} style={{ marginTop: 12 }} />
          </Card>
        ) : null}

        <View style={{ marginTop: 12 }}>
          {filtered.length === 0 ? (
            <Empty title="No customers" subtitle="Start by creating your first customer above." />
          ) : isDesktop ? (
            <DTable>
              <DHead>
                <DH flex={1}>Customer ID</DH>
                <DH flex={1.6}>Name</DH>
                <DH flex={1.2}>GSTIN</DH>
                <DH flex={1.3}>Contact</DH>
                <DH flex={0.7}>POs</DH>
                <DH flex={0.7}>Status</DH>
                {canWrite ? <DH flex={1.4}>Actions</DH> : null}
              </DHead>
              {filtered.map((c) => (
                <DRow key={c.customer_id} testID={`cust-row-${c.customer_id}`}>
                  <DC flex={1} strong color={theme.colors.primary}>{c.customer_id}</DC>
                  <DC flex={1.6}>{c.name}</DC>
                  <DC flex={1.2} muted>{c.gstin || "—"}</DC>
                  <DC flex={1.3} muted>{c.contact_person ? `${c.contact_person}${c.phone ? " · " + c.phone : ""}` : "—"}</DC>
                  <DC flex={0.7}>{c.po_count || 0}</DC>
                  <DC flex={0.7} color={c.active ? theme.colors.success : theme.colors.textMuted}>{c.active ? "Active" : "Inactive"}</DC>
                  {canWrite ? (
                    <DC flex={1.4}>
                      <View style={{ flexDirection: "row", gap: 6 }}>
                        <TouchableOpacity testID={`cust-po-${c.customer_id}`} onPress={() => openPOs(c)} style={styles.iconBtn}>
                          <Ionicons name="document-text-outline" size={16} color={theme.colors.primary} />
                        </TouchableOpacity>
                        <TouchableOpacity testID={`cust-audit-${c.customer_id}`}
                          onPress={() => router.push({ pathname: "/audit", params: { entity_id: c.customer_id } })}
                          style={styles.iconBtn}>
                          <Ionicons name="time-outline" size={16} color={theme.colors.action} />
                        </TouchableOpacity>
                        <TouchableOpacity testID={`cust-edit-${c.customer_id}`} onPress={() => openEdit(c)} style={styles.iconBtn}>
                          <Ionicons name="pencil" size={16} color={theme.colors.primary} />
                        </TouchableOpacity>
                        {c.active ? (
                          <TouchableOpacity testID={`cust-del-${c.customer_id}`} onPress={() => deactivate(c)} style={styles.iconBtn}>
                            <Ionicons name="power" size={16} color={theme.colors.danger} />
                          </TouchableOpacity>
                        ) : null}
                      </View>
                    </DC>
                  ) : null}
                </DRow>
              ))}
            </DTable>
          ) : filtered.map((c) => (
            <Card key={c.customer_id} style={{ marginTop: 8 }} testID={`cust-row-${c.customer_id}`}>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cid}>{c.customer_id}</Text>
                  <Text style={styles.cname}>{c.name}</Text>
                  {c.gstin ? <Muted>GSTIN: {c.gstin}</Muted> : null}
                  {c.contact_person ? <Muted>Contact: {c.contact_person}{c.phone ? ` · ${c.phone}` : ""}</Muted> : null}
                  <Muted>{c.active ? "Active" : "Inactive"} · Customer POs: {c.po_count || 0}</Muted>
                </View>
                {canWrite ? (
                  <View style={{ gap: 6 }}>
                    <TouchableOpacity testID={`cust-po-${c.customer_id}`} onPress={() => openPOs(c)} style={styles.iconBtn}>
                      <Ionicons name="document-text-outline" size={18} color={theme.colors.primary} />
                    </TouchableOpacity>
                    <TouchableOpacity
                      testID={`cust-audit-${c.customer_id}`}
                      onPress={() => router.push({ pathname: "/audit", params: { entity_id: c.customer_id } })}
                      style={styles.iconBtn}
                    >
                      <Ionicons name="time-outline" size={18} color={theme.colors.action} />
                    </TouchableOpacity>
                    <TouchableOpacity testID={`cust-edit-${c.customer_id}`} onPress={() => openEdit(c)} style={styles.iconBtn}>
                      <Ionicons name="pencil" size={18} color={theme.colors.primary} />
                    </TouchableOpacity>
                    {c.active ? (
                      <TouchableOpacity testID={`cust-del-${c.customer_id}`} onPress={() => deactivate(c)} style={styles.iconBtn}>
                        <Ionicons name="power" size={18} color={theme.colors.danger} />
                      </TouchableOpacity>
                    ) : null}
                  </View>
                ) : null}
              </View>
            </Card>
          ))}
        </View>
      </ScrollView>

      {/* Edit Modal */}
      <Modal visible={!!edit} animationType="slide" transparent>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <ScrollView>
              <H2>Edit Customer</H2>
              {edit ? (
                <>
                  <Label>CUSTOMER ID {editingIdChange ? "(EDITING — cascade)" : ""}</Label>
                  <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
                    <TextInput
                      testID="cust-edit-cid"
                      value={edit.customer_id}
                      onChangeText={(v) => setEdit({ ...edit, customer_id: v.replace(/[^A-Za-z0-9_-]/g, "") })}
                      style={[styles.input, { flex: 1, backgroundColor: editingIdChange ? "#fff8e1" : theme.colors.surface }]}
                      editable={editingIdChange}
                      autoCapitalize="characters"
                    />
                    <TouchableOpacity onPress={() => setEditingIdChange((x) => !x)} testID="toggle-edit-cid" style={styles.iconBtn}>
                      <Ionicons name={editingIdChange ? "lock-closed" : "pencil"} size={18} color={theme.colors.primary} />
                    </TouchableOpacity>
                  </View>
                  {editingIdChange ? <Muted>All references (projects, MRFs, POs, invoices) will be updated to the new ID.</Muted> : null}
                  <Label>NAME</Label>
                  <TextInput value={edit.name} onChangeText={(v) => setEdit({ ...edit, name: v })} style={styles.input} />
                  <Label>GSTIN</Label>
                  <TextInput value={edit.gstin} onChangeText={(v) => setEdit({ ...edit, gstin: v.toUpperCase() })} style={styles.input} autoCapitalize="characters" />
                  <Label>PAN</Label>
                  <TextInput value={edit.pan} onChangeText={(v) => setEdit({ ...edit, pan: v.toUpperCase() })} style={styles.input} autoCapitalize="characters" />
                  <Label>BILLING ADDRESS</Label>
                  <TextInput value={edit.billing_address} onChangeText={(v) => setEdit({ ...edit, billing_address: v })} style={styles.input} multiline />
                  <Label>SHIPPING ADDRESS</Label>
                  <TextInput value={edit.shipping_address} onChangeText={(v) => setEdit({ ...edit, shipping_address: v })} style={styles.input} multiline />
                  <Label>CONTACT PERSON</Label>
                  <TextInput value={edit.contact_person} onChangeText={(v) => setEdit({ ...edit, contact_person: v })} style={styles.input} />
                  <Label>PHONE</Label>
                  <TextInput value={edit.phone} onChangeText={(v) => setEdit({ ...edit, phone: v })} style={styles.input} keyboardType="phone-pad" />
                  <Label>EMAIL</Label>
                  <TextInput value={edit.email} onChangeText={(v) => setEdit({ ...edit, email: v })} style={styles.input} keyboardType="email-address" autoCapitalize="none" />
                  <Label>REMARKS</Label>
                  <TextInput value={edit.remarks} onChangeText={(v) => setEdit({ ...edit, remarks: v })} style={styles.input} multiline />

                  <View style={{ height: 12 }} />
                  <Label>REASON FOR CHANGE * (mandatory audit)</Label>
                  <TextInput
                    testID="cust-edit-reason"
                    value={editReason}
                    onChangeText={setEditReason}
                    style={[styles.input, { backgroundColor: "#fffbea" }]}
                    placeholder="e.g. Correct billing address per contract"
                    multiline
                  />
                </>
              ) : null}
              <View style={{ height: 12 }} />
              <View style={{ flexDirection: "row", gap: 8 }}>
                <View style={{ flex: 1 }}><Btn testID="cust-edit-cancel" title="Cancel" variant="outline" onPress={() => { setEdit(null); setEditReason(""); }} /></View>
                <View style={{ flex: 1 }}><Btn testID="cust-edit-save" title="Save (with reason)" variant="action" onPress={saveEdit} /></View>
              </View>
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* Customer POs Modal */}
      <Modal visible={!!posOpen} animationType="slide" transparent>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <ScrollView>
              <H2>{posOpen ? `Customer POs — ${posOpen.customer_id}` : "Customer POs"}</H2>
              <Muted>{posOpen?.name}</Muted>

              {pos.length === 0 ? (
                <Empty title="No customer POs yet" subtitle="Add the first PO issued by this customer." />
              ) : pos.map((p) => (
                <Card key={p.cpo_id} style={{ marginTop: 8 }} testID={`cpo-row-${p.cpo_id}`}>
                  <Text style={{ fontWeight: "700" }}>{p.po_number}</Text>
                  {p.po_date ? <Muted>Date: {p.po_date}</Muted> : null}
                  <Muted>Value: ₹{INR(Number(p.value || 0))}</Muted>
                  {p.validity_till ? <Muted>Valid till: {p.validity_till}</Muted> : null}
                  {p.attachment_name ? <Muted>Attachment: {p.attachment_name}</Muted> : null}
                  {p.remarks ? <Muted>{p.remarks}</Muted> : null}
                </Card>
              ))}

              <View style={{ height: 16, borderTopWidth: 1, borderTopColor: theme.colors.border, marginTop: 12 }} />
              <H2>Add Customer PO</H2>
              <Label>PO NUMBER *</Label>
              <TextInput value={nfCPO.po_number} onChangeText={(v) => setNfCPO({ ...nfCPO, po_number: v })} style={styles.input} testID="cpo-num" />
              <Label>PO DATE (YYYY-MM-DD)</Label>
              <TextInput value={nfCPO.po_date} onChangeText={(v) => setNfCPO({ ...nfCPO, po_date: v })} style={styles.input} placeholder="2026-06-15" testID="cpo-date" />
              <Label>VALUE (₹)</Label>
              <TextInput value={String(nfCPO.value || "")} onChangeText={(v) => setNfCPO({ ...nfCPO, value: Number(v.replace(/[^0-9.]/g, "")) })} style={styles.input} keyboardType="numeric" testID="cpo-value" />
              <Label>VALIDITY TILL (YYYY-MM-DD)</Label>
              <TextInput value={nfCPO.validity_till} onChangeText={(v) => setNfCPO({ ...nfCPO, validity_till: v })} style={styles.input} placeholder="2027-06-14" testID="cpo-valid" />
              <Label>REMARKS</Label>
              <TextInput value={nfCPO.remarks} onChangeText={(v) => setNfCPO({ ...nfCPO, remarks: v })} style={styles.input} multiline testID="cpo-rem" />
              <Muted>Attachment upload: use Edit &gt; Attach after creating the PO.</Muted>
              <View style={{ height: 12 }} />
              <View style={{ flexDirection: "row", gap: 8 }}>
                <View style={{ flex: 1 }}><Btn testID="cpo-close" title="Close" variant="outline" onPress={() => { setPosOpen(null); setPos([]); setNfCPO(emptyCPO); }} /></View>
                <View style={{ flex: 1 }}><Btn testID="cpo-add" title="Add PO" variant="action" onPress={addPO} /></View>
              </View>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 8, paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "700", color: theme.colors.text },
  input: { backgroundColor: theme.colors.surface, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, marginTop: 6, color: theme.colors.text },
  cid: { fontSize: 14, fontWeight: "700", color: theme.colors.primary, letterSpacing: 0.4 },
  cname: { fontSize: 15, fontWeight: "600", color: theme.colors.text, marginTop: 2 },
  iconBtn: { padding: 8, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 8, alignItems: "center" },
  err: { color: theme.colors.danger, marginTop: 8 },
  msg: { color: theme.colors.success, marginTop: 8 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modalCard: { backgroundColor: theme.colors.background, padding: 16, borderTopLeftRadius: 20, borderTopRightRadius: 20, maxHeight: "90%" },
});
