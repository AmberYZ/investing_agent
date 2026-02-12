import type { Metadata } from "next";
import { AppHeader } from "./components/AppHeader";
import "./globals.css";

export const metadata: Metadata = {
  title: "Investing agent",
  description: "Themes, narratives, and document explorer",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased font-sans">
        <AppHeader />
        {children}
      </body>
    </html>
  );
}
