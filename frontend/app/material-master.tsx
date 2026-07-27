import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Modal,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";

type Tab = "materials" | "categories" | "uoms" | "classification";

type Category = {
  category_id: string;
  name: string;
  description?: string;
  active: boolean;
};

type Uom = {
  uom_id: string;
  name: string;
  code: string;
  conversion_quantity: number;
  base_uom_id?: string;
  is_standard: boolean;
  active: boolean;
};

type Material = {
  material_uid: string;
  category_id?: string;
  category_name: string;
  item: string;
  specification: string;
  description: string;
  make?: string;
  model?: string;
  uom_id?: string;
  uom_name: string;
  unit: string;
  unit_value: number;
  is_consumable: boolean;
  force_traceable: boolean;
  reconciliation_required: boolean;
  classification: string;
  fastener_protected: boolean;
  amc_material: boolean;
  billing_option: "billed" | "not_billed" | "either";
  item_code?: string;
  remarks?: string;
  active: boolean;
};

type MaterialForm = {
  category_id: string;
  item: string;
  specification: string;
  description: string;
  make: string;
  model: string;
  uom_id: string;
  unit_value: string;
  is_consumable: boolean;
  force_traceable: boolean;
  amc_material: boolean;
  billing_option: "billed" | "not_billed" | "either";
  item_code: string;
  remarks: string;
  reason: string;
};

const MATERIAL_EMPTY: MaterialForm = {
  category_id: "",
  item: "",
  specification: "",
  description: "",
  make: "",
  model: "",
  uom_id: "",
  unit_value: "0",
  is_consumable: false,
  force_traceable: false,
  amc_material: false,
  billing_option: "either",
  item_code: "",
  remarks: "",
  reason: "",
};

const STANDARD_UOMS = ["nos", "metre", "kg", "litre", "set", "box", "lot"];

