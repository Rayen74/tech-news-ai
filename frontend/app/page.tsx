"use client";

import { useEffect, useState, useTransition } from "react";
import Link from "next/link";
import { Article, fetchArticles, fetchTopArticle, runPipelineForTopic, PipelineRunResult } from "@/lib/api";

export default function HomePage() {
  const [topArticle, setTopArticle] = useState<Article | null>(null);
  const [todayArticles, setTodayArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [themeSearch, setThemeSearch] = useState("");
  const [isPending, startTransition] = useTransition();

  // On-demand pipeline execution states
  const [topicInput, setTopicInput] = useState("");
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [streamLogs, setStreamLogs] = useState<Array<{ timestamp: string; phase: string; tool: string; message: string }>>([]);
  const [pipelineResult, setPipelineResult] = useState<PipelineRunResult | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [showRadarDrawer, setShowRadarDrawer] = useState(false);

  const loadData = async (query = "") => {
    setLoading(true);
    const [top, articles] = await Promise.all([
      fetchTopArticle(),
      fetchArticles({ limit: 30, query }),
    ]);

    setTopArticle(top);

    const others = top
      ? articles.filter((a) => a.id !== top.id)
      : articles;

    setTodayArticles(others);
    setLoading(false);
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    startTransition(() => {
      loadData(themeSearch);
    });
  };

  // Trigger real-time SSE on-demand pipeline for user topic
  const handleRunPipeline = async (e: React.FormEvent) => {
    e.preventDefault();
    const topic = topicInput.trim();
    if (!topic) return;

    setPipelineRunning(true);
    setPipelineError(null);
    setPipelineResult(null);
    setStreamLogs([]);
    setShowRadarDrawer(true);

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const eventSource = new EventSource(`${apiUrl}/api/pipeline/stream?topic=${encodeURIComponent(topic)}&max_results=5`);

    eventSource.addEventListener("log", (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data);
        setStreamLogs((prev) => [...prev, payload]);
      } catch (err) {
        console.error("Failed to parse log event", err);
      }
    });

    eventSource.addEventListener("done", (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data);
        setPipelineResult(payload);
        if (payload.top_article) {
          setTopArticle(payload.top_article);
        }
        loadData();
      } catch (err) {
        console.error("Failed to parse done event", err);
      } finally {
        eventSource.close();
        setPipelineRunning(false);
      }
    });

    eventSource.addEventListener("error", (event: any) => {
      console.warn("EventSource encountered an event or closed:", event);
      // If error payload is available in data
      if (event.data) {
        try {
          const errPayload = JSON.parse(event.data);
          setPipelineError(errPayload.message || "Pipeline encountered an error.");
        } catch {}
      }
      eventSource.close();
      setPipelineRunning(false);
    });
  };

  return (
    <div className="space-y-12">
      {/* ── Topic Pipeline Execution Banner (On-Demand Feature) ── */}
      <div className="relative overflow-hidden rounded-3xl border border-cyan-500/40 bg-gradient-to-r from-slate-950 via-slate-900 to-cyan-950/40 p-6 sm:p-8 shadow-2xl backdrop-blur-xl">
        <div className="absolute top-0 right-0 -mr-20 -mt-20 h-64 w-64 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />
        
        <div className="relative z-10 max-w-3xl space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-semibold text-cyan-300">
            <span>✨ Autonomous Agent Engine</span>
          </div>

          <h2 className="text-2xl sm:text-3xl font-black tracking-tight text-white">
            Evaluate Any Tech Topic On-Demand
          </h2>
          <p className="text-xs sm:text-sm text-slate-300 leading-relaxed">
            Enter a topic, framework, or cybersecurity incident. Our autonomous agent will discover fresh web articles, verify claims, score them concurrently, and rewrite the single best pick.
          </p>

          <form onSubmit={handleRunPipeline} className="pt-2 flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <input
                type="text"
                placeholder="e.g., Quantum Computing, Kubernetes 1.33, CrowdStrike, Agentic AI..."
                value={topicInput}
                onChange={(e) => setTopicInput(e.target.value)}
                disabled={pipelineRunning}
                className="w-full bg-slate-950/90 border border-slate-700/80 rounded-2xl px-5 py-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20 transition disabled:opacity-50"
              />
            </div>
            <button
              type="submit"
              disabled={pipelineRunning || !topicInput.trim()}
              className="bg-gradient-to-r from-cyan-500 to-teal-400 hover:from-cyan-400 hover:to-teal-300 text-slate-950 font-black px-6 py-3 rounded-2xl text-sm transition shadow-lg shadow-cyan-500/25 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer shrink-0"
            >
              {pipelineRunning ? (
                <>
                  <svg className="animate-spin h-4 w-4 text-slate-950" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                  </svg>
                  <span>Investigating...</span>
                </>
              ) : (
                <>
                  <span>⚡ Discover & Judge Winner</span>
                </>
              )}
            </button>
          </form>

          {/* Live Agent Execution Radar (SSE Stream Logs) */}
          {showRadarDrawer && streamLogs.length > 0 && (
            <div className="mt-4 rounded-2xl border border-cyan-500/30 bg-slate-950/95 overflow-hidden shadow-2xl">
              <div className="flex items-center justify-between px-4 py-2.5 bg-slate-900/90 border-b border-slate-800 text-xs">
                <div className="flex items-center gap-2">
                  <span className="relative flex h-2 w-2">
                    {pipelineRunning ? (
                      <>
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-400"></span>
                      </>
                    ) : (
                      <span className="inline-flex rounded-full h-2 w-2 bg-teal-400"></span>
                    )}
                  </span>
                  <span className="font-mono font-bold text-cyan-300">
                    {pipelineRunning ? "Live ReAct Agent Execution Stream" : "ReAct Execution Completed"}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => setShowRadarDrawer(false)}
                  className="text-slate-500 hover:text-slate-300 text-xs px-2 py-0.5 rounded hover:bg-slate-800 transition"
                >
                  ✕ Close Console
                </button>
              </div>

              <div className="p-4 font-mono text-[11px] sm:text-xs space-y-1.5 max-h-60 overflow-y-auto scrollbar-thin scrollbar-thumb-slate-800">
                {streamLogs.map((log, idx) => (
                  <div key={idx} className="flex items-start gap-2 leading-relaxed">
                    <span className="text-slate-600 shrink-0 select-none">[{log.timestamp}]</span>
                    {log.tool && (
                      <span className="px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-400 border border-cyan-800/60 shrink-0 text-[10px]">
                        {log.tool}
                      </span>
                    )}
                    <span className={log.phase === "error" ? "text-rose-400" : log.phase === "editorial" ? "text-amber-300" : "text-slate-300"}>
                      {log.message}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Error Message */}
          {pipelineError && (
            <div className="mt-3 bg-rose-950/40 border border-rose-800/60 rounded-xl p-3 text-xs text-rose-300 flex items-center gap-2">
              <span>⚠️</span>
              <span>{pipelineError}</span>
            </div>
          )}

          {/* On-Demand Result Banner */}
          {pipelineResult && pipelineResult.top_article && (
            <div className="mt-4 bg-teal-950/40 border border-teal-500/40 rounded-2xl p-4 space-y-2">
              <div className="flex items-center justify-between text-xs text-teal-300 font-bold">
                <span>🏆 Winner Found for &ldquo;{topicInput}&rdquo;</span>
                <span className="bg-teal-500/20 px-2.5 py-0.5 rounded-full border border-teal-500/30">
                  Global Score: {pipelineResult.top_article.score_global}/100
                </span>
              </div>
              <h3 className="text-base font-bold text-white">
                {pipelineResult.top_article.rewritten_title || pipelineResult.top_article.title}
              </h3>
              <p className="text-xs text-slate-300 line-clamp-2">
                {pipelineResult.top_article.rewritten_summary || pipelineResult.top_article.summary}
              </p>
              <div className="text-[11px] text-teal-400 font-medium">
                Discovered: {pipelineResult.discovered_count} | Evaluated: {pipelineResult.unique_count} novel | Saved to Neon DB
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Search & Filter Bar ── */}
      <div className="flex flex-col md:flex-row items-center justify-between gap-4 bg-slate-900/70 border border-slate-800 p-4 sm:p-5 rounded-2xl shadow-xl backdrop-blur-md">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <span className="text-cyan-400">📰</span> Today&apos;s Editorial Digest
          </h1>
          <p className="text-xs sm:text-sm text-slate-400">
            Filtered by 3-layer deduplication & verified by autonomous ReAct tools
          </p>
        </div>

        {/* Theme Search Input */}
        <form onSubmit={handleSearchSubmit} className="w-full md:w-96 flex gap-2">
          <div className="relative flex-1">
            <input
              type="text"
              placeholder="Search theme in database (e.g., devops, kubernetes, LLM)..."
              value={themeSearch}
              onChange={(e) => setThemeSearch(e.target.value)}
              className="w-full bg-slate-950/90 border border-slate-700/80 rounded-xl px-4 py-2 text-xs sm:text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400 transition"
            />
            {themeSearch && (
              <button
                type="button"
                onClick={() => {
                  setThemeSearch("");
                  loadData("");
                }}
                className="absolute right-3 top-2.5 text-xs text-slate-500 hover:text-slate-300"
              >
                ✕
              </button>
            )}
          </div>
          <button
            type="submit"
            disabled={isPending}
            className="bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs sm:text-sm transition shadow-md shadow-cyan-500/20 disabled:opacity-50"
          >
            {isPending ? "..." : "Filter"}
          </button>
        </form>
      </div>

      {/* 1. Best Article of Today (Top Pick Hero) */}
      <section className="relative overflow-hidden rounded-3xl border border-cyan-500/30 bg-gradient-to-br from-slate-900/90 via-slate-950/90 to-blue-950/40 p-6 sm:p-10 shadow-2xl backdrop-blur-2xl">
        <div className="absolute top-0 right-0 -mr-24 -mt-24 h-72 w-72 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />

        <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
          <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/40 bg-cyan-500/10 px-3.5 py-1 text-xs font-semibold text-cyan-300 shadow-sm shadow-cyan-500/20">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-400"></span>
            </span>
            TOP SCORING ARTICLE
          </div>

          {topArticle?.score_global && (
            <div className="flex items-center gap-2 text-sm bg-slate-900/90 px-3.5 py-1.5 rounded-xl border border-slate-700/80 shadow-sm">
              <span className="text-slate-400 text-xs uppercase tracking-wider">Judge Score</span>
              <span className="font-extrabold text-teal-400 text-base">
                {topArticle.score_global}/100
              </span>
            </div>
          )}
        </div>

        {topArticle ? (
          <div className="space-y-6">
            <h2 className="text-2xl sm:text-4xl font-extrabold tracking-tight text-white leading-tight">
              {topArticle.rewritten_title || topArticle.title}
            </h2>

            <p className="text-sm sm:text-lg text-slate-300 leading-relaxed max-w-4xl font-normal">
              {topArticle.rewritten_summary || topArticle.summary}
            </p>

            {topArticle.editor_notes && (
              <div className="rounded-2xl border border-amber-500/30 bg-amber-950/20 p-4 text-xs sm:text-sm text-amber-200/90 flex items-start gap-3 shadow-inner">
                <span className="text-amber-400 text-lg">💡</span>
                <div>
                  <strong className="font-semibold block text-amber-300 mb-0.5">Editor Caveat & Verification:</strong>
                  {topArticle.editor_notes}
                </div>
              </div>
            )}

            {/* Score Pillars */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
              <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-3.5 shadow-sm">
                <div className="text-[11px] uppercase tracking-wider text-slate-400">Impact</div>
                <div className="text-xl font-extrabold text-cyan-400">
                  {topArticle.score_impact ?? "--"}/100
                </div>
              </div>
              <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-3.5 shadow-sm">
                <div className="text-[11px] uppercase tracking-wider text-slate-400">Substance</div>
                <div className="text-xl font-extrabold text-cyan-400">
                  {topArticle.score_substance ?? "--"}/100
                </div>
              </div>
              <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-3.5 shadow-sm">
                <div className="text-[11px] uppercase tracking-wider text-slate-400">Practicality</div>
                <div className="text-xl font-extrabold text-cyan-400">
                  {topArticle.score_practicality ?? "--"}/100
                </div>
              </div>
              <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-3.5 shadow-sm">
                <div className="text-[11px] uppercase tracking-wider text-slate-400">Source</div>
                <div className="text-base font-bold text-slate-200 truncate pt-1">
                  {topArticle.source}
                </div>
              </div>
            </div>

            {/* Justification quote */}
            {topArticle.justification && (
              <div className="rounded-2xl border border-slate-800 bg-slate-950/40 p-4 text-xs sm:text-sm text-slate-400 italic">
                &ldquo;{topArticle.justification}&rdquo;
              </div>
            )}

            {/* CTAs */}
            <div className="flex flex-wrap items-center gap-4 pt-2">
              <a
                href={topArticle.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold px-6 py-3 text-xs sm:text-sm transition shadow-lg shadow-cyan-500/25"
              >
                Read Primary Source ↗
              </a>
              <Link
                href="/articles"
                className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 hover:bg-slate-800 px-6 py-3 text-xs sm:text-sm font-semibold text-slate-200 transition"
              >
                Inspect Agent Scoring 🔍
              </Link>
            </div>
          </div>
        ) : loading ? (
          <div className="space-y-4 animate-pulse">
            <div className="h-8 bg-slate-800/60 rounded-xl w-3/4" />
            <div className="h-20 bg-slate-800/40 rounded-xl w-full" />
            <div className="grid grid-cols-4 gap-3">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-16 bg-slate-800/50 rounded-xl" />
              ))}
            </div>
          </div>
        ) : (
          <div className="text-center py-12 text-slate-400 space-y-3">
            <div className="text-3xl">☕</div>
            <p className="text-base font-semibold">No Top Pick evaluated yet today.</p>
            <p className="text-xs text-slate-500">
              Enter a topic in the launcher above or run the pipeline to generate today&apos;s standout articles.
            </p>
          </div>
        )}
      </section>

      {/* 2. Other Articles Scored Today */}
      <section className="space-y-6">
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div>
            <h2 className="text-lg sm:text-xl font-bold text-white flex items-center gap-2">
              <span>📚</span> Other Articles Scored
            </h2>
            <p className="text-xs text-slate-400">
              Surviving candidates categorized as RECOMMEND or REVIEW
            </p>
          </div>
          <Link
            href="/articles"
            className="text-xs font-bold text-cyan-400 hover:text-cyan-300 hover:underline flex items-center gap-1"
          >
            View All Scored Articles →
          </Link>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1, 2, 3].map((n) => (
              <div key={n} className="h-56 rounded-2xl bg-slate-900/50 border border-slate-800/60 animate-pulse" />
            ))}
          </div>
        ) : todayArticles.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-400 bg-slate-900/40 rounded-2xl border border-slate-800/80">
            No other articles found. Enter a topic above to trigger discovery.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {todayArticles.map((art) => (
              <div
                key={art.id}
                className="flex flex-col justify-between rounded-2xl border border-slate-800/90 bg-slate-900/60 p-5 hover:border-slate-700 hover:bg-slate-900/90 transition-all shadow-md group"
              >
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-mono text-cyan-300 bg-cyan-950/60 border border-cyan-800/50 px-2 py-0.5 rounded text-[11px]">
                      {art.source}
                    </span>
                    <span
                      className={`font-semibold px-2 py-0.5 rounded-full text-[10px] uppercase ${
                        art.decision === "RECOMMEND"
                          ? "bg-teal-500/10 text-teal-300 border border-teal-500/30"
                          : art.decision === "REVIEW"
                          ? "bg-amber-500/10 text-amber-300 border border-amber-500/30"
                          : "bg-rose-500/10 text-rose-300 border border-rose-500/30"
                      }`}
                    >
                      {art.decision || "PENDING"}
                    </span>
                  </div>

                  <h3 className="font-bold text-sm sm:text-base text-slate-100 group-hover:text-cyan-300 transition-colors line-clamp-2">
                    <a href={art.url} target="_blank" rel="noopener noreferrer">
                      {art.rewritten_title || art.title}
                    </a>
                  </h3>

                  <p className="text-xs text-slate-400 line-clamp-3 leading-relaxed">
                    {art.rewritten_summary || art.summary || "No summary provided."}
                  </p>
                </div>

                <div className="pt-4 mt-4 border-t border-slate-800 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-1.5">
                    <span className="text-slate-500">Score:</span>
                    <span className="font-bold text-cyan-400 text-sm">
                      {art.score_global ?? "--"}/100
                    </span>
                  </div>
                  <a
                    href={art.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-slate-400 hover:text-cyan-300 transition flex items-center gap-1"
                  >
                    Open Source ↗
                  </a>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
