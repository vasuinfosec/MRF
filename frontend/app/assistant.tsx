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

type Tab = "standardise" | "compare" | "reconcile" | "review";

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
            { k: "standardise", label: "Standardise", icon: "sparkles-outline" as const, tier: "Haiku" },
            { k: "compare", label: "Compare Quotes", icon: "swap-vertical-outline" as const, tier: "Sonnet" },
            { k: "reconcile", label: "3-Way Match", icon: "git-compare-outline" as const, tier: "Sonnet" },
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
});
