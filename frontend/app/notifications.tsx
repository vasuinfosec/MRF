import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, TouchableOpacity } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Card, Muted, Empty, Loader } from "@/src/components/ui";
import { theme } from "@/src/theme";

export default function Notifications() {
  const router = useRouter();
  const { user } = useAuth();
  const [items, setItems] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try { setItems(await api("/notifications")); } catch (_e) { /* noop */ }
    setBusy(false);
  }, []);

  useEffect(() => { if (user) load(); }, [user, load]);

  const openItem = async (n: any) => {
    if (!n.read) { try { await api(`/notifications/${n.notification_id}/read`, { method: "POST" }); } catch (_e) { /* noop */ } }
    if (n.link) router.push(n.link as any);
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }}>
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>Notifications</Text>
        <View style={{ width: 38 }} />
      </View>
      <View style={{ padding: 16 }}>
        {busy && !items.length ? <Loader /> : null}
        {items.map((n) => (
          <TouchableOpacity key={n.notification_id} testID={`notif-${n.notification_id}`}
            onPress={() => openItem(n)} activeOpacity={0.7} style={{ marginBottom: 8 }}>
            <Card>
              <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                <Text style={{ fontWeight: "700" }}>{n.title}</Text>
                {!n.read ? <View style={styles.dot} /> : null}
              </View>
              <Muted style={{ marginTop: 4 }}>{n.body}</Muted>
              <Text style={{ fontSize: 10, color: theme.colors.textMuted, marginTop: 6 }}>
                {new Date(n.created_at).toLocaleString()}
              </Text>
            </Card>
          </TouchableOpacity>
        ))}
        {!busy && !items.length ? <Empty msg="No notifications." testID="empty-notif" /> : null}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 8, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: theme.colors.action },
});
