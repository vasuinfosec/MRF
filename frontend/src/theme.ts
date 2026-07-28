// ViL AI Prompt Control — design tokens — high-contrast industrial theme
export const theme = {
  colors: {
    bg: "#FFFFFF",
    surface: "#F8FAFC",
    surface2: "#F1F5F9",
    border: "#E2E8F0",
    borderStrong: "#CBD5E1",
    text: "#0F172A",
    textSecondary: "#475569",
    textMuted: "#64748B",
    primary: "#002FA7",
    primaryHover: "#002480",
    action: "#F97316",
    actionHover: "#EA580C",
    danger: "#DC2626",
    success: "#059669",
  },
  status: {
    draft: { bg: "#F1F5F9", text: "#334155", border: "#94A3B8" },
    // Canonical Phase-3 statuses
    submitted: { bg: "#DBEAFE", text: "#1E40AF", border: "#60A5FA" },
    under_pm_review: { bg: "#FEF3C7", text: "#92400E", border: "#FBBF24" },
    under_purchase_review: { bg: "#CFFAFE", text: "#155E75", border: "#22D3EE" },
    under_gm_review: { bg: "#EDE9FE", text: "#5B21B6", border: "#A78BFA" },
    under_director_review: { bg: "#FCE7F3", text: "#9D174D", border: "#F472B6" },
    under_review: { bg: "#FEF3C7", text: "#92400E", border: "#FBBF24" },
    authorised: { bg: "#D1FAE5", text: "#065F46", border: "#34D399" },
    purchase_pending: { bg: "#CFFAFE", text: "#155E75", border: "#22D3EE" },
    quotation_received: { bg: "#DBEAFE", text: "#1E40AF", border: "#60A5FA" },
    po_pending: { bg: "#FEF3C7", text: "#92400E", border: "#FBBF24" },
    po_issued: { bg: "#E0E7FF", text: "#3730A3", border: "#818CF8" },
    fully_received: { bg: "#D1FAE5", text: "#065F46", border: "#34D399" },
    cancelled: { bg: "#F3F4F6", text: "#4B5563", border: "#9CA3AF" },
    // Legacy status colors (kept for backwards-compat)
    pm_review: { bg: "#FEF3C7", text: "#92400E", border: "#FBBF24" },
    approved: { bg: "#D1FAE5", text: "#065F46", border: "#34D399" },
    rejected: { bg: "#FEE2E2", text: "#991B1B", border: "#F87171" },
    returned: { bg: "#E0E7FF", text: "#3730A3", border: "#818CF8" },
    sent_to_purchase: { bg: "#CFFAFE", text: "#155E75", border: "#22D3EE" },
    partially_ordered: { bg: "#FEF3C7", text: "#92400E", border: "#FBBF24" },
    fully_ordered: { bg: "#D1FAE5", text: "#065F46", border: "#34D399" },
    received: { bg: "#D1FAE5", text: "#065F46", border: "#34D399" },
    partially_received: { bg: "#FEF3C7", text: "#92400E", border: "#FBBF24" },
    closed: { bg: "#F1F5F9", text: "#334155", border: "#94A3B8" },
    not_billed: { bg: "#FEE2E2", text: "#991B1B", border: "#F87171" },
    partially_billed: { bg: "#FEF3C7", text: "#92400E", border: "#FBBF24" },
    fully_billed: { bg: "#D1FAE5", text: "#065F46", border: "#34D399" },
    non_billable: { bg: "#F1F5F9", text: "#475569", border: "#94A3B8" },
    // DC / CS statuses
    issued: { bg: "#E0E7FF", text: "#3730A3", border: "#818CF8" },
    in_transit: { bg: "#FEF3C7", text: "#92400E", border: "#FBBF24" },
    delivered: { bg: "#D1FAE5", text: "#065F46", border: "#34D399" },
    outbound: { bg: "#DBEAFE", text: "#1E40AF", border: "#60A5FA" },
    inbound: { bg: "#EDE9FE", text: "#5B21B6", border: "#A78BFA" },
    active: { bg: "#D1FAE5", text: "#065F46", border: "#34D399" },
    superseded: { bg: "#F3F4F6", text: "#4B5563", border: "#9CA3AF" },
    pending_approval: { bg: "#FEF3C7", text: "#92400E", border: "#FBBF24" },
  } as Record<string, { bg: string; text: string; border: string }>,
  space: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 },
  radius: { sm: 4, md: 6, lg: 10 },
  font: {
    heading: "System",
    body: "System",
  },
};

export const STATUS_LABELS: Record<string, string> = {
  all: "All",
  draft: "Draft",
  submitted: "Submitted",
  under_review: "Under PM Review",
  pm_review: "Under PM Review",
  under_pm_review: "Under PM Review",
  under_purchase_review: "Under Purchase Review",
  under_gm_review: "Under GM Review",
  under_director_review: "Under Director Review",
  authorised: "Authorised",
  approved: "Authorised",
  rejected: "Rejected",
  returned: "Returned for Correction",
  purchase_pending: "Purchase Pending",
  sent_to_purchase: "Purchase Pending",
  quotation_received: "Quotation Received",
  po_pending: "PO Pending",
  po_issued: "PO Issued",
  partially_ordered: "PO Issued",
  fully_ordered: "PO Issued",
  partially_received: "Partially Received",
  fully_received: "Fully Received",
  received: "Fully Received",
  closed: "Closed",
  cancelled: "Cancelled",
};

export const statusLabel = (s: string) =>
  STATUS_LABELS[s] || s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// Full canonical status list (17 statuses per Phase 3b spec)
export const MRF_ALL_STATUSES = [
  "draft", "submitted", "under_pm_review",
  "under_purchase_review", "under_gm_review", "under_director_review",
  "authorised", "rejected", "returned",
  "purchase_pending", "quotation_received", "po_pending",
  "po_issued", "partially_received", "fully_received",
  "closed", "cancelled",
];

// Legacy → canonical alias (mirrors backend MRF_STATUS_ALIAS)
export const STATUS_ALIAS: Record<string, string> = {
  submitted: "under_pm_review",
  pm_review: "under_pm_review",
  under_review: "under_pm_review",
  approved: "authorised",
  sent_to_purchase: "purchase_pending",
  partially_ordered: "po_issued",
  fully_ordered: "po_issued",
  received: "fully_received",
};
export const canonicalStatus = (s?: string) =>
  s ? (STATUS_ALIAS[s] || s) : "";