export default function MaterialMaster() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const { user } = useAuth();
  const compact = width < 760;
  const actorRoles = user?.roles?.length ? user.roles : user?.role ? [user.role] : [];
  const authorised = Boolean(user?.is_active && actorRoles.includes("admin"));

  const [tab, setTab] = useState<Tab>("materials");
  const [categories, setCategories] = useState<Category[]>([]);
  const [uoms, setUoms] = useState<Uom[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [threshold, setThreshold] = useState("100");
  const [thresholdReason, setThresholdReason] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const [categoryModal, setCategoryModal] = useState(false);
  const [categoryEditing, setCategoryEditing] = useState<Category | null>(null);
  const [categoryName, setCategoryName] = useState("");
  const [categoryDescription, setCategoryDescription] = useState("");
  const [categoryReason, setCategoryReason] = useState("");

  const [uomModal, setUomModal] = useState(false);
  const [uomEditing, setUomEditing] = useState<Uom | null>(null);
  const [uomName, setUomName] = useState("");
  const [uomCode, setUomCode] = useState("nos");
  const [uomConversion, setUomConversion] = useState("1");
  const [uomBase, setUomBase] = useState("");
  const [uomReason, setUomReason] = useState("");

  const [materialModal, setMaterialModal] = useState(false);
  const [materialEditing, setMaterialEditing] = useState<Material | null>(null);
  const [materialForm, setMaterialForm] = useState<MaterialForm>(MATERIAL_EMPTY);

  const load = useCallback(async () => {
    if (!authorised) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const [categoryRows, uomRows, materialRows, settings] = await Promise.all([
        api<Category[]>("/admin/material-master/categories"),
        api<Uom[]>("/admin/material-master/uoms"),
        api<Material[]>("/admin/material-master/materials"),
        api<{ low_value_threshold_inr: number }>("/admin/material-master/settings"),
      ]);
      setCategories(categoryRows);
      setUoms(uomRows);
      setMaterials(materialRows);
      setThreshold(String(settings.low_value_threshold_inr));
    } catch (e: any) {
      setError(e?.message || "Unable to load Material Master");
    } finally {
      setLoading(false);
    }
  }, [authorised]);

  useEffect(() => { load(); }, [load]);

  const activeCategories = useMemo(
    () => categories.filter((row) => row.active),
    [categories],
  );
  const activeUoms = useMemo(() => uoms.filter((row) => row.active), [uoms]);

  const visibleMaterials = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return materials;
    return materials.filter((row) => [
      row.material_uid, row.category_name, row.item, row.specification,
      row.make, row.model, row.description, row.uom_name,
    ].join(" ").toLowerCase().includes(needle));
  }, [materials, query]);

  const visibleCategories = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle
      ? categories.filter((row) => `${row.name} ${row.description || ""}`.toLowerCase().includes(needle))
      : categories;
  }, [categories, query]);

  const visibleUoms = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle
      ? uoms.filter((row) => `${row.name} ${row.code}`.toLowerCase().includes(needle))
      : uoms;
  }, [uoms, query]);

  const notify = (text: string) => {
    setMessage(text);
    setError("");
  };

  const fail = (e: any) => {
    setError(e?.message || "Action failed");
    setMessage("");
  };

  const openCategory = (row?: Category) => {
    setCategoryEditing(row || null);
    setCategoryName(row?.name || "");
    setCategoryDescription(row?.description || "");
    setCategoryReason("");
    setCategoryModal(true);
  };

  const saveCategory = async () => {
    if (!categoryName.trim()) return setError("Category name is required");
    if (categoryEditing && !categoryReason.trim()) return setError("Reason is required");
    setSaving(true);
    try {
      await api(
        categoryEditing
          ? `/admin/material-master/categories/${categoryEditing.category_id}`
          : "/admin/material-master/categories",
        {
          method: categoryEditing ? "PUT" : "POST",
          body: {
            name: categoryName,
            description: categoryDescription,
            reason: categoryReason,
          },
        },
      );
      setCategoryModal(false);
      notify(categoryEditing ? "Category updated" : "Category created");
      await load();
    } catch (e) { fail(e); } finally { setSaving(false); }
  };

  const openUom = (row?: Uom) => {
    setUomEditing(row || null);
    setUomName(row?.name || "");
    setUomCode(row?.code || "nos");
    setUomConversion(String(row?.conversion_quantity || 1));
    setUomBase(row?.base_uom_id || "");
    setUomReason("");
    setUomModal(true);
  };

  const saveUom = async () => {
    if (!uomName.trim() || !uomCode.trim()) return setError("UOM name and code are required");
    if (["box", "lot"].includes(uomCode) && (!uomBase || Number(uomConversion) <= 0)) {
      return setError("Box/lot requires a base UOM and conversion greater than zero");
    }
    if (uomEditing && !uomReason.trim()) return setError("Reason is required");
    setSaving(true);
    try {
      await api(
        uomEditing
          ? `/admin/material-master/uoms/${uomEditing.uom_id}`
          : "/admin/material-master/uoms",
        {
          method: uomEditing ? "PUT" : "POST",
          body: {
            name: uomName,
            code: uomCode,
            conversion_quantity: Number(uomConversion),
            base_uom_id: uomBase,
            reason: uomReason,
          },
        },
      );
      setUomModal(false);
      notify(uomEditing ? "UOM updated" : "UOM created");
      await load();
    } catch (e) { fail(e); } finally { setSaving(false); }
  };

  const openMaterial = (row?: Material) => {
    setMaterialEditing(row || null);
    setMaterialForm(row ? {
      category_id: row.category_id || "",
      item: row.item || "",
      specification: row.specification || "",
      description: row.description || "",
      make: row.make || "",
      model: row.model || "",
      uom_id: row.uom_id || "",
      unit_value: String(row.unit_value || 0),
      is_consumable: Boolean(row.is_consumable),
      force_traceable: Boolean(row.force_traceable),
      amc_material: Boolean(row.amc_material),
      billing_option: row.billing_option || "either",
      item_code: row.item_code || "",
      remarks: row.remarks || "",
      reason: "",
    } : MATERIAL_EMPTY);
    setMaterialModal(true);
  };

  const saveMaterial = async () => {
    const words = materialForm.description.trim().split(/\s+/).filter(Boolean).length;
    if (!materialForm.category_id || !materialForm.uom_id) return setError("Category and UOM are required");
    if (!materialForm.item.trim() || !materialForm.specification.trim()) {
      return setError("Item and specification are required");
    }
    if (!materialForm.description.trim()) return setError("Description is required");
    if (words > 100) return setError("Description cannot exceed 100 words");
    if (materialEditing && !materialForm.reason.trim()) return setError("Reason is required");
    setSaving(true);
    try {
      await api(
        materialEditing
          ? `/admin/material-master/materials/${materialEditing.material_uid}`
          : "/admin/material-master/materials",
        {
          method: materialEditing ? "PUT" : "POST",
          body: { ...materialForm, unit_value: Number(materialForm.unit_value || 0) },
        },
      );
      setMaterialModal(false);
      notify(materialEditing ? "Material updated" : "Material created");
      await load();
    } catch (e) { fail(e); } finally { setSaving(false); }
  };

  const setStatus = (
    kind: "categories" | "uoms" | "materials",
    id: string,
    active: boolean,
    label: string,
  ) => {
    Alert.alert(
      active ? `Activate ${label}?` : `Deactivate ${label}?`,
      "Historical MRF/PO/GRN/DC records will remain unchanged.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: active ? "Activate" : "Deactivate",
          style: active ? "default" : "destructive",
          onPress: async () => {
            try {
              await api(`/admin/material-master/${kind}/${id}/status`, {
                method: "POST",
                body: { active, reason: `${active ? "Activated" : "Deactivated"} via Material Master` },
              });
              notify(`${label} ${active ? "activated" : "deactivated"}`);
              await load();
            } catch (e) { fail(e); }
          },
        },
      ],
    );
  };

  const saveThreshold = async () => {
    if (Number(threshold) <= 0) return setError("Threshold must be greater than zero");
    if (!thresholdReason.trim()) return setError("Reason is required");
    setSaving(true);
    try {
      await api("/admin/material-master/settings", {
        method: "PUT",
        body: {
          low_value_threshold_inr: Number(threshold),
          reason: thresholdReason,
        },
      });
      setThresholdReason("");
      notify("Classification threshold updated");
      await load();
    } catch (e) { fail(e); } finally { setSaving(false); }
  };

  if (!authorised) {
    return (
      <SafeAreaView style={styles.safe}>
        <Header onBack={() => router.back()} />
        <StatePanel
          icon="lock-closed-outline"
          title="Permission denied"
          message="Only an active Admin can manage categories, materials and UOM controls."
        />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe}>
      <Header onBack={() => router.back()} />
      <ScrollView contentContainerStyle={[styles.page, compact ? styles.pageCompact : null]}>
        <View style={[styles.hero, compact ? styles.heroCompact : null]}>
          <View style={[{ flex: 1 }, compact ? styles.heroCopyCompact : null]}>
            <Text style={styles.eyebrow}>PROCUREMENT MASTER DATA</Text>
            <Text style={styles.h1}>Material Master & UOM Controls</Text>
            <Text style={styles.sub}>
              Category → item → specification with immutable UIDs and historical traceability.
            </Text>
          </View>
          <TouchableOpacity
            testID="material-create"
            style={[styles.primaryBtn, compact ? styles.primaryBtnCompact : null]}
            onPress={() => openMaterial()}
          >
            <Ionicons name="add-circle-outline" size={18} color="#fff" />
            <Text style={styles.primaryText}>Add material</Text>
          </TouchableOpacity>
        </View>

        <View style={[styles.stats, compact ? styles.statsCompact : null]}>
          <Stat icon="cube-outline" value={materials.length} label="Materials" />
          <Stat icon="layers-outline" value={categories.length} label="Categories" />
          <Stat icon="resize-outline" value={uoms.length} label="Approved UOMs" />
          <Stat
            icon="git-compare-outline"
            value={materials.filter((row) => row.reconciliation_required).length}
            label="Traceable"
          />
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabs}>
          {([
            ["materials", "Materials", "cube-outline"],
            ["categories", "Categories", "layers-outline"],
            ["uoms", "UOM controls", "resize-outline"],
            ["classification", "Classification", "options-outline"],
          ] as [Tab, string, any][]).map(([key, label, icon]) => (
            <TouchableOpacity
              key={key}
              testID={`task4-tab-${key}`}
              onPress={() => { setTab(key); setQuery(""); }}
              style={[styles.tab, tab === key ? styles.tabActive : null]}
            >
              <Ionicons name={icon} size={16} color={tab === key ? "#fff" : theme.colors.text} />
              <Text style={[styles.tabText, tab === key ? { color: "#fff" } : null]}>{label}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>

        {tab !== "classification" ? (
          <View style={styles.search}>
            <Ionicons name="search-outline" size={18} color={theme.colors.textMuted} />
            <TextInput
              testID="task4-search"
              value={query}
              onChangeText={setQuery}
              placeholder={`Search ${tab}`}
              style={styles.searchInput}
            />
          </View>
        ) : null}

        {error ? <Banner tone="error" text={error} /> : null}
        {message ? <Banner tone="success" text={message} /> : null}

        {loading ? (
          <StatePanel icon="hourglass-outline" title="Loading Material Master" message="Reading approved master data…" loading />
        ) : tab === "materials" ? (
          <View testID="task4-materials-section">
            {visibleMaterials.length ? visibleMaterials.map((row) => (
              <MaterialCard
                key={row.material_uid}
                row={row}
                compact={compact}
                onEdit={() => openMaterial(row)}
                onStatus={() => setStatus("materials", row.material_uid, !row.active, row.material_uid)}
              />
            )) : (
              <StatePanel icon="cube-outline" title="No materials" message="Add a genuine material definition to begin." />
            )}
          </View>
        ) : tab === "categories" ? (
          <View testID="task4-categories-section">
            <SectionHeader
              title="Material categories"
              subtitle="Stable category IDs link every material without rewriting historical records."
              action="Add category"
              onAction={() => openCategory()}
            />
            <View style={[styles.grid, compact ? styles.gridCompact : null]}>
              {visibleCategories.length ? visibleCategories.map((row) => (
                <LifecycleCard
                  key={row.category_id}
                  title={row.name}
                  code={row.category_id}
                  detail={row.description || "No description"}
                  active={row.active}
                  onEdit={() => openCategory(row)}
                  onStatus={() => setStatus("categories", row.category_id, !row.active, row.name)}
                />
              )) : (
                <StatePanel icon="layers-outline" title="No categories" message="No genuine categories have been configured." />
              )}
            </View>
          </View>
        ) : tab === "uoms" ? (
          <View testID="task4-uoms-section">
            <SectionHeader
              title="Approved units of measure"
              subtitle="Box and lot require a positive conversion to an active base UOM."
              action="Add UOM"
              onAction={() => openUom()}
            />
            <View style={[styles.grid, compact ? styles.gridCompact : null]}>
              {visibleUoms.length ? visibleUoms.map((row) => (
                <LifecycleCard
                  key={row.uom_id}
                  title={`${row.name} · ${row.code}`}
                  code={row.uom_id}
                  detail={["box", "lot"].includes(row.code)
                    ? `${row.conversion_quantity} × ${uoms.find((u) => u.uom_id === row.base_uom_id)?.name || "base UOM"}`
                    : "Base quantity · 1"}
                  active={row.active}
                  onEdit={() => openUom(row)}
                  onStatus={() => setStatus("uoms", row.uom_id, !row.active, row.name)}
                />
              )) : (
                <StatePanel icon="resize-outline" title="No approved UOMs" message="Configure genuine units before adding materials." />
              )}
            </View>
          </View>
        ) : (
          <View testID="task4-classification-section">
            <View style={styles.panel}>
              <Text style={styles.panelTitle}>Low-value consumable threshold</Text>
              <Text style={styles.sub}>
                Consumables below this value skip reconciliation. Fasteners and all higher-value items remain traceable.
              </Text>
              <View style={[styles.formRow, compact ? styles.formRowCompact : null]}>
                <Field label="THRESHOLD (₹)" style={{ flex: 1 }}>
                  <TextInput
                    testID="classification-threshold"
                    value={threshold}
                    onChangeText={(value) => setThreshold(value.replace(/[^0-9.]/g, ""))}
                    keyboardType="decimal-pad"
                    style={styles.input}
                  />
                </Field>
                <Field label="AUDIT REASON" style={{ flex: 2 }}>
                  <TextInput
                    testID="classification-reason"
                    value={thresholdReason}
                    onChangeText={setThresholdReason}
                    placeholder="Why is this threshold changing?"
                    style={styles.input}
                  />
                </Field>
                <TouchableOpacity
                  testID="classification-save"
                  onPress={saveThreshold}
                  disabled={saving}
                  style={styles.primaryBtn}
                >
                  <Text style={styles.primaryText}>{saving ? "Saving…" : "Save threshold"}</Text>
                </TouchableOpacity>
              </View>
            </View>
            <View style={[styles.grid, compact ? styles.gridCompact : null]}>
              <RuleCard icon="leaf-outline" title="Low-value consumable" text={`Consumable and below ₹${threshold || "100"} · reconciliation not required.`} />
              <RuleCard icon="shield-checkmark-outline" title="Traceable material" text="High-value, non-consumable, manually forced, or fastener-related." />
              <RuleCard icon="construct-outline" title="Fastener protection" text="Bolts, nuts, screws, washers, anchors and rivets remain traceable." />
              <RuleCard icon="receipt-outline" title="AMC & billing" text="AMC classification and billed/not-billed/either options remain explicit." />
            </View>
          </View>
        )}

        <View style={styles.historyNotice}>
          <Ionicons name="archive-outline" size={18} color={theme.colors.primary} />
          <Text style={styles.historyText}>
            Deactivation never deletes historical material, category or UOM references already used in MRF/PO/GRN/DC.
          </Text>
        </View>
      </ScrollView>

      <FormModal
        visible={categoryModal}
        title={categoryEditing ? "Edit category" : "Add category"}
        onClose={() => setCategoryModal(false)}
        onSave={saveCategory}
        saving={saving}
        bottomInset={insets.bottom}
      >
        <Field label="CATEGORY NAME">
          <TextInput value={categoryName} onChangeText={setCategoryName} style={styles.input} />
        </Field>
        <Field label="DESCRIPTION">
          <TextInput value={categoryDescription} onChangeText={setCategoryDescription} style={[styles.input, styles.multiline]} multiline />
        </Field>
        {categoryEditing ? (
          <Field label="REASON FOR CHANGE">
            <TextInput value={categoryReason} onChangeText={setCategoryReason} style={styles.input} />
          </Field>
        ) : null}
      </FormModal>

      <FormModal
        visible={uomModal}
        title={uomEditing ? "Edit UOM" : "Add UOM"}
        onClose={() => setUomModal(false)}
        onSave={saveUom}
        saving={saving}
        bottomInset={insets.bottom}
      >
        <Field label="APPROVED UOM">
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}>
            {STANDARD_UOMS.map((code) => (
              <Choice key={code} label={code} selected={uomCode === code} onPress={() => {
                setUomCode(code);
                if (!uomName || STANDARD_UOMS.includes(uomName.toLowerCase())) {
                  setUomName(code[0].toUpperCase() + code.slice(1));
                }
              }} />
            ))}
            <Choice label="other" selected={!STANDARD_UOMS.includes(uomCode)} onPress={() => { setUomCode(""); setUomName(""); }} />
          </ScrollView>
        </Field>
        <View style={styles.formRow}>
          <Field label="DISPLAY NAME" style={{ flex: 1 }}>
            <TextInput value={uomName} onChangeText={setUomName} style={styles.input} />
          </Field>
          <Field label="CODE" style={{ flex: 1 }}>
            <TextInput value={uomCode} onChangeText={(v) => setUomCode(v.toLowerCase())} style={styles.input} autoCapitalize="none" />
          </Field>
        </View>
        {["box", "lot"].includes(uomCode) ? (
          <>
            <Field label="BASE UOM">
              <View style={styles.choiceWrap}>
                {activeUoms.filter((row) => !["box", "lot"].includes(row.code) && row.uom_id !== uomEditing?.uom_id).map((row) => (
                  <Choice key={row.uom_id} label={row.name} selected={uomBase === row.uom_id} onPress={() => setUomBase(row.uom_id)} />
                ))}
              </View>
            </Field>
            <Field label="CONVERSION QUANTITY (> 0)">
              <TextInput value={uomConversion} onChangeText={setUomConversion} keyboardType="decimal-pad" style={styles.input} />
            </Field>
          </>
        ) : null}
        {uomEditing ? (
          <Field label="REASON FOR CHANGE">
            <TextInput value={uomReason} onChangeText={setUomReason} style={styles.input} />
          </Field>
        ) : null}
      </FormModal>

      <FormModal
        visible={materialModal}
        title={materialEditing ? `Edit ${materialEditing.material_uid}` : "Add material"}
        onClose={() => setMaterialModal(false)}
        onSave={saveMaterial}
        saving={saving}
        bottomInset={insets.bottom}
      >
        <Field label="CATEGORY">
          <View style={styles.choiceWrap}>
            {activeCategories.map((row) => (
              <Choice key={row.category_id} label={row.name} selected={materialForm.category_id === row.category_id}
                onPress={() => setMaterialForm((form) => ({ ...form, category_id: row.category_id }))} />
            ))}
          </View>
        </Field>
        <Field label="ITEM">
          <TextInput value={materialForm.item} onChangeText={(item) => setMaterialForm((form) => ({ ...form, item }))} style={styles.input} />
        </Field>
        <Field label="SPECIFICATION">
          <TextInput value={materialForm.specification} onChangeText={(specification) => setMaterialForm((form) => ({ ...form, specification }))} style={styles.input} />
        </Field>
        <Field label={`DESCRIPTION · ${materialForm.description.trim().split(/\s+/).filter(Boolean).length}/100 WORDS`}>
          <TextInput
            value={materialForm.description}
            onChangeText={(description) => setMaterialForm((form) => ({ ...form, description }))}
            style={[styles.input, styles.multiline]}
            multiline
          />
        </Field>
        <View style={[styles.formRow, compact ? styles.formRowCompact : null]}>
          <Field label="MAKE" style={{ flex: 1 }}>
            <TextInput value={materialForm.make} onChangeText={(make) => setMaterialForm((form) => ({ ...form, make }))} style={styles.input} />
          </Field>
          <Field label="MODEL" style={{ flex: 1 }}>
            <TextInput value={materialForm.model} onChangeText={(model) => setMaterialForm((form) => ({ ...form, model }))} style={styles.input} />
          </Field>
        </View>
        <Field label="UOM">
          <View style={styles.choiceWrap}>
            {activeUoms.map((row) => (
              <Choice key={row.uom_id} label={`${row.name} (${row.code})`} selected={materialForm.uom_id === row.uom_id}
                onPress={() => setMaterialForm((form) => ({ ...form, uom_id: row.uom_id }))} />
            ))}
          </View>
        </Field>
        <Field label="ESTIMATED UNIT VALUE (₹)">
          <TextInput
            value={materialForm.unit_value}
            onChangeText={(unit_value) => setMaterialForm((form) => ({ ...form, unit_value }))}
            keyboardType="decimal-pad"
            style={styles.input}
          />
        </Field>
        <Toggle label="Low-value consumable candidate" value={materialForm.is_consumable}
          onChange={(is_consumable) => setMaterialForm((form) => ({ ...form, is_consumable }))} />
        <Toggle label="Force traceability / reconciliation" value={materialForm.force_traceable}
          onChange={(force_traceable) => setMaterialForm((form) => ({ ...form, force_traceable }))} />
        <Toggle label="AMC material" value={materialForm.amc_material}
          onChange={(amc_material) => setMaterialForm((form) => ({ ...form, amc_material }))} />
        <Field label="BILLING OPTION">
          <View style={styles.choiceWrap}>
            {(["billed", "not_billed", "either"] as const).map((option) => (
              <Choice key={option} label={option.replace("_", " ")} selected={materialForm.billing_option === option}
                onPress={() => setMaterialForm((form) => ({ ...form, billing_option: option }))} />
            ))}
          </View>
        </Field>
        {materialEditing ? (
          <Field label="REASON FOR CHANGE">
            <TextInput value={materialForm.reason} onChangeText={(reason) => setMaterialForm((form) => ({ ...form, reason }))} style={styles.input} />
          </Field>
        ) : null}
      </FormModal>
    </SafeAreaView>
  );
}

