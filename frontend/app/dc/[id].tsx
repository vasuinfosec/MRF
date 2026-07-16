import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Card, H2, Muted, Loader, Label, Pill } from "@/src/components/ui";
import ExportMenu from "@/src/components/ExportMenu";
import AuditTrail from "@/src/components/AuditTrail";
import { theme } from "@/src/theme";

export default function DCDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [dc, setDC] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [exportOpen, setExportOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api<any>(`/dc/${id}`);
      setDC(d);
    } catch { setDC(null); }
    setLoading(false);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <SafeAreaView style={{ flex: 1 }}><Loader /></SafeAreaView>;
  if (!dc) return <SafeAreaView style={{ flex: 1 }}><Muted>DC not found.</Muted></SafeAreaView>;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }} testID="back-btn">
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>{dc.dc_number}</Text>
        <TouchableOpacity testID="download-dc-btn" onPress={() => setExportOpen(true)} style={{ padding: 8 }}>
          <Ionicons name="download-outline" size={22} color={theme.colors.primary} />
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
        <View style={{ flexDirection: "row", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
          <Pill status={dc.dc_type || "outbound"} />
          <Pill status={dc.status || "issued"} />
        </View>

        <Card>
          <Label>Route</Label>
          <Text style={styles.val}>{dc.from_location}  →  {dc.to_location}</Text>
          <Label style={{ marginTop: 8 }}>Dispatch Date</Label>
          <Text style={styles.val}>{dc.dispatch_date}</Text>
          {dc.vehicle_no ? (<><Label style={{ marginTop: 8 }}>Vehicle / Driver</Label><Text style={styles.val}>{dc.vehicle_no}  ·  {dc.driver_name || "—"}  ·  {dc.driver_contact || "—"}</Text></>) : null}
          {dc.transporter ? (<><Label style={{ marginTop: 8 }}>Transporter</Label><Text style={styles.val}>{dc.transporter}</Text></>) : null}
          {dc.e_way_bill_no ? (<><Label style={{ marginTop: 8 }}>E-Way Bill</Label><Text style={styles.val}>{dc.e_way_bill_no}</Text></>) : null}
          {dc.vendor_dc_ref ? (<><Label style={{ marginTop: 8 }}>Vendor DC Ref</Label><Text style={styles.val}>{dc.vendor_dc_ref}</Text></>) : null}
        </Card>

        <H2 style={{ marginTop: 16 }}>Line Items ({dc.items?.length || 0})</H2>
        {(dc.items || []).map((it: any, idx: number) => (
          <Card key={idx} style={{ marginTop: 8 }}>
            <Text style={styles.itemDesc}>{idx + 1}. {it.description || "—"}</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", marginTop: 4, gap: 8 }}>
              {it.material_uid ? <Text style={styles.chip}>MAT {it.material_uid}</Text> : null}
              {it.variant_uid ? <Text style={styles.chipAlt}>VAR {it.variant_uid}</Text> : null}
              <Text style={styles.qty}>{it.qty} {it.unit}</Text>
              {it.make ? <Muted>{it.make}{it.model ? " · " + it.model : ""}</Muted> : null}
            </View>
            {it.remarks ? <Muted>{it.remarks}</Muted> : null}
          </Card>
        ))}

        {dc.remarks ? (<><H2 style={{ marginTop: 16 }}>Remarks</H2><Card><Text>{dc.remarks}</Text></Card></>) : null}

        <View style={{ marginTop: 20 }}>
          <AuditTrail entityId={String(id || "")} title="Audit Trail" limit={100} />
        </View>
      </ScrollView>

      <ExportMenu
        visible={exportOpen}
        onClose={() => setExportOpen(false)}
        entity="dc"
        id={String(id || "")}
        recordNumber={dc.dc_number}
        formats={["pdf", "excel"]}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 4, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { flex: 1, textAlign: "center", fontSize: 16, fontWeight: "800", color: theme.colors.text },
  val: { fontSize: 14, color: theme.colors.text, fontWeight: "700" },
  itemDesc: { fontWeight: "700", color: theme.colors.text, fontSize: 14 },
  chip: { backgroundColor: "#EEF2FF", color: "#3730A3", fontSize: 11, fontWeight: "700", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  chipAlt: { backgroundColor: "#ECFCCB", color: "#3F6212", fontSize: 11, fontWeight: "700", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  qty: { backgroundColor: "#F3F4F6", color: theme.colors.text, fontSize: 12, fontWeight: "700", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
});
