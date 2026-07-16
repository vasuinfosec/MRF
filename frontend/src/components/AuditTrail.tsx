import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ActivityIndicator,
  TouchableOpacity,
  FlatList,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { theme, statusLabel } from "@/src/theme";

export type AuditEntity = "mrf" | "po" | "customer" | "material" | "vendor" | "project" | string;

export interface AuditTrailProps {
  /** Entity ID to fetch audit for (e.g. mrf_xxx, po_xxx, CUS-0001, MAT-0001). */
  entityId?: string;
  /** Optional entity type filter (server accepts entity= param). */
  entity?: AuditEntity;
  /** Maximum entries; server hard cap = 500. */
  limit?: number;
  /** Compact list style — omits sub-details, useful inside cards. */
  compact?: boolean;
  /** Auto-refresh interval (ms). Omit for one-shot. */
  refreshMs?: number;
  /** Header slot — pass empty node to hide. */
  title?: string;
}

interface AuditEntry {
  audit_id: string;
  timestamp: string;
  user_id: string;
  user_name?: string;
  user_role?: string;
  entity: string;
  entity_id: string;
  action: string;
  details?: any;
}

const ROLE_STYLE: Record<string, { bg: string; fg: string }> = {
  director: { bg: "#DC2626", fg: "#fff" },
  gm: { bg: "#7C3AED", fg: "#fff" },
  pm: { bg: "#2563EB", fg: "#fff" },
  purchase: { bg: "#059669", fg: "#fff" },
  site_engineer: { bg: "#F59E0B", fg: "#fff" },
  store: { bg: "#0891B2", fg: "#fff" },
  admin: { bg: "#111827", fg: "#fff" },
};

const ACTION_ICON: Record<string, keyof typeof Ionicons.glyphMap> = {
  login: "log-in-outline",
  logout: "log-out-outline",
  create: "add-circle-outline",
  submit: "paper-plane-outline",
  approve: "checkmark-circle-outline",
  reject: "close-circle-outline",
  return: "return-up-back-outline",
  send_to_purchase: "cart-outline",
  edit_draft: "pencil-outline",
  soft_delete: "trash-outline",
  update: "create-outline",
  received: "checkmark-done-outline",
  po_approve: "checkmark-circle-outline",
  po_reject: "close-circle-outline",
  po_return: "return-up-back-outline",
  export_pdf: "document-text-outline",
  export_excel: "grid-outline",
  export_tally: "cash-outline",
  pm_approve: "checkmark-circle-outline",
  pm_reject: "close-circle-outline",
  gm_approve: "checkmark-circle-outline",
  gm_reject: "close-circle-outline",
  bulk_import: "cloud-upload-outline",
  import: "cloud-upload-outline",
  rename_id: "swap-horizontal-outline",
  deactivate: "power-outline",
};

function iconFor(action: string): keyof typeof Ionicons.glyphMap {
  if (ACTION_ICON[action]) return ACTION_ICON[action];
  if (action.startsWith("export_")) return "download-outline";
  if (action.startsWith("po_")) return "cube-outline";
  if (action.startsWith("pm_") || action.startsWith("gm_")) return "shield-checkmark-outline";
  return "time-outline";
}

function extractOldNew(details: any): { old?: any; nw?: any; reason?: string } {
  if (!details || typeof details !== "object") return {};
  const nw = details.new_value ?? details.new ?? undefined;
  const old = details.old_value ?? details.old ?? undefined;
  const reason = details.reason || details.comment || undefined;
  return { old, nw, reason };
}

function formatValue(v: any): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    const s = JSON.stringify(v);
    return s.length > 160 ? s.slice(0, 157) + "…" : s;
  } catch {
    return String(v);
  }
}

function diffPairs(oldV: any, newV: any): Array<{ k: string; o: any; n: any }> {
  if (!oldV && !newV) return [];
  if (typeof oldV !== "object" || typeof newV !== "object" || Array.isArray(oldV) || Array.isArray(newV)) {
    return [{ k: "value", o: oldV, n: newV }];
  }
  const keys = new Set<string>([...Object.keys(oldV || {}), ...Object.keys(newV || {})]);
  const out: Array<{ k: string; o: any; n: any }> = [];
  keys.forEach((k) => {
    const o = oldV?.[k];
    const n = newV?.[k];
    if (JSON.stringify(o) === JSON.stringify(n)) return;
    out.push({ k, o, n });
  });
  return out;
}

