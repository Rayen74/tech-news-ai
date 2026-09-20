"use client";

import { useEffect, useState, useMemo } from "react";
import { Article, fetchArticles } from "@/lib/api";

interface DayGroup {
  date: string;
  articles: Article[];
}

export default function ArchivePage() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [themeSearch, setThemeSearch] = useState("");

  useEffect(() => {
    async function load() {
      setLoading(true);
      const data = await fetchArticles({ limit: 150 });
      setArticles(data);
      setLoading(false);
    }
    load();
  }, []);

  // Group articles by date, then take Top 2 highest-scoring articles per day
  const daysArchive = useMemo(() => {
    const filtered = articles.filter((art) => {
      if (!themeSearch) return true;
      const q = themeSearch.toLowerCase();
      return (
        art.title.toLowerCase().includes(q) ||
        art.source.toLowerCase().includes(q) ||
        (art.rewritten_title && art.rewritten_title.toLowerCase().includes(q)) ||
        (art.summary && art.summary.toLowerCase().includes(q))
      );
    });

    const groups: { [date: string]: Article[] } = {};

    filtered.forEach((art) => {
      const dateStr = art.created_at
        ? new Date(art.created_at).toLocaleDateString("en-US", {
            year: "numeric",
            month: "long",
            day: "numeric",
          })
        : "Unscheduled Archive";

      if (!groups[dateStr]) groups[dateStr] = [];
      groups[dateStr].push(art);
    });

    // For each day, sort by score_global descending and keep top 2
    const result: DayGroup[] = Object.keys(groups).map((date) => {
      const sorted = groups[date].sort(
        (a, b) => (b.score_global || 0) - (a.score_global || 0)
      );
      return {
        date,
        articles: sorted.slice(0, 2),
      };
    });

    return result;
  }, [articles, themeSearch]);

  return (
    <div className="space-y-8">
      {/* Header & Theme Search */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-900/70 border border-slate-800 p-5 rounded-2xl shadow-xl backdrop-blur-md">
        <div>
          <h1 className="text-2xl font-black text-white flex items-center gap-2">
            <span className="text-cyan-400">📅</span> Previous Days Archive (Top 2 Picks)
          </h1>
          <p className="text-xs sm:text-sm text-slate-400">
            Historical top 2 standout articles for each day evaluated by the pipeline
          </p>
        </div>

        <div className="w-full md:w-80">
          <input
            type="text"
            placeholder="Filter previous days by theme..."
            value={themeSearch}
            onChange={(e) => setThemeSearch(e.target.value)}
            className="w-full bg-slate-950/90 border border-slate-700/80 rounded-xl px-4 py-2 text-xs sm:text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400 transition"
          />
        </div>
      </div>

      {/* Days List */}
      {loading ? (
        <div className="space-y-6">
          {[1, 2].map((i) => (
            <div key={i} className="h-44 rounded-2xl bg-slate-900/50 border border-slate-800/60 animate-pulse" />
          ))}
        </div>
      ) : daysArchive.length === 0 ? (
        <div className="p-12 text-center text-slate-400 bg-slate-900/40 rounded-2xl border border-slate-800">
          No historical articles found matching your criteria.
        </div>
      ) : (
        <div className="space-y-10">
          {daysArchive.map((group) => (
            <div key={group.date} className="space-y-4">
              <div className="flex items-center gap-3 border-b border-slate-800 pb-2">
                <span className="text-cyan-400 text-sm font-bold">●</span>
                <h2 className="text-lg font-bold text-white tracking-wide">{group.date}</h2>
                <span className="text-xs text-slate-400 bg-slate-900 border border-slate-800 px-2.5 py-0.5 rounded-full font-mono">
                  Top 2 Winners
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {group.articles.map((art, idx) => (
                  <div
                    key={art.id}
                    className="relative flex flex-col justify-between rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-900/90 to-slate-950/90 p-6 hover:border-cyan-500/50 transition-all shadow-lg group"
                  >
                    <div className="absolute top-4 right-4 h-7 w-7 rounded-full bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-xs font-bold text-cyan-300">
                      #{idx + 1}
                    </div>

                    <div className="space-y-3 pr-8">
                      <div className="flex items-center gap-2 text-xs">
                        <span className="font-mono text-cyan-300 bg-cyan-950/70 border border-cyan-800/50 px-2 py-0.5 rounded text-[11px]">
                          {art.source}
                        </span>
                        <span
                          className={`font-semibold px-2 py-0.5 rounded-full text-[10px] ${
                            art.decision === "RECOMMEND"
                              ? "bg-teal-500/10 text-teal-300 border border-teal-500/30"
                              : "bg-amber-500/10 text-amber-300 border border-amber-500/30"
                          }`}
                        >
                          {art.decision || "REVIEW"}
                        </span>
                      </div>

                      <h3 className="font-bold text-base text-white group-hover:text-cyan-300 transition-colors line-clamp-2">
                        <a href={art.url} target="_blank" rel="noopener noreferrer">
                          {art.rewritten_title || art.title}
                        </a>
                      </h3>

                      <p className="text-xs text-slate-400 line-clamp-3 leading-relaxed">
                        {art.rewritten_summary || art.summary || "No summary recorded."}
                      </p>
                    </div>

                    <div className="pt-4 mt-4 border-t border-slate-800/80 flex items-center justify-between text-xs">
                      <div className="flex items-center gap-3">
                        <span className="text-slate-400">
                          Score:{" "}
                          <strong className="text-cyan-400 font-bold text-sm">
                            {art.score_global ?? "--"}/100
                          </strong>
                        </span>
                        <span className="hidden sm:inline-block text-[11px] text-slate-400 font-mono">
                          (Imp: {art.score_impact ?? "-"} / Sub: {art.score_substance ?? "-"} / Prac:{" "}
                          {art.score_practicality ?? "-"})
                        </span>
                      </div>
                      <a
                        href={art.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-bold text-cyan-400 hover:text-cyan-300 transition"
                      >
                        Read Article ↗
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
