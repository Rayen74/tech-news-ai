"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Navbar() {
  const pathname = usePathname();

  const navLinks = [
    { href: "/", label: "Today's Edition" },
    { href: "/archive", label: "Previous Days (Top 2)" },
    { href: "/articles", label: "Intelligence Pipeline" },
  ];

  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-xl">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-cyan-500 via-teal-500 to-blue-600 flex items-center justify-center text-white font-black text-base shadow-lg shadow-cyan-500/25">
            ⚡
          </div>
          <Link href="/" className="font-extrabold text-xl tracking-tight text-white hover:opacity-95">
            TECH<span className="text-cyan-400">NEWS</span>
            <span className="text-xs ml-1 px-1.5 py-0.5 rounded bg-cyan-950 border border-cyan-700/60 text-cyan-300 uppercase font-mono">
              AI-CURATED
            </span>
          </Link>
        </div>

        <nav className="flex items-center gap-2 sm:gap-4 text-sm font-medium">
          {navLinks.map((link) => {
            const isActive = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`px-3 py-1.5 rounded-lg transition-all ${
                  isActive
                    ? "bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 shadow-sm"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
