import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Btn, Card, Empty, H1, H2, Input, Label, Muted } from "@/src/components/ui";
import { theme } from "@/src/theme";

const ROLES = [
  "site_engineer", "pm", "purchase", "gm", "director", "admin", "store",
] as const;

type AccessUser = {
  user_id: string;
  email: string;
  name: string;
  role?: string;
  roles?: string[];
  is_active: boolean;
  invited_role?: string;
  pending_since?: string;
  activated_at?: string;
  deactivated_at?: string;
  deactivation_reason?: string;
};

type AccessRequest = {
  request_id: string;
  email: string;
  name?: string;
  attempt_count?: number;
  last_attempt_at?: string;
};

type Invitation = {
  invitation_id: string;
  email: string;
  role: string;
  expires_at?: string;
};

type HistoryRow = {
  audit_id?: string;
  action: string;
  timestamp?: string;
  user_name?: string;
  details?: Record<string, unknown>;
};

type ConfirmState = {
  title: string;
  message: string;
  actionLabel: string;
  danger?: boolean;
  needsReason?: boolean;
  run: (reason: string) => Promise<void>;
};

const effectiveRoles = (value?: { role?: string; roles?: string[] }) =>
  value?.roles?.length ? value.roles : (value?.role ? [value.role] : []);

const roleLabel = (role: string) =>
  role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const when = (value?: string) =>
  value ? new Date(value).toLocaleString() : "Not recorded";

