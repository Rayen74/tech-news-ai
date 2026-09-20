"""
api.py
======
Read-only FastAPI backend for the Next.js frontend.

Serves two things:
    GET /api/top       - today's editorial pick (public digest page)
    GET /api/articles   - paginated, filterable article list (admin table view)

This is deliberately thin — it has no business logic of its own, just
HTTP wrapping around the read functions in database.py
(get_latest_editorial_pick, get_articles). It never writes anything; all
writes still happen via main.py's pipeline run.

Run locally:
    uvicorn api:app --reload --port 8000

CORS is restricted to FRONTEND_ORIGIN (defaults to the Next.js dev server
at http://localhost:3000) — set it in .env for a deployed frontend origin.
"""

import os
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import get_articles, get_latest_editorial_pick

load_dotenv()

app = FastAPI(title="Tech News AI API", version="1.0.0")

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_ORIGIN,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


import json
import asyncio
from fastapi.responses import StreamingResponse

class Article(BaseModel):
    id: str
    title: str
    url: str
    source: str
    summary: Optional[str] = None
    score_impact: Optional[int] = None
    score_substance: Optional[int] = None
    score_practicality: Optional[int] = None
    score_global: Optional[int] = None
    source_tier: Optional[str] = None
    verification_status: Optional[str] = None
    confidence: Optional[str] = None
    decision: Optional[str] = None
    justification: Optional[str] = None
    rewritten_title: Optional[str] = None
    rewritten_summary: Optional[str] = None
    editor_notes: Optional[str] = None
    provenance: Optional[list] = None
    claims: Optional[list] = None
    created_at: Optional[str] = None


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/top", response_model=Optional[Article])
def top_pick():
    """Today's editorial pick — the most recently rewritten RECOMMEND article. Null if none yet."""
    article = get_latest_editorial_pick()
    return article


@app.get("/api/articles", response_model=list[Article])
def articles(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    decision: Optional[Literal["RECOMMEND", "REVIEW", "REJECT"]] = Query(default=None),
    query: Optional[str] = Query(default=None, description="Search by theme or keyword"),
):
    """Paginated, newest-first article list for the admin table view with theme search."""
    return get_articles(limit=limit, offset=offset, decision=decision, query=query)


class PipelineRunRequest(BaseModel):
    topic: str
    max_results: Optional[int] = 5


