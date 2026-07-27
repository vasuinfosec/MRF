/**
 * MatVarChips
 * Renders MAT-####/VAR-#### pill chips for a workflow line item.
 * Consistent styling across MRF / PO / GRN / DC / CS item cards.
 *
 * Usage:
 *   <MatVarChips materialUid={it.material_uid} variantUid={it.variant_uid} />
 */
import React from "react";
import { StyleSheet, Text, View } from "react-native";

export type MatVarChipsProps = {
  materialUid?: string | null;
  variantUid?: string | null;
  size?: "sm" | "md";
  style?: any;
};

export default function MatVarChips({
  materialUid,
  variantUid,
  size = "sm",
  style,
}: MatVarChipsProps) {
  if (!materialUid && !variantUid) return null;
  const s = size === "md" ? styles.chipMd : styles.chip;
  const sAlt = size === "md" ? styles.chipAltMd : styles.chipAlt;
  return (
    <View style={[styles.row, style]}>
      {materialUid ? (
        <Text style={s} testID={`mat-chip-${materialUid}`}>
          MAT {materialUid}
        </Text>
      ) : null}
      {variantUid ? (
        <Text style={sAlt} testID={`var-chip-${variantUid}`}>
          VAR {variantUid}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
    marginTop: 4,
  },
  chip: {
    backgroundColor: "#EEF2FF",
    color: "#3730A3",
    fontSize: 11,
    fontWeight: "700",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  chipAlt: {
    backgroundColor: "#ECFCCB",
    color: "#3F6212",
    fontSize: 11,
    fontWeight: "700",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  chipMd: {
    backgroundColor: "#EEF2FF",
    color: "#3730A3",
    fontSize: 12,
    fontWeight: "700",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  chipAltMd: {
    backgroundColor: "#ECFCCB",
    color: "#3F6212",
    fontSize: 12,
    fontWeight: "700",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
});