function Header({ onBack }: { onBack: () => void }) {
  return (
    <View style={styles.header}>
      <TouchableOpacity onPress={onBack} style={styles.headerIcon}>
        <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
      </TouchableOpacity>
      <View style={{ flex: 1 }}>
        <Text style={styles.headerTitle}>Material Master</Text>
        <Text style={styles.headerSub}>Category, UOM and traceability control</Text>
      </View>
      <Ionicons name="shield-checkmark-outline" size={22} color={theme.colors.primary} />
    </View>
  );
}

function Stat({ icon, value, label }: { icon: any; value: number; label: string }) {
  return (
    <View style={styles.stat}>
      <View style={styles.statIcon}><Ionicons name={icon} size={20} color={theme.colors.primary} /></View>
      <View><Text style={styles.statValue}>{value}</Text><Text style={styles.statLabel}>{label}</Text></View>
    </View>
  );
}

function MaterialCard({ row, compact, onEdit, onStatus }: {
  row: Material; compact: boolean; onEdit: () => void; onStatus: () => void;
}) {
  return (
    <View style={[styles.materialCard, !row.active ? styles.inactiveCard : null]}>
      <View style={[styles.materialTop, compact ? styles.materialTopCompact : null]}>
        <View style={{ flex: 1 }}>
          <View style={styles.badgeRow}>
            <Badge text={row.material_uid} tone="blue" />
            <Badge text={row.active ? "Active" : "Deactivated"} tone={row.active ? "green" : "gray"} />
            <Badge text={row.reconciliation_required ? "Traceable" : "No reconciliation"} tone={row.reconciliation_required ? "orange" : "green"} />
            {row.amc_material ? <Badge text="AMC" tone="purple" /> : null}
          </View>
          <Text style={styles.materialPath}>
            {row.category_name || "Legacy category"} → {row.item || row.description} → {row.specification || "Legacy specification"}
          </Text>
          <Text style={styles.materialDescription}>{row.description}</Text>
          <Text style={styles.materialMeta}>
            {[row.make, row.model].filter(Boolean).join(" · ") || "Make/model not specified"}
            {"  ·  "}{row.uom_name || row.unit || "UOM pending"}
            {"  ·  "}₹{Number(row.unit_value || 0).toLocaleString("en-IN")}
            {"  ·  "}{row.billing_option.replace("_", " ")}
          </Text>
        </View>
        <View style={styles.actions}>
          <TouchableOpacity onPress={onEdit} style={styles.iconBtn}><Ionicons name="pencil-outline" size={17} color={theme.colors.text} /></TouchableOpacity>
          <TouchableOpacity onPress={onStatus} style={styles.iconBtn}>
            <Ionicons name={row.active ? "pause-circle-outline" : "play-circle-outline"} size={18} color={row.active ? theme.colors.danger : theme.colors.success} />
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );
}

