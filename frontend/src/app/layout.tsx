import type { Metadata } from 'next'
import './globals.css'
import './print.css'

export const metadata: Metadata = {
  title: 'AR Aging Dashboard',
  description: 'Local, deterministic Accounts Receivable aging dashboard — nothing leaves this machine.',
}

// Runs BEFORE first paint (inline in <head>) to set the `.dark` class from the user's
// stored preference, else the OS `prefers-color-scheme`. This prevents a flash of the
// wrong theme. The key must match THEME_STORAGE_KEY in src/lib/theme.ts.
const themeInitScript = `(function(){try{var t=localStorage.getItem('ar-theme');if(t!=='light'&&t!=='dark'){t=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}document.documentElement.classList.toggle('dark',t==='dark');}catch(e){}})();`

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100">
        {children}
      </body>
    </html>
  )
}
