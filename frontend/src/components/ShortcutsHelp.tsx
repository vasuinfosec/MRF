import React from "react";
import { View, Text, StyleSheet, Modal, TouchableOpacity } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { theme } from "@/src/theme";

const SHORTCUTS: { keys: string; label: string }[] = [
  { keys: "/", label: "Focus search" },
  { keys: "?", label: "Show this help" },
  { keys: "g  h", label: "Go to Home" },
  { keys: "g  m", label: "Go to MRF list" },
  { keys: "g  p", label: "Go to PO list" },
  { keys: "g  b", label: "Go to Billing" },
  { keys: "g  s", label: "Go to Masters" },
  { keys: "g  a", label: "Go to Admin · Access" },
  { keys: "g  u", label: "Go to Admin · UOM" },
  { keys: "g  c", label: "Go to Admin · Categories" },
  { keys: "Esc", label: "Close dialogs" },
];

export function ShortcutsHelp({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <TouchableOpacity style={styles.bg} activeOpacity={1} onPress={onClose}>
        <View style={styles.card} onStartShouldSetResponder={() => true}>
          <View style={styles.header}>
            <Text style={styles.title}>Keyboard shortcuts</Text>
            <TouchableOpacity onPress={onClose} style={{ padding: 4 }}>
              <Ionicons name="close" size={22} color={theme.colors.text} />
            </TouchableOpacity>
          </View>
          <View style={{ height: 8 }} />
          {SHORTCUTS.map((s) => (
            <View key={s.keys} style={styles.row}>
              <View style={styles.kbdWrap}>
                {s.keys.split("  ").map((k, i) => (
                  <React.Fragment key={i}>
                    {i > 0 ? <Text style={styles.then}>then</Text> : null}
                    <Text style={styles.kbd}>{k}</Text>
                  </React.Fragment>
                ))}
              </View>
              <Text style={styles.desc}>{s.label}</Text>
            </View>
          ))}
          <Text style={styles.hint}>Tip: shortcuts are ignored while typing in a field.</Text>
        </View>
      </TouchableOpacity>
    </Modal>
  );
}

const styles = StyleSheet.create({
  bg: { flex: 1, backgroundColor: "rgba(15,23,42,0.55)", alignItems: "center", justifyContent: "center", padding: 24 },
  card: {
    width: "100%", maxWidth: 480,
    backgroundColor: "#fff", borderRadius: 14, padding: 20,
    shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 20, shadowOffset: { width: 0, height: 8 }, elevation: 12,
  },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  title: { fontSize: 18, fontWeight: "800", color: theme.colors.text },
  row: { flexDirection: "row", alignItems: "center", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  kbdWrap: { flexDirection: "row", alignItems: "center", minWidth: 130 },
  kbd: {
    fontFamily: "monospace", fontSize: 12, fontWeight: "700",
    backgroundColor: "#F1F5F9", borderWidth: 1, borderColor: "#CBD5E1",
    borderRadius: 4, paddingHorizontal: 8, paddingVertical: 3, color: theme.colors.text,
  },
  then: { marginHorizontal: 6, color: theme.colors.textMuted, fontSize: 11 },
  desc: { flex: 1, marginLeft: 12, color: theme.colors.text, fontSize: 14 },
  hint: { marginTop: 12, fontSize: 11, color: theme.colors.textMuted, textAlign: "center" },
});
