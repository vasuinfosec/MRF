import React, { useEffect, useState, useCallback, useMemo } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal, TextInput, Platform } from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { api, backendUrl, getToken } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, H1, H2, Muted, Pill, Label, Body, Loader } from "@/src/components/ui";
import { theme, statusLabel, canonicalStatus } from "@/src/theme";

function ownerRoleForStatus(status: string): string {
  const s = canonicalStatus(status);
  if (s === "draft" || s === "returned") return "site_engineer";
  if (["submitted", "under_pm_review", "under_review", "pm_review"].includes(s)) return "pm";
  if (["under_purchase_review", "purchase_pending", "sent_to_purchase", "quotation_received", "po_pending"].includes(s)) return "purchase";
  if (s === "under_gm_review") return "gm";
  if (s === "under_director_review") return "director";
  if (s === "authorised") return "purchase";
  return "";
}

const OWNER_LABEL: Record<string, string> = {
  site_engineer: "Site Engineer (creator)",
  pm: "Project Manager",
  gm: "General Manager",
  director: "Director",
  purchase: "Purchase Team",
  admin: "Administrator",
};

export default function MRFDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();

  const [mrf, setMrf] = useState<any>(null);
  const [projects, setProjects] = useState<any[]>([]);
  const [customer, setCustomer] = useState<any>(null);
  const [audit, setAudit] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [loadErr, setLoadErr] = useState("");
  const [action, setAction] = useState<null | "approve" | "reject" | "return">(null);
  const [comment, setComment] = useState("");
  const [itemActions, setItemActions] = useState<Record<string, { action?: string; qty_approved?: number; reason?: string }>>({});

  const load = useCallback(async () => {
    if (!id) return;
    setBusy(true); setLoadErr("");
    try {
      // Fetch MRF + projects first (critical). Audit is optional — never block.
      const [m, p] = await Promise.all([
        api<any>(`/mrf/${id}`),
        api<any[]>("/projects"),
      ]);
      setMrf(m); setProjects(p);
      const map: any = {};
      (m.items || []).forEach((it: any) => { map[it.item_line_id] = { qty_approved: it.qty_approved ?? it.qty_requested }; });
      setItemActions(map);
      // Audit — best-effort. If backend forbids, we just skip that section.
      try {
        const a = await api<any[]>(`/audit?entity_id=${id}`);
        setAudit(a || []);
      } catch { setAudit([]); }
      // Load customer if MRF has one
      if (m.customer_id) {
        try {
          const c = await api<any>(`/customers/${m.customer_id}`);
          setCustomer(c);
        } catch { setCustomer(null); }
      } else { setCustomer(null); }
    } catch (e: any) {
      setLoadErr(e?.message || "Could not load this MRF. It may have been deleted or you may not have permission.");
      setMrf(null);
    }
    setBusy(false);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const project = projects.find((p) => p.project_id === mrf?.project_id);
  const canonical = canonicalStatus(mrf?.status);
  const owner = ownerRoleForStatus(mrf?.status || "");
  const ownerLabel = OWNER_LABEL[owner] || "—";

  const isPMRole = user?.role === "pm" || user?.role === "gm" || user?.role === "director" || user?.role === "admin";
  const canSubmit = mrf && ["draft", "returned"].includes(canonical) && (user?.user_id === mrf.created_by || user?.role === "admin" || user?.role === "director");
  const canEdit = canSubmit;
  const canReview = mrf && ["under_pm_review", "under_review"].includes(canonical) && isPMRole;
  const canSendPurchase = mrf && canonical === "authorised" && isPMRole;

  const isPending = user && owner && (user.role === owner || user.role === "admin" || user.role === "director");
  const pendingAction = useMemo(() => {
    switch (canonical) {
      case "draft":
      case "returned":
        return "Site Engineer must complete/submit the MRF";
      case "under_pm_review":
        return "Project Manager must authorise, reject, or return the MRF";
      case "under_purchase_review":
      case "purchase_pending":
      case "quotation_received":
      case "po_pending":
        return "Purchase team must issue quotation / PO";
      case "under_gm_review": return "GM approval pending";
      case "under_director_review": return "Director approval pending";
      case "authorised": return "Send to Purchase to begin procurement";
      case "po_issued": return "Awaiting goods receipt";
      case "partially_received": return "Awaiting remaining goods";
      case "fully_received": return "Ready to close / bill";
      case "closed":
      case "cancelled":
      case "rejected":
        return "No further action required";
      default: return "";
    }
  }, [canonical]);

  const doSubmit = async () => {
    try {
      await api(`/mrf/${id}/submit`, { method: "POST" });
      await load();
    } catch (e: any) { setLoadErr(e?.message || "Submit failed"); }
  };
  const doSendPurchase = async () => {
    try {
      await api(`/mrf/${id}/send-to-purchase`, { method: "POST" });
      await load();
    } catch (e: any) { setLoadErr(e?.message || "Failed"); }
  };
  const doAction = async () => {
    if (!action) return;
    try {
      const payload: any = { action, comment };
      if (action !== "return") {
        payload.item_actions = Object.entries(itemActions).map(([lid, v]) => ({
          item_line_id: lid,
          action: v.action || "approve",
          qty_approved: v.qty_approved,
          reason: v.reason,
        }));
      }
      await api(`/mrf/${id}/approve`, { method: "POST", body: payload });
      setAction(null); setComment("");
      await load();
    } catch (e: any) { setLoadErr(e?.message || "Action failed"); setAction(null); }
  };

  // Print MRF (browser print)
  const doPrint = () => {
    if (Platform.OS === "web" && typeof window !== "undefined") window.print();
  };

  // Export MRF as PDF via backend? MRF PDF endpoint isn't present — export Excel row.
  const doExport = async () => {
    const t = await getToken();
    if (typeof window !== "undefined") window.open(`${backendUrl}/api/export/mrf?token=${t}`, "_blank");
  };

  // ---- Render states ----
  if (busy && !mrf && !loadErr) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }}><Ionicons name="arrow-back" size={22} color={theme.colors.text} /></TouchableOpacity>
          <Text style={styles.title}>Loading MRF…</Text>
          <View style={{ width: 38 }} />
        </View>
        <View style={{ padding: 40, alignItems: "center" }}>
          <Loader />
          <Muted>Fetching MRF details…</Muted>
        </View>
      </SafeAreaView>
    );
  }

  if (!mrf) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }}><Ionicons name="arrow-back" size={22} color={theme.colors.text} /></TouchableOpacity>
          <Text style={styles.title}>MRF Unavailable</Text>
          <View style={{ width: 38 }} />
        </View>
        <View style={{ padding: 24 }}>
          <Card testID="mrf-load-err">
            <Text style={{ fontSize: 16, fontWeight: "700", color: theme.colors.danger }}>Unable to open MRF</Text>
            <Muted style={{ marginTop: 6 }}>{loadErr || "MRF not found."}</Muted>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 16 }}>
              <View style={{ flex: 1 }}><Btn testID="retry-btn" title="Retry" variant="outline" onPress={load} /></View>
              <View style={{ flex: 1 }}><Btn testID="back-list-btn" title="Back to List" variant="primary" onPress={() => router.replace("/mrf" as any)} /></View>
            </View>
          </Card>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity testID="back-btn" onPress={() => router.back()} style={{ padding: 8 }}>
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>{mrf.mrf_number}</Text>
        <View style={{ width: 38 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 200 }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
          <View style={{ flex: 1 }}>
            <H1>{mrf.mrf_number}</H1>
            <Muted>{project ? `${project.code} — ${project.name}` : mrf.project_id}</Muted>
            {mrf.customer_id ? (
              <View style={{ marginTop: 6, backgroundColor: "rgba(0,47,167,0.06)", borderWidth: 1, borderColor: "rgba(0,47,167,0.2)", borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4, alignSelf: "flex-start" }} testID="mrf-customer">
                <Text style={{ fontSize: 11, color: "#002FA7", fontWeight: "700", letterSpacing: 0.4 }}>{mrf.customer_id}</Text>
                {mrf.customer_name ? <Text style={{ fontSize: 12, color: "#111" }}>{mrf.customer_name}</Text> : null}
              </View>
            ) : null}
          </View>
          <Pill status={mrf.status} />
        </View>

        <Card style={{ marginTop: 12 }} testID="mrf-meta-card">
          <Row2 label="Status" value={statusLabel(mrf.status)} />
          <Row2 label="Current Owner" value={ownerLabel} />
          {pendingAction ? <Row2 label="Pending Action" value={pendingAction} /> : null}
          <Row2 label="Site" value={mrf.site} />
          <Row2 label="System" value={mrf.system_category} />
          <Row2 label="Requested by" value={mrf.requesting_person} />
          <Row2 label="Required by" value={mrf.required_by} />
          <Row2 label="Date" value={new Date(mrf.date).toLocaleDateString()} />
          {mrf.remarks ? <Row2 label="Remarks" value={mrf.remarks} /> : null}
          {mrf.pm_comments ? <Row2 label="PM Comments" value={mrf.pm_comments} /> : null}
        </Card>

        {/* Customer + Customer PO */}
        {customer || mrf.customer_id ? (
          <Card style={{ marginTop: 12 }} testID="mrf-customer-card">
            <H2>Customer</H2>
            <Row2 label="Customer ID" value={mrf.customer_id || "—"} />
            <Row2 label="Name" value={customer?.name || mrf.customer_name || "—"} />
            {customer?.gstin ? <Row2 label="GSTIN" value={customer.gstin} /> : null}
            {customer?.billing_address ? <Row2 label="Billing" value={customer.billing_address} /> : null}
            {customer?.contact_person ? <Row2 label="Contact" value={`${customer.contact_person} · ${customer.phone || ""}`} /> : null}
            {(customer?.customer_pos || []).length > 0 ? (
              <>
                <View style={{ height: 6 }} />
                <Label>CUSTOMER POs</Label>
                {(customer.customer_pos || []).map((cp: any) => (
                  <View key={cp.cpo_id} style={{ marginTop: 6, paddingVertical: 4, borderBottomWidth: 1, borderBottomColor: theme.colors.surface }}>
                    <Text style={{ fontWeight: "700", color: theme.colors.text }}>{cp.po_number}{cp.po_date ? ` · ${cp.po_date}` : ""}</Text>
                    <Text style={{ fontSize: 12, color: theme.colors.textMuted }}>
                      ₹{new Intl.NumberFormat("en-IN").format(Number(cp.value || 0))}
                      {cp.validity_till ? ` · Valid till ${cp.validity_till}` : ""}
                    </Text>
                    {cp.attachment_name ? <Text style={{ fontSize: 11, color: theme.colors.primary, marginTop: 2 }}>📎 {cp.attachment_name}</Text> : null}
                  </View>
                ))}
              </>
            ) : null}
          </Card>
        ) : null}

        {/* Documents / attachments */}
        {(mrf.attachments && mrf.attachments.length > 0) ? (
          <Card style={{ marginTop: 12 }} testID="mrf-docs-card">
            <H2>Documents</H2>
            {mrf.attachments.map((a: string, i: number) => (
              <View key={i} style={{ flexDirection: "row", alignItems: "center", paddingVertical: 6 }}>
                <Ionicons name="document-attach-outline" size={16} color={theme.colors.primary} />
                <Text style={{ marginLeft: 8, color: theme.colors.text, fontSize: 13 }}>{a}</Text>
              </View>
            ))}
          </Card>
        ) : null}

        <H2 style={{ marginTop: 20, marginBottom: 8 }}>Items ({mrf.items.length})</H2>
        {mrf.items.map((it: any, i: number) => (
          <Card key={it.item_line_id} style={{ marginBottom: 10 }} testID={`item-${i}`}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
              <Text style={styles.itemTitle}>{i + 1}. {it.description}</Text>
              {it.status === "rejected" ? <Pill status="rejected" /> :
               it.status === "approved" ? <Pill status="approved" /> : null}
            </View>
            {it.specification ? <Muted>{it.specification}{it.part_number ? ` · ${it.part_number}` : ""}</Muted> : null}
            <View style={styles.itemGrid}>
              <MiniStat label="Unit" value={it.unit} />
              <MiniStat label="Qty Req" value={it.qty_requested} />
              <MiniStat label="Approved" value={it.qty_approved ?? "—"} />
              <MiniStat label="Ordered" value={it.qty_ordered || 0} />
              <MiniStat label="Received" value={it.qty_received || 0} />
              <MiniStat label="Billed" value={it.qty_billed || 0} />
            </View>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
              <Pill status={it.billing_status || "not_billed"} />
              {it.billable === false ? <Pill status="non_billable" /> : null}
              {it.boq_ref ? <Text style={styles.tag}>BOQ: {it.boq_ref}</Text> : null}
              {it.drawing_ref ? <Text style={styles.tag}>DWG: {it.drawing_ref}</Text> : null}
            </View>
            {it.rejection_reason ? (
              <Text style={styles.rej} testID={`item-rej-${i}`}>Rejected: {it.rejection_reason}</Text>
            ) : null}

            {canReview ? (
              <View style={styles.reviewBox}>
                <Label>PM REVIEW</Label>
                <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
                  <TouchableOpacity
                    testID={`item-approve-${i}`}
                    onPress={() => setItemActions((s) => ({ ...s, [it.item_line_id]: { ...s[it.item_line_id], action: "approve" } }))}
                    style={[styles.reviewBtn, itemActions[it.item_line_id]?.action !== "reject" ? { backgroundColor: theme.colors.success, borderColor: theme.colors.success } : {}]}>
                    <Text style={{ color: itemActions[it.item_line_id]?.action !== "reject" ? "#fff" : theme.colors.text, fontWeight: "600", fontSize: 12 }}>Approve</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    testID={`item-reject-${i}`}
                    onPress={() => setItemActions((s) => ({ ...s, [it.item_line_id]: { ...s[it.item_line_id], action: "reject" } }))}
                    style={[styles.reviewBtn, itemActions[it.item_line_id]?.action === "reject" ? { backgroundColor: theme.colors.danger, borderColor: theme.colors.danger } : {}]}>
                    <Text style={{ color: itemActions[it.item_line_id]?.action === "reject" ? "#fff" : theme.colors.text, fontWeight: "600", fontSize: 12 }}>Reject</Text>
                  </TouchableOpacity>
                </View>
                <TextInput
                  testID={`item-qty-approved-${i}`}
                  placeholder="Modify approved qty"
                  keyboardType="decimal-pad"
                  value={String(itemActions[it.item_line_id]?.qty_approved ?? "")}
                  onChangeText={(v) => setItemActions((s) => ({ ...s, [it.item_line_id]: { ...s[it.item_line_id], qty_approved: Number(v) } }))}
                  style={styles.reviewInput}
                />
                {itemActions[it.item_line_id]?.action === "reject" ? (
                  <TextInput
                    testID={`item-reject-reason-${i}`}
                    placeholder="Rejection reason"
                    value={itemActions[it.item_line_id]?.reason || ""}
                    onChangeText={(v) => setItemActions((s) => ({ ...s, [it.item_line_id]: { ...s[it.item_line_id], reason: v } }))}
                    style={styles.reviewInput}
                  />
                ) : null}
              </View>
            ) : null}
          </Card>
        ))}

        {/* Actions */}
        <View style={{ gap: 8, marginTop: 12 }}>
          {canSubmit ? (
            <>
              <Btn testID="edit-draft-btn" title="Edit MRF" variant="outline" onPress={() => router.push(`/mrf/create?edit=${mrf.mrf_id}` as any)} />
              <Btn testID="submit-btn" title="Submit for PM Review" variant="action" onPress={doSubmit} />
            </>
          ) : null}
          {canReview ? (
            <>
              <Btn testID="approve-mrf-btn" title="Authorise MRF" variant="primary" onPress={() => setAction("approve")} />
              <Btn testID="reject-mrf-btn" title="Reject MRF" variant="danger" onPress={() => setAction("reject")} />
              <Btn testID="return-mrf-btn" title="Return for Correction" variant="outline" onPress={() => setAction("return")} />
            </>
          ) : null}
          {canSendPurchase ? (
            <Btn testID="send-purchase-btn" title="Send to Purchase" variant="action" onPress={doSendPurchase} />
          ) : null}
          <View style={{ flexDirection: "row", gap: 8, marginTop: 4 }}>
            {Platform.OS === "web" ? (
              <View style={{ flex: 1 }}><Btn testID="print-btn" title="🖨 Print" variant="outline" onPress={doPrint} /></View>
            ) : null}
            <View style={{ flex: 1 }}><Btn testID="export-btn" title="⬇ Export (Excel)" variant="outline" onPress={doExport} /></View>
          </View>
        </View>

        {/* Audit */}
        <H2 style={{ marginTop: 24, marginBottom: 8 }}>Audit Trail</H2>
        <Card testID="audit-card">
          {audit.length ? audit.map((a) => (
            <View key={a.audit_id} style={styles.auditRow}>
              <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                <Text style={{ fontWeight: "700", color: theme.colors.text }}>{statusLabel(a.action)}</Text>
                <Text style={styles.auditDate}>{new Date(a.timestamp).toLocaleString()}</Text>
              </View>
              <Text style={{ color: theme.colors.textSecondary, fontSize: 12 }}>{a.user_name} · {statusLabel(a.user_role)}</Text>
              {a.details?.comment ? <Text style={styles.auditDetail}>&ldquo;{a.details.comment}&rdquo;</Text> : null}
            </View>
          )) : <Muted>No history yet.</Muted>}
        </Card>
      </ScrollView>

      {/* Action Modal */}
      <Modal visible={!!action} transparent animationType="fade" onRequestClose={() => setAction(null)}>
        <View style={styles.modalBg}>
          <View style={[styles.modal, { marginBottom: insets.bottom + 16 }]}>
            <Text style={{ fontSize: 18, fontWeight: "800", marginBottom: 8 }}>
              {action === "approve" ? "Approve MRF" : action === "reject" ? "Reject MRF" : "Return MRF"}
            </Text>
            <Muted>Add a comment for the audit trail</Muted>
            <TextInput
              testID="action-comment"
              placeholder="Comments (optional)"
              multiline
              value={comment}
              onChangeText={setComment}
              style={styles.commentBox}
            />
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <View style={{ flex: 1 }}><Btn title="Cancel" variant="outline" onPress={() => setAction(null)} /></View>
              <View style={{ flex: 1 }}>
                <Btn testID="confirm-action-btn"
                  title="Confirm"
                  variant={action === "reject" ? "danger" : "primary"}
                  onPress={doAction} />
              </View>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function Row2({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row2}>
      <Text style={styles.row2Label}>{label}</Text>
      <Text style={styles.row2Value}>{value}</Text>
    </View>
  );
}
function MiniStat({ label, value }: { label: string; value: any }) {
  return (
    <View style={styles.mini}>
      <Text style={styles.miniLabel}>{label}</Text>
      <Text style={styles.miniVal}>{String(value)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 8, paddingVertical: 8, backgroundColor: theme.colors.bg,
    borderBottomWidth: 1, borderBottomColor: theme.colors.border,
  },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  row2: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: theme.colors.surface },
  row2Label: { fontSize: 12, color: theme.colors.textMuted, textTransform: "uppercase", letterSpacing: 1, fontWeight: "700" },
  row2Value: { fontSize: 14, color: theme.colors.text, fontWeight: "500", flex: 1, textAlign: "right", marginLeft: 12 },
  itemTitle: { fontSize: 14, fontWeight: "700", color: theme.colors.text, flex: 1 },
  itemGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 10 },
  mini: { minWidth: 70, flex: 1, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 4, padding: 6 },
  miniLabel: { fontSize: 9, textTransform: "uppercase", color: theme.colors.textMuted, letterSpacing: 1 },
  miniVal: { fontSize: 13, fontWeight: "700", color: theme.colors.text, marginTop: 2 },
  tag: { fontSize: 10, backgroundColor: theme.colors.surface2, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3, color: theme.colors.textSecondary },
  rej: { color: theme.colors.danger, fontSize: 12, marginTop: 6 },
  reviewBox: { marginTop: 10, padding: 10, backgroundColor: theme.colors.surface, borderRadius: 6 },
  reviewBtn: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 4, borderWidth: 1, borderColor: theme.colors.borderStrong, backgroundColor: "#fff" },
  reviewInput: { marginTop: 6, borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 4, padding: 8, minHeight: 40, backgroundColor: "#fff", fontSize: 13 },
  auditRow: { paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  auditDate: { fontSize: 11, color: theme.colors.textMuted },
  auditDetail: { fontSize: 12, fontStyle: "italic", color: theme.colors.textSecondary, marginTop: 2 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modal: { backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 20 },
  commentBox: { borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, padding: 12, minHeight: 80, marginTop: 8, textAlignVertical: "top" },
});