@app.post("/api/pipeline/run")
def trigger_pipeline_for_topic(req: PipelineRunRequest):
    """
    On-demand pipeline execution for a user-specified topic.
    Discovers live web news, filters duplicates, scores with ReAct Judge,
    rewrites the top RECOMMEND pick, persists to Neon, and returns the winner.
    """
    topic = (req.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")

    from main import run_pipeline
    
    max_res = min(max(req.max_results or 5, 1), 10)
    result = run_pipeline(query=topic, max_results=max_res)
    return result


@app.get("/api/pipeline/stream")
async def stream_pipeline_execution(
    topic: str = Query(..., description="Tech topic to discover and evaluate"),
    max_results: int = Query(default=5, ge=1, le=10)
):
    """
    Server-Sent Events (SSE) stream providing real-time ReAct observability.
    Emits timestamped log events as the agent discovers, filters, verifies claims,
    and calculates scores. Concludes with an 'artifact' event containing the final top pick.
    """
    cleaned_topic = topic.strip()
    if not cleaned_topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")

    async def event_generator():
        import queue
        import threading
        from datetime import datetime

        q = queue.Queue()

        def log_event(phase: str, message: str, tool: str = "", data: dict = None):
            event_payload = {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "phase": phase,
                "tool": tool,
                "message": message,
                "data": data or {}
            }
            q.put({"type": "log", "payload": event_payload})

        def run_in_thread():
            try:
                from scrapper import discover_todays_live_news_tavily
                from database import is_lexical_duplicate, check_semantic_similarity, normalize_url, upsert_articles
                from embeddings import generate_embedding
                from judge import judge_articles_batch
                from editorial import editorial_top_article

                log_event("discovery", f"Initiating live news search on '{cleaned_topic}' via Tavily API...", tool="Tavily")
                all_articles = discover_todays_live_news_tavily(query=cleaned_topic, max_results=max_results)
                
                if not all_articles:
                    log_event("discovery", "0 articles discovered from search. Exiting.", tool="Tavily")
                    q.put({"type": "done", "payload": {"status": "empty", "top_article": None, "articles": []}})
                    return

                log_event("discovery", f"Discovered {len(all_articles)} live articles with real publisher links.", tool="Tavily")

                # Phase 1: Fast-path lexical dedup
                log_event("deduplication", "Running Layer 1 & 2 lexical duplicate filter (URL -> SHA-256)...", tool="FastPath")
                surviving_lexical = []
                for i, art in enumerate(all_articles, 1):
                    u = normalize_url(art.get("url", ""))
                    t = f"{art.get('title', '')}. {art.get('summary', '')}"
                    is_dup, reason = is_lexical_duplicate(u, t)
                    if is_dup:
                        log_event("deduplication", f"Filtered duplicate: {art.get('title', '')[:45]}... ({reason})", tool="FastPath")
                    else:
                        surviving_lexical.append(art)

                log_event("deduplication", f"{len(surviving_lexical)}/{len(all_articles)} candidates passed to vector similarity check.", tool="FastPath")

                # Phase 2: Semantic check
                unique_articles = []
                for i, art in enumerate(surviving_lexical, 1):
                    t = f"{art.get('title', '')}. {art.get('summary', '')}"
                    log_event("embeddings", f"Computing 768-d embedding for candidate {i}/{len(surviving_lexical)}...", tool="OllamaEmbed")
                    emb = generate_embedding(t)
                    art["embedding"] = emb
                    is_sem_dup, match = check_semantic_similarity(emb, threshold=0.88, day_window=30)
                    if is_sem_dup and match:
                        log_event("embeddings", f"Semantic duplicate found (>88%): '{match.get('title', '')[:40]}'", tool="pgvector")
                    else:
                        unique_articles.append(art)

                log_event("deduplication", f"Deduplication complete: {len(unique_articles)} novel unique articles retained.", tool="Deduplication")

                if not unique_articles:
                    q.put({"type": "done", "payload": {"status": "empty", "top_article": None, "articles": []}})
                    return

                # Phase 3: Concurrent ReAct Judge
                log_event("judge", f"Evaluating {len(unique_articles)} articles concurrently with ReAct Agent...", tool="ReActJudge")
                judged_articles = judge_articles_batch(unique_articles, max_workers=4)

                for art in judged_articles:
                    log_event(
                        "judge",
                        f"Scored '{art.get('title', '')[:40]}...' -> {art.get('score_global')}/100 [{art.get('decision')}]",
                        tool="DeterministicEngine",
                        data={"score": art.get("score_global"), "decision": art.get("decision")}
                    )

                # Phase 4: Editorial Rewrite
                log_event("editorial", "Selecting and rewriting top RECOMMEND pick with editorial LLM...", tool="EditorialLLM")
                judged_articles = editorial_top_article(judged_articles)
                top = judged_articles[0] if judged_articles else None
                if top and "rewritten_title" in top:
                    log_event("editorial", f"Synthesized headline: '{top.get('rewritten_title')}'", tool="EditorialLLM")

                # Phase 5: Persist
                log_event("persistence", "Persisting scored articles and evidence dossiers to Neon PostgreSQL...", tool="PostgresPool")
                db_res = upsert_articles(judged_articles)
                log_event("persistence", f"Upsert complete: {db_res['inserted']} inserted/updated.", tool="PostgresPool")

                q.put({
                    "type": "done",
                    "payload": {
                        "status": "success",
                        "top_article": top,
                        "articles": judged_articles,
                        "discovered_count": len(all_articles),
                        "unique_count": len(unique_articles),
                        "db_result": db_res
                    }
                })
            except Exception as e:
                log_event("error", f"Pipeline error: {str(e)}", tool="SystemError")
                q.put({"type": "error", "payload": {"message": str(e)}})

        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()

        while True:
            try:
                item = q.get_nowait()
                msg_type = item.get("type")
                payload = item.get("payload")
                yield f"event: {msg_type}\ndata: {json.dumps(payload)}\n\n"
                if msg_type in ("done", "error"):
                    break
            except queue.Empty:
                await asyncio.sleep(0.1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )