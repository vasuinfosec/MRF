import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl, TextInput, Alert, Modal, Platform } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";
import * as DocumentPicker from "expo-document-picker";

import { api, backendUrl, getDownloadToken } from "@/src/api";
import { Btn, Card, H2, Label, Muted, Loader, Pill } from "@/src/components/ui";
import AuditTrail from "@/src/components/AuditTrail";
import ApprovalPanel from "@/src/components/ApprovalPanel";
import { theme } from "@/src/theme";
import { useAuth } from "@/src/auth";

interface CS {
  cs_id: string; cs_number: string;
  mrf_id?: string; po_id?: string; project_id?: string; customer_id?: string;
  title: string; remarks?: string;
  file_name: string; mime_type: string; file_size: number;
  l1_vendor?: string; l1_amount?: number;
  vendors?: { vendor_name: string; amount: number }[];
  selected_vendor?: string; selection_reason?: string;
  uploaded_by: string; uploaded_by_name?: string; uploaded_at: string;
  status: string;
  approval_history?: any[];
}

export default function ComparativeStatement() {
  const router = useRouter();
  const params = useLocalSearchParams<{ mrf_id?: string; po_id?: string }>();
  const { user } = useAuth();
  const canWrite = ["purchase", "admin"].includes(user?.role || "");
  const canApprove = ["pm", "gm", "director"].includes(user?.role || "");
  const [rows, setRows] = useState<CS[]>([]);
  const [loading, setLoading] = useState(true);
  const [showUpload, setShowUpload] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (params.mrf_id) p.set("mrf_id", String(params.mrf_id));
      if (params.po_id) p.set("po_id", String(params.po_id));
      const data = await api<CS[]>(`/comparative-statement${p.toString() ? "?" + p.toString() : ""}`);
      setRows(data || []);
    } catch { setRows([]); }
    setLoading(false);
  }, [params.mrf_id, params.po_id]);

  useEffect(() => { load(); }, [load]);

  const download = async (cs: CS) => {
    const t = await getDownloadToken();
    if (!t) return;
    const url = `${backendUrl}/api/comparative-statement/${cs.cs_id}/download?token=${t}`;
    if (Platform.OS === "web" && typeof window !== "undefined") window.open(url, "_blank");
  };

  const del = (cs: CS) => {
    Alert.alert("Delete Comparative Statement?", cs.cs_number, [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: async () => {
        try {
          await api(`/comparative-statement/${cs.cs_id}?reason=User%20deleted`, { method: "DELETE" });
          load();
        } catch (e: any) {
          Alert.alert("Error", e?.message || "Failed");
        }
      }},
    ]);
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }} testID="back-btn">
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Comparative Statements</Text>
        {canWrite ? (
          <TouchableOpacity onPress={() => setShowUpload(true)} style={{ padding: 8 }} testID="cs-upload-btn">
            <Ionicons name="cloud-upload-outline" size={22} color={theme.colors.primary} />
          </TouchableOpacity>
        ) : <View style={{ width: 38 }} />}
      </View>

      <ScrollView
        contentContainerStyle={{ padding: 12, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
      >
        <Muted>
          Comparative Statements are prepared outside the app and imported here. Attach each
          to an MRF or PO. L1/L2/L3 vendor snapshot and selection reason are captured for audit.
        </Muted>
        {loading ? <Loader /> : null}
        {!loading && !rows.length ? (
          <View style={{ padding: 24 }}>
            <Muted>No comparative statements uploaded yet.</Muted>
          </View>
        ) : null}
        {rows.map((cs) => (
          <Card key={cs.cs_id} style={{ marginTop: 8 }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <Text style={styles.csNo}>{cs.cs_number}</Text>
                  <Pill status={cs.status || "active"} />
                </View>
                <Text style={{ fontWeight: "700", marginTop: 4 }}>{cs.title}</Text>
                <Muted>File: {cs.file_name}  ·  {(cs.file_size / 1024).toFixed(1)} KB</Muted>
                <Muted>Uploaded by {cs.uploaded_by_name || cs.uploaded_by}  ·  {new Date(cs.uploaded_at).toLocaleString()}</Muted>
                {cs.mrf_id ? <Muted>Attached to MRF: {cs.mrf_id}</Muted> : null}
                {cs.po_id ? <Muted>Attached to PO: {cs.po_id}</Muted> : null}
                {cs.vendors && cs.vendors.length ? (
                  <View style={styles.vendorGrid}>
                    {cs.vendors.slice(0, 3).map((v, i) => {
                      const rank = ["L1", "L2", "L3"][i];
                      const bg = ["#10B981", "#F59E0B", "#94A3B8"][i];
                      return (
                        <View key={i} style={[styles.vendorPill, { backgroundColor: bg }]}>
                          <Text style={styles.vendorRank}>{rank}</Text>
                          <Text style={styles.vendorName} numberOfLines={1}>{v.vendor_name}</Text>
                          <Text style={styles.vendorAmt}>₹ {Number(v.amount || 0).toLocaleString("en-IN")}</Text>
                        </View>
                      );
                    })}
                  </View>
                ) : null}
                {cs.selected_vendor ? (
                  <View style={{ marginTop: 6 }}>
                    <Text style={{ fontWeight: "700", color: theme.colors.success }}>
                      ✓ Selected: {cs.selected_vendor}
                    </Text>
                    {cs.selection_reason ? <Muted>{cs.selection_reason}</Muted> : null}
                  </View>
                ) : null}

                <ApprovalPanel
                  entity="comparative_statement"
                  id={cs.cs_id}
                  currentStatus={cs.status || "pending_approval"}
                  canAct={canApprove}
                  onDone={load}
                  history={(cs as any).approval_history || []}
                  approverLabel="PM / GM / Director"
                />
              </View>
              <View style={{ gap: 6 }}>
                <TouchableOpacity onPress={() => download(cs)} style={styles.iconBtn} testID={`cs-dl-${cs.cs_id}`}>
                  <Ionicons name="download-outline" size={18} color={theme.colors.primary} />
                </TouchableOpacity>
                {["admin", "director"].includes(user?.role || "") ? (
                  <TouchableOpacity onPress={() => del(cs)} style={styles.iconBtn}>
                    <Ionicons name="trash-outline" size={18} color={theme.colors.danger} />
                  </TouchableOpacity>
                ) : null}
              </View>
            </View>
          </Card>
        ))}

        {rows.length > 0 && !params.mrf_id && !params.po_id ? (
          <View style={{ marginTop: 16 }}>
            <H2>Audit Trail</H2>
            <AuditTrail entity="comparative_statement" limit={50} title="" />
          </View>
        ) : null}
      </ScrollView>

      <UploadModal
        visible={showUpload}
        onClose={() => setShowUpload(false)}
        onDone={() => { setShowUpload(false); load(); }}
        defaultMRFId={String(params.mrf_id || "")}
        defaultPOId={String(params.po_id || "")}
      />
    </SafeAreaView>
  );
}

interface UploadModalProps {
  visible: boolean;
  onClose: () => void;
  onDone: () => void;
  defaultMRFId?: string;
  defaultPOId?: string;
}

function UploadModal({ visible, onClose, onDone, defaultMRFId, defaultPOId }: UploadModalProps) {
  const [title, setTitle] = useState("");
  const [mrfId, setMRFId] = useState(defaultMRFId || "");
  const [poId, setPOId] = useState(defaultPOId || "");
  const [l1Vendor, setL1Vendor] = useState("");
  const [l1Amt, setL1Amt] = useState("");
  const [l2Vendor, setL2Vendor] = useState("");
  const [l2Amt, setL2Amt] = useState("");
  const [l3Vendor, setL3Vendor] = useState("");
  const [l3Amt, setL3Amt] = useState("");
  const [selectedVendor, setSelectedVendor] = useState("");
  const [selectionReason, setSelectionReason] = useState("");
  const [remarks, setRemarks] = useState("");
  const [fileName, setFileName] = useState("");
  const [fileB64, setFileB64] = useState("");
  const [mime, setMime] = useState("");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (visible) {
      setMRFId(defaultMRFId || "");
      setPOId(defaultPOId || "");
    }
  }, [visible, defaultMRFId, defaultPOId]);

  const pickFile = async () => {
    setErr("");
    const res = await DocumentPicker.getDocumentAsync({
      copyToCacheDirectory: true,
      multiple: false,
      type: ["application/pdf", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel", "text/csv", "image/*"],
    });
    if (res.canceled || !res.assets?.length) return;
    const f = res.assets[0];
    setFileName(f.name);
    setMime(f.mimeType || "application/octet-stream");
    // Read as base64 (works on web via fetch())
    try {
      const resp = await fetch(f.uri);
      const blob = await resp.blob();
      const reader = new FileReader();
      reader.onloadend = () => {
        const s = String(reader.result || "");
        // reader gives "data:...;base64,XXXX" — send only the base64 part
        const b64 = s.includes(",") ? s.split(",")[1] : s;
        setFileB64(b64);
      };
      reader.readAsDataURL(blob);
    } catch {
      setErr("Failed to read file.");
    }
  };

  const submit = async () => {
    setErr("");
    if (!title.trim()) { setErr("Title is required."); return; }
    if (!mrfId.trim() && !poId.trim()) { setErr("Attach to an MRF or PO."); return; }
    if (!fileB64) { setErr("Select a file."); return; }
    setSaving(true);
    try {
      const vendors = [
        l1Vendor.trim() ? { vendor_name: l1Vendor, amount: parseFloat(l1Amt) || 0 } : null,
        l2Vendor.trim() ? { vendor_name: l2Vendor, amount: parseFloat(l2Amt) || 0 } : null,
        l3Vendor.trim() ? { vendor_name: l3Vendor, amount: parseFloat(l3Amt) || 0 } : null,
      ].filter(Boolean);
      await api("/comparative-statement", {
        method: "POST", body: {
          mrf_id: mrfId || undefined,
          po_id: poId || undefined,
          title, remarks,
          file_name: fileName, mime_type: mime, file_base64: fileB64,
          vendors,
          l1_vendor: l1Vendor || undefined,
          l1_amount: parseFloat(l1Amt) || 0,
          selected_vendor: selectedVendor || undefined,
          selection_reason: selectionReason || undefined,
        },
      });
      // reset form
      setTitle(""); setL1Vendor(""); setL1Amt(""); setL2Vendor(""); setL2Amt("");
      setL3Vendor(""); setL3Amt(""); setSelectedVendor(""); setSelectionReason("");
      setRemarks(""); setFileName(""); setFileB64(""); setMime("");
      onDone();
    } catch (e: any) {
      setErr(e?.message || "Upload failed.");
    }
    setSaving(false);
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.modalBg}>
        <View style={styles.modalCard}>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <Text style={{ fontSize: 16, fontWeight: "800" }}>Upload Comparative Statement</Text>
            <TouchableOpacity onPress={onClose}><Ionicons name="close" size={22} color={theme.colors.text} /></TouchableOpacity>
          </View>
          <ScrollView style={{ maxHeight: 520, marginTop: 8 }}>
            <Label>Title</Label>
            <TextInput value={title} onChangeText={setTitle} placeholder="e.g. CS for CAT6 cable procurement" style={styles.input} testID="cs-title" />
            <Label style={{ marginTop: 8 }}>Attach To</Label>
            <TextInput value={mrfId} onChangeText={setMRFId} placeholder="MRF ID (mrf_xxx)" style={styles.input} testID="cs-mrf-id" />
            <TextInput value={poId} onChangeText={setPOId} placeholder="OR PO ID (po_xxx)" style={[styles.input, { marginTop: 4 }]} testID="cs-po-id" />

            <Label style={{ marginTop: 8 }}>L1 Vendor / Amount</Label>
            <View style={{ flexDirection: "row", gap: 6 }}>
              <TextInput value={l1Vendor} onChangeText={setL1Vendor} placeholder="Vendor" style={[styles.input, { flex: 2 }]} testID="cs-l1-vendor" />
              <TextInput value={l1Amt} onChangeText={setL1Amt} placeholder="Amount" keyboardType="decimal-pad" style={[styles.input, { flex: 1 }]} />
            </View>
            <Label style={{ marginTop: 6 }}>L2 Vendor / Amount</Label>
            <View style={{ flexDirection: "row", gap: 6 }}>
              <TextInput value={l2Vendor} onChangeText={setL2Vendor} placeholder="Vendor" style={[styles.input, { flex: 2 }]} />
              <TextInput value={l2Amt} onChangeText={setL2Amt} placeholder="Amount" keyboardType="decimal-pad" style={[styles.input, { flex: 1 }]} />
            </View>
            <Label style={{ marginTop: 6 }}>L3 Vendor / Amount</Label>
            <View style={{ flexDirection: "row", gap: 6 }}>
              <TextInput value={l3Vendor} onChangeText={setL3Vendor} placeholder="Vendor" style={[styles.input, { flex: 2 }]} />
              <TextInput value={l3Amt} onChangeText={setL3Amt} placeholder="Amount" keyboardType="decimal-pad" style={[styles.input, { flex: 1 }]} />
            </View>

            <Label style={{ marginTop: 8 }}>Selected Vendor</Label>
            <TextInput value={selectedVendor} onChangeText={setSelectedVendor} placeholder="e.g. Digilink" style={styles.input} />
            <Label style={{ marginTop: 8 }}>Selection Reason</Label>
            <TextInput value={selectionReason} onChangeText={setSelectionReason} multiline placeholder="e.g. Lowest bid, best warranty" style={[styles.input, { minHeight: 50 }]} />
            <Label style={{ marginTop: 8 }}>Remarks</Label>
            <TextInput value={remarks} onChangeText={setRemarks} multiline style={[styles.input, { minHeight: 50 }]} />

            <Label style={{ marginTop: 12 }}>File Attachment</Label>
            <TouchableOpacity onPress={pickFile} style={styles.filePickBtn} testID="cs-pick-file">
              <Ionicons name="attach" size={18} color={theme.colors.primary} />
              <Text style={{ color: theme.colors.primary, fontWeight: "700" }}>
                {fileName || "Pick PDF / Excel / CSV"}
              </Text>
            </TouchableOpacity>
          </ScrollView>

          {err ? <Text style={styles.err} testID="cs-err">{err}</Text> : null}

          <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
            <View style={{ flex: 1 }}><Btn title="Cancel" variant="outline" onPress={onClose} /></View>
            <View style={{ flex: 1 }}><Btn testID="cs-submit-btn" title={saving ? "Uploading…" : "Upload"} variant="primary" onPress={submit} disabled={saving} /></View>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 4, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  csNo: { fontSize: 15, fontWeight: "800", color: theme.colors.primary },
  iconBtn: { padding: 6, borderRadius: 6 },
  vendorGrid: { flexDirection: "row", gap: 6, marginTop: 8, flexWrap: "wrap" },
  vendorPill: { flex: 1, minWidth: 90, paddingHorizontal: 8, paddingVertical: 6, borderRadius: 6 },
  vendorRank: { color: "#fff", fontSize: 10, fontWeight: "800" },
  vendorName: { color: "#fff", fontSize: 12, fontWeight: "700", marginTop: 2 },
  vendorAmt: { color: "#fff", fontSize: 11, marginTop: 2 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "center", padding: 16 },
  modalCard: { backgroundColor: "#fff", borderRadius: 12, padding: 16 },
  input: { borderWidth: 1, borderColor: theme.colors.border, backgroundColor: "#fff", borderRadius: 6, padding: 8, fontSize: 13, marginTop: 4 },
  filePickBtn: { flexDirection: "row", alignItems: "center", gap: 8, borderWidth: 1.5, borderColor: theme.colors.primary, borderStyle: "dashed", borderRadius: 8, padding: 12, justifyContent: "center" },
  err: { color: theme.colors.danger, backgroundColor: "#FEF2F2", padding: 10, borderRadius: 6, marginTop: 10, fontSize: 12 },
});
