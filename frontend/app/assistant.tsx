import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert,
  ActivityIndicator,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Btn, Card, H2, Label, Muted, Pill } from "@/src/components/ui";
import LlmFilePicker, { LlmAttachment } from "@/src/components/LlmFilePicker";
import { theme } from "@/src/theme";
import { useAuth } from "@/src/auth";

type Tab = "standardise" | "compare" | "reconcile" | "negotiate" | "review";

/**
 * LLM Co-pilot — three suggestion-only tools.
 *
 * HARD SAFETY CONTRACT (also enforced server-side):
 *   • LLM outputs are SUGGESTIONS. Humans accept / reject before any downstream
 *     workflow write happens.
 *   • LLM never approves, releases POs, posts financials, or updates stock.
 *   • Every call is audit-logged with tier (Haiku=cheap, Sonnet=premium).
 */
export default function AssistantScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const canUse = ["purchase", "admin", "pm", "gm", "director"].includes(user?.role || "");
  const [tab, setTab] = useState<Tab>("standardise");

  if (!canUse) {
    return (
      <SafeAreaView style={{ flex: 1, padding: 16 }}>
        <Muted>The Assistant is available to Purchase, PM, GM, Accounts and Director.</Muted>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={{ padding: 8 }} testID="back-btn">
          <Ionicons name="arrow-back" size={22} color={theme.colors.text} />
        </TouchableOpacity>
        <Text style={styles.title}>AI Co-pilot</Text>
        <View style={{ width: 38 }} />
      </View>

      <View style={styles.safety}>
        <Ionicons name="shield-checkmark-outline" size={14} color="#065F46" />
        <Text style={styles.safetyText}>
          Suggestions only. Approvals, PO release, stock and financial posting stay human-authorised.
        </Text>
      </View>

      <View style={styles.tabs}>
        {(
          [
            { k: "standardise", label: "Standardise", icon: "sparkles-outline" as const, tier: "gpt-4o-mini" },
            { k: "compare", label: "Compare Quotes", icon: "swap-vertical-outline" as const, tier: "Sonnet" },
            { k: "reconcile", label: "3-Way Match", icon: "git-compare-outline" as const, tier: "Sonnet" },
            { k: "negotiate", label: "Negotiate", icon: "cash-outline" as const, tier: "Auto" },
            { k: "review", label: "Review", icon: "list-outline" as const, tier: "" },
          ] as { k: Tab; label: string; icon: any; tier: string }[]
        ).map((t) => (
          <TouchableOpacity
            key={t.k}
            onPress={() => setTab(t.k)}
            style={[styles.tab, tab === t.k ? styles.tabActive : null]}
            testID={`llm-tab-${t.k}`}
          >
            <Ionicons name={t.icon} size={14} color={tab === t.k ? "#fff" : theme.colors.text} />
            <Text style={[styles.tabText, tab === t.k ? styles.tabTextActive : null]}>{t.label}</Text>
            {t.tier ? <Text style={[styles.tierBadge, tab === t.k ? styles.tierBadgeActive : null]}>{t.tier}</Text> : null}
          </TouchableOpacity>
        ))}
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
        {tab === "standardise" && <StandardisePanel />}
        {tab === "compare" && <ComparePanel />}
        {tab === "reconcile" && <ReconcilePanel />}
        {tab === "negotiate" && <NegotiatePanel />}
        {tab === "review" && <ReviewPanel />}
      </ScrollView>
    </SafeAreaView>
  );
}

// ---------- Standardise (Haiku) ----------

function StandardisePanel() {
  const [description, setDescription] = useState("");
  const [make, setMake] = useState("");
  const [modelStr, setModelStr] = useState("");
  const [unit, setUnit] = useState("");
  const [ctx, setCtx] = useState("");
  const [attachments, setAttachments] = useState<LlmAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<any | null>(null);

  const run = async () => {
    setErr("");
    if (!description.trim() && !attachments.length) { setErr("Description or an attachment is required."); return; }
    setBusy(true);
    setResult(null);
    try {
      const doc = await api<any>("/llm/item-standardise", {
        method: "POST",
        body: {
          description: description || "(see attachment)",
          make, model: modelStr, unit, context: ctx,
          attachments: attachments.length ? attachments : undefined,
        },
      });
      setResult(doc);
    } catch (e: any) { setErr(e?.message || "LLM call failed"); }
    setBusy(false);
  };

  return (
    <View>
      <H2>Standardise Item</H2>
      <Muted>Match free-text descriptions to MAT-#### / VAR-#### UIDs from the approved master. Optionally attach a BOQ PDF/Excel. Uses Claude Haiku 4.5 (cheap tier).</Muted>
      <Card style={{ marginTop: 10 }}>
        <Label>Description *</Label>
        <TextInput value={description} onChangeText={setDescription} placeholder='e.g. "CAT6 UTP cable 305m box"' style={styles.input} testID="std-desc" />
        <Label style={{ marginTop: 8 }}>Make</Label>
        <TextInput value={make} onChangeText={setMake} placeholder="D-Link, Digilink, …" style={styles.input} />
        <Label style={{ marginTop: 8 }}>Model</Label>
        <TextInput value={modelStr} onChangeText={setModelStr} placeholder="e.g. NCB-C6UGRYR-305" style={styles.input} />
        <Label style={{ marginTop: 8 }}>Unit / Context</Label>
        <TextInput value={unit} onChangeText={setUnit} placeholder="box, mtr, nos" style={styles.input} />
        <TextInput value={ctx} onChangeText={setCtx} placeholder="Context — e.g. structured cabling" style={[styles.input, { marginTop: 6 }]} />
        <LlmFilePicker
          attachments={attachments}
          onChange={setAttachments}
          max={3}
          label="Attach BOQ / indent (optional)"
          helperText="LLM will extract line items from your PDF / Excel and match against the approved master."
        />
      </Card>
      {err ? <Text style={styles.err}>{err}</Text> : null}
      <Btn testID="std-run" title={busy ? "Thinking…" : "Suggest matches"} variant="primary" onPress={run} disabled={busy} />
      {busy ? <ActivityIndicator style={{ marginTop: 10 }} /> : null}
      {result ? <StdResult doc={result} onDone={() => setResult(null)} /> : null}
    </View>
  );
}

