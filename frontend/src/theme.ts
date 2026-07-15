// Vasu Infosec design tokens — high-contrast industrial theme
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
    submitted: { bg: "#DBEAFE", text: "#1E40AF", border: "#60A5FA" },
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
  } as Record<string, { bg: string; text: string; border: string }>,
  space: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 },
  radius: { sm: 4, md: 6, lg: 10 },
  font: {
    heading: "System",
    body: "System",
  },
};

export const statusLabel = (s: string) =>
  s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
