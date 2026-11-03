import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Newsreader } from "next/font/google";
import { Suspense } from "react";
import Nav, { NavBar } from "@/components/Nav";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const newsreader = Newsreader({ variable: "--font-serif", subsets: ["latin"], style: ["normal", "italic"] });

export const metadata: Metadata = {
  title: "FINN",
  description: "Your portfolio's morning briefing: what changed, why it matters, and the research behind it.",
  appleWebApp: { capable: true, title: "FINN", statusBarStyle: "default" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f2ede3" },
    { media: "(prefers-color-scheme: dark)", color: "#121410" },
  ],
};

const THEME_SCRIPT =
  "try{var t=JSON.parse(localStorage.getItem('finn.theme')||'\"light\"');" +
  "if(t==='dark'||t==='system'||t==='light')document.documentElement.dataset.theme=t}catch(e){}";

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" data-theme="light" suppressHydrationWarning
          className={`${geistSans.variable} ${geistMono.variable} ${newsreader.variable}`}>
      <head>
        {/* apply the saved theme before first paint, so there is no light/dark flash */}
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <main className="app">{children}</main>
        <Suspense fallback={<NavBar path="" />}>
          <Nav />
        </Suspense>
      </body>
    </html>
  );
}
