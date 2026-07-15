import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Card, Muted, Empty, Loader } from "@/src/components/ui";
import { theme, statusLabel } from "@/src/theme";

export default function AuditScreen() {
  const router = useRouter();
  const [logs, setLogs] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => { (async () => { setBusy(true); try { setLogs(await api("/audit")); } catch (_e) { /* noop */ } setBusy(false); })(); }, []);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }}>
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Audit Trail</Text>
        <View style={{ width: 38 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: 16 }}>
        <Text style={{ fontSize: 24, fontWeight: "800" }}>System Audit</Text>
        <Muted>Last 200 events. Immutable.</Muted>
        {busy && !logs.length ? <Loader /> : null}
        <View style={{ marginTop: 12, gap: 6 }}>
          {logs.map((a) => (
            <Card key={a.audit_id} testID={`audit-${a.audit_id}`}>
              <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                <Text style={{ fontWeight: "700" }}>{statusLabel(a.entity)} · {statusLabel(a.action)}</Text>
                <Text style={{ fontSize: 10, color: theme.colors.textMuted }}>{new Date(a.timestamp).toLocaleString()}</Text>
              </View>
              <Text style={{ fontSize: 12, color: theme.colors.textSecondary, marginTop: 2 }}>
                by {a.user_name} ({statusLabel(a.user_role)})
              </Text>
              {a.details && Object.keys(a.details).length > 0 ? (
                <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>
                  {JSON.stringify(a.details).slice(0, 200)}
                </Text>
              ) : null}
            </Card>
          ))}
          {!busy && !logs.length ? <Empty msg="No audit entries yet." testID="audit-empty" /> : null}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 8, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
});
