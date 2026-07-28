import React, { useCallback, useEffect, useState } from "react";
import { View, Text, ScrollView, RefreshControl, TouchableOpacity, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { AppShell } from "@/src/components/AppShell";
import { api } from "@/src/api";
import { useAccessGuard } from "@/src/hooks/useAccessGuard";
import { Card, H1, H2, Muted, Loader, Btn, Stat } from "@/src/components/ui";
import { theme } from "@/src/theme";
import { ACCESS_ADMIN_EMAIL } from "@/src/access";

type Counts = {
  pending_requests: number;
  invitations_open: number;
  pending_users: number;
  users_total: number;
  active_directors: number;
};

export default function AccessHub() {
  const { permitted, loading } = useAccessGuard(["admin"], [ACCESS_ADMIN_EMAIL]);
  const router = useRouter();
  const [refreshing, setRefreshing] = useState(false);
  const [counts, setCounts] = useState<Counts | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [reqs, invs, pu, us] = await Promise.all([
        api<any[]>("/admin/access/pending-requests").catch(() => []),
        api<any[]>("/admin/access/invitations").catch(() => []),
        api<any[]>("/admin/access/pending-users").catch(() => []),
        api<any[]>("/users").catch(() => []),
      ]);
      const activeDirectors = (us || []).filter(
        (u: any) => u.is_active && (u.role === "director" || (u.roles || []).includes("director"))
      ).length;
      const invsOpen = (invs || []).filter((i: any) => !i.consumed).length;
      setCounts({
        pending_requests: (reqs || []).length,
        invitations_open: invsOpen,
        pending_users: (pu || []).length,
        users_total: (us || []).length,
        active_directors: activeDirectors,
      });
    } catch (e: any) {
      setErr(e?.message || "Failed to load counts");
    }
  }, []);

  useEffect(() => {
    if (permitted) load();
  }, [permitted, load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  if (loading || !permitted) return <AppShell title="Access Control"><Loader /></AppShell>;

  return (
    <AppShell title="Access Control" testID="admin-access-hub">
      <ScrollView
        contentContainerStyle={{ paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        <H1>Access Control</H1>
        <Muted>Invitations, pending users, and roles.</Muted>

        {err ? (
          <Card style={{ marginTop: 12, borderColor: theme.colors.danger }}>
            <Text style={{ color: theme.colors.danger }}>{err}</Text>
            <Btn title="Retry" variant="outline" onPress={load} style={{ marginTop: 8 }} />
          </Card>
        ) : null}

        {counts ? (
          <View style={styles.statsRow}>
            <Stat label="Pending Requests" value={counts.pending_requests} tone="action" />
            <Stat label="Open Invitations" value={counts.invitations_open} />
            <Stat label="Awaiting Activation" value={counts.pending_users} tone="action" />
            <Stat label="Total Users" value={counts.users_total} tone="success" />
          </View>
        ) : (
          <Loader />
        )}

        {counts && counts.active_directors <= 1 ? (
          <Card style={{ marginTop: 12, borderColor: theme.colors.action }}>
            <Text style={{ fontWeight: "700", color: theme.colors.action }}>
              Only {counts.active_directors} active Director
            </Text>
            <Muted>Consider inviting a second Director for resiliency. The last-Director guardrail prevents accidental lockout.</Muted>
          </Card>
        ) : null}

        <View style={{ marginTop: 16, gap: 10 }}>
          <Tile
            testID="tile-pending-requests"
            icon="mail-unread-outline"
            title="Pending Access Requests"
            subtitle="Uninvited sign-in attempts you can promote to invitations"
            badge={counts?.pending_requests || 0}
            onPress={() => router.push("/admin/access/pending-requests")}
          />
          <Tile
            testID="tile-invitations"
            icon="mail-open-outline"
            title="Google Login Access"
            subtitle="Add, update or revoke email access and assigned roles"
            badge={counts?.invitations_open || 0}
            onPress={() => router.push("/admin/access/invitations")}
          />
          <Tile
            testID="tile-pending-users"
            icon="hourglass-outline"
            title="Pending Activation"
            subtitle="Invited users awaiting role assignment"
            badge={counts?.pending_users || 0}
            onPress={() => router.push("/admin/access/pending-users")}
          />
          <Tile
            testID="tile-users-roles"
            icon="people-outline"
            title="Users & Roles"
            subtitle="Assign multiple roles, deactivate accounts"
            badge={counts?.users_total || 0}
            onPress={() => router.push("/admin/access/users")}
          />
        </View>

        <Card style={{ marginTop: 16, backgroundColor: theme.colors.surface2 }}>
          <H2>Access Model</H2>
          <Muted>
            Under Access-Security V2, all new sign-ins require an active invitation. Uninvited attempts are recorded for
            Access Admin review. Other office accounts receive access only after an explicit role invitation.
          </Muted>
        </Card>
      </ScrollView>
    </AppShell>
  );
}

function Tile({ testID, icon, title, subtitle, badge, onPress }: {
  testID?: string; icon: any; title: string; subtitle: string; badge?: number; onPress: () => void;
}) {
  return (
    <TouchableOpacity testID={testID} onPress={onPress} activeOpacity={0.7}>
      <View style={styles.tile}>
        <View style={styles.tileIcon}>
          <Ionicons name={icon} size={22} color={theme.colors.primary} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.tileTitle}>{title}</Text>
          <Text style={styles.tileSubtitle}>{subtitle}</Text>
        </View>
        {badge && badge > 0 ? (
          <View style={styles.badge}>
            <Text style={styles.badgeText}>{badge}</Text>
          </View>
        ) : null}
        <Ionicons name="chevron-forward" size={20} color={theme.colors.textMuted} />
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  statsRow: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 12 },
  tile: {
    flexDirection: "row", alignItems: "center",
    padding: 14, borderWidth: 1, borderColor: theme.colors.border,
    borderRadius: theme.radius.md, backgroundColor: theme.colors.bg, gap: 12,
  },
  tileIcon: {
    width: 40, height: 40, borderRadius: 20,
    alignItems: "center", justifyContent: "center", backgroundColor: theme.colors.surface2,
  },
  tileTitle: { fontWeight: "700", fontSize: 15, color: theme.colors.text },
  tileSubtitle: { fontSize: 12, color: theme.colors.textMuted, marginTop: 2 },
  badge: {
    minWidth: 24, height: 24, borderRadius: 12, paddingHorizontal: 8,
    alignItems: "center", justifyContent: "center", backgroundColor: theme.colors.action,
  },
  badgeText: { color: "#fff", fontWeight: "800", fontSize: 12 },
});
