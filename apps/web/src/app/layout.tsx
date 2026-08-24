import type { Metadata } from "next";
import "@promotion-control-plane/ui/styles.css";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Agent Promotion Control Plane",
    template: "%s · Agent Promotion Control Plane"
  },
  description: "A governed reference implementation for evidence-led agent promotion.",
  robots: { index: false, follow: false }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
