import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal, TextInput } from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, H1, H2, Muted, Pill, Label, Body, Loader } from "@/src/components/ui";
import { theme, statusLabel } from "@/src/theme";

export default function MRFDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();

  const [mrf, setMrf] = useState<any>(null);
  const [projects, setProjects] = useState<any[]>([]);
  const [audit, setAudit] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState<null | "approve" | "reject" | "return">(null);
  const [comment, setComment] = useState("");
  const [itemActions, setItemActions] = useState<Record<string, { action?: string; qty_approved?: number; reason?: string }>>({});

  const load = useCallback(async () => {
    if (!id) return;
    setBusy(true);
    try {
      const [m, p, a] = await Promise.all([api(`/mrf/${id}`), api("/projects"), api(`/audit?entity_id=${id}`)]);
      setMrf(m); setProjects(p); setAudit(a);
      const map: any = {};
      m.items.forEach((it: any) => { map[it.item_line_id] = { qty_approved: it.qty_approved ?? it.qty_requested }; });
      setItemActions(map);
    } catch (_e) { /* noop */ }
    setBusy(false);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const project = projects.find((p) => p.project_id === mrf?.project_id);
  const isPM = user?.role === "pm" || user?.role === "gm" || user?.role === "director" || user?.role === "admin";
  const canSubmit = mrf && (mrf.status === "draft" || mrf.status === "returned") && (user?.user_id === mrf.created_by || user?.role === "admin");
  const canReview = mrf && mrf.status === "pm_review" && isPM;
  const canSendPurchase = mrf && mrf.status === "approved" && isPM;

  const doSubmit = async () => {
    await api(`/mrf/${id}/submit`, { method: "POST" });
    await load();
  };
  const doSendPurchase = async () => {
    await api(`/mrf/${id}/send-to-purchase`, { method: "POST" });
    await load();
  };
  const doAction = async () => {
    if (!action) return;
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
  };

  if (!mrf) return busy ? <Loader /> : null;

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
          <Row2 label="Site" value={mrf.site} />
          <Row2 label="System" value={mrf.system_category} />
          <Row2 label="Requested by" value={mrf.requesting_person} />
          <Row2 label="Required by" value={mrf.required_by} />
          <Row2 label="Date" value={new Date(mrf.date).toLocaleDateString()} />
          {mrf.remarks ? <Row2 label="Remarks" value={mrf.remarks} /> : null}
          {mrf.pm_comments ? <Row2 label="PM Comments" value={mrf.pm_comments} /> : null}
        </Card>

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
          {canSubmit ? <Btn testID="submit-btn" title="Submit for Approval" variant="action" onPress={doSubmit} /> : null}
          {canReview ? (
            <>
              <Btn testID="approve-mrf-btn" title="Approve MRF" variant="primary" onPress={() => setAction("approve")} />
              <Btn testID="reject-mrf-btn" title="Reject MRF" variant="danger" onPress={() => setAction("reject")} />
              <Btn testID="return-mrf-btn" title="Return for Correction" variant="outline" onPress={() => setAction("return")} />
            </>
          ) : null}
          {canSendPurchase ? (
            <Btn testID="send-purchase-btn" title="Send to Purchase" variant="action" onPress={doSendPurchase} />
          ) : null}
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
