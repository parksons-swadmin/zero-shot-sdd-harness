import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'AR Aging Dashboard',
  description: 'Local, deterministic Accounts Receivable aging dashboard — nothing leaves this machine.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">{children}</body>
    </html>
  )
}
