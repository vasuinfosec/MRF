import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Modal, TextInput } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AppShell } from "@/src/components/AppShell";
import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { Btn, Card, H1, Muted, Pill, Empty, Loader, Label, Stat } from "@/src/components/ui";
import { theme, statusLabel } from "@/src/theme";
import { useResponsive } from "@/src/hooks/useResponsive";
import { DTable, DHead, DH, DRow, DC } from "@/src/components/DataTable";

const FILTERS = ["all", "not_billed", "partially_billed", "fully_billed", "non_billable"];

export default function BillingScreen() {
  const { user } = useAuth();
  const { isDesktop } = useResponsive();
  const insets = useSafeAreaInsets();
  const [items, setItems] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("not_billed");
  const [editing, setEditing] = useState<any>(null);
  const [form, setForm] = useState<any>({});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const f = filter === "all" ? "" : `?filter=${filter}`;
      const d = await api<any[]>(`/billing/items${f}`);
      setItems(d);
    } catch (_e) { /* noop */ }
    setBusy(false);
  }, [filter]);

  useEffect(() => { if (user) load(); }, [user, load, filter]);

  const openEdit = (it: any) => {
    setEditing(it);
    setForm({
      qty_received: String(it.qty_received || 0),
      qty_issued: String(it.qty_issued || 0),
      qty_billed: String(it.qty_billed || 0),
      client_bill_ref: it.client_bill_ref || "",
      ra_bill_no: it.ra_bill_no || "",
      billing_date: it.billing_date || "",
      billing_remarks: "",
      billing_status: it.billing_status,
      override_reason: "",
    });
    setErr("");
  };

  const saveBilling = async () => {
    setSaving(true); setErr("");
    try {
      await api("/billing/update", {
        method: "POST",
        body: {
          mrf_id: editing.mrf_id, item_line_id: editing.item_line_id,
          qty_received: Number(form.qty_received),
          qty_issued: Number(form.qty_issued),
          qty_billed: Number(form.qty_billed),
          client_bill_ref: form.client_bill_ref,
          ra_bill_no: form.ra_bill_no,
          billing_date: form.billing_date,
          billing_remarks: form.billing_remarks,
          billing_status: form.billing_status,
          override_reason: form.override_reason || null,
        },
      });
      setEditing(null); load();
    } catch (e: any) { setErr(e.message); }
    setSaving(false);
  };

  const counts = {
    not_billed: items.filter((i) => i.billing_status === "not_billed").length,
    partially_billed: items.filter((i) => i.billing_status === "partially_billed").length,
    fully_billed: items.filter((i) => i.billing_status === "fully_billed").length,
    non_billable: items.filter((i) => i.billing_status === "non_billable" || !i.billable).length,
  };

  return (
    <AppShell title="Billing Control" testID="billing-screen">
      <H1>Billing Dashboard</H1>
      <Muted>Item-wise billing status across all MRFs.</Muted>

      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
        <Stat testID="stat-not-billed" label="Not Billed" value={counts.not_billed} tone="action" />
        <Stat testID="stat-partial-billed" label="Partial" value={counts.partially_billed} />
        <Stat testID="stat-full-billed" label="Fully Billed" value={counts.fully_billed} tone="success" />
        <Stat testID="stat-non-billable" label="Non-Billable" value={counts.non_billable} />
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow} style={{ marginTop: 12, marginHorizontal: -16, paddingHorizontal: 16 }}>
        {FILTERS.map((f) => {
          const active = filter === f;
          return (
            <TouchableOpacity key={f} testID={`bfilter-${f}`} onPress={() => setFilter(f)}
              style={[styles.chip, { borderColor: active ? theme.colors.primary : theme.colors.border, backgroundColor: active ? theme.colors.primary : "#fff" }]}>
              <Text style={{ color: active ? "#fff" : theme.colors.text, fontSize: 12, fontWeight: "600" }}>{statusLabel(f)}</Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>

      {busy && !items.length ? <Loader /> : null}

      {isDesktop ? (
        <View style={{ marginTop: 16 }}>
          <DTable>
            <DHead>
              <DH flex={2}>Description</DH>
              <DH flex={1}>MRF · Site</DH>
              <DH flex={0.7} right>Approved</DH>
              <DH flex={0.7} right>Received</DH>
              <DH flex={0.7} right>Issued</DH>
              <DH flex={0.7} right>Billed</DH>
              <DH flex={1.2}>Status</DH>
            </DHead>
            {items.map((it, i) => (
              <DRow key={i} testID={`bill-item-${it.item_line_id}`} onPress={() => openEdit(it)}>
                <DC flex={2} strong>{it.description}</DC>
                <DC flex={1} muted>{it.mrf_number} · {it.site}</DC>
                <DC flex={0.7} right>{it.qty_approved || 0}</DC>
                <DC flex={0.7} right>{it.qty_received || 0}</DC>
                <DC flex={0.7} right>{it.qty_issued || 0}</DC>
                <DC flex={0.7} right strong color={theme.colors.primary}>{it.qty_billed || 0}</DC>
                <DC flex={1.2}><Pill status={it.billing_status || "not_billed"} /></DC>
              </DRow>
            ))}
            {!busy && !items.length ? (
              <View style={{ paddingVertical: 24 }}>
                <Empty msg="No items to display." testID="bill-empty" />
              </View>
            ) : null}
          </DTable>
        </View>
      ) : (
        <View style={{ marginTop: 16, gap: 10 }}>
          {items.map((it, i) => (
            <TouchableOpacity key={i} testID={`bill-item-${it.item_line_id}`} onPress={() => openEdit(it)} activeOpacity={0.7}>
              <Card>
                <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                  <Text style={{ fontWeight: "700", flex: 1 }}>{it.description}</Text>
                  <Pill status={it.billing_status || "not_billed"} />
                </View>
                <Text style={{ fontSize: 12, color: theme.colors.textMuted, marginTop: 2 }}>{it.mrf_number} · {it.site}</Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                  <BillStat label="Approved" v={it.qty_approved} />
                  <BillStat label="Received" v={it.qty_received} />
                  <BillStat label="Issued" v={it.qty_issued} />
                  <BillStat label="Billed" v={it.qty_billed} tone />
                </View>
              </Card>
            </TouchableOpacity>
          ))}
          {!busy && !items.length ? <Empty msg="No items to display." testID="bill-empty" /> : null}
        </View>
      )}

      <Modal visible={!!editing} transparent animationType="fade" onRequestClose={() => setEditing(null)}>
        <View style={styles.modalBg}>
          <View style={[styles.modal, { paddingBottom: 16 + insets.bottom }]}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <Text style={{ fontWeight: "800", fontSize: 16 }}>Update Billing</Text>
              <TouchableOpacity onPress={() => setEditing(null)}><Ionicons name="close" size={22} /></TouchableOpacity>
            </View>
            <ScrollView>
              <Muted>{editing?.description}</Muted>
              <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>MRF: {editing?.mrf_number}</Text>
              <View style={{ marginTop: 12 }}>
                <FormInput testID="qty-received" label="Qty Received" value={form.qty_received} onChange={(v) => setForm({ ...form, qty_received: v })} keyboardType="decimal-pad" />
                <FormInput testID="qty-issued" label="Qty Issued/Consumed" value={form.qty_issued} onChange={(v) => setForm({ ...form, qty_issued: v })} keyboardType="decimal-pad" />
                <FormInput testID="qty-billed" label="Qty Billed" value={form.qty_billed} onChange={(v) => setForm({ ...form, qty_billed: v })} keyboardType="decimal-pad" />
                <FormInput testID="client-bill-ref" label="Client Billing Reference" value={form.client_bill_ref} onChange={(v) => setForm({ ...form, client_bill_ref: v })} />
                <FormInput testID="ra-bill-no" label="RA Bill Number" value={form.ra_bill_no} onChange={(v) => setForm({ ...form, ra_bill_no: v })} />
                <FormInput testID="billing-date" label="Billing Date (YYYY-MM-DD)" value={form.billing_date} onChange={(v) => setForm({ ...form, billing_date: v })} />
                <FormInput testID="billing-remarks" label="Remarks" value={form.billing_remarks} onChange={(v) => setForm({ ...form, billing_remarks: v })} />
                <Label>STATUS</Label>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
                  {["not_billed", "partially_billed", "fully_billed", "non_billable"].map((s) => (
                    <TouchableOpacity key={s} testID={`bstat-${s}`} onPress={() => setForm({ ...form, billing_status: s })}
                      style={[styles.statBtn, form.billing_status === s ? { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary } : {}]}>
                      <Text style={{ color: form.billing_status === s ? "#fff" : theme.colors.text, fontSize: 11, fontWeight: "600" }}>{statusLabel(s)}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
                {form.billing_status === "fully_billed" ? (
                  <FormInput testID="override-reason" label="Override Reason (required if billed < received)" value={form.override_reason} onChange={(v) => setForm({ ...form, override_reason: v })} />
                ) : null}
                {err ? <Text style={{ color: theme.colors.danger, marginTop: 6 }}>{err}</Text> : null}
                <Btn testID="save-billing-btn" title={saving ? "Saving…" : "Save"} variant="action" onPress={saveBilling} disabled={saving} style={{ marginTop: 8 }} />
              </View>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </AppShell>
  );
}

function BillStat({ label, v, tone }: { label: string; v: any; tone?: boolean }) {
  return (
    <View style={{ minWidth: 68, flex: 1, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 4, padding: 6 }}>
      <Text style={{ fontSize: 9, color: theme.colors.textMuted, textTransform: "uppercase", letterSpacing: 1 }}>{label}</Text>
      <Text style={{ fontSize: 13, fontWeight: "700", marginTop: 2, color: tone ? theme.colors.primary : theme.colors.text }}>{v}</Text>
    </View>
  );
}
function FormInput({ label, value, onChange, testID, ...rest }: any) {
  return (
    <View style={{ marginBottom: 10 }}>
      <Text style={{ fontSize: 11, fontWeight: "700", color: theme.colors.textMuted, textTransform: "uppercase", letterSpacing: 1.5, marginBottom: 4 }}>{label}</Text>
      <TextInput testID={testID} value={value} onChangeText={onChange} style={styles.inp} {...rest} />
    </View>
  );
}

const styles = StyleSheet.create({
  chipRow: { gap: 8, paddingRight: 16 },
  chip: { flexShrink: 0, height: 36, paddingHorizontal: 14, borderRadius: 999, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modal: { backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 20, maxHeight: "88%" },
  statBtn: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 6, borderWidth: 1, borderColor: theme.colors.borderStrong },
  inp: { borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, minHeight: 44, paddingHorizontal: 10, backgroundColor: "#fff", fontSize: 14 },
});
