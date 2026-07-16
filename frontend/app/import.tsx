import React, { useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Platform } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";
import * as DocumentPicker from "expo-document-picker";

import { useAuth } from "@/src/auth";
import { backendUrl, getToken } from "@/src/api";
import { Btn, Card, H1, H2, Muted, Label, Body } from "@/src/components/ui";
import { theme } from "@/src/theme";

export default function ImportScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [busy, setBusy] = useState<null | "vendors" | "mrf">(null);
  const [result, setResult] = useState<any>(null);

  const downloadTemplate = async (kind: "vendors" | "mrf") => {
    const t = await getToken();
    if (typeof window !== "undefined") {
      window.open(`${backendUrl}/api/import/${kind}/template?token=${t}`, "_blank");
    }
  };

  const uploadFile = async (kind: "vendors" | "mrf") => {
    try {
      const pick = await DocumentPicker.getDocumentAsync({
        type: [
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "application/vnd.ms-excel",
          ".xlsx",
        ],
        copyToCacheDirectory: true,
      });
      if (pick.canceled) return;
      const asset = pick.assets[0];
      setBusy(kind); setResult(null);
      const form = new FormData();
      if (Platform.OS === "web") {
        // asset.file is available on web via expo-document-picker
        // Fetch the URI and turn into blob
        const res = await fetch(asset.uri);
        const blob = await res.blob();
        form.append("file", blob, asset.name);
      } else {
        form.append("file", {
          // @ts-ignore RN FormData accepts this shape
          uri: asset.uri, name: asset.name, type: asset.mimeType || "application/octet-stream",
        } as any);
      }
      const token = await getToken();
      const resp = await fetch(`${backendUrl}/api/import/${kind}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      const j = await resp.json();
      if (!resp.ok) throw new Error(j.detail || "Import failed");
      setResult({ kind, ...j });
    } catch (e: any) {
      setResult({ kind, error: e.message || "Failed" });
    }
    setBusy(null);
  };

  if (!user) return null;
  const canImport = user.role === "admin" || user.role === "purchase" || user.role === "pm";

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity testID="back-btn" onPress={() => router.back()} style={{ padding: 8 }}>
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Excel Bulk Import</Text>
        <View style={{ width: 38 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: 16 }}>
        <H1>Bulk Import</H1>
        <Muted>Upload xlsx files to create vendors or MRFs in bulk.</Muted>

        {!canImport ? (
          <Card style={{ marginTop: 16 }}>
            <Text>Your role does not permit imports.</Text>
          </Card>
        ) : null}

        {/* Vendors */}
        {canImport ? (
          <Card style={{ marginTop: 16 }} testID="vendors-import-card">
            <H2>Vendors</H2>
            <Muted style={{ marginTop: 4 }}>Columns: name, address, gstin, contact, email.</Muted>
            <View style={{ marginTop: 12, gap: 8 }}>
              <Btn testID="dl-vendor-template" title="Download Template" variant="outline" onPress={() => downloadTemplate("vendors")} />
              <Btn testID="upload-vendors-btn" title={busy === "vendors" ? "Uploading…" : "Upload Vendors xlsx"} variant="action" onPress={() => uploadFile("vendors")} disabled={!!busy} />
            </View>
          </Card>
        ) : null}

        {/* MRFs */}
        {canImport ? (
          <Card style={{ marginTop: 12 }} testID="mrf-import-card">
            <H2>Material Requisitions</H2>
            <Muted style={{ marginTop: 4 }}>
              Columns include project_code, site, required_by, requesting_person, system_category,
              description, unit, qty_requested. Rows sharing header fields are grouped into one MRF.
            </Muted>
            <View style={{ marginTop: 12, gap: 8 }}>
              <Btn testID="dl-mrf-template" title="Download Template" variant="outline" onPress={() => downloadTemplate("mrf")} />
              <Btn testID="upload-mrf-btn" title={busy === "mrf" ? "Uploading…" : "Upload MRF xlsx"} variant="action" onPress={() => uploadFile("mrf")} disabled={!!busy} />
            </View>
          </Card>
        ) : null}

        {result ? (
          <Card style={{ marginTop: 16, backgroundColor: result.error ? "#FEE2E2" : theme.colors.surface }} testID="import-result">
            <Label>{result.kind?.toUpperCase()} RESULT</Label>
            {result.error ? (
              <Body style={{ color: theme.colors.danger, marginTop: 6 }}>{result.error}</Body>
            ) : result.kind === "vendors" ? (
              <>
                <Body style={{ marginTop: 6 }}>Inserted: {result.inserted} · Skipped: {result.skipped}</Body>
                {result.errors?.length ? <Body style={{ color: theme.colors.danger, marginTop: 6 }}>{result.errors.join("\n")}</Body> : null}
              </>
            ) : (
              <>
                <Body style={{ marginTop: 6 }}>Created: {result.count} MRF(s)</Body>
                {result.created?.length ? <Body style={{ marginTop: 4 }}>{result.created.join(", ")}</Body> : null}
                {result.errors?.length ? <Body style={{ color: theme.colors.danger, marginTop: 6 }}>{result.errors.join("\n")}</Body> : null}
              </>
            )}
          </Card>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 8, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
});