function LifecycleCard({ title, code, detail, active, onEdit, onStatus }: {
  title: string; code: string; detail: string; active: boolean; onEdit: () => void; onStatus: () => void;
}) {
  return (
    <View style={[styles.lifecycleCard, !active ? styles.inactiveCard : null]}>
      <View style={styles.badgeRow}><Badge text={active ? "Active" : "Deactivated"} tone={active ? "green" : "gray"} /></View>
      <Text style={styles.lifecycleTitle}>{title}</Text>
      <Text style={styles.code}>{code}</Text>
      <Text style={styles.lifecycleDetail}>{detail}</Text>
      <View style={styles.actions}>
        <TouchableOpacity onPress={onEdit} style={styles.outlineBtn}><Text style={styles.outlineText}>Edit</Text></TouchableOpacity>
        <TouchableOpacity onPress={onStatus} style={styles.outlineBtn}>
          <Text style={[styles.outlineText, { color: active ? theme.colors.danger : theme.colors.success }]}>{active ? "Deactivate" : "Activate"}</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

function SectionHeader({ title, subtitle, action, onAction }: {
  title: string; subtitle: string; action: string; onAction: () => void;
}) {
  return (
    <View style={styles.sectionHeader}>
      <View style={{ flex: 1 }}><Text style={styles.panelTitle}>{title}</Text><Text style={styles.sub}>{subtitle}</Text></View>
      <TouchableOpacity onPress={onAction} style={styles.primaryBtn}><Text style={styles.primaryText}>{action}</Text></TouchableOpacity>
    </View>
  );
}

function RuleCard({ icon, title, text }: { icon: any; title: string; text: string }) {
  return (
    <View style={styles.lifecycleCard}>
      <View style={styles.statIcon}><Ionicons name={icon} size={20} color={theme.colors.primary} /></View>
      <Text style={styles.lifecycleTitle}>{title}</Text>
      <Text style={styles.lifecycleDetail}>{text}</Text>
    </View>
  );
}

function StatePanel({ icon, title, message, loading = false }: {
  icon: any; title: string; message: string; loading?: boolean;
}) {
  return (
    <View style={styles.state}>
      {loading ? <ActivityIndicator color={theme.colors.primary} /> : <Ionicons name={icon} size={30} color={theme.colors.primary} />}
      <Text style={styles.stateTitle}>{title}</Text>
      <Text style={styles.stateText}>{message}</Text>
    </View>
  );
}

function Banner({ tone, text }: { tone: "error" | "success"; text: string }) {
  return (
    <View style={[styles.banner, tone === "error" ? styles.bannerError : styles.bannerSuccess]}>
      <Ionicons name={tone === "error" ? "alert-circle-outline" : "checkmark-circle-outline"} size={18} color={tone === "error" ? theme.colors.danger : theme.colors.success} />
      <Text style={styles.bannerText}>{text}</Text>
    </View>
  );
}

function Badge({ text, tone }: { text: string; tone: "blue" | "green" | "orange" | "gray" | "purple" }) {
  const map = {
    blue: { bg: "#e9efff", fg: theme.colors.primary },
    green: { bg: "#dcfce7", fg: "#166534" },
    orange: { bg: "#ffedd5", fg: "#9a3412" },
    gray: { bg: "#e2e8f0", fg: "#475569" },
    purple: { bg: "#f3e8ff", fg: "#7e22ce" },
  };
  return <Text style={[styles.badge, { backgroundColor: map[tone].bg, color: map[tone].fg }]}>{text}</Text>;
}

function Choice({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  return (
    <TouchableOpacity onPress={onPress} style={[styles.choice, selected ? styles.choiceActive : null]}>
      <Text style={[styles.choiceText, selected ? { color: "#fff" } : null]}>{label}</Text>
    </TouchableOpacity>
  );
}

function Toggle({ label, value, onChange }: { label: string; value: boolean; onChange: (value: boolean) => void }) {
  return (
    <View style={styles.toggle}>
      <Text style={styles.toggleLabel}>{label}</Text>
      <Switch value={value} onValueChange={onChange} trackColor={{ true: theme.colors.primary }} />
    </View>
  );
}

function Field({ label, children, style }: { label: string; children: React.ReactNode; style?: any }) {
  return <View style={[{ marginTop: 12 }, style]}><Text style={styles.label}>{label}</Text>{children}</View>;
}

function FormModal({ visible, title, onClose, onSave, saving, bottomInset, children }: {
  visible: boolean; title: string; onClose: () => void; onSave: () => void;
  saving: boolean; bottomInset: number; children: React.ReactNode;
}) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.modalBg}>
        <View style={[styles.modal, { paddingBottom: 16 + bottomInset }]}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>{title}</Text>
            <TouchableOpacity onPress={onClose}><Ionicons name="close" size={24} color={theme.colors.text} /></TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={{ paddingBottom: 16 }}>{children}</ScrollView>
          <View style={styles.modalActions}>
            <TouchableOpacity onPress={onClose} style={[styles.outlineBtn, { flex: 1 }]}><Text style={styles.outlineText}>Cancel</Text></TouchableOpacity>
            <TouchableOpacity onPress={onSave} disabled={saving} style={[styles.primaryBtn, { flex: 1 }]}>
              <Text style={styles.primaryText}>{saving ? "Saving…" : "Save"}</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.colors.surface },
  header: { height: 66, paddingHorizontal: 16, flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: "#fff", borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  headerIcon: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontSize: 17, fontWeight: "800", color: theme.colors.text },
  headerSub: { fontSize: 11, color: theme.colors.textMuted, marginTop: 1 },
  page: { width: "100%", maxWidth: 1220, alignSelf: "center", padding: 22, paddingBottom: 70 },
  pageCompact: { padding: 12 },
  hero: { flexDirection: "row", alignItems: "center", gap: 18, paddingVertical: 10 },
  heroCompact: { flexDirection: "column", alignItems: "stretch" },
  heroCopyCompact: { width: "100%" },
  primaryBtnCompact: { alignSelf: "stretch" },
  eyebrow: { fontSize: 11, fontWeight: "800", letterSpacing: 1.4, color: theme.colors.textMuted },
  h1: { fontSize: 28, lineHeight: 34, fontWeight: "900", color: theme.colors.text, marginTop: 5 },
  sub: { fontSize: 13, lineHeight: 19, color: theme.colors.textMuted, marginTop: 4 },
  primaryBtn: { minHeight: 42, paddingHorizontal: 16, borderRadius: 7, backgroundColor: theme.colors.action, flexDirection: "row", gap: 7, alignItems: "center", justifyContent: "center" },
  primaryText: { color: "#fff", fontWeight: "800", fontSize: 13 },
  stats: { display: "flex", flexDirection: "row", gap: 9, marginTop: 10 },
  statsCompact: { flexDirection: "column" },
  stat: { flex: 1, minWidth: 0, flexDirection: "row", gap: 10, alignItems: "center", backgroundColor: "#fff", borderWidth: 1, borderColor: theme.colors.border, borderRadius: 9, padding: 13 },
  statIcon: { width: 40, height: 40, borderRadius: 8, backgroundColor: "#eef2ff", alignItems: "center", justifyContent: "center" },
  statValue: { fontSize: 21, fontWeight: "900", color: theme.colors.text },
  statLabel: { fontSize: 10, letterSpacing: 0.5, textTransform: "uppercase", fontWeight: "700", color: theme.colors.textMuted },
  tabs: { gap: 8, paddingVertical: 14 },
  tab: { height: 38, paddingHorizontal: 14, borderRadius: 999, borderWidth: 1, borderColor: theme.colors.borderStrong, backgroundColor: "#fff", flexDirection: "row", gap: 6, alignItems: "center" },
  tabActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  tabText: { fontSize: 12, fontWeight: "700", color: theme.colors.text },
  search: { height: 42, flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#fff", borderWidth: 1, borderColor: theme.colors.border, borderRadius: 8, paddingHorizontal: 12, marginBottom: 10 },
  searchInput: { flex: 1, fontSize: 14, color: theme.colors.text },
  materialCard: { backgroundColor: "#fff", borderWidth: 1, borderColor: theme.colors.border, borderRadius: 10, padding: 15, marginTop: 9 },
  inactiveCard: { opacity: 0.62, backgroundColor: "#f8fafc" },
  materialTop: { flexDirection: "row", alignItems: "flex-start", gap: 12 },
  materialTopCompact: { flexDirection: "column" },
  materialPath: { fontSize: 15, lineHeight: 21, fontWeight: "800", color: theme.colors.text, marginTop: 8 },
  materialDescription: { fontSize: 13, lineHeight: 19, color: theme.colors.textSecondary, marginTop: 4 },
  materialMeta: { fontSize: 11, lineHeight: 17, color: theme.colors.textMuted, marginTop: 7 },
  badgeRow: { flexDirection: "row", flexWrap: "wrap", gap: 5 },
  badge: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999, fontSize: 10, fontWeight: "800", overflow: "hidden" },
  actions: { flexDirection: "row", gap: 7, alignItems: "center" },
  iconBtn: { width: 36, height: 36, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 7, backgroundColor: "#fff", alignItems: "center", justifyContent: "center" },
  sectionHeader: { marginTop: 4, marginBottom: 5, flexDirection: "row", alignItems: "center", gap: 12 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  gridCompact: { flexDirection: "column" },
  lifecycleCard: { flexGrow: 1, flexBasis: 280, minWidth: 0, backgroundColor: "#fff", borderWidth: 1, borderColor: theme.colors.border, borderRadius: 10, padding: 14 },
  lifecycleTitle: { fontSize: 15, fontWeight: "800", color: theme.colors.text, marginTop: 8 },
  lifecycleDetail: { fontSize: 12, lineHeight: 18, color: theme.colors.textMuted, marginTop: 6, flex: 1 },
  code: { fontSize: 10, fontWeight: "700", color: theme.colors.primary, marginTop: 3 },
  outlineBtn: { minHeight: 38, paddingHorizontal: 12, borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 7, backgroundColor: "#fff", alignItems: "center", justifyContent: "center" },
  outlineText: { fontSize: 12, fontWeight: "700", color: theme.colors.text },
  panel: { backgroundColor: "#fff", borderWidth: 1, borderColor: theme.colors.border, borderRadius: 10, padding: 16, marginBottom: 10 },
  panelTitle: { fontSize: 18, fontWeight: "900", color: theme.colors.text },
  formRow: { flexDirection: "row", gap: 10, alignItems: "flex-end" },
  formRowCompact: { flexDirection: "column", alignItems: "stretch" },
  input: { minHeight: 44, borderWidth: 1, borderColor: theme.colors.borderStrong, borderRadius: 7, backgroundColor: "#fff", paddingHorizontal: 11, paddingVertical: 9, fontSize: 14, color: theme.colors.text },
  multiline: { minHeight: 84, textAlignVertical: "top" },
  label: { fontSize: 10, fontWeight: "800", color: theme.colors.textMuted, letterSpacing: 0.6, marginBottom: 5 },
  choiceWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  choice: { paddingHorizontal: 11, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: theme.colors.borderStrong, backgroundColor: "#fff" },
  choiceActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  choiceText: { fontSize: 12, fontWeight: "700", color: theme.colors.text },
  toggle: { minHeight: 48, marginTop: 9, paddingHorizontal: 11, borderRadius: 8, backgroundColor: "#f8fafc", borderWidth: 1, borderColor: theme.colors.border, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  toggleLabel: { flex: 1, fontSize: 13, color: theme.colors.text, fontWeight: "600" },
  banner: { flexDirection: "row", alignItems: "center", gap: 8, padding: 11, borderRadius: 8, marginVertical: 5, borderWidth: 1 },
  bannerError: { backgroundColor: "#fef2f2", borderColor: "#fecaca" },
  bannerSuccess: { backgroundColor: "#f0fdf4", borderColor: "#bbf7d0" },
  bannerText: { flex: 1, fontSize: 12, color: theme.colors.text },
  state: { minHeight: 180, alignItems: "center", justifyContent: "center", padding: 24, marginTop: 12, borderWidth: 1, borderStyle: "dashed", borderColor: theme.colors.border, borderRadius: 10, backgroundColor: "#fff" },
  stateTitle: { fontSize: 15, fontWeight: "800", color: theme.colors.text, marginTop: 9 },
  stateText: { maxWidth: 430, textAlign: "center", fontSize: 12, lineHeight: 18, color: theme.colors.textMuted, marginTop: 4 },
  historyNotice: { flexDirection: "row", alignItems: "flex-start", gap: 8, marginTop: 15, padding: 11, backgroundColor: "#eef2ff", borderRadius: 8 },
  historyText: { flex: 1, fontSize: 11, lineHeight: 17, color: theme.colors.textSecondary },
  modalBg: { flex: 1, backgroundColor: "rgba(15,23,42,0.48)", justifyContent: "flex-end" },
  modal: { maxHeight: "92%", width: "100%", maxWidth: 720, alignSelf: "center", backgroundColor: "#fff", borderTopLeftRadius: 18, borderTopRightRadius: 18, padding: 18 },
  modalHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingBottom: 4 },
  modalTitle: { fontSize: 18, fontWeight: "900", color: theme.colors.text },
  modalActions: { flexDirection: "row", gap: 9, paddingTop: 10, borderTopWidth: 1, borderTopColor: theme.colors.border },
});
