import type { Metadata, Viewport } from "next"
import "./globals.css"

export const metadata: Metadata = {
  title: "Sala de discusión",
  description: "Research discussion platform",
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="es">
      <body className="m-0 p-0 font-sans antialiased bg-bg-page">
        {children}
      </body>
    </html>
  )
}
