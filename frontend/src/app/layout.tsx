import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'ETAIR — Industrial Knowledge Intelligence Platform',
  description: 'Unified document workspace for asset-intensive industries. Version-controlled, permission-aware, AI-powered.',
  keywords: ['industrial', 'document management', 'knowledge graph', 'AI retrieval', 'engineering'],
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body className="min-h-screen bg-surface-0 text-white antialiased">
        {children}
      </body>
    </html>
  )
}