export default function AccessConsole() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const { user } = useAuth();
  const compact = width < 760;
  const actorRoles = effectiveRoles(user || undefined);
  const actorIsDirector = actorRoles.includes("director");
  const actorIsManager = !!user?.is_active &&
    (actorRoles.includes("admin") || actorIsDirector);

  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [inactive, setInactive] = useState<AccessUser[]>([]);
  const [users, setUsers] = useState<AccessUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [permissionDenied, setPermissionDenied] = useState(!actorIsManager);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("site_engineer");
  const [requestToApprove, setRequestToApprove] = useState<AccessRequest | null>(null);
  const [roleUser, setRoleUser] = useState<AccessUser | null>(null);
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [activateUser, setActivateUser] = useState<AccessUser | null>(null);
  const [historyUser, setHistoryUser] = useState<AccessUser | null>(null);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [confirmReason, setConfirmReason] = useState("");

  const assignableRoles = useMemo(
    () => ROLES.filter((role) => role !== "director" || actorIsDirector),
    [actorIsDirector],
  );

  const load = useCallback(async (refresh = false) => {
    if (!actorIsManager) {
      setPermissionDenied(true);
      setLoading(false);
      return;
    }
    refresh ? setRefreshing(true) : setLoading(true);
    setError("");
    try {
      await api("/admin/access/permissions/me");
      const [requestRows, inviteRows, inactiveRows, userRows] = await Promise.all([
        api<AccessRequest[]>("/admin/access/pending-requests"),
        api<Invitation[]>("/admin/access/invitations"),
        api<AccessUser[]>("/admin/access/pending-users"),
        api<AccessUser[]>("/admin/access/users"),
      ]);
      setRequests(requestRows);
      setInvitations(inviteRows.filter((row) => !("consumed" in row) || !(row as any).consumed));
      setInactive(inactiveRows);
      setUsers(userRows);
      setPermissionDenied(false);
    } catch (e: any) {
      const message = e?.message || "Unable to load access data.";
      if (/403|404|active account|required|Admin or Director/i.test(message)) {
        setPermissionDenied(true);
      } else {
        setError(message);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [actorIsManager]);

  useEffect(() => { load(); }, [load]);

  const completed = async (message: string) => {
    setNotice(message);
    setTimeout(() => setNotice(""), 3500);
    await load(true);
  };

  const submitInvitation = async () => {
    if (!inviteEmail.trim() || !inviteEmail.includes("@")) {
      setError("Enter a valid company email address.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (requestToApprove) {
        await api(`/admin/access/pending-requests/${requestToApprove.request_id}/invite`, {
          method: "POST", body: { role: inviteRole, expires_in_hours: 72 },
        });
        await completed(`Access request approved for ${inviteEmail.trim()}.`);
      } else {
        await api("/admin/access/invitations", {
          method: "POST",
          body: { email: inviteEmail.trim(), role: inviteRole, expires_in_hours: 72 },
        });
        await completed(`Invitation sent to ${inviteEmail.trim()}.`);
      }
      setInviteOpen(false);
      setRequestToApprove(null);
      setInviteEmail("");
      setInviteRole("site_engineer");
    } catch (e: any) {
      setError(e?.message || "Invitation failed.");
    } finally {
      setBusy(false);
    }
  };

  const openApprove = (request: AccessRequest) => {
    setRequestToApprove(request);
    setInviteEmail(request.email);
    setInviteRole("site_engineer");
    setInviteOpen(true);
  };

  const rejectRequest = (request: AccessRequest) => setConfirm({
    title: "Reject access request?",
    message: `${request.email} will not receive an invitation.`,
    actionLabel: "Reject request",
    danger: true,
    needsReason: true,
    run: async (reason) => {
      await api(`/admin/access/pending-requests/${request.request_id}/reject`, {
        method: "POST", body: { reason },
      });
      await completed(`Access request rejected for ${request.email}.`);
    },
  });

  const revokeInvitation = (invitation: Invitation) => setConfirm({
    title: "Revoke invitation?",
    message: `${invitation.email} will no longer be able to accept this invitation.`,
    actionLabel: "Revoke invitation",
    danger: true,
    run: async () => {
      await api(`/admin/access/invitations/${invitation.invitation_id}`, {
        method: "DELETE",
      });
      await completed(`Invitation revoked for ${invitation.email}.`);
    },
  });

  const activate = async (target: AccessUser, role: string) => {
    setBusy(true);
    setError("");
    try {
      await api(`/admin/access/users/${target.user_id}/activate`, {
        method: "POST", body: { role, note: "Activated from Admin Access Console" },
      });
      setActivateUser(null);
      await completed(`${target.name || target.email} activated.`);
    } catch (e: any) {
      setError(e?.message || "Activation failed.");
    } finally {
      setBusy(false);
    }
  };

  const openActivate = (target: AccessUser) => {
    const preferredRole = effectiveRoles(target)[0] || target.invited_role;
    const initialRole = preferredRole && assignableRoles.includes(preferredRole as any)
      ? preferredRole
      : "site_engineer";
    setInviteRole(initialRole);
    setActivateUser(target);
  };

  const deactivate = (target: AccessUser) => setConfirm({
    title: "Deactivate user?",
    message: `${target.name || target.email} will lose access and all active sessions.`,
    actionLabel: "Deactivate user",
    danger: true,
    needsReason: true,
    run: async (reason) => {
      await api(`/admin/access/users/${target.user_id}/deactivate`, {
        method: "POST", body: { reason },
      });
      await completed(`${target.name || target.email} deactivated.`);
    },
  });

  const openRoles = (target: AccessUser) => {
    setRoleUser(target);
    setSelectedRoles(effectiveRoles(target));
  };

  const toggleRole = (role: string) => {
    setSelectedRoles((current) =>
      current.includes(role)
        ? current.filter((item) => item !== role)
        : [...current, role],
    );
  };

  const saveRoles = async () => {
    if (!roleUser || selectedRoles.length === 0) {
      setError("Select at least one role.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api(`/admin/access/users/${roleUser.user_id}/roles`, {
        method: "POST", body: { roles: selectedRoles, note: "Updated from Admin Access Console" },
      });
      setRoleUser(null);
      await completed(`Roles updated for ${roleUser.name || roleUser.email}.`);
    } catch (e: any) {
      setError(e?.message || "Role update failed.");
    } finally {
      setBusy(false);
    }
  };

  const revokeSessions = (target: AccessUser) => setConfirm({
    title: "Revoke active sessions?",
    message: `${target.name || target.email} will need to sign in again.`,
    actionLabel: "Revoke sessions",
    danger: true,
    run: async () => {
      const result = await api<{ revoked_sessions: number }>(
        `/admin/access/users/${target.user_id}/sessions/revoke`,
        { method: "POST" },
      );
      await completed(`${result.revoked_sessions} session(s) revoked.`);
    },
  });

  const showHistory = async (target: AccessUser) => {
    setHistoryUser(target);
    setHistory([]);
    setHistoryLoading(true);
    try {
      const result = await api<{ history: HistoryRow[] }>(
        `/admin/access/users/${target.user_id}/history`,
      );
      setHistory(result.history);
    } catch (e: any) {
      setError(e?.message || "Could not load access history.");
    } finally {
      setHistoryLoading(false);
    }
  };

  const runConfirmation = async () => {
    if (!confirm || (confirm.needsReason && !confirmReason.trim())) return;
    setBusy(true);
    setError("");
    try {
      await confirm.run(confirmReason.trim());
      setConfirm(null);
      setConfirmReason("");
    } catch (e: any) {
      setError(e?.message || "Action failed.");
    } finally {
      setBusy(false);
    }
  };

  if (permissionDenied) {
    return (
      <SafeAreaView style={styles.safe} testID="access-console-denied">
        <View style={styles.centerState}>
          <Ionicons name="lock-closed-outline" size={34} color={theme.colors.danger} />
          <H2 style={{ marginTop: 12 }}>Permission denied</H2>
          <Muted style={{ textAlign: "center", marginTop: 6 }}>
            Only an active Admin or Director can open the Access Console.
          </Muted>
          <Btn title="Go back" variant="outline" onPress={() => router.back()} style={{ marginTop: 16 }} />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]} testID="access-console-screen">
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconButton} testID="access-console-back">
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.headerTitle}>Admin Access Console</Text>
          <Text style={styles.headerSubtitle}>Identity, roles and session control</Text>
        </View>
        <TouchableOpacity onPress={() => load(true)} style={styles.iconButton} testID="access-console-refresh">
          <Ionicons name="refresh-outline" size={22} color={theme.colors.primary} />
        </TouchableOpacity>
      </View>

      {notice ? (
        <View style={styles.successBanner} testID="access-console-success">
          <Ionicons name="checkmark-circle" size={18} color={theme.colors.success} />
          <Text style={styles.successText}>{notice}</Text>
        </View>
      ) : null}
      {error ? (
        <View style={styles.errorBanner} testID="access-console-error">
          <Ionicons name="alert-circle" size={18} color={theme.colors.danger} />
          <Text style={styles.errorText}>{error}</Text>
          <TouchableOpacity onPress={() => setError("")}>
            <Ionicons name="close" size={18} color={theme.colors.danger} />
          </TouchableOpacity>
        </View>
      ) : null}

      {loading ? (
        <View style={styles.centerState} testID="access-console-loading">
          <ActivityIndicator color={theme.colors.primary} size="large" />
          <Muted style={{ marginTop: 10 }}>Loading access controls…</Muted>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} />}
        >
          <View style={[styles.hero, compact && styles.heroCompact]}>
            <View style={{ flex: 1, minWidth: compact ? 0 : 360 }}>
              <Label>SECURITY ADMINISTRATION</Label>
              <H1>Access overview</H1>
              <Muted style={{ marginTop: 6 }}>
                Backend policy remains authoritative. Director protections cannot be overridden here.
              </Muted>
            </View>
            <Btn
              title="Invite company user"
              variant="action"
              testID="access-invite-open"
              icon={<Ionicons name="mail-unread-outline" size={18} color="#fff" />}
              onPress={() => {
                setRequestToApprove(null);
                setInviteEmail("");
                setInviteRole("site_engineer");
                setInviteOpen(true);
              }}
              style={compact ? { width: "100%", marginTop: 14 } : undefined}
            />
          </View>

          <View style={[styles.stats, compact && styles.statsCompact]}>
            <SummaryStat icon="hourglass-outline" value={requests.length} label="Pending requests" />
            <SummaryStat icon="mail-outline" value={invitations.length + inactive.length} label="Invited / inactive" />
            <SummaryStat icon="people-outline" value={users.length} label="Managed users" />
          </View>

          <SectionCard
            title="Pending access requests"
            subtitle="Uninvited sign-in attempts awaiting approval or rejection."
            icon="person-add-outline"
            count={requests.length}
            testID="pending-requests-section"
          >
            {requests.length === 0 ? (
              <Empty title="No pending access requests" subtitle="New company sign-in requests will appear here." />
            ) : requests.map((request) => (
              <AccessRow
                key={request.request_id}
                compact={compact}
                title={request.name || request.email}
                subtitle={`${request.email} · ${request.attempt_count || 1} attempt(s)`}
                badge="Pending"
                badgeTone="warning"
                actions={(
                  <>
                    <SmallAction icon="checkmark" label="Approve" testID={`approve-${request.request_id}`} onPress={() => openApprove(request)} />
                    <SmallAction icon="close" label="Reject" danger testID={`reject-${request.request_id}`} onPress={() => rejectRequest(request)} />
                  </>
                )}
              />
            ))}
          </SectionCard>

          <SectionCard
            title="Invited / inactive users"
            subtitle="Outstanding invitations and accepted accounts awaiting activation."
            icon="mail-open-outline"
            count={invitations.length + inactive.length}
            testID="invited-inactive-section"
          >
            {invitations.length === 0 && inactive.length === 0 ? (
              <Empty title="No invited or inactive users" subtitle="Use Invite company user to begin onboarding." />
            ) : null}
            {invitations.map((invitation) => (
              <AccessRow
                key={invitation.invitation_id}
                compact={compact}
                title={invitation.email}
                subtitle={`Invited as ${roleLabel(invitation.role)} · expires ${when(invitation.expires_at)}`}
                roles={[invitation.role]}
                badge="Invited"
                badgeTone="info"
                actions={(
                  <SmallAction icon="trash-outline" label="Revoke" danger onPress={() => revokeInvitation(invitation)} />
                )}
              />
            ))}
            {inactive.map((target) => (
              <AccessRow
                key={target.user_id}
                compact={compact}
                title={target.name || target.email}
                subtitle={`${target.email} · waiting since ${when(target.pending_since)}`}
                badge="Awaiting activation"
                badgeTone="warning"
                actions={(
                  <SmallAction
                    icon="power-outline"
                    label="Activate"
                    testID={`activate-${target.user_id}`}
                    onPress={() => openActivate(target)}
                  />
                )}
              />
            ))}
          </SectionCard>

          <SectionCard
            title="Active / deactivated users"
            subtitle="Manage roles, account status, sessions and access history."
            icon="shield-checkmark-outline"
            count={users.length}
            testID="active-users-section"
          >
            {users.length === 0 ? (
              <Empty title="No managed users" subtitle="Activated and deactivated accounts appear here." />
            ) : users.map((target) => {
              const targetRoles = effectiveRoles(target);
              const targetIsDirector = targetRoles.includes("director");
              const self = target.user_id === user?.user_id;
              const canMutateDirector = !targetIsDirector || actorIsDirector;
              return (
                <AccessRow
                  key={target.user_id}
                  compact={compact}
                  title={target.name || target.email}
                  subtitle={`${target.email} · ${target.is_active ? "active" : `deactivated ${when(target.deactivated_at)}`}`}
                  roles={targetRoles}
                  badge={target.is_active ? "Active" : "Deactivated"}
                  badgeTone={target.is_active ? "success" : "neutral"}
                  actions={(
                    <>
                      {!self && canMutateDirector ? (
                        <SmallAction icon="key-outline" label="Roles" testID={`roles-${target.user_id}`} onPress={() => openRoles(target)} />
                      ) : null}
                      {target.is_active && !self && canMutateDirector ? (
                        <SmallAction icon="person-remove-outline" label="Deactivate" danger testID={`deactivate-${target.user_id}`} onPress={() => deactivate(target)} />
                      ) : null}
                      {!target.is_active && !self && canMutateDirector ? (
                        <SmallAction icon="power-outline" label="Activate" onPress={() => openActivate(target)} />
                      ) : null}
                      {canMutateDirector ? (
                        <SmallAction icon="log-out-outline" label="Sessions" danger onPress={() => revokeSessions(target)} />
                      ) : null}
                      <SmallAction icon="time-outline" label="History" testID={`history-${target.user_id}`} onPress={() => showHistory(target)} />
                    </>
                  )}
                />
              );
            })}
          </SectionCard>
        </ScrollView>
      )}

      <Modal visible={inviteOpen} transparent animationType="fade" onRequestClose={() => setInviteOpen(false)}>
        <ModalFrame title={requestToApprove ? "Approve access request" : "Invite company user"} onClose={() => setInviteOpen(false)}>
          <Input
            label="Company email"
            value={inviteEmail}
            onChangeText={setInviteEmail}
            autoCapitalize="none"
            keyboardType="email-address"
            editable={!requestToApprove}
            placeholder="name@vasuinfosec.com"
            testID="access-invite-email"
          />
          <Label>INITIAL ROLE</Label>
          <RolePicker roles={assignableRoles} selected={[inviteRole]} onToggle={(role) => setInviteRole(role)} single />
          {!actorIsDirector ? <Muted style={{ marginTop: 8 }}>Director authority can only be granted by an active Director.</Muted> : null}
          <Btn title={requestToApprove ? "Approve & invite" : "Send invitation"} onPress={submitInvitation} disabled={busy} style={{ marginTop: 16 }} testID="access-invite-submit" />
        </ModalFrame>
      </Modal>

      <Modal visible={!!activateUser} transparent animationType="fade" onRequestClose={() => setActivateUser(null)}>
        <ModalFrame title={`Activate ${activateUser?.name || "user"}`} onClose={() => setActivateUser(null)}>
          <Muted>Select the initial role. Additional roles can be assigned after activation.</Muted>
          <View style={{ marginTop: 14 }}>
            <RolePicker roles={assignableRoles} selected={[inviteRole]} onToggle={(role) => setInviteRole(role)} single />
          </View>
          <Btn title="Activate user" onPress={() => activateUser && activate(activateUser, inviteRole)} disabled={busy} style={{ marginTop: 16 }} />
        </ModalFrame>
      </Modal>

      <Modal visible={!!roleUser} transparent animationType="fade" onRequestClose={() => setRoleUser(null)}>
        <ModalFrame title={`Roles — ${roleUser?.name || "user"}`} onClose={() => setRoleUser(null)}>
          <Muted>Select one or more roles. Removing Director from the last active Director is blocked by the backend.</Muted>
          <View style={{ marginTop: 14 }}>
            <RolePicker roles={assignableRoles} selected={selectedRoles} onToggle={toggleRole} />
          </View>
          <Btn title="Save roles" onPress={saveRoles} disabled={busy || selectedRoles.length === 0} style={{ marginTop: 16 }} testID="access-roles-save" />
        </ModalFrame>
      </Modal>

      <Modal visible={!!confirm} transparent animationType="fade" onRequestClose={() => setConfirm(null)}>
        <ModalFrame title={confirm?.title || "Confirm action"} onClose={() => setConfirm(null)}>
          <Muted>{confirm?.message}</Muted>
          {confirm?.needsReason ? (
            <Input label="Reason" value={confirmReason} onChangeText={setConfirmReason} placeholder="Required for the access audit" style={{ marginTop: 14 }} />
          ) : null}
          <Btn
            title={confirm?.actionLabel || "Confirm"}
            variant={confirm?.danger ? "danger" : "primary"}
            onPress={runConfirmation}
            disabled={busy || (!!confirm?.needsReason && !confirmReason.trim())}
            style={{ marginTop: 16 }}
            testID="access-confirm-submit"
          />
        </ModalFrame>
      </Modal>

      <Modal visible={!!historyUser} transparent animationType="fade" onRequestClose={() => setHistoryUser(null)}>
        <ModalFrame title={`Access history — ${historyUser?.name || "user"}`} onClose={() => setHistoryUser(null)} wide>
          {historyLoading ? <ActivityIndicator color={theme.colors.primary} /> : null}
          {!historyLoading && history.length === 0 ? <Empty title="No access history" /> : null}
          <ScrollView style={{ maxHeight: 430 }}>
            {history.map((row, index) => (
              <View key={row.audit_id || `${row.action}-${index}`} style={styles.historyRow}>
                <View style={styles.historyDot} />
                <View style={{ flex: 1 }}>
                  <Text style={{ fontWeight: "700", color: theme.colors.text }}>{roleLabel(row.action)}</Text>
                  <Muted>{when(row.timestamp)} · by {row.user_name || "System"}</Muted>
                </View>
              </View>
            ))}
          </ScrollView>
        </ModalFrame>
      </Modal>
    </SafeAreaView>
  );
}

