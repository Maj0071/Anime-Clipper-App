import './globals.css'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Anime Auto-Clipper',
  description: 'AI-powered anime clip generation for TikTok and Instagram',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
