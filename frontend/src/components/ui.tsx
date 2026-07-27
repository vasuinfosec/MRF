import React from "react";
import { View, Text, TouchableOpacity, StyleSheet, TextInput, ViewStyle, TextStyle, ActivityIndicator } from "react-native";
import { theme, statusLabel } from "@/src/theme";

export function Card({ children, style, testID }: { children: React.ReactNode; style?: ViewStyle; testID?: string }) {
  return <View style={[s.card, style]} testID={testID}>{children}</View>;
}

export function H1({ children, style }: { children: React.ReactNode; style?: TextStyle }) {
  return <Text style={[s.h1, style]}>{children}</Text>;
}
export function H2({ children, style }: { children: React.ReactNode; style?: TextStyle }) {
  return <Text style={[s.h2, style]}>{children}</Text>;
}
export function Label({ children, style }: { children: React.ReactNode; style?: TextStyle }) {
  return <Text style={[s.label, style]}>{children}</Text>;
}
export function Muted({ children, style }: { children: React.ReactNode; style?: TextStyle }) {
  return <Text style={[s.muted, style]}>{children}</Text>;
}
export function Body({ children, style }: { children: React.ReactNode; style?: TextStyle }) {
  return <Text style={[s.body, style]}>{children}</Text>;
}

export function Btn({ title, onPress, variant = "primary", testID, disabled, style, icon }: {
  title: string; onPress?: () => void; variant?: "primary" | "action" | "outline" | "ghost" | "danger";
  testID?: string; disabled?: boolean; style?: ViewStyle; icon?: React.ReactNode;
}) {
  const bg = variant === "primary" ? theme.colors.primary
    : variant === "action" ? theme.colors.action
    : variant === "danger" ? theme.colors.danger
    : variant === "outline" ? "transparent" : "transparent";
  const color = variant === "outline" || variant === "ghost" ? theme.colors.text : "#fff";
  const border = variant === "outline" ? theme.colors.borderStrong : "transparent";
  return (
    <TouchableOpacity
      testID={testID}
      onPress={onPress}
      disabled={disabled}
      style={[
        s.btn,
        { backgroundColor: bg, borderColor: border, borderWidth: variant === "outline" ? 1 : 0, opacity: disabled ? 0.5 : 1 },
        style,
      ]}
    >
      {icon}
      <Text style={[s.btnText, { color, marginLeft: icon ? 6 : 0 }]}>{title}</Text>
    </TouchableOpacity>
  );
}

export function Input(props: React.ComponentProps<typeof TextInput> & { label?: string; testID?: string }) {
  const { label, style, testID, ...rest } = props;
  return (
    <View style={{ marginBottom: theme.space.md }}>
      {label ? <Label>{label}</Label> : null}
      <TextInput
        testID={testID}
        placeholderTextColor={theme.colors.textMuted}
        style={[s.input, style]}
        {...rest}
      />
    </View>
  );
}

export function Pill({ status }: { status: string }) {
  const c = theme.status[status] || theme.status.draft;
  return (
    <View style={[s.pill, { backgroundColor: c.bg, borderColor: c.border }]}>
      <Text style={[s.pillText, { color: c.text }]}>{statusLabel(status)}</Text>
    </View>
  );
}

export function Row({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  return <View style={[{ flexDirection: "row", alignItems: "center" }, style]}>{children}</View>;
}

export function Loader() {
  return <View style={{ padding: 24, alignItems: "center" }}><ActivityIndicator color={theme.colors.primary} /></View>;
}

export function Empty({ msg, title, subtitle, testID }: { msg?: string; title?: string; subtitle?: string; testID?: string }) {
  const primary = title || msg || "Nothing here yet.";
  return (
    <View style={s.empty} testID={testID}>
      <Text style={{ color: theme.colors.text, textAlign: "center", fontWeight: "600", marginBottom: subtitle ? 6 : 0 }}>{primary}</Text>
      {subtitle ? <Text style={{ color: theme.colors.textMuted, textAlign: "center", fontSize: 12 }}>{subtitle}</Text> : null}
    </View>
  );
}

export function Stat({ label, value, testID, tone }: { label: string; value: string | number; testID?: string; tone?: "primary" | "action" | "success" }) {
  const color = tone === "action" ? theme.colors.action : tone === "success" ? theme.colors.success : theme.colors.primary;
  return (
    <View style={s.stat} testID={testID}>
      <Text style={s.statValue as any}>
        <Text style={{ color }}>{value}</Text>
      </Text>
      <Text style={s.statLabel}>{label}</Text>
    </View>
  );
}

export function SectionHeader({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8, marginTop: 16 }}>
      <H2>{title}</H2>
      {right}
    </View>
  );
}

export const s = StyleSheet.create({
  card: {
    backgroundColor: theme.colors.bg,
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.md,
    padding: theme.space.lg,
  },
  h1: { fontSize: 26, fontWeight: "800", color: theme.colors.text, letterSpacing: -0.5 },
  h2: { fontSize: 18, fontWeight: "700", color: theme.colors.text },
  label: { fontSize: 11, fontWeight: "700", textTransform: "uppercase", letterSpacing: 1.5, color: theme.colors.textMuted, marginBottom: 4 },
  muted: { fontSize: 13, color: theme.colors.textMuted },
  body: { fontSize: 14, color: theme.colors.text },
  btn: { minHeight: 48, borderRadius: theme.radius.md, alignItems: "center", justifyContent: "center", flexDirection: "row", paddingHorizontal: 16, paddingVertical: 12 },
  btnText: { fontWeight: "700", fontSize: 14, letterSpacing: 0.3 },
  input: {
    borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: theme.radius.md,
    paddingHorizontal: 12, paddingVertical: 12, minHeight: 48, fontSize: 15, color: theme.colors.text, backgroundColor: theme.colors.bg,
  },
  pill: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, borderWidth: 1, alignSelf: "flex-start",
  },
  pillText: { fontSize: 10, fontWeight: "700", letterSpacing: 0.8, textTransform: "uppercase" },
  empty: { padding: 32, alignItems: "center", justifyContent: "center", borderWidth: 1, borderStyle: "dashed", borderColor: theme.colors.border, borderRadius: theme.radius.md },
  stat: { flex: 1, minWidth: 140, borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.md, padding: 14, backgroundColor: theme.colors.bg },
  statValue: { fontSize: 28, fontWeight: "800", marginBottom: 4 },
  statLabel: { fontSize: 11, textTransform: "uppercase", letterSpacing: 1.2, color: theme.colors.textMuted, fontWeight: "700" },
});
