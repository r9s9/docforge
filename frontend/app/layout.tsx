import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { Fraunces } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import AppShell from "@/components/AppShell";

// Modern type: Geist (sans, UI/body — sets --font-geist-sans) + Fraunces
// (refined serif, large headings — sets --font-serif-loaded). globals.css uses
// these with a system fallback.
const serif = Fraunces({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-serif-loaded",
  display: "swap",
});

export const metadata: Metadata = {
  title: "DocForge",
  description: "AI-powered DOCX reverse-engineering and document assembly platform",
};

// Applied before paint to avoid a flash of the wrong theme.
const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem('docforge-theme');if(t==='dark'){document.documentElement.setAttribute('data-theme','dark');}}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${serif.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <AuthProvider>
          <AppShell>{children}</AppShell>
        </AuthProvider>
      </body>
    </html>
  );
}
