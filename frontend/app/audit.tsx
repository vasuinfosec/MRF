import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  TextInput,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api";
import AuditTrail from "@/src/components/AuditTrail";
import { Muted } from "@/src/components/ui";
import { theme, statusLabel } from "@/src/theme";
import { useAuth } from "@/src/auth";

interface Facets {
  entities: string[];
  actions: string[];
  users: { user_id: string; name: string; role: string }[];
}

export default function AuditScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ entity_id?: string; entity?: string }>();
  const { user } = useAuth();
  const [facets, setFacets] = useState<Facets | null>(null);
  const [entity, setEntity] = useState<string>(String(params.entity || ""));
  const [action, setAction] = useState<string>("");
  const [userRole, setUserRole] = useState<string>("");
  const [q, setQ] = useState<string>(String(params.entity_id || ""));

  const canFilter = ["admin", "director", "gm", "purchase", "pm"].includes(user?.role || "");

  const loadFacets = useCallback(async () => {
    if (!canFilter) return;
    try {
      const f = await api<Facets>("/audit/facets");
      setFacets(f);
    } catch (_e) {
      /* noop */
    }
  }, [canFilter]);

  useEffect(() => {
    loadFacets();
  }, [loadFacets]);

  const queryTail = useMemo(() => {
    const p = new URLSearchParams();
    if (entity) p.set("entity", entity);
    if (action) p.set("action", action);
    if (userRole) p.set("user_role", userRole);
    if (q.trim()) p.set("entity_id", q.trim());
    return p.toString();
  }, [entity, action, userRole, q]);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }}>
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>System Audit Trail</Text>
        <View style={{ width: 38 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 16 }}>
        <Text style={{ fontSize: 22, fontWeight: "800", color: theme.colors.text }}>
          Audit Trail
        </Text>
        <Muted>
          Every user action is recorded — logins, MRF/PO flows, approvals, master-data edits,
          bulk imports, exports and downloads. Immutable log.
        </Muted>

        {canFilter ? (
          <View style={styles.filterBox}>
            <Text style={styles.filterHead}>Filters</Text>
            <TextInput
              testID="audit-q"
              value={q}
              onChangeText={setQ}
              placeholder="Search by record ID (e.g. mrf_..., po_..., CUS-0001)"
              autoCapitalize="none"
              style={styles.input}
            />
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }}>
              <Chip label="All entities" active={!entity} onPress={() => setEntity("")} />
              {(facets?.entities || []).slice(0, 20).map((e) => (
                <Chip key={e} label={statusLabel(e)} active={entity === e} onPress={() => setEntity(e)} />
              ))}
            </ScrollView>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 6 }}>
              <Chip label="All actions" active={!action} onPress={() => setAction("")} />
              {(facets?.actions || []).slice(0, 30).map((a) => (
                <Chip key={a} label={statusLabel(a)} active={action === a} onPress={() => setAction(a)} />
              ))}
            </ScrollView>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 6 }}>
              {["", "site_engineer", "pm", "purchase", "gm", "director", "admin", "store"].map((r) => (
                <Chip
                  key={r || "__all_roles"}
                  label={r ? statusLabel(r) : "All roles"}
                  active={userRole === r}
                  onPress={() => setUserRole(r)}
                />
              ))}
            </ScrollView>
          </View>
        ) : null}

        <View style={{ marginTop: 12 }}>
          <AuditTrail
            key={queryTail}
            entityId={q.trim() || undefined}
            entity={entity || undefined}
            limit={200}
            title=""
          />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function Chip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <TouchableOpacity
      onPress={onPress}
      style={[styles.chip, active ? styles.chipActive : null]}
    >
      <Text style={[styles.chipText, active ? styles.chipTextActive : null]}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 8,
    paddingVertical: 8,
    backgroundColor: theme.colors.bg,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.border,
  },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  filterBox: {
    marginTop: 14,
    padding: 12,
    borderRadius: 10,
    backgroundColor: "#F9FAFB",
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  filterHead: {
    fontSize: 11,
    fontWeight: "800",
    color: theme.colors.textMuted,
    textTransform: "uppercase",
    letterSpacing: 0.8,
    marginBottom: 6,
  },
  input: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: "#fff",
    borderRadius: 6,
    padding: 8,
    fontSize: 13,
  },
  chip: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: "#fff",
    marginRight: 6,
  },
  chipActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  chipText: { fontSize: 12, color: theme.colors.text, fontWeight: "600" },
  chipTextActive: { color: "#fff" },
});
