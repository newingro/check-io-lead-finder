import type { Metadata, Viewport } from "next";
import { Inter, Manrope } from "next/font/google";
import "./globals.css";

const manrope = Manrope({ subsets: ["latin"], variable: "--font-manrope", display: "swap" });
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Gestionale CHECK-iO", template: "%s · Gestionale CHECK-iO" },
  description: "Area riservata del team CHECK-iO.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#06111d" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="it" className={`${manrope.variable} ${inter.variable}`}>
      <body className="min-h-svh">{children}</body>
    </html>
  );
}