function fmtRelTime(iso: string): string {
  try {
    const t = new Date(iso).getTime();
    const secs = Math.floor((Date.now() - t) / 1000);
    if (secs < 60) return `${secs}s ago`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
    if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/**
 * Renders the audit trail for a record (or the global feed when neither entityId
 * nor entity is provided). Every row shows: user + role chip, action, old→new
 * diff, reason, and time.
 */
export default function AuditTrail({
  entityId,
  entity,
  limit = 100,
  compact = false,
  refreshMs,
  title = "Audit Trail",
}: AuditTrailProps) {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string>("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const url = useMemo(() => {
    const p = new URLSearchParams({ limit: String(limit) });
    if (entityId) p.set("entity_id", entityId);
    if (entity) p.set("entity", entity);
    return `/audit?${p.toString()}`;
  }, [entityId, entity, limit]);

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const rows = await api(url);
      setEntries(Array.isArray(rows) ? rows : []);
    } catch (e: any) {
      setErr(e?.message || "Failed to load audit trail");
    }
    setLoading(false);
  }, [url]);

  useEffect(() => {
    load();
    if (!refreshMs) return;
    const t = setInterval(load, refreshMs);
    return () => clearInterval(t);
  }, [load, refreshMs]);

  const renderItem = ({ item }: { item: AuditEntry }) => {
    const rs = ROLE_STYLE[item.user_role || ""] || { bg: theme.colors.borderStrong, fg: "#fff" };
    const { old, nw, reason } = extractOldNew(item.details);
    const diff = diffPairs(old, nw);
    const isOpen = !!expanded[item.audit_id];
    const showToggle = diff.length > 1 || (reason && reason.length > 60);
    const rec = item.details?.record_number || item.details?.mrf_number || item.details?.po_number;
    return (
      <View style={styles.row} testID={`audit-row-${item.audit_id}`}>
        <View style={styles.timeline}>
          <View style={[styles.iconWrap, { backgroundColor: rs.bg }]}>
            <Ionicons name={iconFor(item.action)} size={14} color="#fff" />
          </View>
          <View style={styles.timelineBar} />
        </View>
        <View style={{ flex: 1 }}>
          <View style={styles.headRow}>
            <Text style={styles.actionText}>{statusLabel(item.action)}</Text>
            <Text style={styles.time}>{fmtRelTime(item.timestamp)}</Text>
          </View>
          <View style={styles.metaRow}>
            <Text style={styles.userName} numberOfLines={1}>
              {item.user_name || "—"}
            </Text>
            <View style={[styles.roleChip, { backgroundColor: rs.bg }]}>
              <Text style={[styles.roleTxt, { color: rs.fg }]}>
                {(item.user_role || "?").toUpperCase()}
              </Text>
            </View>
            {rec ? (
              <View style={styles.recChip}>
                <Text style={styles.recTxt} numberOfLines={1}>
                  {String(rec)}
                </Text>
              </View>
            ) : null}
          </View>
          {!compact ? (
            <View style={{ marginTop: 4 }}>
              {reason ? (
                <Text style={styles.reason} numberOfLines={isOpen ? undefined : 2}>
                  <Text style={styles.reasonLabel}>Reason: </Text>
                  {reason}
                </Text>
              ) : null}
              {(isOpen ? diff : diff.slice(0, 2)).map((d, i) => (
                <View key={`${item.audit_id}-d-${i}`} style={styles.diffRow}>
                  <Text style={styles.diffKey}>{d.k}</Text>
                  <View style={styles.diffChip}>
                    <Text style={styles.diffOld} numberOfLines={1}>
                      {formatValue(d.o)}
                    </Text>
                    <Ionicons name="arrow-forward" size={11} color={theme.colors.textMuted} />
                    <Text style={styles.diffNew} numberOfLines={1}>
                      {formatValue(d.n)}
                    </Text>
                  </View>
                </View>
              ))}
              {showToggle ? (
                <TouchableOpacity
                  onPress={() => setExpanded((s) => ({ ...s, [item.audit_id]: !isOpen }))}
                  testID={`audit-toggle-${item.audit_id}`}
                  style={{ marginTop: 4 }}
                >
                  <Text style={styles.toggleTxt}>
                    {isOpen ? "Show less" : `Show ${diff.length - 2 > 0 ? diff.length - 2 + " more" : "more"}`}
                  </Text>
                </TouchableOpacity>
              ) : null}
              {item.details && !diff.length && !reason ? (
                <Text style={styles.reason} numberOfLines={isOpen ? undefined : 2}>
                  {formatValue(item.details)}
                </Text>
              ) : null}
            </View>
          ) : null}
        </View>
      </View>
    );
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Ionicons name="time-outline" size={16} color={theme.colors.text} />
        <Text style={styles.title}>{title}</Text>
        {loading ? <ActivityIndicator size="small" color={theme.colors.primary} /> : null}
        <TouchableOpacity onPress={load} testID="audit-refresh" style={{ marginLeft: "auto", padding: 4 }}>
          <Ionicons name="refresh" size={16} color={theme.colors.textMuted} />
        </TouchableOpacity>
      </View>
      {err ? (
        <Text style={styles.err} testID="audit-err">
          {err}
        </Text>
      ) : null}
      {!loading && !entries.length && !err ? (
        <Text style={styles.emptyTxt} testID="audit-empty">
          No audit entries yet.
        </Text>
      ) : null}
      <FlatList
        data={entries}
        keyExtractor={(x) => x.audit_id}
        renderItem={renderItem}
        scrollEnabled={false}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginTop: 6,
    padding: 10,
    backgroundColor: "#F9FAFB",
    borderRadius: 10,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 8,
  },
  title: { fontSize: 14, fontWeight: "800", color: theme.colors.text },
  row: {
    flexDirection: "row",
    gap: 8,
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: "#EEF0F3",
  },
  timeline: { alignItems: "center", width: 24 },
  iconWrap: {
    width: 22,
    height: 22,
    borderRadius: 11,
    alignItems: "center",
    justifyContent: "center",
  },
  timelineBar: {
    flex: 1,
    width: 2,
    backgroundColor: "#E5E7EB",
    marginTop: 2,
  },
  headRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  actionText: { fontSize: 13, fontWeight: "700", color: theme.colors.text, flexShrink: 1 },
  time: { fontSize: 10, color: theme.colors.textMuted, marginLeft: 8 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2, flexWrap: "wrap" },
  userName: { fontSize: 12, color: theme.colors.textSecondary, maxWidth: 120 },
  roleChip: { paddingHorizontal: 6, paddingVertical: 1, borderRadius: 4 },
  roleTxt: { fontSize: 9, fontWeight: "800", letterSpacing: 0.4 },
  recChip: {
    paddingHorizontal: 6,
    paddingVertical: 1,
    backgroundColor: "#EEF2FF",
    borderRadius: 4,
    maxWidth: 160,
  },
  recTxt: { fontSize: 10, color: "#3730A3", fontWeight: "700" },
  reason: { fontSize: 12, color: theme.colors.textSecondary, marginTop: 2 },
  reasonLabel: { fontWeight: "700", color: theme.colors.text },
  diffRow: { marginTop: 4 },
  diffKey: { fontSize: 10, fontWeight: "700", color: theme.colors.textMuted, textTransform: "uppercase" },
  diffChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 1,
    padding: 4,
    backgroundColor: "#fff",
    borderRadius: 4,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  diffOld: { flex: 1, fontSize: 11, color: "#B91C1C", fontWeight: "600" },
  diffNew: { flex: 1, fontSize: 11, color: "#065F46", fontWeight: "700" },
  toggleTxt: { fontSize: 11, color: theme.colors.primary, fontWeight: "700" },
  err: {
    color: theme.colors.danger,
    fontSize: 12,
    padding: 6,
    marginBottom: 4,
    backgroundColor: "#FEF2F2",
    borderRadius: 4,
  },
  emptyTxt: {
    fontSize: 12,
    color: theme.colors.textMuted,
    textAlign: "center",
    padding: 12,
    fontStyle: "italic",
  },
});
