import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Modal,
  TextInput,
  ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { theme, statusLabel } from "@/src/theme";
import { Btn } from "@/src/components/ui";

export type ApprovableEntity = "grn" | "dc" | "comparative-statement" | "comparative_statement";

interface ApprovalPanelProps {
  entity: ApprovableEntity;
  id: string;
  currentStatus: string;
  /** Roles that can act on this record. Passed by the calling screen based on entity + user role. */
  canAct: boolean;
  /** Called after successful approve/reject so caller can reload the record. */
  onDone: () => void;
  /** Approval history rows to display: [{user_name, user_role, action, comment, timestamp}] */
  history?: any[];
  /** Optional label — defaults to entity-appropriate wording. */
  approverLabel?: string;
}

/**
 * Reusable approve/reject panel for GRN, DC and Comparative Statement records.
 * Shows the current status pill, the last N history entries, and — for eligible
 * roles — Approve/Reject buttons that open a modal requiring a comment.
 *
 * DESIGN NOTE: This is a *rule-based* human-authorised action. The LLM co-pilot
 * (Phase 8, next commit) may suggest which record to approve/reject but must
 * never call this panel directly.
 */
export default function ApprovalPanel({
  entity,
  id,
  currentStatus,
  canAct,
  onDone,
  history = [],
  approverLabel,
}: ApprovalPanelProps) {
  const [modalAction, setModalAction] = useState<null | "approve" | "reject">(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const isPending = ["pending_approval", "issued", "active", "rejected"].includes(currentStatus || "");
  const isApproved = currentStatus === "approved";
  const isRejected = currentStatus === "rejected";

  const submit = async () => {
    if (!modalAction) return;
    if (modalAction === "reject" && !comment.trim()) {
      setErr("Please provide a rejection reason.");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const entityPath = entity === "comparative_statement" ? "comparative-statement" : entity;
      await api(`/${entityPath}/${id}/approve`, {
        method: "POST",
        body: { action: modalAction, comment: comment.trim() },
      });
      setModalAction(null);
      setComment("");
      onDone();
    } catch (e: any) {
      setErr(e?.message || "Action failed.");
    }
    setBusy(false);
  };

  const label = approverLabel ||
    (entity.startsWith("comparative") ? "PM / GM / Director" : "Accounts / Director");

  const statusStyle = statusStyleFor(currentStatus);

  return (
    <View style={styles.container} testID={`approval-panel-${entity}`}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>Approval</Text>
        <View style={[styles.pill, { backgroundColor: statusStyle.bg, borderColor: statusStyle.border }]}>
          <Text style={[styles.pillText, { color: statusStyle.text }]}>
            {statusLabel(currentStatus || "pending_approval")}
          </Text>
        </View>
      </View>

      <Text style={styles.info}>
        Approver: <Text style={styles.infoStrong}>{label}</Text>
      </Text>

      {history.length ? (
        <View style={{ marginTop: 8 }}>
          {history.slice(-5).map((h: any, i: number) => (
            <View key={i} style={styles.historyRow}>
              <Ionicons
                name={h.action === "approve" ? "checkmark-circle" : "close-circle"}
                size={14}
                color={h.action === "approve" ? theme.colors.success : theme.colors.danger}
              />
              <Text style={styles.historyText} numberOfLines={2}>
                <Text style={{ fontWeight: "700" }}>{h.user_name}</Text>{" "}
                <Text style={styles.historyRole}>({(h.user_role || "").toUpperCase()})</Text>
                {" · "}
                {h.action === "approve" ? "approved" : "rejected"}
                {h.comment ? " — " + h.comment : ""}
                {"  "}
                <Text style={styles.historyTime}>
                  {new Date(h.timestamp).toLocaleString()}
                </Text>
              </Text>
            </View>
          ))}
        </View>
      ) : null}

      {canAct && (isPending || isRejected) ? (
        <View style={styles.actionRow}>
          <View style={{ flex: 1 }}>
            <Btn
              testID={`approve-btn-${entity}`}
              title="✓ Approve"
              variant="primary"
              onPress={() => { setComment(""); setErr(""); setModalAction("approve"); }}
            />
          </View>
          <View style={{ flex: 1 }}>
            <Btn
              testID={`reject-btn-${entity}`}
              title="✕ Reject"
              variant="outline"
              onPress={() => { setComment(""); setErr(""); setModalAction("reject"); }}
            />
          </View>
        </View>
      ) : null}

      {!canAct && isPending ? (
        <Text style={styles.awaiting}>Awaiting {label} approval.</Text>
      ) : null}
      {isApproved ? (
        <Text style={styles.approved}>✓ Approved — record is locked to further edits.</Text>
      ) : null}

      <Modal
        visible={modalAction !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setModalAction(null)}
      >
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>
              {modalAction === "approve" ? "Approve" : "Reject"} — confirm
            </Text>
            <Text style={styles.modalSub}>
              This action is audit-logged. You are signing off as{" "}
              <Text style={{ fontWeight: "700" }}>{label}</Text>.
            </Text>

            <Text style={styles.modalLbl}>
              {modalAction === "reject" ? "Reason (required)" : "Comment (optional)"}
            </Text>
            <TextInput
              value={comment}
              onChangeText={setComment}
              multiline
              placeholder={modalAction === "reject" ? "e.g. Amount mismatch on Line 3." : "Optional remark…"}
              style={styles.input}
              testID={`approval-comment-${entity}`}
            />

            {err ? <Text style={styles.err}>{err}</Text> : null}

            <View style={styles.modalActions}>
              <View style={{ flex: 1 }}>
                <Btn
                  title="Cancel"
                  variant="outline"
                  onPress={() => setModalAction(null)}
                  disabled={busy}
                />
              </View>
              <View style={{ flex: 1 }}>
                <Btn
                  testID={`approval-submit-${entity}`}
                  title={busy ? "Submitting…" : modalAction === "approve" ? "Confirm Approve" : "Confirm Reject"}
                  variant={modalAction === "approve" ? "primary" : "outline"}
                  onPress={submit}
                  disabled={busy}
                />
              </View>
            </View>

            {busy ? (
              <View style={{ marginTop: 8, alignItems: "center" }}>
                <ActivityIndicator size="small" />
              </View>
            ) : null}
          </View>
        </View>
      </Modal>
    </View>
  );
}

function statusStyleFor(status: string) {
  const s = (status || "").toLowerCase();
  if (s === "approved" || s === "delivered" || s === "active") {
    return { bg: "#D1FAE5", text: "#065F46", border: "#34D399" };
  }
  if (s === "rejected" || s === "cancelled") {
    return { bg: "#FEE2E2", text: "#991B1B", border: "#F87171" };
  }
  if (s === "pending_approval" || s === "issued") {
    return { bg: "#FEF3C7", text: "#92400E", border: "#FBBF24" };
  }
  return { bg: "#F3F4F6", text: "#374151", border: "#9CA3AF" };
}

const styles = StyleSheet.create({
  container: {
    marginTop: 8,
    padding: 12,
    backgroundColor: "#F9FAFB",
    borderRadius: 10,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  title: { fontSize: 14, fontWeight: "800", color: theme.colors.text },
  pill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
    borderWidth: 1,
  },
  pillText: { fontSize: 11, fontWeight: "800", letterSpacing: 0.4 },
  info: { marginTop: 6, fontSize: 12, color: theme.colors.textSecondary },
  infoStrong: { fontWeight: "700", color: theme.colors.text },
  historyRow: { flexDirection: "row", alignItems: "flex-start", gap: 6, paddingVertical: 3 },
  historyText: { flex: 1, fontSize: 12, color: theme.colors.text },
  historyRole: { fontSize: 10, color: theme.colors.textMuted, fontWeight: "700" },
  historyTime: { fontSize: 10, color: theme.colors.textMuted },
  actionRow: { flexDirection: "row", gap: 8, marginTop: 10 },
  awaiting: {
    marginTop: 8,
    fontSize: 12,
    color: theme.colors.warning || "#B45309",
    fontStyle: "italic",
  },
  approved: {
    marginTop: 8,
    fontSize: 12,
    color: theme.colors.success,
    fontWeight: "700",
  },
  modalBg: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "center",
    padding: 16,
  },
  modalCard: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 16,
  },
  modalTitle: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  modalSub: { fontSize: 12, color: theme.colors.textSecondary, marginTop: 4 },
  modalLbl: { fontSize: 11, fontWeight: "700", color: theme.colors.textMuted, marginTop: 12, textTransform: "uppercase", letterSpacing: 0.6 },
  input: {
    marginTop: 4,
    padding: 10,
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: 8,
    minHeight: 70,
    textAlignVertical: "top",
    fontSize: 13,
  },
  err: {
    marginTop: 8,
    fontSize: 12,
    color: theme.colors.danger,
    backgroundColor: "#FEF2F2",
    borderRadius: 6,
    padding: 8,
  },
  modalActions: { flexDirection: "row", gap: 8, marginTop: 14 },
});
