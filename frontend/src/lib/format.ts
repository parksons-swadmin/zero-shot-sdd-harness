// Single shared formatting utility — used EVERYWHERE money / percent / counts render.
// See spec/ui.md "INR formatting rule (global)".

/**
 * Indian rupee formatter with lakh/crore digit grouping.
 * e.g. inr(12345678.9) -> "₹1,23,45,678.90"
 */
export const inr = (n: number): string =>
  new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n)

/**
 * Ratio (0..1) -> one-decimal percentage.
 * e.g. pct(0.415) -> "41.5%"
 */
export const pct = (r: number): string => (r * 100).toFixed(1) + '%'

/**
 * Plain integer with Indian digit grouping (for counts, e.g. customer_count, row_count).
 * e.g. intFmt(60000) -> "60,000"
 */
export const intFmt = (n: number): string => new Intl.NumberFormat('en-IN').format(n)

/**
 * Weighted-average days-overdue → one-decimal number, or the em-dash "—" when null.
 * Null is the honest "no overdue balance in this group" case — never rendered as 0.
 * e.g. dpd(73.42) -> "73.4"; dpd(null) -> "—"
 */
export const dpd = (v: number | null | undefined): string =>
  v == null ? '—' : v.toFixed(1)

/** Human labels for aging buckets. Covers overdue bands, current, and the "no overdue" case. */
export const BUCKET_LABELS: Record<string, string> = {
  current: 'Current',
  '0-30': '0–30 days',
  '31-60': '31–60 days',
  '61-90': '61–90 days',
  '90+': '90+ days',
  none: 'None',
  unclassified: 'Unclassified',
}

/** Safe bucket label lookup that never returns undefined. */
export const bucketLabel = (b: string): string => BUCKET_LABELS[b] ?? b
