import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Card, H2, Muted, Loader, Label } from "@/src/components/ui";
import ExportMenu from "@/src/components/ExportMenu";
import AuditTrail from "@/src/components/AuditTrail";
import ApprovalPanel from "@/src/components/ApprovalPanel";
import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";

interface GRN {
  grn_id: string; grn_number: string; date: string;
  po_id: string; po_number: string;
  vendor_id: string; project_id: string;
  mrf_refs: string[]; items: any[];
  received_by_name: string; remarks?: string; status?: string;
  vehicle_no?: string; driver_name?: string; vendor_dc_ref?: string;
  approval_history?: any[];
}

export default function GRNDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const [grn, setGRN] = useState<GRN | null>(null);
  const [loading, setLoading] = useState(true);
  const [exportOpen, setExportOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Prefer dedicated single-GRN endpoint for speed; fallback to list scan.
      let one: GRN | null = null;
      try {
        one = await api<GRN>(`/grn/${id}`);
      } catch {
        const rows = await api<GRN[]>("/grns");
        one = (rows || []).find((r) => r.grn_id === id) || null;
      }
      setGRN(one);
    } catch {
      setGRN(null);
    }
    setLoading(false);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <SafeAreaView style={{ flex: 1 }}><Loader /></SafeAreaView>;
  if (!grn) return <SafeAreaView style={{ flex: 1 }}><Muted>GRN not found.</Muted></SafeAreaView>;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }} testID="back-btn">
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>{grn.grn_number}</Text>
        <TouchableOpacity testID="download-grn-btn" onPress={() => setExportOpen(true)} style={{ padding: 8 }}>
          <Ionicons name="download-outline" size={22} color={theme.colors.primary} />
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
        <Card>
          <Label>Date</Label>
          <Text style={styles.val}>{new Date(grn.date).toLocaleDateString()}</Text>
          <Label style={{ marginTop: 8 }}>PO</Label>
          <Text style={styles.val}>{grn.po_number || "—"}</Text>
          <Label style={{ marginTop: 8 }}>Received By</Label>
          <Text style={styles.val}>{grn.received_by_name || "—"}</Text>
          {grn.vehicle_no ? (
            <>
              <Label style={{ marginTop: 8 }}>Vehicle / Driver</Label>
              <Text style={styles.val}>{grn.vehicle_no}  ·  {grn.driver_name || "—"}</Text>
            </>
          ) : null}
          {grn.vendor_dc_ref ? (
            <>
              <Label style={{ marginTop: 8 }}>Vendor DC/Invoice Ref</Label>
              <Text style={styles.val}>{grn.vendor_dc_ref}</Text>
            </>
          ) : null}
        </Card>

        <H2 style={{ marginTop: 16 }}>Line Items ({grn.items?.length || 0})</H2>
        {(grn.items || []).map((it, idx) => (
          <Card key={idx} style={{ marginTop: 8 }}>
            <Text style={styles.itemDesc}>{idx + 1}. {it.description || "—"}</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", marginTop: 4, gap: 8 }}>
              {it.material_uid ? <Text style={styles.chip}>MAT {it.material_uid}</Text> : null}
              {it.variant_uid ? <Text style={styles.chipAlt}>VAR {it.variant_uid}</Text> : null}
              <Text style={styles.qty}>{it.qty} {it.unit}</Text>
            </View>
            {it.remarks ? <Muted>{it.remarks}</Muted> : null}
          </Card>
        ))}

        {grn.remarks ? (
          <>
            <H2 style={{ marginTop: 16 }}>Remarks</H2>
            <Card><Text>{grn.remarks}</Text></Card>
          </>
        ) : null}

        <ApprovalPanel
          entity="grn"
          id={String(id || "")}
          currentStatus={grn.status || "pending_approval"}
          canAct={["admin", "director"].includes(user?.role || "")}
          onDone={load}
          history={grn.approval_history}
          approverLabel="Accounts / Director"
        />

        <View style={{ marginTop: 20 }}>
          <AuditTrail entityId={String(id || "")} title="Audit Trail" limit={100} />
        </View>
      </ScrollView>

      <ExportMenu
        visible={exportOpen}
        onClose={() => setExportOpen(false)}
        entity="grn"
        id={String(id || "")}
        recordNumber={grn.grn_number}
        formats={["pdf", "excel"]}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 4, paddingVertical: 8, backgroundColor: theme.colors.bg,
    borderBottomWidth: 1, borderBottomColor: theme.colors.border,
  },
  title: { flex: 1, textAlign: "center", fontSize: 16, fontWeight: "800", color: theme.colors.text },
  val: { fontSize: 14, color: theme.colors.text, fontWeight: "700" },
  itemDesc: { fontWeight: "700", color: theme.colors.text, fontSize: 14 },
  chip: {
    backgroundColor: "#EEF2FF", color: "#3730A3", fontSize: 11, fontWeight: "700",
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
  },
  chipAlt: {
    backgroundColor: "#ECFCCB", color: "#3F6212", fontSize: 11, fontWeight: "700",
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
  },
  qty: {
    backgroundColor: "#F3F4F6", color: theme.colors.text, fontSize: 12, fontWeight: "700",
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
  },
});
