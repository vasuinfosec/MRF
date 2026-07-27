/**
 * Shared desktop table primitives (Task: web-polish extension).
 *
 * Screens use this whenever `useResponsive().isDesktop` is true and want a
 * dense row layout instead of card list. Column widths are supplied by the
 * caller via `flex` on each cell so every list can tune its own grid.
 *
 * Uses `data-role="table-row"` so the global CSS in theme-context.tsx applies
 * a hover background on desktop.
 */
import React from "react";
import { View, Text, StyleSheet, TouchableOpacity, ViewStyle, StyleProp } from "react-native";
import { theme } from "@/src/theme";

export function DTable({ children, style }: { children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[s.table, style]}>{children}</View>;
}

export function DHead({ children }: { children: React.ReactNode }) {
  return <View style={[s.row, s.head]}>{children}</View>;
}

export function DH({ children, flex = 1, right }: { children: React.ReactNode; flex?: number; right?: boolean }) {
  return <Text style={[s.th, { flex, textAlign: right ? "right" : "left" }]}>{children}</Text>;
}

export function DRow({
  children, onPress, testID,
}: {
  children: React.ReactNode; onPress?: () => void; testID?: string;
}) {
  const Wrap: any = onPress ? TouchableOpacity : View;
  const extra: any = onPress
    ? { activeOpacity: 0.7, testID, dataSet: { role: "table-row" } }
    : { testID, dataSet: { role: "table-row" } };
  return (
    <Wrap onPress={onPress} style={s.row} {...extra}>
      {children}
    </Wrap>
  );
}

export function DC({
  children, flex = 1, right, strong, muted, color,
}: {
  children: React.ReactNode;
  flex?: number; right?: boolean; strong?: boolean; muted?: boolean; color?: string;
}) {
  const isText = typeof children === "string" || typeof children === "number";
  if (isText) {
    return (
      <Text
        numberOfLines={1}
        style={[
          s.cell,
          { flex, textAlign: right ? "right" : "left" },
          strong && { fontWeight: "700" },
          muted && { color: theme.colors.textMuted },
          color && { color },
        ]}
      >
        {children}
      </Text>
    );
  }
  return (
    <View style={{ flex, alignItems: right ? "flex-end" : "flex-start", justifyContent: "center" }}>
      {children}
    </View>
  );
}

const s = StyleSheet.create({
  table: {
    borderWidth: 1, borderColor: theme.colors.border, borderRadius: 8,
    backgroundColor: theme.colors.bg, overflow: "hidden", marginBottom: 40,
  },
  row: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 14, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: theme.colors.border,
    gap: 12,
  },
  head: { backgroundColor: theme.colors.surface2, paddingVertical: 10 },
  th: { fontSize: 11, fontWeight: "700", color: theme.colors.textMuted, textTransform: "uppercase", letterSpacing: 0.8 },
  cell: { fontSize: 13, color: theme.colors.text },
});
