import React, { useMemo, useState, useCallback } from "react";
import {
  View,
  Text,
  StyleSheet,
  Modal,
  Pressable,
  TouchableOpacity,
  Platform,
  ScrollView,
  Linking,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { backendUrl, getToken } from "@/src/api";
import { theme } from "@/src/theme";

export type ExportEntity = "po" | "mrf" | "grn" | "invoice" | "dc" | "comparative_statement" | string;
export type ExportFormat = "pdf" | "excel" | "tally";

export interface ExportMenuProps {
  visible: boolean;
  onClose: () => void;
  entity: ExportEntity;
  id: string;
  recordNumber?: string;
  /** Which formats to show; defaults per entity. */
  formats?: ExportFormat[];
  /** Optional callback fired after a successful download attempt. */
  onExported?: (fmt: ExportFormat) => void;
}

interface ValidationError {
  format: string;
  missing_mandatory: string[];
  warnings: string[];
  hint?: string;
}

/**
 * Common Export/Download menu for record-level downloads (PDF / Excel / Tally).
 * Uses `/api/{entity}/{id}/export?format=...` on the backend.
 * Mobile-friendly: renders as a bottom sheet on both web + native.
 * Handles server-side validation (HTTP 422) by showing missing fields and offering
 * a "Force download anyway" bypass which is audit-logged on the server.
 */
export default function ExportMenu({
  visible,
  onClose,
  entity,
  id,
  recordNumber,
  formats,
  onExported,
}: ExportMenuProps) {
  const insets = useSafeAreaInsets();
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [err, setErr] = useState<string>("");
  const [validation, setValidation] = useState<ValidationError | null>(null);
  const [pendingFmt, setPendingFmt] = useState<ExportFormat | null>(null);

  const defaultFormats = useMemo<ExportFormat[]>(() => {
    if (formats && formats.length) return formats;
    if (entity === "mrf") return ["pdf", "excel"];
    if (entity === "grn" || entity === "invoice") return ["pdf"];
    return ["pdf", "excel", "tally"];
  }, [formats, entity]);

  const reset = useCallback(() => {
    setBusy(null);
    setErr("");
    setValidation(null);
    setPendingFmt(null);
  }, []);

  const closeAll = useCallback(() => {
    reset();
    onClose();
  }, [onClose, reset]);

  const buildUrl = useCallback(
    (fmt: ExportFormat, token: string, force: boolean) => {
      const base = `${backendUrl}/api/${entity}/${id}/export`;
      const q = new URLSearchParams({ format: fmt, token });
      if (force) q.set("force", "1");
      return `${base}?${q.toString()}`;
    },
    [entity, id]
  );

  const openDownload = useCallback((url: string) => {
    if (Platform.OS === "web" && typeof window !== "undefined") {
      window.open(url, "_blank");
    } else {
      Linking.openURL(url).catch(() => {});
    }
  }, []);

  const doDownload = useCallback(
    async (fmt: ExportFormat, force = false) => {
      setBusy(fmt);
      setErr("");
      setValidation(null);
      try {
        const t = (await getToken()) || "";
        // Preflight the request so we can surface 422 validation errors in-UI.
        const preflight = await fetch(buildUrl(fmt, t, force), {
          method: "GET",
        });
        if (preflight.status === 422) {
          const body = await preflight.json().catch(() => ({} as any));
          const det: any = body?.detail || {};
          setValidation({
            format: det.format || fmt,
            missing_mandatory: det.missing_mandatory || [],
            warnings: det.warnings || [],
            hint: det.hint,
          });
          setPendingFmt(fmt);
          setBusy(null);
          return;
        }
        if (!preflight.ok) {
          const j = await preflight.json().catch(() => ({} as any));
          throw new Error(j?.detail || `HTTP ${preflight.status}`);
        }
        // Success — open real URL in a new tab so the browser downloads via
        // native file-save dialog. On native we route via Linking.
        openDownload(buildUrl(fmt, t, force));
        onExported?.(fmt);
        // Close a short moment later so the user sees confirmation flash
        setTimeout(closeAll, 250);
      } catch (e: any) {
        setErr(e?.message || "Download failed");
      }
      setBusy(null);
    },
    [buildUrl, openDownload, onExported, closeAll]
  );

  const formatMeta: Record<ExportFormat, { icon: any; label: string; sub: string; color: string }> = {
    pdf: {
      icon: "document-text-outline",
      label: "PDF",
      sub: "Branded, print-ready",
      color: theme.colors.primary,
    },
    excel: {
      icon: "grid-outline",
      label: "Excel",
      sub: "Per-line, with taxes & UIDs",
      color: theme.colors.action,
    },
    tally: {
      icon: "cash-outline",
      label: "Tally Voucher",
      sub: "Purchase voucher, GST-split",
      color: "#7C3AED",
    },
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={closeAll}
      testID="export-menu-modal"
    >
      <Pressable style={styles.backdrop} onPress={closeAll}>
        <Pressable
          style={[styles.sheet, { paddingBottom: (insets.bottom || 8) + 8 }]}
          onPress={(e) => e.stopPropagation()}
        >
          <View style={styles.handle} />
          <View style={styles.header}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>Export / Download</Text>
              <Text style={styles.subtitle}>
                {recordNumber || entity.toUpperCase()}
              </Text>
            </View>
            <TouchableOpacity onPress={closeAll} style={styles.closeBtn} testID="export-close-btn">
              <Ionicons name="close" size={22} color={theme.colors.text} />
            </TouchableOpacity>
          </View>

          {validation ? (
            <ValidationBanner
              v={validation}
              onCancel={reset}
              onForce={() => pendingFmt && doDownload(pendingFmt, true)}
              busy={busy !== null}
            />
          ) : (
            <ScrollView contentContainerStyle={{ gap: 8, paddingTop: 4 }}>
              {defaultFormats.map((fmt) => {
                const m = formatMeta[fmt];
                const isBusy = busy === fmt;
                return (
                  <TouchableOpacity
                    key={fmt}
                    testID={`export-fmt-${fmt}`}
                    style={[styles.tile, { borderColor: m.color + "55" }]}
                    onPress={() => doDownload(fmt)}
                    disabled={isBusy}
                  >
                    <View style={[styles.iconWrap, { backgroundColor: m.color + "18" }]}>
                      <Ionicons name={m.icon} size={22} color={m.color} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.tileLabel}>{m.label}</Text>
                      <Text style={styles.tileSub}>{m.sub}</Text>
                    </View>
                    {isBusy ? (
                      <Text style={{ color: theme.colors.textMuted, fontSize: 12 }}>…</Text>
                    ) : (
                      <Ionicons name="download-outline" size={20} color={m.color} />
                    )}
                  </TouchableOpacity>
                );
              })}

              {err ? (
                <Text style={styles.err} testID="export-error">
                  {err}
                </Text>
              ) : null}

              <Text style={styles.footNote}>
                Every download is recorded in the audit trail.
              </Text>
            </ScrollView>
          )}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function ValidationBanner({
  v,
  onCancel,
  onForce,
  busy,
}: {
  v: ValidationError;
  onCancel: () => void;
  onForce: () => void;
  busy: boolean;
}) {
  return (
    <View testID="export-validation-banner" style={styles.validBox}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Ionicons name="alert-circle" size={22} color="#B45309" />
        <Text style={styles.validTitle}>
          Cannot export {v.format.toUpperCase()} — missing mandatory fields
        </Text>
      </View>
      <ScrollView style={{ maxHeight: 220, marginTop: 8 }}>
        {v.missing_mandatory.map((m, i) => (
          <View key={`m-${i}`} style={styles.validRow}>
            <Ionicons name="close-circle" size={14} color="#B91C1C" />
            <Text style={styles.validMsg}>{m}</Text>
          </View>
        ))}
        {v.warnings.length ? (
          <>
            <Text style={styles.validSubHeader}>Optional (advisory):</Text>
            {v.warnings.map((w, i) => (
              <View key={`w-${i}`} style={styles.validRow}>
                <Ionicons name="warning-outline" size={14} color="#B45309" />
                <Text style={[styles.validMsg, { color: "#B45309" }]}>{w}</Text>
              </View>
            ))}
          </>
        ) : null}
      </ScrollView>
      <View style={styles.validActions}>
        <TouchableOpacity onPress={onCancel} style={[styles.validBtn, styles.validBtnGhost]} testID="export-validation-cancel">
          <Text style={{ color: theme.colors.text, fontWeight: "700" }}>Cancel</Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={onForce}
          disabled={busy}
          style={[styles.validBtn, styles.validBtnForce, { opacity: busy ? 0.6 : 1 }]}
          testID="export-validation-force"
        >
          <Text style={{ color: "#fff", fontWeight: "700" }}>Force Download (audit-logged)</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: "#fff",
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 16,
    paddingTop: 8,
    maxHeight: "80%",
  },
  handle: {
    alignSelf: "center",
    width: 44,
    height: 4,
    borderRadius: 3,
    backgroundColor: "#D5D8DE",
    marginBottom: 8,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingBottom: 8,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.border,
    marginBottom: 8,
  },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  subtitle: { fontSize: 12, color: theme.colors.textMuted, marginTop: 2 },
  closeBtn: { padding: 6, borderRadius: 6 },
  tile: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 12,
    borderWidth: 1.5,
    borderRadius: 10,
    backgroundColor: "#FCFDFF",
    minHeight: 60,
  },
  iconWrap: {
    width: 40,
    height: 40,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
  },
  tileLabel: { fontSize: 15, fontWeight: "700", color: theme.colors.text },
  tileSub: { fontSize: 12, color: theme.colors.textMuted, marginTop: 2 },
  err: {
    marginTop: 8,
    padding: 10,
    borderRadius: 6,
    backgroundColor: "#FEF2F2",
    color: theme.colors.danger,
    fontSize: 12,
    fontWeight: "600",
  },
  footNote: {
    marginTop: 6,
    fontSize: 11,
    color: theme.colors.textMuted,
    textAlign: "center",
  },
  validBox: {
    backgroundColor: "#FFFBEB",
    borderWidth: 1,
    borderColor: "#FBBF24",
    borderRadius: 10,
    padding: 12,
    marginTop: 4,
  },
  validTitle: { fontSize: 14, fontWeight: "800", color: "#92400E", flex: 1 },
  validSubHeader: {
    fontSize: 12,
    fontWeight: "700",
    color: theme.colors.textMuted,
    marginTop: 8,
    marginBottom: 4,
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },
  validRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 3 },
  validMsg: { fontSize: 13, color: "#7C2D12", flex: 1 },
  validActions: { flexDirection: "row", gap: 8, marginTop: 10 },
  validBtn: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
  },
  validBtnGhost: { borderWidth: 1, borderColor: theme.colors.borderStrong, backgroundColor: "#fff" },
  validBtnForce: { backgroundColor: "#B45309" },
});
