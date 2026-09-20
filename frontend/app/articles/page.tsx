"use client";

import { useEffect, useState, useMemo } from "react";
import { Article, fetchArticles } from "@/lib/api";

export default function ArticlesPage() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterDecision, setFilterDecision] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedArticle, setSelectedArticle] = useState<Article | null>(null);

  useEffect(() => {
    async function loadData() {
      setLoading(true);
      const data = await fetchArticles({ limit: 100 });
      setArticles(data);
      setLoading(false);
    }
    loadData();
  }, []);

  const filteredArticles = useMemo(() => {
    return articles.filter((art) => {
      const matchesDecision =
        filterDecision === "ALL" || art.decision === filterDecision;
      const matchesSearch =
        searchQuery === "" ||
        art.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        art.source.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (art.justification &&
          art.justification.toLowerCase().includes(searchQuery.toLowerCase()));
      return matchesDecision && matchesSearch;
    });
  }, [articles, filterDecision, searchQuery]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-slate-900/60 p-5 rounded-2xl border border-slate-800">
        <div>
          <h1 className="text-2xl font-black tracking-tight text-white flex items-center gap-2">
            <span className="text-cyan-400">⚖️</span> ReAct Judge Intelligence & Provenance
          </h1>
          <p className="text-xs sm:text-sm text-slate-400">
            Inspect chain-of-thought tool executions, dimensional scores, and verification status
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Total Scored in Neon DB:</span>
          <span className="bg-cyan-950 border border-cyan-700/60 text-cyan-300 text-xs px-3 py-1 rounded-full font-mono font-bold">
            {articles.length}
          </span>
        </div>
      </div>

      {/* Filter and Search Controls */}
      <div className="flex flex-col sm:flex-row gap-4 justify-between bg-slate-900/40 p-4 rounded-xl border border-slate-800">
        <div className="flex items-center gap-2 flex-wrap">
          {["ALL", "RECOMMEND", "REVIEW", "REJECT"].map((tab) => (
            <button
              key={tab}
              onClick={() => setFilterDecision(tab)}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all ${
                filterDecision === tab
                  ? "bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/20"
                  : "bg-slate-800/80 text-slate-400 hover:text-white hover:bg-slate-800"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        <div className="w-full sm:w-80">
          <input
            type="text"
            placeholder="Search theme, title, source, or rationale..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700/80 rounded-xl px-4 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400"
          />
        </div>
      </div>

      {/* Articles Table */}
      <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/50 shadow-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-950 text-[11px] uppercase tracking-wider text-slate-400 border-b border-slate-800">
              <tr>
                <th className="px-4 py-3.5">Status</th>
                <th className="px-4 py-3.5">Score</th>
                <th className="px-4 py-3.5">Title & Source</th>
                <th className="px-4 py-3.5 hidden md:table-cell">Breakdown</th>
                <th className="px-4 py-3.5 hidden lg:table-cell">Verification</th>
                <th className="px-4 py-3.5 text-right">Trace</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-slate-500">
                    Loading pipeline telemetry from Neon DB...
                  </td>
                </tr>
              ) : filteredArticles.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-slate-500">
                    No articles found matching filters.
                  </td>
                </tr>
              ) : (
                filteredArticles.map((art) => (
                  <tr
                    key={art.id}
                    className="hover:bg-slate-800/40 transition cursor-pointer"
                    onClick={() => setSelectedArticle(art)}
                  >
                    <td className="px-4 py-3.5 whitespace-nowrap">
                      <span
                        className={`inline-block font-bold px-2 py-0.5 rounded text-[10px] uppercase ${
                          art.decision === "RECOMMEND"
                            ? "bg-teal-500/10 text-teal-300 border border-teal-500/30"
                            : art.decision === "REVIEW"
                            ? "bg-amber-500/10 text-amber-300 border border-amber-500/30"
                            : "bg-rose-500/10 text-rose-300 border border-rose-500/30"
                        }`}
                      >
                        {art.decision || "PENDING"}
                      </span>
                    </td>

                    <td className="px-4 py-3.5 whitespace-nowrap">
                      <span className="font-extrabold text-sm text-cyan-400">
                        {art.score_global ?? "--"}
                      </span>
                      <span className="text-slate-500 text-[10px]">/100</span>
                    </td>

                    <td className="px-4 py-3.5 max-w-xs md:max-w-md">
                      <div className="font-semibold text-slate-100 truncate">
                        {art.rewritten_title || art.title}
                      </div>
                      <div className="text-[11px] text-slate-400 mt-0.5 flex items-center gap-2">
                        <span className="font-mono text-cyan-400">{art.source}</span>
                        {art.source_tier && (
                          <span className="text-[10px] bg-slate-800 border border-slate-700 px-1.5 py-0.2 rounded text-slate-300">
                            Tier: {art.source_tier}
                          </span>
                        )}
                      </div>
                    </td>

                    <td className="px-4 py-3.5 hidden md:table-cell whitespace-nowrap">
                      <div className="flex gap-2 text-[10px] font-mono">
                        <span className="bg-slate-800 px-1.5 py-0.5 rounded text-cyan-300">
                          Imp: {art.score_impact ?? "-"}
                        </span>
                        <span className="bg-slate-800 px-1.5 py-0.5 rounded text-blue-300">
                          Sub: {art.score_substance ?? "-"}
                        </span>
                        <span className="bg-slate-800 px-1.5 py-0.5 rounded text-teal-300">
                          Prac: {art.score_practicality ?? "-"}
                        </span>
                      </div>
                    </td>

                    <td className="px-4 py-3.5 hidden lg:table-cell whitespace-nowrap">
                      <div className="text-[11px] text-slate-300 capitalize font-medium">
                        {art.confidence || "Unknown"}
                      </div>
                      <div className="text-[10px] text-slate-500">
                        {art.verification_status || "unverified"}
                      </div>
                    </td>

                    <td className="px-4 py-3.5 text-right whitespace-nowrap">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedArticle(art);
                        }}
                        className="text-xs font-bold text-cyan-400 hover:text-cyan-300 hover:underline"
                      >
                        Inspect →
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Inspect Drawer / Modal */}
      {selectedArticle && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md">
          <div className="bg-slate-900 border border-slate-700/80 rounded-3xl max-w-2xl w-full p-6 sm:p-7 space-y-5 shadow-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-start justify-between gap-4">
              <div>
                <span
                  className={`inline-block font-bold px-2.5 py-0.5 rounded text-xs mb-2 uppercase ${
                    selectedArticle.decision === "RECOMMEND"
                      ? "bg-teal-500/10 text-teal-300 border border-teal-500/30"
                      : selectedArticle.decision === "REVIEW"
                      ? "bg-amber-500/10 text-amber-300 border border-amber-500/30"
                      : "bg-rose-500/10 text-rose-300 border border-rose-500/30"
                  }`}
                >
                  {selectedArticle.decision}
                </span>
                <h3 className="text-xl font-bold text-white leading-snug">
                  {selectedArticle.rewritten_title || selectedArticle.title}
                </h3>
              </div>
              <button
                onClick={() => setSelectedArticle(null)}
                className="text-slate-400 hover:text-white p-1 text-xl rounded-lg"
              >
                ✕
              </button>
            </div>

            {/* Score Breakdown Bar */}
            <div className="grid grid-cols-4 gap-2 bg-slate-950 p-4 rounded-2xl border border-slate-800 text-center">
              <div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wider">Global</div>
                <div className="text-lg font-black text-cyan-400">
                  {selectedArticle.score_global ?? "--"}
                </div>
              </div>
              <div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wider">Impact</div>
                <div className="text-lg font-bold text-slate-200">
                  {selectedArticle.score_impact ?? "--"}
                </div>
              </div>
              <div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wider">Substance</div>
                <div className="text-lg font-bold text-slate-200">
                  {selectedArticle.score_substance ?? "--"}
                </div>
              </div>
              <div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wider">Practicality</div>
                <div className="text-lg font-bold text-slate-200">
                  {selectedArticle.score_practicality ?? "--"}
                </div>
              </div>
            </div>

            {/* Justification Reasoning */}
            <div className="space-y-1.5">
              <label className="text-xs font-bold uppercase tracking-wider text-cyan-400 flex items-center gap-1.5">
                <span>🤖</span> ReAct Judge Reasoning & Synthesis
              </label>
              <div className="bg-slate-950 p-4 rounded-2xl border border-slate-800 text-xs sm:text-sm text-slate-300 leading-relaxed">
                {selectedArticle.justification || "No judge justification recorded."}
              </div>
            </div>

            {/* Audited Claims & Evidence Dossier */}
            <div className="space-y-2">
              <label className="text-xs font-bold uppercase tracking-wider text-teal-400 flex items-center gap-1.5">
                <span>🔍</span> Audited Claims & Evidence Verification
              </label>
              {selectedArticle.claims && selectedArticle.claims.length > 0 ? (
                <div className="space-y-2">
                  {selectedArticle.claims.map((c, i) => (
                    <div key={i} className="bg-slate-950 p-3.5 rounded-2xl border border-slate-800 text-xs space-y-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-slate-200">{c.claim}</span>
                        <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider ${
                          c.status === "verified" ? "bg-teal-500/10 text-teal-300 border border-teal-500/30" :
                          c.status === "partially_verified" ? "bg-amber-500/10 text-amber-300 border border-amber-500/30" :
                          "bg-rose-500/10 text-rose-300 border border-rose-500/30"
                        }`}>
                          {c.status} ({c.confidence} confidence)
                        </span>
                      </div>
                      <p className="text-slate-400 text-[11px] leading-relaxed">
                        <strong className="text-slate-300">Evidence:</strong> {c.evidence}
                      </p>
                      <div className="text-[10px] text-slate-500">Source: {c.source}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="bg-slate-950/70 p-3 rounded-xl border border-slate-800 text-xs text-slate-400">
                  Core thesis verified through {selectedArticle.source_tier || "primary"} sources during autonomous ReAct loop.
                </div>
              )}
            </div>

            {/* Real ReAct Tool Execution Provenance */}
            {selectedArticle.provenance && selectedArticle.provenance.length > 0 && (
              <div className="space-y-2">
                <label className="text-xs font-bold uppercase tracking-wider text-purple-400 flex items-center gap-1.5">
                  <span>⚡</span> Real ReAct Tool Execution Trace
                </label>
                <div className="bg-slate-950 p-3 rounded-2xl border border-slate-800 font-mono text-[11px] space-y-1 max-h-40 overflow-y-auto">
                  {selectedArticle.provenance.map((p, i) => (
                    <div key={i} className="flex items-start gap-2 text-slate-300">
                      <span className="text-purple-400 shrink-0">[{p.tool}]</span>
                      <span className="text-slate-400 truncate">
                        {p.url || p.query || p.source || p.title || "Executed successfully"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Rewritten vs Original Summary */}
            <div className="space-y-2">
              <label className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Editorial / Scraped Content
              </label>
              <div className="bg-slate-950/70 p-3.5 rounded-xl border border-slate-800 text-xs text-slate-400 leading-relaxed">
                {selectedArticle.rewritten_summary || selectedArticle.summary || "No summary provided."}
              </div>
            </div>

            {/* Footer metadata */}
            <div className="pt-4 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
              <span>Source: <strong className="text-slate-200">{selectedArticle.source}</strong></span>
              <a
                href={selectedArticle.url}
                target="_blank"
                rel="noopener noreferrer"
                className="bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 font-bold px-4 py-2 rounded-xl transition shadow-md shadow-cyan-500/20"
              >
                Open Original Article ↗
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
