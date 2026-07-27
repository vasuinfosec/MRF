import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal, TextInput } from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { api, backendUrl, getDownloadToken } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, H1, H2, Muted, Pill, Label, Loader } from "@/src/components/ui";
import ExportMenu from "@/src/components/ExportMenu";
import AuditTrail from "@/src/components/AuditTrail";
import MatVarChips from "@/src/components/MatVarChips";
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
  const [invoices, setInvoices] = useState<any[]>([]);
  const [invoiceOpen, setInvoiceOpen] = useState(false);
  const [invLines, setInvLines] = useState<Record<string, { qty: string; rate: string; discount: string; gst: string }>>({});
  const [vendorInvNo, setVendorInvNo] = useState("");
  const [invDate, setInvDate] = useState("");
  const [invFreight, setInvFreight] = useState("0");
  const [invOther, setInvOther] = useState("0");
  const [invRemarks, setInvRemarks] = useState("");
  const [invSaving, setInvSaving] = useState(false);
  const [invErr, setInvErr] = useState("");
  const [mrfNumbers, setMrfNumbers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [receiveOpen, setReceiveOpen] = useState(false);
  const [receiveQty, setReceiveQty] = useState<Record<string, string>>({});
  const [receiveRemarks, setReceiveRemarks] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [exportOpen, setExportOpen] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const p = await api<any>(`/po/${id}`);
      setPo(p);
      const [v, pr, gs, ivs] = await Promise.all([
        api<any[]>("/vendors").then((vs) => vs.find((x) => x.vendor_id === p.vendor_id)),
        api<any[]>("/projects").then((ps) => ps.find((x) => x.project_id === p.project_id)),
        api<any[]>(`/po/${id}/grns`),
        api<any[]>(`/po/${id}/invoices`),
      ]);
      setVendor(v); setProject(pr); setGrns(gs); setInvoices(ivs);
      // Resolve MRF ids -> mrf_number for display
      const refs: string[] = p.mrf_refs || [];
      const map: Record<string, string> = {};
      await Promise.all(refs.map(async (mid) => {
        try { const m = await api<any>(`/mrf/${mid}`); map[mid] = m.mrf_number; } catch (_e) { /* noop */ }
      }));
      setMrfNumbers(map);
    } catch (_e) { /* noop */ }
    setBusy(false);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const downloadPDF = async () => {
    // Kept for backward-compat: opens the unified Export menu.
    setExportOpen(true);
  };

  const openExport = () => setExportOpen(true);

  const markReceived = async () => {
    // Prefill remaining qty for each line
    const initial: Record<string, string> = {};
    (po.items || []).forEach((it: any) => {
      const remaining = Math.max(0, (Number(it.qty) || 0) - (Number(it.qty_received) || 0));
      initial[it.item_line_id] = String(remaining);
    });
    setReceiveQty(initial);
    setReceiveRemarks("");
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
      await api(`/po/${id}/received`, { method: "POST", body: { items, remarks: receiveRemarks } });
      setReceiveOpen(false);
      load();
    } catch (e: any) { setErr(e.message || "Failed"); }
    setSaving(false);
  };

  const downloadGRN = async (grn_id: string) => {
    const t = await getDownloadToken();
    if (!t) return;
    if (typeof window !== "undefined") window.open(`${backendUrl}/api/grn/${grn_id}/pdf?token=${t}`, "_blank");
  };

  const downloadInvoice = async (inv_id: string) => {
    const t = await getDownloadToken();
    if (!t) return;
    if (typeof window !== "undefined") window.open(`${backendUrl}/api/invoice/${inv_id}/pdf?token=${t}`, "_blank");
  };

  const openInvoice = () => {
    const map: Record<string, any> = {};
    (po.items || []).forEach((it: any) => {
      const already = (invoices || []).reduce((s: number, iv: any) => {
        return s + (iv.items || []).filter((r: any) => r.item_line_id === it.item_line_id)
          .reduce((ss: number, r: any) => ss + Number(r.qty || 0), 0);
      }, 0);
      const remaining = Math.max(0, Number(it.qty || 0) - already);
      map[it.item_line_id] = {
        qty: String(remaining),
        rate: String(it.rate || 0),
        discount: String(it.discount || 0),
        gst: String(it.gst || 0),
      };
    });
    setInvLines(map);
    setVendorInvNo(""); setInvDate(new Date().toISOString().slice(0, 10));
    setInvFreight(String(po.freight || 0));
    setInvOther(String(po.other_charges || 0));
    setInvRemarks(""); setInvErr("");
    setInvoiceOpen(true);
  };

  const submitInvoice = async () => {
    setInvSaving(true); setInvErr("");
    try {
      const items = (po.items || []).map((it: any) => {
        const l = invLines[it.item_line_id];
        return {
          mrf_id: it.mrf_id, item_line_id: it.item_line_id,
          description: it.description, unit: it.unit,
          qty: Number(l?.qty || 0), rate: Number(l?.rate || 0),
          discount: Number(l?.discount || 0), gst: Number(l?.gst || 0),
        };
      }).filter((r: any) => r.qty > 0);
      if (!items.length) { setInvErr("Enter qty > 0 on at least one line."); setInvSaving(false); return; }
      await api("/invoice", { method: "POST", body: {
        po_id: id, vendor_invoice_number: vendorInvNo, invoice_date: invDate,
        items, freight: Number(invFreight) || 0, other_charges: Number(invOther) || 0,
        remarks: invRemarks,
      } });
      setInvoiceOpen(false);
      load();
    } catch (e: any) { setInvErr(e.message || "Failed"); }
    setInvSaving(false);
  };

  const invoiceTotal = React.useMemo(() => {
    let sub = 0, gstTot = 0;
    Object.values(invLines).forEach((l) => {
      const g = Number(l.qty) * Number(l.rate);
      const ad = g - Number(l.discount);
      sub += ad;
      gstTot += ad * Number(l.gst) / 100;
    });
    return sub + gstTot + (Number(invFreight) || 0) + (Number(invOther) || 0);
  }, [invLines, invFreight, invOther]);

  if (!po) return busy ? <Loader /> : null;

  const canReceive = (po.status === "issued" || po.status === "partially_received") &&
    (user?.role === "purchase" || user?.role === "director" || user?.role === "admin" ||
     user?.role === "site_engineer" || user?.role === "store" || user?.role === "pm");
  const isPendingGM = po.status === "pending_gm_approval";
  const isPendingDir = po.status === "pending_director_approval";
  const canApprovePO =
    (isPendingGM && (user?.role === "gm" || user?.role === "director" || user?.role === "admin")) ||
    (isPendingDir && (user?.role === "director" || user?.role === "admin"));

  const doApprovePO = async (action: "approve" | "reject") => {
    try {
      await api(`/po/${id}/approve`, { method: "POST", body: { action } });
      load();
    } catch (e: any) { setErr(e.message || "Failed"); }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity testID="back-btn" onPress={() => router.back()} style={{ padding: 8 }}>
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>{po.po_number}</Text>
        <TouchableOpacity testID="download-pdf-btn" onPress={openExport} style={{ padding: 8 }}>
          <Ionicons name="download-outline" size={22} color={theme.colors.primary} />
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 120 }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
          <View style={{ flex: 1 }}>
            <H1>{po.po_number}</H1>
            <Muted>{new Date(po.date).toLocaleDateString()}</Muted>
            {po.customer_id ? (
              <View style={{ marginTop: 6, backgroundColor: "rgba(0,47,167,0.06)", borderWidth: 1, borderColor: "rgba(0,47,167,0.2)", borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4, alignSelf: "flex-start" }} testID="po-customer">
                <Text style={{ fontSize: 11, color: "#002FA7", fontWeight: "700", letterSpacing: 0.4 }}>{po.customer_id}</Text>
                {po.customer_name ? <Text style={{ fontSize: 12, color: "#111" }}>{po.customer_name}</Text> : null}
              </View>
            ) : null}
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
          <Text style={{ color: theme.colors.textMuted, marginTop: 4 }}>
            MRF Refs: {(po.mrf_refs || []).map((r: string) => mrfNumbers[r] || r).join(", ") || "—"}
          </Text>
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
              <MatVarChips
                materialUid={it.material_uid || (typeof it.material_id === "string" && it.material_id.startsWith("MAT-") ? it.material_id : undefined)}
                variantUid={it.variant_uid || (typeof it.variant_id === "string" && it.variant_id.startsWith("VAR-") ? it.variant_id : undefined)}
              />
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
          <Btn testID="pdf-download-btn" title="Export / Download" variant="primary" onPress={openExport} />
          {canApprovePO ? (
            <>
              <Btn testID="po-approve-btn" title={`Approve PO (₹${new Intl.NumberFormat("en-IN").format(po.total || 0)})`} variant="action" onPress={() => doApprovePO("approve")} />
              <Btn testID="po-reject-btn" title="Reject PO" variant="outline" onPress={() => doApprovePO("reject")} />
            </>
          ) : null}
          {isPendingGM || isPendingDir ? (
            <Text style={{ color: theme.colors.textMuted, fontSize: 12, textAlign: "center", marginTop: 2 }}>
              {isPendingDir ? "Awaiting Director approval" : "Awaiting GM approval"} · Receipts blocked until approved
            </Text>
          ) : null}
          {canReceive ? <Btn testID="mark-received-btn" title="Receive Items" variant="action" onPress={markReceived} /> : null}
          {(user?.role === "purchase" || user?.role === "director" || user?.role === "admin") ? (
            <Btn testID="record-invoice-btn" title="Record Vendor Invoice" variant="outline" onPress={openInvoice} />
          ) : null}
        </View>

        {invoices.length > 0 ? (
          <>
            <H2 style={{ marginTop: 20, marginBottom: 8 }}>Vendor Invoices ({invoices.length})</H2>
            {invoices.map((iv) => (
              <Card key={iv.invoice_id} style={{ marginBottom: 8 }} testID={`inv-${iv.invoice_number.replace(/\//g, "-")}`}>
                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontWeight: "700", color: theme.colors.primary }}>{iv.invoice_number}</Text>
                    <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>
                      {iv.invoice_date} · Vendor Ref: {iv.vendor_invoice_number || "—"}
                    </Text>
                    <Text style={{ fontSize: 13, fontWeight: "700", marginTop: 4, color: theme.colors.text }}>
                      ₹ {new Intl.NumberFormat("en-IN").format(Math.round(iv.total || 0))}
                    </Text>
                  </View>
                  <TouchableOpacity testID={`inv-pdf-${iv.invoice_number.replace(/\//g, "-")}`}
                    onPress={() => downloadInvoice(iv.invoice_id)} style={styles.grnPdfBtn}>
                    <Ionicons name="document-outline" size={18} color="#fff" />
                    <Text style={{ color: "#fff", fontWeight: "700", fontSize: 12, marginLeft: 4 }}>PDF</Text>
                  </TouchableOpacity>
                </View>
              </Card>
            ))}
          </>
        ) : null}

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

        {/* Audit Trail */}
        <View style={{ marginTop: 20 }}>
          <AuditTrail entityId={String(id || "")} title="Audit Trail" limit={100} />
        </View>

        <View style={{ marginTop: 12 }}>
          <Btn
            testID="cs-btn-po"
            title="View / Attach Comparative Statement"
            variant="outline"
            onPress={() => router.push({ pathname: "/comparative-statement", params: { po_id: String(id || "") } })}
          />
        </View>
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

      {/* Vendor Invoice Modal */}
      <Modal visible={invoiceOpen} transparent animationType="fade" onRequestClose={() => setInvoiceOpen(false)}>
        <View style={styles.modalBg}>
          <View style={[styles.modal, { paddingBottom: 16 + insets.bottom, maxHeight: "90%" }]}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
              <Text style={{ fontWeight: "800", fontSize: 16 }}>Record Vendor Invoice</Text>
              <TouchableOpacity testID="close-invoice-btn" onPress={() => setInvoiceOpen(false)}>
                <Ionicons name="close" size={22} />
              </TouchableOpacity>
            </View>
            <ScrollView style={{ marginTop: 6 }}>
              <View style={{ flexDirection: "row", gap: 8 }}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.miniLbl}>Vendor Invoice #</Text>
                  <TextInput testID="vendor-inv-no" value={vendorInvNo} onChangeText={setVendorInvNo} placeholder="e.g. HW-2026-0451" style={styles.miniInp} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.miniLbl}>Date</Text>
                  <TextInput testID="inv-date" value={invDate} onChangeText={setInvDate} placeholder="YYYY-MM-DD" style={styles.miniInp} />
                </View>
              </View>

              {(po.items || []).map((it: any, i: number) => {
                const l = invLines[it.item_line_id] || { qty: "0", rate: "0", discount: "0", gst: "0" };
                return (
                  <View key={it.item_line_id} style={styles.recvRow}>
                    <View style={{ flex: 1, paddingRight: 6 }}>
                      <Text style={{ fontWeight: "700", fontSize: 13 }} numberOfLines={2}>{it.description}</Text>
                      <Text style={{ fontSize: 10, color: theme.colors.textMuted }}>PO qty {it.qty} · rate {it.rate}</Text>
                    </View>
                    <View style={{ flexDirection: "row", gap: 4 }}>
                      <TextInput testID={`inv-qty-${i}`} value={l.qty} onChangeText={(v) => setInvLines((s) => ({ ...s, [it.item_line_id]: { ...s[it.item_line_id], qty: v } }))} keyboardType="decimal-pad" style={styles.tinyInp} />
                      <TextInput testID={`inv-rate-${i}`} value={l.rate} onChangeText={(v) => setInvLines((s) => ({ ...s, [it.item_line_id]: { ...s[it.item_line_id], rate: v } }))} keyboardType="decimal-pad" style={styles.tinyInp} />
                      <TextInput testID={`inv-gst-${i}`} value={l.gst} onChangeText={(v) => setInvLines((s) => ({ ...s, [it.item_line_id]: { ...s[it.item_line_id], gst: v } }))} keyboardType="decimal-pad" style={styles.tinyInp} />
                    </View>
                  </View>
                );
              })}

              <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.miniLbl}>Freight</Text>
                  <TextInput testID="inv-freight" value={invFreight} onChangeText={setInvFreight} keyboardType="decimal-pad" style={styles.miniInp} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.miniLbl}>Other</Text>
                  <TextInput testID="inv-other" value={invOther} onChangeText={setInvOther} keyboardType="decimal-pad" style={styles.miniInp} />
                </View>
              </View>
              <TextInput testID="inv-remarks" value={invRemarks} onChangeText={setInvRemarks} placeholder="Remarks (optional)" style={[styles.remarksInp, { marginTop: 8 }]} multiline />
              <View style={{ marginTop: 10, padding: 10, backgroundColor: theme.colors.surface, borderRadius: 6, flexDirection: "row", justifyContent: "space-between" }}>
                <Text style={{ fontWeight: "700" }}>Invoice Total</Text>
                <Text testID="inv-total" style={{ fontWeight: "800", fontSize: 16, color: theme.colors.primary }}>
                  ₹ {new Intl.NumberFormat("en-IN").format(Math.round(invoiceTotal))}
                </Text>
              </View>
              {invErr ? <Text testID="inv-err" style={{ color: theme.colors.danger, marginTop: 6 }}>{invErr}</Text> : null}
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <View style={{ flex: 1 }}><Btn title="Cancel" variant="outline" onPress={() => setInvoiceOpen(false)} /></View>
              <View style={{ flex: 1 }}>
                <Btn testID="submit-invoice-btn" title={invSaving ? "Saving…" : "Save Invoice"} variant="action" onPress={submitInvoice} disabled={invSaving} />
              </View>
            </View>
          </View>
        </View>
      </Modal>

      <ExportMenu
        visible={exportOpen}
        onClose={() => setExportOpen(false)}
        entity="po"
        id={String(id || "")}
        recordNumber={po?.po_number}
      />
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
  miniLbl: { fontSize: 10, fontWeight: "700", color: theme.colors.textMuted, textTransform: "uppercase", letterSpacing: 1, marginBottom: 4 },
  miniInp: { borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, paddingHorizontal: 10, paddingVertical: 8, backgroundColor: "#fff", fontSize: 13 },
  tinyInp: { width: 54, borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 4, paddingHorizontal: 6, paddingVertical: 6, textAlign: "right", fontSize: 12, backgroundColor: "#fff" },
});
