import React, { useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";
import { theme } from "@/src/theme";

export interface LlmAttachment {
  file_name: string;
  mime_type: string;
  file_base64: string;
  size?: number;
}

interface Props {
  attachments: LlmAttachment[];
  onChange: (next: LlmAttachment[]) => void;
  max?: number;
  label?: string;
  helperText?: string;
}

const SUPPORTED_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.ms-excel",
  "text/csv",
  "text/plain",
];

/**
 * Reusable multi-file attach control for the AI Co-pilot.
 * Server-side extraction supports PDF, Excel (xlsx/xls), CSV, and plain text.
 * Images and other formats are rejected. Max 10 MB each.
 */
export default function LlmFilePicker({
  attachments,
  onChange,
  max = 5,
  label = "Attach documents (optional)",
  helperText = "PDF, Excel or CSV. Max 10 MB each. Server extracts text and feeds it to the LLM.",
}: Props) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const pick = async () => {
    setErr("");
    if (attachments.length >= max) {
      setErr(`Max ${max} files reached — remove one to add more.`);
      return;
    }
    setBusy(true);
    try {
      const res = await DocumentPicker.getDocumentAsync({
        multiple: true,
        copyToCacheDirectory: true,
        type: SUPPORTED_TYPES,
      });
      if (res.canceled || !res.assets?.length) {
        setBusy(false);
        return;
      }
      const remainingSlots = Math.max(0, max - attachments.length);
      const picked = res.assets.slice(0, remainingSlots);
      const next: LlmAttachment[] = [...attachments];
      for (const f of picked) {
        try {
          const blob = await (await fetch(f.uri)).blob();
          if (blob.size > 10 * 1024 * 1024) {
            setErr(`${f.name} exceeds 10 MB and was skipped.`);
            continue;
          }
          const b64 = await new Promise<string>((resolve, reject) => {
            const rd = new FileReader();
            rd.onerror = () => reject(new Error("read fail"));
            rd.onloadend = () => {
              const s = String(rd.result || "");
              resolve(s.includes(",") ? s.split(",")[1] : s);
            };
            rd.readAsDataURL(blob);
          });
          next.push({
            file_name: f.name,
            mime_type: f.mimeType || "application/octet-stream",
            file_base64: b64,
            size: blob.size,
          });
        } catch {
          setErr(`Could not read ${f.name}.`);
        }
      }
      onChange(next);
    } catch (e: any) {
      setErr(e?.message || "File pick failed");
    }
    setBusy(false);
  };

  const remove = (i: number) => onChange(attachments.filter((_, idx) => idx !== i));

  return (
    <View style={styles.container} testID="llm-file-picker">
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.count}>{attachments.length}/{max}</Text>
      </View>
      <Text style={styles.helper}>{helperText}</Text>
      <TouchableOpacity
        onPress={pick}
        disabled={busy || attachments.length >= max}
        style={[styles.dropZone, attachments.length >= max ? styles.dropZoneDisabled : null]}
        testID="llm-file-pick-btn"
      >
        <Ionicons name="cloud-upload-outline" size={20} color={theme.colors.primary} />
        <Text style={styles.dropText}>
          {busy ? "Loading…" : attachments.length ? "Add more" : "Tap to attach PDF / Excel / CSV"}
        </Text>
      </TouchableOpacity>
      {attachments.map((a, i) => (
        <View key={`${a.file_name}-${i}`} style={styles.chip} testID={`llm-attach-chip-${i}`}>
          <Ionicons name="document-attach-outline" size={14} color={theme.colors.primary} />
          <Text style={styles.chipName} numberOfLines={1}>{a.file_name}</Text>
          {a.size ? <Text style={styles.chipSize}>{(a.size / 1024).toFixed(0)} KB</Text> : null}
          <TouchableOpacity onPress={() => remove(i)} testID={`llm-attach-rm-${i}`} style={{ padding: 4 }}>
            <Ionicons name="close" size={14} color={theme.colors.danger} />
          </TouchableOpacity>
        </View>
      ))}
      {err ? <Text style={styles.err}>{err}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { marginTop: 12 },
  label: { fontSize: 12, fontWeight: "800", color: theme.colors.textMuted, textTransform: "uppercase", letterSpacing: 0.6 },
  count: { fontSize: 11, color: theme.colors.textMuted, fontWeight: "700" },
  helper: { fontSize: 11, color: theme.colors.textMuted, marginTop: 2 },
  dropZone: {
    marginTop: 8,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    padding: 12,
    borderWidth: 1.5,
    borderStyle: "dashed",
    borderColor: theme.colors.primary,
    borderRadius: 8,
    backgroundColor: "#F5F8FF",
  },
  dropZoneDisabled: { opacity: 0.5, borderStyle: "solid" },
  dropText: { color: theme.colors.primary, fontWeight: "700", fontSize: 13 },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    padding: 6,
    marginTop: 6,
    backgroundColor: "#EEF2FF",
    borderRadius: 6,
    borderWidth: 1,
    borderColor: "#C7D2FE",
  },
  chipName: { flex: 1, fontSize: 12, color: theme.colors.text, fontWeight: "600" },
  chipSize: { fontSize: 10, color: theme.colors.textMuted },
  err: {
    marginTop: 6,
    padding: 6,
    color: theme.colors.danger,
    backgroundColor: "#FEF2F2",
    borderRadius: 4,
    fontSize: 11,
  },
});
