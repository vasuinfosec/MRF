import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal, TextInput } from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { api, backendUrl, getToken } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, H1, H2, Muted, Pill, Label, Loader } from "@/src/components/ui";
import { theme } from "@/src/theme";

export default function PODetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const [po, setPo] = useState<any>(null);
  const [vendor, setVendor] = useState<any>(null);
  const [project, setProject] = useState<any>(null);
  const [grns, setGrns] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [receiveOpen, setReceiveOpen] = useState(false);
  const [receiveQty, setReceiveQty] = useState<Record<string, string>>({});
  const [receiveRemarks, setReceiveRemarks] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const p = await api<any>(`/po/${id}`);
      setPo(p);
      const [v, pr, gs] = await Promise.all([
        api<any[]>("/vendors").then((vs) => vs.find((x) => x.vendor_id === p.vendor_id)),
        api<any[]>("/projects").then((ps) => ps.find((x) => x.project_id === p.project_id)),
        api<any[]>(`/po/${id}/grns`),
      ]);
      setVendor(v); setProject(pr); setGrns(gs);
    } catch (_e) { /* noop */ }
    setBusy(false);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const downloadPDF = async () => {
    const t = await getToken();
    const url = `${backendUrl}/api/po/${id}/pdf?token=${t}`;
    if (typeof window !== "undefined") window.open(url, "_blank");
  };

  const markReceived = async () => {
    // Prefill remaining qty for each line
    const initial: Record<string, string> = {};
    (po.items || []).forEach((it: any) => {
      const remaining = Math.max(0, (Number(it.qty) || 0) - (Number(it.qty_received) || 0));
      initial[it.item_line_id] = String(remaining);
    });
    setReceiveQty(initial);
    setErr("");
    setReceiveOpen(true);
  };

  const submitReceipt = async () => {
    setSaving(true); setErr("");
    try {
      const items = (po.items || []).map((it: any) => ({
        mrf_id: it.mrf_id,
        item_line_id: it.item_line_id,
        qty: Number(receiveQty[it.item_line_id] || 0),
      })).filter((r: any) => r.qty > 0);
      if (!items.length) { setErr("Enter at least one quantity to receive."); setSaving(false); return; }
      await api(`/po/${id}/received`, { method: "POST", body: { items } });
      setReceiveOpen(false);
      load();
    } catch (e: any) { setErr(e.message || "Failed"); }
    setSaving(false);
  };

  if (!po) return busy ? <Loader /> : null;

  const canReceive = (po.status === "issued" || po.status === "partially_received") && (user?.role === "purchase" || user?.role === "billing" || user?.role === "admin");

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity testID="back-btn" onPress={() => router.back()} style={{ padding: 8 }}>
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>{po.po_number}</Text>
        <TouchableOpacity testID="download-pdf-btn" onPress={downloadPDF} style={{ padding: 8 }}>
          <Ionicons name="document-outline" size={22} color={theme.colors.primary} />
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 120 }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
          <View style={{ flex: 1 }}>
            <H1>{po.po_number}</H1>
            <Muted>{new Date(po.date).toLocaleDateString()}</Muted>
          </View>
          <Pill status={po.status === "issued" ? "sent_to_purchase" : po.status} />
        </View>

        <Card style={{ marginTop: 12 }}>
          <Label>VENDOR</Label>
          <Text style={{ fontWeight: "700", fontSize: 15 }}>{vendor?.name || po.vendor_id}</Text>
          <Text style={{ color: theme.colors.textMuted, marginTop: 2 }}>{vendor?.address}</Text>
          <Text style={{ color: theme.colors.textMuted }}>GSTIN: {vendor?.gstin}</Text>
        </Card>

        <Card style={{ marginTop: 10 }}>
          <Label>PROJECT</Label>
          <Text style={{ fontWeight: "700", fontSize: 15 }}>{project?.code} — {project?.name}</Text>
          <Text style={{ color: theme.colors.textMuted }}>Delivery: {po.delivery_site}</Text>
          <Text style={{ color: theme.colors.textMuted, marginTop: 4 }}>MRF Refs: {po.mrf_refs?.join(", ")}</Text>
        </Card>

        <H2 style={{ marginTop: 16, marginBottom: 8 }}>Items</H2>
        {po.items.map((it: any, i: number) => {
          const gross = it.qty * it.rate;
          const ad = gross - (it.discount || 0);
          const gst = ad * (it.gst || 0) / 100;
          const received = Number(it.qty_received || 0);
          const remaining = Math.max(0, Number(it.qty || 0) - received);
          return (
            <Card key={i} style={{ marginBottom: 8 }} testID={`po-item-${i}`}>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
                <Text style={{ fontWeight: "700", flex: 1 }}>{i + 1}. {it.description}</Text>
                {received > 0 ? (
                  <Pill status={remaining > 0 ? "partially_received" : "received"} />
                ) : null}
              </View>
              {it.specification ? <Muted>{it.specification}</Muted> : null}
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                <MiniStat label="Ordered" value={`${it.qty} ${it.unit}`} />
                <MiniStat label="Received" value={`${received}`} />
                <MiniStat label="Remaining" value={`${remaining}`} />
                <MiniStat label="Rate" value={`₹${it.rate}`} />
                <MiniStat label="GST" value={`${it.gst}%`} />
                <MiniStat label="Total" value={`₹${(ad + gst).toFixed(2)}`} />
              </View>
              {Array.isArray(it.receipts) && it.receipts.length > 0 ? (
                <View style={styles.receiptsBox} testID={`receipts-${i}`}>
                  <Text style={styles.receiptsLabel}>Receipt History</Text>
                  {it.receipts.map((r: any, ri: number) => (
                    <View key={ri} style={styles.receiptRow}>
                      <Text style={styles.receiptDate}>{new Date(r.date).toLocaleString()}</Text>
                      <Text style={styles.receiptQty}>+{r.qty} {it.unit}</Text>
                      <Text style={styles.receiptUser}>{r.user_name}</Text>
                    </View>
                  ))}
                </View>
              ) : null}
            </Card>
          );
        })}

        <Card style={{ marginTop: 12, backgroundColor: theme.colors.surface }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 }}>
            <Text>Freight</Text><Text>₹ {po.freight || 0}</Text>
          </View>
          <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 }}>
            <Text>Other Charges</Text><Text>₹ {po.other_charges || 0}</Text>
          </View>
          <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 8, borderTopWidth: 1, borderTopColor: theme.colors.border, marginTop: 8 }}>
            <Text style={{ fontWeight: "800", fontSize: 16 }}>Grand Total</Text>
            <Text style={{ fontWeight: "800", fontSize: 18, color: theme.colors.primary }}>
              ₹ {new Intl.NumberFormat("en-IN").format(po.total || 0)}
            </Text>
          </View>
        </Card>

        <Card style={{ marginTop: 10 }}>
          <Label>TERMS</Label>
          <Text style={{ marginTop: 4 }}><Text style={{ fontWeight: "700" }}>Delivery: </Text>{po.delivery_schedule || "—"}</Text>
          <Text style={{ marginTop: 4 }}><Text style={{ fontWeight: "700" }}>Payment: </Text>{po.payment_terms || "—"}</Text>
          <Text style={{ marginTop: 4 }}><Text style={{ fontWeight: "700" }}>Warranty: </Text>{po.warranty_terms || "—"}</Text>
          <Text style={{ marginTop: 4 }}><Text style={{ fontWeight: "700" }}>Signatory: </Text>{po.authorised_signatory || "—"}</Text>
        </Card>

        <View style={{ marginTop: 16, gap: 8 }}>
          <Btn testID="pdf-download-btn" title="Download PDF" variant="primary" onPress={downloadPDF} />
          {canReceive ? <Btn testID="mark-received-btn" title="Receive Items" variant="action" onPress={markReceived} /> : null}
        </View>

        {grns.length > 0 ? (
          <>
            <H2 style={{ marginTop: 20, marginBottom: 8 }}>Goods Received Notes ({grns.length})</H2>
            {grns.map((g) => (
              <Card key={g.grn_id} style={{ marginBottom: 8 }} testID={`grn-${g.grn_number.replace(/\//g, "-")}`}>
                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontWeight: "700", color: theme.colors.primary }}>{g.grn_number}</Text>
                    <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>
                      {new Date(g.date).toLocaleString()} · {g.received_by_name}
                    </Text>
                    <Text style={{ fontSize: 12, color: theme.colors.textSecondary, marginTop: 4 }}>
                      {g.items?.length || 0} line(s) · {(g.items || []).reduce((s: number, it: any) => s + (Number(it.qty) || 0), 0)} units received
                    </Text>
                  </View>
                  <TouchableOpacity testID={`grn-pdf-${g.grn_number.replace(/\//g, "-")}`} onPress={() => downloadGRN(g.grn_id)}
                    style={styles.grnPdfBtn}>
                    <Ionicons name="document-outline" size={18} color="#fff" />
                    <Text style={{ color: "#fff", fontWeight: "700", fontSize: 12, marginLeft: 4 }}>PDF</Text>
                  </TouchableOpacity>
                </View>
              </Card>
            ))}
          </>
        ) : null}
      </ScrollView>

      {/* Per-line receipt modal */}
      <Modal visible={receiveOpen} transparent animationType="fade" onRequestClose={() => setReceiveOpen(false)}>
        <View style={styles.modalBg}>
          <View style={[styles.modal, { paddingBottom: 16 + insets.bottom }]}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
              <Text style={{ fontWeight: "800", fontSize: 16 }}>Receive Items</Text>
              <TouchableOpacity testID="close-receive-btn" onPress={() => setReceiveOpen(false)}>
                <Ionicons name="close" size={22} />
              </TouchableOpacity>
            </View>
            <Muted>Enter received quantity per line. Leave 0 to skip.</Muted>
            <ScrollView style={{ marginTop: 10, maxHeight: 380 }}>
              {(po.items || []).map((it: any, i: number) => {
                const already = Number(it.qty_received || 0);
                const remaining = Math.max(0, Number(it.qty || 0) - already);
                return (
                  <View key={it.item_line_id} style={styles.recvRow} testID={`recv-row-${i}`}>
                    <View style={{ flex: 1, paddingRight: 8 }}>
                      <Text style={{ fontWeight: "700", fontSize: 13 }} numberOfLines={2}>{it.description}</Text>
                      <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>
                        Ordered {it.qty} {it.unit} · Received {already} · Rem {remaining}
                      </Text>
                    </View>
                    <TextInput
                      testID={`recv-qty-${i}`}
                      value={receiveQty[it.item_line_id] ?? ""}
                      onChangeText={(v) => setReceiveQty((s) => ({ ...s, [it.item_line_id]: v }))}
                      keyboardType="decimal-pad"
                      editable={remaining > 0}
                      style={[styles.recvInp, remaining <= 0 && { backgroundColor: theme.colors.surface2, opacity: 0.6 }]}
                    />
                  </View>
                );
              })}
            </ScrollView>
            {err ? <Text testID="recv-err" style={{ color: theme.colors.danger, marginTop: 6 }}>{err}</Text> : null}
            <TextInput
              testID="recv-remarks"
              placeholder="Remarks (optional) — challan #, transporter, etc."
              value={receiveRemarks}
              onChangeText={setReceiveRemarks}
              style={styles.remarksInp}
              multiline
            />
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <View style={{ flex: 1 }}>
                <Btn title="Cancel" variant="outline" onPress={() => setReceiveOpen(false)} />
              </View>
              <View style={{ flex: 1 }}>
                <Btn testID="confirm-receive-btn" title={saving ? "Saving…" : "Confirm Receipt"} variant="action" onPress={submitReceipt} disabled={saving} />
              </View>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ minWidth: 70, flex: 1, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 4, padding: 6 }}>
      <Text style={{ fontSize: 9, color: theme.colors.textMuted, textTransform: "uppercase", letterSpacing: 1 }}>{label}</Text>
      <Text style={{ fontSize: 13, fontWeight: "700", marginTop: 2 }}>{value}</Text>
    </View>
  );
}
const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 8, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modal: { backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 20 },
  recvRow: { flexDirection: "row", alignItems: "center", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  recvInp: { width: 80, borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, paddingHorizontal: 10, paddingVertical: 8, textAlign: "right", fontSize: 14, backgroundColor: "#fff" },
  remarksInp: { borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, paddingHorizontal: 10, paddingVertical: 10, marginTop: 10, fontSize: 13, minHeight: 44, backgroundColor: "#fff" },
  receiptsBox: { marginTop: 10, padding: 10, backgroundColor: theme.colors.surface, borderRadius: 6, borderWidth: 1, borderColor: theme.colors.border },
  receiptsLabel: { fontSize: 10, fontWeight: "700", color: theme.colors.textMuted, textTransform: "uppercase", letterSpacing: 1, marginBottom: 4 },
  receiptRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4, borderTopWidth: 1, borderTopColor: theme.colors.border },
  receiptDate: { fontSize: 11, color: theme.colors.textSecondary, flex: 1 },
  receiptQty: { fontSize: 12, fontWeight: "700", color: theme.colors.success, marginHorizontal: 8 },
  receiptUser: { fontSize: 11, color: theme.colors.textMuted, minWidth: 60, textAlign: "right" },
  grnPdfBtn: { flexDirection: "row", alignItems: "center", backgroundColor: theme.colors.primary, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 6 },
});