function SummaryStat({ icon, value, label }: { icon: keyof typeof Ionicons.glyphMap; value: number; label: string }) {
  return (
    <View style={styles.stat}>
      <View style={styles.statIcon}><Ionicons name={icon} size={20} color={theme.colors.primary} /></View>
      <View><Text style={styles.statValue}>{value}</Text><Text style={styles.statLabel}>{label}</Text></View>
    </View>
  );
}

function SectionCard({ title, subtitle, icon, count, children, testID }: {
  title: string; subtitle: string; icon: keyof typeof Ionicons.glyphMap;
  count: number; children: React.ReactNode; testID: string;
}) {
  return (
    <Card style={styles.section} testID={testID}>
      <View style={styles.sectionHeader}>
        <View style={styles.sectionIcon}><Ionicons name={icon} size={21} color={theme.colors.primary} /></View>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <H2>{title}</H2><View style={styles.countBadge}><Text style={styles.countText}>{count}</Text></View>
          </View>
          <Muted style={{ marginTop: 2 }}>{subtitle}</Muted>
        </View>
      </View>
      <View style={{ marginTop: 12 }}>{children}</View>
    </Card>
  );
}

function AccessRow({ compact, title, subtitle, roles = [], badge, badgeTone, actions }: {
  compact: boolean; title: string; subtitle: string; roles?: string[];
  badge: string; badgeTone: "warning" | "info" | "success" | "neutral";
  actions: React.ReactNode;
}) {
  return (
    <View style={[styles.accessRow, compact && styles.accessRowCompact]}>
      <View style={{ flex: 1, minWidth: 190 }}>
        <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 7 }}>
          <Text style={styles.rowTitle}>{title}</Text>
          <StatusBadge label={badge} tone={badgeTone} />
        </View>
        <Text style={styles.rowSubtitle}>{subtitle}</Text>
        {roles.length ? (
          <View style={styles.roleList}>
            {roles.map((role) => <View key={role} style={styles.roleBadge}><Text style={styles.roleBadgeText}>{roleLabel(role)}</Text></View>)}
          </View>
        ) : null}
      </View>
      <View style={[styles.actions, compact && { width: "100%", justifyContent: "flex-start" }]}>{actions}</View>
    </View>
  );
}

