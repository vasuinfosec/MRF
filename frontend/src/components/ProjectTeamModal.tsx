import React, { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal, TextInput } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { theme } from "@/src/theme";
import { Btn } from "@/src/components/ui";

type Props = {
  projectId: string;
  onClose: () => void;
  onChanged?: () => void;
};

export default function ProjectTeamModal({ projectId, onClose, onChanged }: Props) {
  const insets = useSafeAreaInsets();
  const [project, setProject] = useState<any>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [teamSe, setTeamSe] = useState<string[]>([]);
  const [teamPm, setTeamPm] = useState<string[]>([]);
  const [newSiteName, setNewSiteName] = useState("");
  const [newSiteLoc, setNewSiteLoc] = useState("");
  const [siteExpand, setSiteExpand] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [all, us] = await Promise.all([api<any[]>("/projects?all=1"), api<any[]>("/users")]);
      const p = all.find((x) => x.project_id === projectId);
      setProject(p);
      setUsers(us);
      if (p) {
        setTeamSe(p.site_engineers || []);
        setTeamPm(p.project_managers || []);
      }
    } catch (_e) { /* noop */ }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const engineers = users.filter((u) => u.role === "site_engineer" || u.role === "store" || u.role === "pm" || u.role === "director" || u.role === "admin");
  const pms = users.filter((u) => u.role === "pm" || u.role === "gm" || u.role === "director" || u.role === "admin");

  const toggle = (list: string[], setList: (v: string[]) => void, uid: string) => {
    setList(list.includes(uid) ? list.filter((x) => x !== uid) : [...list, uid]);
  };

  const saveTeam = async () => {
    setSaving(true);
    try {
      await api(`/projects/${projectId}/team`, { method: "POST",
        body: { site_engineers: teamSe, project_managers: teamPm } });
      if (onChanged) onChanged();
      onClose();
    } catch (_e) { /* noop */ }
    setSaving(false);
  };

  const addSite = async () => {
    if (!newSiteName.trim()) return;
    await api(`/projects/${projectId}/sites`, { method: "POST",
      body: { name: newSiteName.trim(), location: newSiteLoc.trim(), site_engineers: [] } });
    setNewSiteName(""); setNewSiteLoc("");
    load(); if (onChanged) onChanged();
  };

  const toggleSiteEngineer = async (site: any, uid: string) => {
    const cur: string[] = site.site_engineers || [];
    const next = cur.includes(uid) ? cur.filter((x) => x !== uid) : [...cur, uid];
    await api(`/projects/${projectId}/sites/${site.site_id}`, {
      method: "PUT", body: { site_engineers: next },
    });
    load(); if (onChanged) onChanged();
  };

  const removeSite = async (site_id: string) => {
    await api(`/projects/${projectId}/sites/${site_id}`, { method: "DELETE" });
    load(); if (onChanged) onChanged();
  };

  if (!project) return null;

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <View style={s.modalBg}>
        <View style={[s.modal, { marginBottom: insets.bottom + 16, maxHeight: "88%" }]}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <View style={{ flex: 1 }}>
              <Text style={{ fontWeight: "800", fontSize: 16 }}>Project Team</Text>
              <Text style={{ fontSize: 12, color: theme.colors.textMuted, marginTop: 2 }}>
                {project.code} — {project.name}
              </Text>
            </View>
            <TouchableOpacity testID="close-team-btn" onPress={onClose}>
              <Ionicons name="close" size={22} />
            </TouchableOpacity>
          </View>
          <ScrollView style={{ marginTop: 6 }}>
            <Text style={s.head}>Site Engineers</Text>
            {engineers.map((eu) => (
              <TouchableOpacity key={eu.user_id} testID={`toggle-se-${eu.email}`}
                onPress={() => toggle(teamSe, setTeamSe, eu.user_id)} style={s.row}>
                <View style={{ flex: 1 }}>
                  <Text style={{ fontWeight: "600" }}>{eu.name}</Text>
                  <Text style={{ fontSize: 11, color: theme.colors.textMuted }}>{eu.email}</Text>
                </View>
                <View style={[s.checkbox, { backgroundColor: teamSe.includes(eu.user_id) ? theme.colors.primary : "#fff", borderColor: teamSe.includes(eu.user_id) ? theme.colors.primary : theme.colors.borderStrong }]}>
                  {teamSe.includes(eu.user_id) ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
                </View>
              </TouchableOpacity>
            ))}

            <Text style={[s.head, { marginTop: 12 }]}>Project Managers</Text>
            {pms.map((pu) => (
              <TouchableOpacity key={pu.user_id} testID={`toggle-pm-${pu.email}`}
                onPress={() => toggle(teamPm, setTeamPm, pu.user_id)} style={s.row}>
                <View style={{ flex: 1 }}>
                  <Text style={{ fontWeight: "600" }}>{pu.name}</Text>
                  <Text style={{ fontSize: 11, color: theme.colors.textMuted }}>{pu.email}</Text>
                </View>
                <View style={[s.checkbox, { backgroundColor: teamPm.includes(pu.user_id) ? theme.colors.primary : "#fff", borderColor: teamPm.includes(pu.user_id) ? theme.colors.primary : theme.colors.borderStrong }]}>
                  {teamPm.includes(pu.user_id) ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
                </View>
              </TouchableOpacity>
            ))}

            <Text style={[s.head, { marginTop: 16 }]}>Sub-Sites</Text>
            {(project.sites || []).filter((x: any) => x.active !== false).map((site: any) => (
              <View key={site.site_id} style={s.siteBox}>
                <View style={{ flexDirection: "row", alignItems: "center" }}>
                  <TouchableOpacity onPress={() => setSiteExpand(siteExpand === site.site_id ? null : site.site_id)} style={{ flex: 1 }}>
                    <Text style={{ fontWeight: "700" }}>{site.name}</Text>
                    {site.location ? <Text style={{ fontSize: 11, color: theme.colors.textMuted }}>{site.location}</Text> : null}
                    <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 2 }}>
                      {(site.site_engineers || []).length} engineer(s)
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity testID={`remove-site-${site.site_id}`} onPress={() => removeSite(site.site_id)} style={{ padding: 6 }}>
                    <Ionicons name="trash-outline" size={16} color={theme.colors.danger} />
                  </TouchableOpacity>
                </View>
                {siteExpand === site.site_id ? (
                  <View style={{ marginTop: 8, paddingTop: 8, borderTopWidth: 1, borderTopColor: theme.colors.border }}>
                    {engineers.map((eu) => (
                      <TouchableOpacity key={eu.user_id} onPress={() => toggleSiteEngineer(site, eu.user_id)} style={s.row}>
                        <View style={{ flex: 1 }}>
                          <Text style={{ fontWeight: "600", fontSize: 13 }}>{eu.name}</Text>
                          <Text style={{ fontSize: 10, color: theme.colors.textMuted }}>{eu.email}</Text>
                        </View>
                        <View style={[s.checkbox, {
                          backgroundColor: (site.site_engineers || []).includes(eu.user_id) ? theme.colors.primary : "#fff",
                          borderColor: (site.site_engineers || []).includes(eu.user_id) ? theme.colors.primary : theme.colors.borderStrong,
                        }]}>
                          {(site.site_engineers || []).includes(eu.user_id) ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
                        </View>
                      </TouchableOpacity>
                    ))}
                  </View>
                ) : null}
              </View>
            ))}
            <View style={s.addSite}>
              <TextInput testID="new-site-name" value={newSiteName} onChangeText={setNewSiteName}
                placeholder="New sub-site name (e.g. Tower A)" style={s.inp} />
              <TextInput testID="new-site-loc" value={newSiteLoc} onChangeText={setNewSiteLoc}
                placeholder="Location (optional)" style={[s.inp, { marginTop: 6 }]} />
              <TouchableOpacity testID="add-site-btn" onPress={addSite} style={s.addBtn}>
                <Ionicons name="add-circle-outline" size={16} color="#fff" />
                <Text style={{ color: "#fff", fontWeight: "700", marginLeft: 4, fontSize: 12 }}>Add Sub-Site</Text>
              </TouchableOpacity>
            </View>
          </ScrollView>
          <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
            <View style={{ flex: 1 }}><Btn title="Close" variant="outline" onPress={onClose} /></View>
            <View style={{ flex: 1 }}>
              <Btn testID="save-team-btn" title={saving ? "Saving…" : "Save Team"} variant="action" onPress={saveTeam} disabled={saving} />
            </View>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modal: { backgroundColor: "#fff", borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 20 },
  head: { fontSize: 11, fontWeight: "800", color: theme.colors.textMuted, textTransform: "uppercase", letterSpacing: 1.5, marginBottom: 4 },
  row: { flexDirection: "row", alignItems: "center", paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  checkbox: { width: 22, height: 22, borderWidth: 2, borderRadius: 4, alignItems: "center", justifyContent: "center" },
  siteBox: { padding: 10, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 6, marginBottom: 8 },
  addSite: { padding: 10, borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, marginTop: 6, borderStyle: "dashed" },
  inp: { borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 6, minHeight: 40, paddingHorizontal: 10, backgroundColor: "#fff", fontSize: 13 },
  addBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: theme.colors.primary, paddingVertical: 10, borderRadius: 6, marginTop: 8 },
});