function StdResult({ doc, onDone }: { doc: any; onDone: () => void }) {
  const suggestions = doc.output_parsed?.suggestions || [];
  return (
    <Card style={{ marginTop: 14, backgroundColor: "#EEF2FF" }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <Text style={{ fontWeight: "800" }}>Top matches</Text>
        <Pill status="pending_approval" />
      </View>
      {suggestions.length ? suggestions.map((s: any, i: number) => (
        <View key={i} style={styles.stdRow}>
          <View style={{ flex: 1 }}>
            <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
              {s.material_uid ? <Text style={styles.matChip}>MAT {s.material_uid}</Text> : null}
              {s.variant_uid ? <Text style={styles.varChip}>VAR {s.variant_uid}</Text> : null}
              <Text style={styles.conf}>{Math.round((s.confidence || 0) * 100)}%</Text>
            </View>
            <Text style={styles.stdDesc}>{s.matched_description || "—"}</Text>
            {s.reasoning ? <Muted>{s.reasoning}</Muted> : null}
          </View>
        </View>
      )) : <Muted>No plausible matches. Consider adding this item to Material Master.</Muted>}
      <DecisionRow sugId={doc.suggestion_id} onDone={onDone} />
    </Card>
  );
}

// ---------- Compare (Sonnet) ----------

function ComparePanel() {
  const [ctx, setCtx] = useState("");
  const [linkedId, setLinkedId] = useState("");
  const [quotes, setQuotes] = useState<any[]>([
    { vendor_name: "", items: [{ description: "", qty: 1, unit: "nos", rate: 0, gst: 18 }] },
    { vendor_name: "", items: [{ description: "", qty: 1, unit: "nos", rate: 0, gst: 18 }] },
  ]);
  const [attachments, setAttachments] = useState<LlmAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<any | null>(null);

  const updV = (i: number, k: string, v: any) => setQuotes((s) => s.map((q, idx) => idx === i ? { ...q, [k]: v } : q));
  const updI = (qi: number, ii: number, k: string, v: any) => setQuotes((s) => s.map((q, idx) => idx === qi ? { ...q, items: q.items.map((it: any, jj: number) => jj === ii ? { ...it, [k]: v } : it) } : q));
  const addVendor = () => setQuotes((s) => [...s, { vendor_name: "", items: [{ description: "", qty: 1, unit: "nos", rate: 0, gst: 18 }] }]);
  const addItem = (qi: number) => setQuotes((s) => s.map((q, idx) => idx === qi ? { ...q, items: [...q.items, { description: "", qty: 1, unit: "nos", rate: 0, gst: 18 }] } : q));
  const rmVendor = (i: number) => setQuotes((s) => s.filter((_, idx) => idx !== i));

  const run = async () => {
    setErr("");
    // With attachments, we can rely on LLM to parse; otherwise need ≥2 named vendors
    const namedQuotes = quotes.filter((q) => q.vendor_name.trim());
    if (namedQuotes.length + attachments.length < 2) {
      setErr("Provide at least 2 vendor quotes (either structured or attach vendor quotation files).");
      return;
    }
    setBusy(true); setResult(null);
    try {
      const doc = await api<any>("/llm/quotation-compare", {
        method: "POST",
        body: {
          context: ctx,
          mrf_id: linkedId.startsWith("mrf_") ? linkedId : "",
          po_id: linkedId.startsWith("po_") ? linkedId : "",
          quotes: namedQuotes,
          attachments: attachments.length ? attachments : undefined,
        },
      });
      setResult(doc);
    } catch (e: any) { setErr(e?.message || "LLM call failed"); }
    setBusy(false);
  };

  return (
    <View>
      <H2>Compare Vendor Quotes</H2>
      <Muted>Rank L1/L2/L3, per-item delta % and anomaly flags. Enter structured lines OR attach vendor PDFs/Excels and let the LLM parse them. Uses Claude Sonnet 4.5 (premium tier).</Muted>
      <Card style={{ marginTop: 10 }}>
        <Label>Context (optional)</Label>
        <TextInput value={ctx} onChangeText={setCtx} placeholder="MRF-2026-0287 — CAT6 procurement" style={styles.input} />
        <Label style={{ marginTop: 8 }}>Attach to (MRF or PO id, optional)</Label>
        <TextInput value={linkedId} onChangeText={setLinkedId} placeholder="mrf_… or po_…" style={styles.input} />
        <LlmFilePicker
          attachments={attachments}
          onChange={setAttachments}
          max={6}
          label="Vendor quotation files (optional)"
          helperText="Upload each vendor's quote (PDF/Excel/CSV). LLM will extract vendor name + line rates automatically."
        />
      </Card>
      {quotes.map((q, qi) => (
        <Card key={qi} style={{ marginTop: 10 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <TextInput value={q.vendor_name} onChangeText={(v) => updV(qi, "vendor_name", v)} placeholder={`Vendor ${qi + 1} (leave blank to skip)`} style={[styles.input, { flex: 1, fontWeight: "700" }]} />
            {quotes.length > 2 ? (
              <TouchableOpacity onPress={() => rmVendor(qi)} style={{ padding: 6 }}>
                <Ionicons name="trash-outline" size={16} color={theme.colors.danger} />
              </TouchableOpacity>
            ) : null}
          </View>
          {q.items.map((it: any, ii: number) => (
            <View key={ii} style={{ marginTop: 6, padding: 6, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 6 }}>
              <TextInput value={it.description} onChangeText={(v) => updI(qi, ii, "description", v)} placeholder="Description" style={styles.input} />
              <View style={{ flexDirection: "row", gap: 6, marginTop: 4 }}>
                <TextInput value={String(it.qty)} onChangeText={(v) => updI(qi, ii, "qty", parseFloat(v) || 0)} placeholder="Qty" keyboardType="decimal-pad" style={[styles.input, { flex: 1 }]} />
                <TextInput value={it.unit} onChangeText={(v) => updI(qi, ii, "unit", v)} placeholder="Unit" style={[styles.input, { flex: 1 }]} />
                <TextInput value={String(it.rate)} onChangeText={(v) => updI(qi, ii, "rate", parseFloat(v) || 0)} placeholder="Rate" keyboardType="decimal-pad" style={[styles.input, { flex: 1 }]} />
                <TextInput value={String(it.gst)} onChangeText={(v) => updI(qi, ii, "gst", parseFloat(v) || 0)} placeholder="GST %" keyboardType="decimal-pad" style={[styles.input, { width: 60 }]} />
              </View>
            </View>
          ))}
          <TouchableOpacity onPress={() => addItem(qi)} style={{ marginTop: 6 }}><Text style={{ color: theme.colors.primary, fontWeight: "700" }}>+ Add line</Text></TouchableOpacity>
        </Card>
      ))}
      <Btn title="+ Add vendor" variant="outline" onPress={addVendor} />
      {err ? <Text style={styles.err}>{err}</Text> : null}
      <Btn testID="cmp-run" title={busy ? "Comparing…" : "Compare"} variant="primary" onPress={run} disabled={busy} />
      {busy ? <ActivityIndicator style={{ marginTop: 10 }} /> : null}
      {result ? <CompareResult doc={result} onDone={() => setResult(null)} /> : null}
    </View>
  );
}

function CompareResult({ doc, onDone }: { doc: any; onDone: () => void }) {
  const p = doc.output_parsed || {};
  return (
    <Card style={{ marginTop: 14, backgroundColor: "#F0FDF4" }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <Text style={{ fontWeight: "800" }}>Ranking</Text>
        <Pill status="pending_approval" />
      </View>
      {(p.ranking || []).map((r: any, i: number) => (
        <View key={i} style={styles.rankRow}>
          <Text style={styles.rankTag}>L{r.rank}</Text>
          <View style={{ flex: 1 }}>
            <Text style={{ fontWeight: "700" }}>{r.vendor_name}</Text>
            <Muted>₹ {Number(r.total_with_tax || r.total_taxable || 0).toLocaleString("en-IN")}  ·  Δ vs L1: {r.delta_pct_vs_L1 ?? 0}%</Muted>
          </View>
        </View>
      ))}
      {p.recommendation ? (
        <View style={{ marginTop: 8, padding: 8, backgroundColor: "#DCFCE7", borderRadius: 6 }}>
          <Text style={{ fontWeight: "700", fontSize: 12 }}>Recommendation</Text>
          <Text style={{ fontSize: 12, marginTop: 2 }}>{p.recommendation}</Text>
        </View>
      ) : null}
      {p.anomalies?.length ? (
        <View style={{ marginTop: 8 }}>
          <Text style={{ fontWeight: "700", fontSize: 12 }}>Anomalies ({p.anomalies.length})</Text>
          {p.anomalies.slice(0, 5).map((a: any, i: number) => (
            <View key={i} style={styles.anomRow}>
              <Text style={styles.anomSev}>{(a.severity || "info").toUpperCase()}</Text>
              <Text style={{ flex: 1, fontSize: 11 }}>{a.reason}</Text>
            </View>
          ))}
        </View>
      ) : null}
      {p.summary ? <Muted style={{ marginTop: 6 }}>{p.summary}</Muted> : null}
      <DecisionRow sugId={doc.suggestion_id} onDone={onDone} />
    </Card>
  );
}

// ---------- Reconcile (Sonnet) ----------

function ReconcilePanel() {
  const [poId, setPoId] = useState("");
  const [attachments, setAttachments] = useState<LlmAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<any | null>(null);

  const run = async () => {
    setErr("");
    if (!poId.trim()) { setErr("PO id required."); return; }
    setBusy(true); setResult(null);
    try {
      const doc = await api<any>("/llm/reconcile", {
        method: "POST",
        body: {
          po_id: poId.trim(),
          attachments: attachments.length ? attachments : undefined,
        },
      });
      setResult(doc);
    } catch (e: any) { setErr(e?.message || "LLM call failed"); }
    setBusy(false);
  };

  return (
    <View>
      <H2>PO – GRN – Invoice 3-Way Match</H2>
      <Muted>Line-by-line qty + rate reconciliation with exception flags. Optionally attach vendor invoice PDFs so the LLM can cross-check totals. Uses Sonnet 4.5. Purchase/GM/Director gated.</Muted>
      <Card style={{ marginTop: 10 }}>
        <Label>PO ID</Label>
        <TextInput value={poId} onChangeText={setPoId} placeholder="po_xxx" style={styles.input} testID="rec-po" />
        <LlmFilePicker
          attachments={attachments}
          onChange={setAttachments}
          max={5}
          label="Vendor invoice files (optional)"
          helperText="Upload vendor invoice PDFs to include in the reconciliation."
        />
      </Card>
      {err ? <Text style={styles.err}>{err}</Text> : null}
      <Btn testID="rec-run" title={busy ? "Analysing…" : "Run 3-Way Match"} variant="primary" onPress={run} disabled={busy} />
      {busy ? <ActivityIndicator style={{ marginTop: 10 }} /> : null}
      {result ? <ReconcileResult doc={result} onDone={() => setResult(null)} /> : null}
    </View>
  );
}

function ReconcileResult({ doc, onDone }: { doc: any; onDone: () => void }) {
  const p = doc.output_parsed || {};
  const lines = p.per_line || [];
  const badge = (s: string) => {
    const color = s === "match" ? "#065F46" : s?.includes("mismatch") || s === "over_delivered" ? "#B91C1C" : "#B45309";
    return <Text style={[styles.recBadge, { color, borderColor: color }]}>{(s || "?").toUpperCase()}</Text>;
  };
  return (
    <Card style={{ marginTop: 14, backgroundColor: "#FEFCE8" }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <Text style={{ fontWeight: "800" }}>{p.po_number || doc.entity_id}</Text>
        <Pill status="pending_approval" />
      </View>
      {p.aggregate ? (
        <View style={{ flexDirection: "row", gap: 6, marginTop: 4 }}>
          <Text style={styles.aggPill}>PO ₹ {Number(p.aggregate.po_total || 0).toLocaleString("en-IN")}</Text>
          <Text style={styles.aggPill}>GRN ₹ {Number(p.aggregate.grn_total_est || 0).toLocaleString("en-IN")}</Text>
          <Text style={styles.aggPill}>Inv ₹ {Number(p.aggregate.invoice_total || 0).toLocaleString("en-IN")}</Text>
        </View>
      ) : null}
      <View style={{ marginTop: 8 }}>
        {lines.slice(0, 8).map((r: any, i: number) => (
          <View key={i} style={styles.recRow}>
            <View style={{ flex: 1 }}>
              <Text style={{ fontWeight: "700" }}>Line {r.line} — {r.description}</Text>
              <Muted>PO {r.po_qty} · GRN {r.grn_qty} · Inv {r.invoice_qty}  ·  Rate PO {r.po_rate} vs Inv {r.invoice_rate}</Muted>
            </View>
            {badge(r.status)}
          </View>
        ))}
      </View>
      {p.exceptions?.length ? (
        <View style={{ marginTop: 8 }}>
          <Text style={{ fontWeight: "700", fontSize: 12 }}>Exceptions</Text>
          {p.exceptions.slice(0, 6).map((e: any, i: number) => (
            <View key={i} style={styles.anomRow}>
              <Text style={[styles.anomSev, e.severity === "critical" ? { backgroundColor: "#DC2626", color: "#fff" } : null]}>{(e.severity || "info").toUpperCase()}</Text>
              <Text style={{ flex: 1, fontSize: 11 }}>{e.reason}</Text>
            </View>
          ))}
        </View>
      ) : null}
      {p.summary ? <Muted style={{ marginTop: 6 }}>{p.summary}</Muted> : null}
      <DecisionRow sugId={doc.suggestion_id} onDone={onDone} />
    </Card>
  );
}

// ---------- AI Purchase Manager (Negotiate) ----------

function NegotiatePanel() {
  const [description, setDescription] = useState("");
  const [make, setMake] = useState("");
  const [modelStr, setModelStr] = useState("");
  const [unit, setUnit] = useState("Nos");
  const [qty, setQty] = useState("1");
  const [vendorName, setVendorName] = useState("");
  const [rate, setRate] = useState("");
  const [freight, setFreight] = useState("0");
  const [gst, setGst] = useState("18");
  const [paymentTerms, setPaymentTerms] = useState("30 days");
  const [deliveryDays, setDeliveryDays] = useState("");
  const [warranty, setWarranty] = useState("");
  const [ctx, setCtx] = useState("");
  const [tier, setTier] = useState<"auto" | "cheap" | "premium">("auto");
  const [routePreview, setRoutePreview] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [aggBusy, setAggBusy] = useState(false);
  const [aggregates, setAggregates] = useState<any | null>(null);
  const [result, setResult] = useState<any | null>(null);
  const [err, setErr] = useState("");

  const previewRoute = useCallback(async () => {
    if (!description.trim()) { setRoutePreview(null); return; }
    try {
      const p = new URLSearchParams({
        description, make, model: modelStr,
        qty: qty || "0", rate: rate || "0",
      });
      const d = await api<any>(`/llm/purchase-analysis/route?${p.toString()}`);
      setRoutePreview(d);
    } catch {
      setRoutePreview(null);
    }
  }, [description, make, modelStr, qty, rate]);

  useEffect(() => { previewRoute(); }, [previewRoute]);

  const runAggregates = async () => {
    setErr(""); setAggregates(null);
    if (!description.trim()) { setErr("Description required"); return; }
    setAggBusy(true);
    try {
      const p = new URLSearchParams({ description });
      const d = await api<any>(`/llm/purchase-analysis/aggregates?${p.toString()}`);
      setAggregates(d);
    } catch (e: any) { setErr(e?.message || "aggregate failed"); }
    setAggBusy(false);
  };

  const runAnalysis = async () => {
    setErr(""); setResult(null);
    if (!description.trim()) { setErr("Description required"); return; }
    setBusy(true);
    try {
      const doc = await api<any>("/llm/purchase-analysis", {
        method: "POST",
        body: {
          description, make, model: modelStr, unit,
          qty: parseFloat(qty) || 1,
          context: ctx,
          tier,
          current_quote: rate ? {
            vendor_name: vendorName, make, model: modelStr, unit,
            qty: parseFloat(qty) || 1, rate: parseFloat(rate) || 0,
            gst: parseFloat(gst) || 18, freight: parseFloat(freight) || 0,
            payment_terms: paymentTerms,
            delivery_days: deliveryDays ? parseInt(deliveryDays, 10) : undefined,
            warranty,
          } : undefined,
        },
      });
      setResult(doc);
    } catch (e: any) { setErr(e?.message || "Analysis failed"); }
    setBusy(false);
  };

  const parsed = result?.output_parsed || {};
  const computed = parsed._computed_by_server || {};
  const routing = computed.routing || {};
  const history = parsed.history || {};
  const market = parsed.market_benchmark || {};
  const variance = parsed.variance || {};
  const decisionColor: any = {
    issue_at_target: "#065F46", ok_current: "#065F46",
    negotiate_more: "#B45309", reject_and_retender: "#B91C1C",
  }[parsed.decision] || theme.colors.muted;

  return (
    <View>
      <H2>Negotiate — AI Purchase Manager</H2>
      <Muted>
        Aggregates history from POs, invoices, GRNs, DCs, comparative statements, then benchmarks
        against market indicators. Every field is tagged verified / estimated.
      </Muted>

      <Card style={{ marginTop: 12 }}>
        <Label>Item description *</Label>
        <TextInput style={styles.input} placeholder="e.g. Cat6 UTP cable 305m box"
          value={description} onChangeText={setDescription} />
        <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
          <View style={{ flex: 1 }}><Label>Make</Label>
            <TextInput style={styles.input} placeholder="e.g. D-Link" value={make} onChangeText={setMake} /></View>
          <View style={{ flex: 1 }}><Label>Model</Label>
            <TextInput style={styles.input} placeholder="e.g. NCB-C6UGRYR-305" value={modelStr} onChangeText={setModelStr} /></View>
        </View>
        <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
          <View style={{ flex: 1 }}><Label>Unit</Label>
            <TextInput style={styles.input} value={unit} onChangeText={setUnit} /></View>
          <View style={{ flex: 1 }}><Label>Quantity</Label>
            <TextInput style={styles.input} value={qty} onChangeText={setQty} keyboardType="decimal-pad" /></View>
        </View>

        {routePreview ? (
          <View style={styles.routeBar}>
            <Ionicons name="hardware-chip-outline" size={14} color="#3730A3" />
            <Text style={styles.routeText}>
              AI: <Text style={{ fontWeight: "700" }}>{routePreview.model_label}</Text>
              {"  ·  "}reason: {routePreview.reason}
              {routePreview.matched_keyword ? `  ·  keyword: ${routePreview.matched_keyword}` : ""}
            </Text>
          </View>
        ) : null}
      </Card>

      <Card style={{ marginTop: 12 }}>
        <Text style={styles.sectionTitle}>Current vendor quote (optional but recommended)</Text>
        <Label>Vendor</Label>
        <TextInput style={styles.input} value={vendorName} onChangeText={setVendorName} placeholder="e.g. SecureAlarm India" />
        <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
          <View style={{ flex: 1 }}><Label>Rate ₹</Label>
            <TextInput style={styles.input} value={rate} onChangeText={setRate} keyboardType="decimal-pad" /></View>
          <View style={{ flex: 1 }}><Label>Freight ₹</Label>
            <TextInput style={styles.input} value={freight} onChangeText={setFreight} keyboardType="decimal-pad" /></View>
          <View style={{ flex: 1 }}><Label>GST %</Label>
            <TextInput style={styles.input} value={gst} onChangeText={setGst} keyboardType="decimal-pad" /></View>
        </View>
        <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
          <View style={{ flex: 1 }}><Label>Payment terms</Label>
            <TextInput style={styles.input} value={paymentTerms} onChangeText={setPaymentTerms} placeholder="e.g. 30 days credit" /></View>
          <View style={{ flex: 1 }}><Label>Delivery (days)</Label>
            <TextInput style={styles.input} value={deliveryDays} onChangeText={setDeliveryDays} keyboardType="number-pad" /></View>
          <View style={{ flex: 1 }}><Label>Warranty</Label>
            <TextInput style={styles.input} value={warranty} onChangeText={setWarranty} placeholder="e.g. 3Y" /></View>
        </View>
        <Label style={{ marginTop: 8 }}>Context / notes</Label>
        <TextInput style={[styles.input, { minHeight: 48 }]} value={ctx} onChangeText={setCtx} multiline
          placeholder="e.g. Bangalore retrofit, urgent, alternative L1 available" />
      </Card>

      <Card style={{ marginTop: 12 }}>
        <Label>LLM tier</Label>
        <View style={{ flexDirection: "row", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
          {(["auto", "cheap", "premium"] as const).map((t) => (
            <TouchableOpacity key={t} onPress={() => setTier(t)}
              style={[styles.tierChip, tier === t ? styles.tierChipActive : null]}>
              <Text style={[styles.tierChipText, tier === t ? styles.tierChipTextActive : null]}>
                {t === "auto" ? "Auto (recommended)" :
                 t === "cheap" ? "GPT-4o-mini (₹0.03–₹0.20)" :
                 "Sonnet 4.5 (₹15–₹40, override)"}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
          <Btn variant="secondary" onPress={runAggregates} disabled={aggBusy}>
            {aggBusy ? "Loading…" : "Preview history (free)"}
          </Btn>
          <Btn onPress={runAnalysis} disabled={busy}>
            {busy ? "Analysing…" : "Run analysis"}
          </Btn>
        </View>
        {err ? <Text style={styles.err}>{err}</Text> : null}
      </Card>

      {aggregates ? (
        <Card style={{ marginTop: 12 }}>
          <Text style={styles.sectionTitle}>Verified history — data coverage</Text>
          <View style={styles.covRow}>
            <Kpi label="PO lines" value={aggregates.matched_po_lines} />
            <Kpi label="Invoices" value={aggregates.matched_invoices} />
            <Kpi label="GRNs" value={aggregates.matched_grns} />
            <Kpi label="Vendors" value={aggregates.unique_vendors} />
          </View>
          {aggregates.stats_unit_landed_inr?.count ? (
            <View style={{ marginTop: 10 }}>
              <Muted>Landed cost / unit history (₹)</Muted>
              <View style={styles.statRow}>
                <StatCell label="Lowest" value={aggregates.stats_unit_landed_inr.lowest} />
                <StatCell label="Median" value={aggregates.stats_unit_landed_inr.median} />
                <StatCell label="Average" value={aggregates.stats_unit_landed_inr.average} />
                <StatCell label="Highest" value={aggregates.stats_unit_landed_inr.highest} />
              </View>
              {aggregates.last_purchase ? (
                <Muted>
                  Last purchase: ₹{aggregates.last_purchase.rate} from{" "}
                  {aggregates.last_purchase.vendor_name || aggregates.last_purchase.vendor_id}
                  {aggregates.last_purchase.po_number ? ` · ${aggregates.last_purchase.po_number}` : ""}
                </Muted>
              ) : null}
              {aggregates.recent_trend_pct !== null ? (
                <Muted>90-day trend: {aggregates.recent_trend_pct > 0 ? "↑" : "↓"} {Math.abs(aggregates.recent_trend_pct)}%</Muted>
              ) : null}
            </View>
          ) : <Muted>No verified historical rates for this description.</Muted>}
        </Card>
      ) : null}

      {result ? (
        <Card style={{ marginTop: 12 }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            <Text style={styles.sectionTitle}>Analysis</Text>
            <Pill status={parsed.decision === "issue_at_target" || parsed.decision === "ok_current" ? "approved" :
                          parsed.decision === "reject_and_retender" ? "rejected" : "pending"} />
          </View>
          <Muted>
            Model: <Text style={{ fontWeight: "600" }}>{result.model}</Text> · tier: {result.tier} · routing: {routing.reason || "—"}
            {routing.matched_keyword ? ` · kw: ${routing.matched_keyword}` : ""}
          </Muted>

          {/* --- COST & TOKENS BREAKDOWN ---------------------------------- */}
          {result.cost ? (
            <View style={styles.costCard}>
              <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                <Text style={styles.costTitle}>
                  Cost this call {result.cached ? "· CACHE HIT (₹0)" : ""}
                </Text>
                <Text style={styles.costTotal}>
                  ₹{result.cost.cost_inr ?? 0}
                </Text>
              </View>
              <View style={styles.costGrid}>
                <View style={styles.costCell}>
                  <Text style={styles.costCellV}>{result.cost.input_tokens_approx ?? 0}</Text>
                  <Text style={styles.costCellL}>input tok (~)</Text>
                </View>
                <View style={styles.costCell}>
                  <Text style={styles.costCellV}>{result.cost.output_tokens_approx ?? 0}</Text>
                  <Text style={styles.costCellL}>output tok (~)</Text>
                </View>
                <View style={styles.costCell}>
                  <Text style={styles.costCellV}>${result.cost.input_rate_usd_per_m ?? "—"}</Text>
                  <Text style={styles.costCellL}>in $/M</Text>
                </View>
                <View style={styles.costCell}>
                  <Text style={styles.costCellV}>${result.cost.output_rate_usd_per_m ?? "—"}</Text>
                  <Text style={styles.costCellL}>out $/M</Text>
                </View>
                <View style={styles.costCell}>
                  <Text style={styles.costCellV}>${result.cost.cost_usd ?? "—"}</Text>
                  <Text style={styles.costCellL}>USD</Text>
                </View>
              </View>
              <Text style={styles.costFootnote}>
                Token counts are approximate (chars ÷ 3.6). Actual billing runs against the
                Emergent Universal Key balance.
              </Text>
            </View>
          ) : null}
          {/* --- END COST CARD -------------------------------------------- */}

          <View style={styles.summaryBox}>
            <Text style={styles.summaryText}>{parsed.commercial_summary || "(no commercial summary)"}</Text>
          </View>

          <View style={styles.numberGrid}>
            <NumCell label="Current landed / unit" value={computed.current_quote_landed_cost_per_unit} suffix="₹" />
            <NumCell label="Target price" value={parsed.recommended_target_price_per_unit} suffix="₹" emphasis />
            <NumCell label="Negotiate to" value={parsed.recommended_negotiated_price_per_unit} suffix="₹" emphasis />
            <NumCell label="Saving %" value={parsed.expected_saving_pct} suffix="%" emphasis color="#065F46" />
            <NumCell label="Total saving" value={parsed.expected_saving_total} suffix="₹" color="#065F46" />
            <NumCell label="Confidence" value={parsed.confidence !== undefined ? parsed.confidence : null} />
          </View>

          <Text style={styles.pillGroupLabel}>Decision:</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
            <Text style={[styles.decisionPill, { backgroundColor: decisionColor + "20", color: decisionColor }]}>
              {parsed.decision?.replace(/_/g, " ") || "—"}
            </Text>
          </View>

          {parsed.negotiation_tactics?.length ? (
            <>
              <Text style={styles.pillGroupLabel}>Negotiation tactics:</Text>
              {parsed.negotiation_tactics.map((t: string, i: number) => (
                <View key={i} style={styles.tacticRow}>
                  <Text style={styles.tacticBullet}>▸</Text>
                  <Text style={styles.tacticText}>{t}</Text>
                </View>
              ))}
            </>
          ) : null}

          <Text style={styles.pillGroupLabel}>Historical & market context:</Text>
          <View style={styles.tableGrid}>
            <Row label="Last purchase" value={history.last_purchase_rate ? `₹${history.last_purchase_rate}` : "—"} sub={history.last_supplier || ""} />
            <Row label="Historical low" value={history.historical_lowest_rate ? `₹${history.historical_lowest_rate}` : "—"} />
            <Row label="Historical avg" value={history.historical_average_rate ? `₹${history.historical_average_rate}` : "—"} />
            <Row label="Trend 90d" value={history.trend_last_90_days_pct !== null && history.trend_last_90_days_pct !== undefined ? `${history.trend_last_90_days_pct}%` : "—"} />
            <Row label={`Market ref (${market.commodity_link || "n/a"})`}
                 value={market.value_per_unit ? `₹${market.value_per_unit}` : "—"}
                 sub={market.source_note || ""} estimated />
            <Row label="vs Last" value={variance.current_vs_last_pct !== null && variance.current_vs_last_pct !== undefined ? `${variance.current_vs_last_pct}%` : "—"} />
            <Row label="vs Market" value={variance.current_vs_market_pct !== null && variance.current_vs_market_pct !== undefined ? `${variance.current_vs_market_pct}%` : "—"} estimated />
          </View>

          {parsed.verified_fields?.length || parsed.estimated_fields?.length ? (
            <View style={{ marginTop: 10 }}>
              <Text style={styles.pillGroupLabel}>Data provenance:</Text>
              {parsed.verified_fields?.length ? (
                <Text style={styles.provenance}>
                  <Text style={styles.badgeVerified}> ✓ VERIFIED </Text> {parsed.verified_fields.join(", ")}
                </Text>
              ) : null}
              {parsed.estimated_fields?.length ? (
                <Text style={styles.provenance}>
                  <Text style={styles.badgeEstimated}> ~ ESTIMATED </Text> {parsed.estimated_fields.join(", ")}
                </Text>
              ) : null}
            </View>
          ) : null}

          {parsed.vendor_red_flags?.length ? (
            <View style={{ marginTop: 10 }}>
              <Text style={[styles.pillGroupLabel, { color: "#B91C1C" }]}>Vendor red flags:</Text>
              {parsed.vendor_red_flags.map((f: string, i: number) => (
                <Text key={i} style={styles.flagText}>⚠ {f}</Text>
              ))}
            </View>
          ) : null}

          {parsed.assumptions?.length ? (
            <>
              <Text style={styles.pillGroupLabel}>Assumptions / gaps:</Text>
              {parsed.assumptions.map((a: string, i: number) => (
                <Muted key={i}>• {a}</Muted>
              ))}
            </>
          ) : null}

          <Muted style={{ marginTop: 10, fontSize: 11 }}>
            Suggestion ID: {result.suggestion_id} · saved in AI (pending human review)
          </Muted>
        </Card>
      ) : null}
    </View>
  );
}

// --- Small helper components used by NegotiatePanel ---
function Kpi({ label, value }: { label: string; value: any }) {
  return (
    <View style={styles.kpiCell}>
      <Text style={styles.kpiValue}>{value ?? 0}</Text>
      <Text style={styles.kpiLabel}>{label}</Text>
    </View>
  );
}
function StatCell({ label, value }: { label: string; value: any }) {
  return (
    <View style={styles.statCell}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={styles.statValue}>{value !== null && value !== undefined ? `₹${value}` : "—"}</Text>
    </View>
  );
}
function NumCell({ label, value, suffix, emphasis, color }: any) {
  const display = value !== null && value !== undefined && value !== ""
    ? (suffix === "%" ? `${value}${suffix}` : `${suffix || ""}${value}`)
    : "—";
  return (
    <View style={[styles.numCell, emphasis ? styles.numCellEmph : null]}>
      <Text style={[styles.numValue, color ? { color } : null]}>{display}</Text>
      <Text style={styles.numLabel}>{label}</Text>
    </View>
  );
}
function Row({ label, value, sub, estimated }: { label: string; value: string; sub?: string; estimated?: boolean }) {
  return (
    <View style={styles.tableRow}>
      <Text style={styles.tableLabel}>
        {label}
        {estimated ? <Text style={styles.badgeEstimatedInline}> ~est</Text> : null}
      </Text>
      <View style={{ flex: 1, alignItems: "flex-end" }}>
        <Text style={styles.tableValue}>{value}</Text>
        {sub ? <Text style={styles.tableSub} numberOfLines={2}>{sub}</Text> : null}
      </View>
    </View>
  );
}


// ---------- Review pending suggestions ----------

function ReviewPanel() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<"pending_review" | "accepted" | "rejected">("pending_review");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<any[]>(`/llm/suggestions?status=${status}&limit=50`);
      setRows(data || []);
    } catch { setRows([]); }
    setLoading(false);
  }, [status]);

  useEffect(() => { load(); }, [load]);

  return (
    <View>
      <H2>Review</H2>
      <View style={{ flexDirection: "row", gap: 6, marginTop: 6 }}>
        {(["pending_review", "accepted", "rejected"] as const).map((s) => (
          <TouchableOpacity key={s} onPress={() => setStatus(s)}
            style={[styles.subTab, status === s ? styles.subTabActive : null]}>
            <Text style={[styles.subTabText, status === s ? styles.subTabTextActive : null]}>
              {s === "pending_review" ? "Pending" : s === "accepted" ? "Accepted" : "Rejected"}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
      {loading ? <ActivityIndicator style={{ marginTop: 12 }} /> : null}
      {!loading && !rows.length ? <Muted>No suggestions in this bucket.</Muted> : null}
      {rows.map((r) => (
        <Card key={r.suggestion_id} style={{ marginTop: 8 }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            <Text style={{ fontWeight: "700" }}>
              {r.kind === "item_standardise" ? "Standardise" : r.kind === "quotation_compare" ? "Compare Quotes" : "3-Way Match"}
              <Text style={{ color: theme.colors.textMuted, fontWeight: "600" }}> · {r.tier || "—"}</Text>
            </Text>
            <Pill status={r.status || "pending_review"} />
          </View>
          <Muted>{r.created_by_name || r.created_by} ({(r.created_by_role || "").toUpperCase()}) · {new Date(r.created_at).toLocaleString()}</Muted>
          {r.entity_id ? <Muted>Entity: {r.entity}:{r.entity_id}</Muted> : null}
          <Text style={{ fontSize: 11, color: theme.colors.textMuted, marginTop: 4 }} numberOfLines={3}>
            {JSON.stringify(r.output_parsed || {}).slice(0, 240)}…
          </Text>
          {r.decision ? (
            <Text style={{ fontSize: 11, marginTop: 4 }}>
              <Text style={{ fontWeight: "700" }}>{r.decision.toUpperCase()}</Text>{" "}by {r.decided_by_name || r.decided_by} on {new Date(r.decided_at).toLocaleString()}
              {r.decision_reason ? " — " + r.decision_reason : ""}
            </Text>
          ) : (
            <DecisionRow sugId={r.suggestion_id} onDone={load} compact />
          )}
        </Card>
      ))}
    </View>
  );
}

// ---------- Shared decision row ----------

function DecisionRow({ sugId, onDone, compact }: { sugId: string; onDone: () => void; compact?: boolean }) {
  const [busy, setBusy] = useState<null | "accept" | "reject">(null);
  const [reason, setReason] = useState("");
  const act = async (action: "accept" | "reject") => {
    if (action === "reject" && !reason.trim()) {
      Alert.alert("Reason required", "Please add a rejection reason.");
      return;
    }
    setBusy(action);
    try {
      await api(`/llm/suggestions/${sugId}/decide`, { method: "POST", body: { action, reason } });
      onDone();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Failed");
    }
    setBusy(null);
  };
  return (
    <View style={{ marginTop: 10, gap: 6 }}>
      {!compact ? (
        <TextInput value={reason} onChangeText={setReason} placeholder="Reason / remark (required for reject)" style={styles.input} testID={`decide-reason-${sugId}`} />
      ) : null}
      <View style={{ flexDirection: "row", gap: 6 }}>
        <View style={{ flex: 1 }}><Btn testID={`decide-accept-${sugId}`} title={busy === "accept" ? "Accepting…" : "✓ Accept"} variant="primary" onPress={() => act("accept")} disabled={!!busy} /></View>
        <View style={{ flex: 1 }}><Btn testID={`decide-reject-${sugId}`} title={busy === "reject" ? "Rejecting…" : "✕ Reject"} variant="outline" onPress={() => act("reject")} disabled={!!busy} /></View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 4, paddingVertical: 8, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  title: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  safety: { flexDirection: "row", alignItems: "center", gap: 6, padding: 8, backgroundColor: "#D1FAE5" },
  safetyText: { fontSize: 11, color: "#065F46", flex: 1 },
  tabs: { flexDirection: "row", padding: 8, gap: 4, backgroundColor: theme.colors.bg, borderBottomWidth: 1, borderBottomColor: theme.colors.border, flexWrap: "wrap" },
  tab: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, backgroundColor: "#fff", borderWidth: 1, borderColor: theme.colors.border },
  tabActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  tabText: { fontSize: 12, fontWeight: "700", color: theme.colors.text },
  tabTextActive: { color: "#fff" },
  tierBadge: { fontSize: 9, color: theme.colors.textMuted, backgroundColor: "#F3F4F6", paddingHorizontal: 4, borderRadius: 3, marginLeft: 3 },
  tierBadgeActive: { backgroundColor: "#fff", color: theme.colors.primary },
  input: { borderWidth: 1, borderColor: theme.colors.border, backgroundColor: "#fff", borderRadius: 6, padding: 8, fontSize: 13 },
  err: { color: theme.colors.danger, backgroundColor: "#FEF2F2", padding: 8, borderRadius: 6, marginTop: 8, fontSize: 12 },
  stdRow: { flexDirection: "row", gap: 8, paddingVertical: 6, borderTopWidth: 1, borderTopColor: theme.colors.border, marginTop: 6 },
  stdDesc: { fontSize: 13, fontWeight: "700", marginTop: 3 },
  matChip: { backgroundColor: "#EEF2FF", color: "#3730A3", fontSize: 11, fontWeight: "700", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  varChip: { backgroundColor: "#ECFCCB", color: "#3F6212", fontSize: 11, fontWeight: "700", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  conf: { backgroundColor: "#DBEAFE", color: "#1E40AF", fontSize: 11, fontWeight: "800", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  rankRow: { flexDirection: "row", gap: 8, alignItems: "center", paddingVertical: 6, borderTopWidth: 1, borderTopColor: theme.colors.border, marginTop: 6 },
  rankTag: { backgroundColor: theme.colors.primary, color: "#fff", paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999, fontWeight: "800", fontSize: 11 },
  anomRow: { flexDirection: "row", gap: 6, alignItems: "center", marginTop: 4 },
  anomSev: { fontSize: 9, fontWeight: "800", backgroundColor: "#FEF3C7", color: "#92400E", paddingHorizontal: 5, paddingVertical: 1, borderRadius: 3 },
  aggPill: { backgroundColor: "#F3F4F6", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, fontSize: 10, fontWeight: "700" },
  recRow: { flexDirection: "row", gap: 6, alignItems: "flex-start", paddingVertical: 6, borderTopWidth: 1, borderTopColor: theme.colors.border },
  recBadge: { fontSize: 9, fontWeight: "800", paddingHorizontal: 5, paddingVertical: 2, borderRadius: 3, borderWidth: 1 },
  subTab: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: "#fff" },
  subTabActive: { backgroundColor: theme.colors.action, borderColor: theme.colors.action },
  subTabText: { fontSize: 11, fontWeight: "700", color: theme.colors.text },
  subTabTextActive: { color: "#fff" },
  // ---- Negotiate panel styles ----
  sectionTitle: { fontSize: 14, fontWeight: "700", color: theme.colors.text, marginBottom: 6 },
  routeBar: {
    flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10,
    backgroundColor: "#EEF2FF", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6,
  },
  routeText: { fontSize: 11, color: "#3730A3", flex: 1 },
  tierChip: {
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999,
    borderWidth: 1, borderColor: theme.colors.border, backgroundColor: "#fff",
  },
  tierChipActive: { backgroundColor: theme.colors.action, borderColor: theme.colors.action },
  tierChipText: { fontSize: 11, fontWeight: "700", color: theme.colors.text },
  tierChipTextActive: { color: "#fff" },
  covRow: { flexDirection: "row", gap: 8, marginTop: 4 },
  kpiCell: {
    flex: 1, backgroundColor: "#F7F8FC", borderRadius: 6, padding: 8, alignItems: "center",
  },
  kpiValue: { fontSize: 16, fontWeight: "800", color: theme.colors.text },
  kpiLabel: { fontSize: 10, color: theme.colors.textMuted },
  statRow: { flexDirection: "row", gap: 8, marginTop: 6, marginBottom: 6 },
  statCell: { flex: 1, backgroundColor: "#F7F8FC", borderRadius: 6, padding: 6, alignItems: "center" },
  statLabel: { fontSize: 10, color: theme.colors.textMuted },
  statValue: { fontSize: 13, fontWeight: "700", color: theme.colors.text },
  summaryBox: {
    backgroundColor: "#F7F8FC", padding: 10, borderRadius: 6, marginVertical: 10,
    borderLeftWidth: 3, borderLeftColor: theme.colors.action,
  },
  summaryText: { fontSize: 12, color: theme.colors.text, lineHeight: 17 },
  numberGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 6 },
  numCell: {
    minWidth: "31%", flexGrow: 1, borderWidth: 1, borderColor: theme.colors.border,
    borderRadius: 6, padding: 8, backgroundColor: "#fff",
  },
  numCellEmph: { borderColor: theme.colors.action, backgroundColor: "#EEF2FF" },
  numValue: { fontSize: 15, fontWeight: "800", color: theme.colors.text },
  numLabel: { fontSize: 10, color: theme.colors.textMuted, marginTop: 2 },
  pillGroupLabel: { fontSize: 11, fontWeight: "700", color: theme.colors.text, marginTop: 12, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.4 },
  decisionPill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, fontSize: 12, fontWeight: "800", textTransform: "uppercase" },
  tacticRow: { flexDirection: "row", gap: 6, marginTop: 4 },
  tacticBullet: { color: theme.colors.action, fontWeight: "800" },
  tacticText: { flex: 1, fontSize: 12, color: theme.colors.text, lineHeight: 17 },
  tableGrid: { marginTop: 6, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 6, overflow: "hidden" },
  tableRow: { flexDirection: "row", paddingVertical: 6, paddingHorizontal: 8, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  tableLabel: { flex: 1, fontSize: 12, color: theme.colors.textMuted },
  tableValue: { fontSize: 12, fontWeight: "700", color: theme.colors.text, textAlign: "right" },
  tableSub: { fontSize: 10, color: theme.colors.textMuted, textAlign: "right" },
  badgeVerified: { backgroundColor: "#D1FAE5", color: "#065F46", fontSize: 9, fontWeight: "800", paddingHorizontal: 4, paddingVertical: 1, borderRadius: 3 },
  badgeEstimated: { backgroundColor: "#FEF3C7", color: "#B45309", fontSize: 9, fontWeight: "800", paddingHorizontal: 4, paddingVertical: 1, borderRadius: 3 },
  badgeEstimatedInline: { backgroundColor: "#FEF3C7", color: "#B45309", fontSize: 9, fontWeight: "700", paddingHorizontal: 3, borderRadius: 2 },
  provenance: { fontSize: 11, color: theme.colors.text, marginTop: 4, lineHeight: 16 },
  flagText: { fontSize: 12, color: "#B91C1C", marginTop: 2 },
  costCard: {
    marginTop: 10, padding: 10, borderRadius: 8,
    backgroundColor: "#F0F9FF", borderWidth: 1, borderColor: "#93C5FD",
  },
  costTitle: { fontSize: 11, fontWeight: "700", color: "#1E40AF", textTransform: "uppercase", letterSpacing: 0.5 },
  costTotal: { fontSize: 16, fontWeight: "800", color: "#1E3A8A" },
  costGrid: { flexDirection: "row", gap: 6, marginTop: 8 },
  costCell: { flex: 1, alignItems: "center", paddingVertical: 4 },
  costCellV: { fontSize: 12, fontWeight: "700", color: "#1E3A8A" },
  costCellL: { fontSize: 9, color: "#3B82F6", marginTop: 2 },
  costFootnote: { fontSize: 10, color: "#64748B", marginTop: 8, fontStyle: "italic" },
});
