import Link from "next/link";
import ThemeToggle from "@/components/ThemeToggle";
import "./globals.css";

const NAV = [
  ["/", "Dashboard"], ["/library", "Library"], ["/upload", "Upload"],
  ["/processing", "Processing"], ["/search", "Search"], ["/chat", "Chat"],
  ["/summary", "Summaries"], ["/events", "Events"], ["/alerts", "Alerts"],
  ["/reports", "Reports"], ["/users", "Users"], ["/settings", "Settings"],
] as const;

export const metadata = { title: "VisionIQ", description: "Multimodal Video Intelligence and Agentic Search Platform" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-100">
        <header className="border-b border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4 py-3">
            <Link href="/" className="text-lg font-bold">VisionIQ</Link>
            <nav className="flex flex-wrap gap-3 text-sm">
              {NAV.map(([href, label]) => (
                <Link key={href} href={href} className="text-gray-600 hover:text-indigo-600 dark:text-gray-300">{label}</Link>
              ))}
            </nav>
            <div className="ml-auto flex items-center gap-3">
              <ThemeToggle />
              <Link href="/login" className="text-sm text-indigo-600">Sign in</Link>
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
