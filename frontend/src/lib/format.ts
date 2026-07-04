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
