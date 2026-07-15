import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api, backendUrl, getToken } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, H1, H2, Muted, Pill, Label, Loader } from "@/src/components/ui";
import { theme } from "@/src/theme";

export default function PODetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const [po, setPo] = useState<any>(null);
  const [vendor, setVendor] = useState<any>(null);
  const [project, setProject] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const p = await api<any>(`/po/${id}`);
      setPo(p);
      const [v, pr] = await Promise.all([
        api<any[]>("/vendors").then((vs) => vs.find((x) => x.vendor_id === p.vendor_id)),
        api<any[]>("/projects").then((ps) => ps.find((x) => x.project_id === p.project_id)),
      ]);
      setVendor(v); setProject(pr);
    } catch (_e) { /* noop */ }
    setBusy(false);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const downloadPDF = async () => {
    const t = await getToken();
    const url = `${backendUrl}/api/po/${id}/pdf?token=${t}`;
    if (typeof window !== "undefined") window.open(url, "_blank");
  };

  const markReceived = async () => {
    await api(`/po/${id}/received`, { method: "POST", body: {} });
    load();
  };

  if (!po) return busy ? <Loader /> : null;

  const canReceive = po.status === "issued" && (user?.role === "purchase" || user?.role === "billing" || user?.role === "admin");

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity testID="back-btn" onPress={() => router.back()} style={{ padding: 8 }}>
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>{po.po_number}</Text>
        <TouchableOpacity testID="download-pdf-btn" onPress={downloadPDF} style={{ padding: 8 }}>
          <Ionicons name="document-outline" size={22} color={theme.colors.primary} />
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 120 }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
          <View style={{ flex: 1 }}>
            <H1>{po.po_number}</H1>
            <Muted>{new Date(po.date).toLocaleDateString()}</Muted>
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
          <Text style={{ color: theme.colors.textMuted, marginTop: 4 }}>MRF Refs: {po.mrf_refs?.join(", ")}</Text>
        </Card>

        <H2 style={{ marginTop: 16, marginBottom: 8 }}>Items</H2>
        {po.items.map((it: any, i: number) => {
          const gross = it.qty * it.rate;
          const ad = gross - (it.discount || 0);
          const gst = ad * (it.gst || 0) / 100;
          return (
            <Card key={i} style={{ marginBottom: 8 }}>
              <Text style={{ fontWeight: "700" }}>{i + 1}. {it.description}</Text>
              {it.specification ? <Muted>{it.specification}</Muted> : null}
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                <MiniStat label="Qty" value={`${it.qty} ${it.unit}`} />
                <MiniStat label="Rate" value={`₹${it.rate}`} />
                <MiniStat label="Disc" value={`₹${it.discount || 0}`} />
                <MiniStat label="GST" value={`${it.gst}%`} />
                <MiniStat label="Total" value={`₹${(ad + gst).toFixed(2)}`} />
              </View>
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
          <Btn testID="pdf-download-btn" title="Download PDF" variant="primary" onPress={downloadPDF} />
          {canReceive ? <Btn testID="mark-received-btn" title="Mark as Received" variant="action" onPress={markReceived} /> : null}
        </View>
      </ScrollView>
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
});