function StatusBadge({ label, tone }: { label: string; tone: "warning" | "info" | "success" | "neutral" }) {
  const colors = {
    warning: ["#FFFBEB", "#92400E", "#F59E0B"],
    info: ["#EFF6FF", "#1E40AF", "#60A5FA"],
    success: ["#ECFDF5", "#065F46", "#34D399"],
    neutral: ["#F1F5F9", "#475569", "#CBD5E1"],
  }[tone];
  return <View style={[styles.statusBadge, { backgroundColor: colors[0], borderColor: colors[2] }]}><Text style={[styles.statusText, { color: colors[1] }]}>{label}</Text></View>;
}

function SmallAction({ icon, label, onPress, danger, testID }: {
  icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void;
  danger?: boolean; testID?: string;
}) {
  return (
    <TouchableOpacity onPress={onPress} style={[styles.smallAction, danger && styles.smallActionDanger]} testID={testID}>
      <Ionicons name={icon} size={15} color={danger ? theme.colors.danger : theme.colors.primary} />
      <Text style={[styles.smallActionText, danger && { color: theme.colors.danger }]}>{label}</Text>
    </TouchableOpacity>
  );
}

function RolePicker({ roles, selected, onToggle, single }: {
  roles: readonly string[]; selected: string[]; onToggle: (role: string) => void; single?: boolean;
}) {
  return (
    <View style={styles.rolePicker}>
      {roles.map((role) => {
        const active = selected.includes(role);
        return (
          <TouchableOpacity
            key={role}
            onPress={() => onToggle(role)}
            style={[styles.roleChoice, active && styles.roleChoiceActive]}
            testID={`access-role-${role}`}
          >
            <Ionicons name={active ? "checkmark-circle" : single ? "ellipse-outline" : "square-outline"} size={17} color={active ? "#fff" : theme.colors.textMuted} />
            <Text style={[styles.roleChoiceText, active && { color: "#fff" }]}>{roleLabel(role)}</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

function ModalFrame({ title, onClose, children, wide }: {
  title: string; onClose: () => void; children: React.ReactNode; wide?: boolean;
}) {
  return (
    <View style={styles.modalBackdrop}>
      <View style={[styles.modalCard, wide && { maxWidth: 700 }]}>
        <View style={styles.modalHeader}>
          <Text style={styles.modalTitle}>{title}</Text>
          <TouchableOpacity onPress={onClose} style={styles.iconButton}><Ionicons name="close" size={21} color={theme.colors.text} /></TouchableOpacity>
        </View>
        {children}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.colors.surface },
  header: { minHeight: 68, paddingHorizontal: 16, flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: "#fff", borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  headerTitle: { fontSize: 18, fontWeight: "800", color: theme.colors.text },
  headerSubtitle: { fontSize: 11, color: theme.colors.textMuted, marginTop: 1 },
  iconButton: { width: 40, height: 40, alignItems: "center", justifyContent: "center", borderRadius: 8 },
  content: { width: "100%", maxWidth: 1180, alignSelf: "center", padding: 18, paddingBottom: 52 },
  hero: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 24, paddingVertical: 10 },
  heroCompact: { flexDirection: "column", alignItems: "stretch", gap: 0 },
  stats: { flexDirection: "row", gap: 10, marginTop: 12, marginBottom: 4 },
  statsCompact: { flexWrap: "wrap" },
  stat: { flex: 1, minWidth: 190, flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: "#fff", borderRadius: 8 },
  statIcon: { width: 40, height: 40, borderRadius: 8, backgroundColor: "#EEF2FF", alignItems: "center", justifyContent: "center" },
  statValue: { fontSize: 22, fontWeight: "800", color: theme.colors.text },
  statLabel: { fontSize: 11, color: theme.colors.textMuted, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.6 },
  section: { marginTop: 12, padding: 0, overflow: "hidden" },
  sectionHeader: { flexDirection: "row", gap: 12, alignItems: "center", padding: 16, backgroundColor: theme.colors.surface },
  sectionIcon: { width: 42, height: 42, borderRadius: 8, alignItems: "center", justifyContent: "center", backgroundColor: "#EEF2FF" },
  countBadge: { minWidth: 24, height: 24, paddingHorizontal: 6, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: theme.colors.primary },
  countText: { color: "#fff", fontSize: 11, fontWeight: "800" },
  accessRow: { paddingHorizontal: 16, paddingVertical: 14, borderTopWidth: 1, borderTopColor: theme.colors.border, flexDirection: "row", alignItems: "center", gap: 14 },
  accessRowCompact: { flexDirection: "column", alignItems: "stretch" },
  rowTitle: { fontSize: 14, fontWeight: "800", color: theme.colors.text },
  rowSubtitle: { fontSize: 12, color: theme.colors.textMuted, marginTop: 3 },
  statusBadge: { borderRadius: 999, borderWidth: 1, paddingHorizontal: 8, paddingVertical: 3 },
  statusText: { fontSize: 9, fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.5 },
  roleList: { flexDirection: "row", flexWrap: "wrap", gap: 5, marginTop: 8 },
  roleBadge: { backgroundColor: theme.colors.surface2, borderRadius: 4, paddingHorizontal: 7, paddingVertical: 3 },
  roleBadgeText: { fontSize: 9, color: theme.colors.textSecondary, fontWeight: "700", textTransform: "uppercase" },
  actions: { flexDirection: "row", flexWrap: "wrap", justifyContent: "flex-end", gap: 6 },
  smallAction: { minHeight: 34, flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 9, borderRadius: 6, backgroundColor: "#EEF2FF", borderWidth: 1, borderColor: "#C7D2FE" },
  smallActionDanger: { backgroundColor: "#FEF2F2", borderColor: "#FECACA" },
  smallActionText: { color: theme.colors.primary, fontSize: 11, fontWeight: "800" },
  successBanner: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 18, paddingVertical: 10, backgroundColor: "#ECFDF5", borderBottomWidth: 1, borderBottomColor: "#A7F3D0" },
  successText: { color: "#065F46", fontSize: 13, fontWeight: "700", flex: 1 },
  errorBanner: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 18, paddingVertical: 10, backgroundColor: "#FEF2F2", borderBottomWidth: 1, borderBottomColor: "#FECACA" },
  errorText: { color: "#991B1B", fontSize: 13, fontWeight: "700", flex: 1 },
  centerState: { flex: 1, minHeight: 300, alignItems: "center", justifyContent: "center", padding: 24 },
  modalBackdrop: { flex: 1, backgroundColor: "rgba(15,23,42,0.52)", padding: 16, alignItems: "center", justifyContent: "center" },
  modalCard: { width: "100%", maxWidth: 560, backgroundColor: "#fff", borderRadius: 12, padding: 20, shadowColor: "#000", shadowOpacity: 0.2, shadowRadius: 18, elevation: 8 },
  modalHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 16 },
  modalTitle: { flex: 1, fontSize: 18, fontWeight: "800", color: theme.colors.text },
  rolePicker: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  roleChoice: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 38, paddingHorizontal: 11, borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, backgroundColor: "#fff" },
  roleChoiceActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  roleChoiceText: { fontSize: 12, fontWeight: "700", color: theme.colors.textSecondary },
  historyRow: { flexDirection: "row", alignItems: "flex-start", gap: 10, paddingVertical: 10, borderTopWidth: 1, borderTopColor: theme.colors.border },
  historyDot: { width: 9, height: 9, borderRadius: 5, backgroundColor: theme.colors.primary, marginTop: 5 },
});
