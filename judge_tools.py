"""
judge_tools.py
==============
The 5 tools available to the ReAct Judge agent.

Extracted from the notebook almost unchanged (cell 8: "Tool: Article Body
Extraction" through the `judge_tools = [...]` list). The only change is
adding a module-level `logger`, since the notebook relied on one defined
in an earlier cell.

Tools:
    get_article_context       - fetch + extract full article text (Trafilatura, BS4 fallback)
    search_similar_articles   - vector-DB novelty check (uses embeddings.py / database.py)
    search_web_verification   - Tavily search, DuckDuckGo HTML fallback, query-dedup cache
    get_credibility_adjustment - keyword-based publisher tier classifier
    submit_final_evaluation   - the agent's structured final answer
"""

import logging
import os
import time
from typing import Literal

import httpx
import trafilatura
from bs4 import BeautifulSoup
from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Global storage to capture final evaluation, provenance history, and search cache
CURRENT_EVALUATION = {}
CURRENT_RUN_PROVENANCE = []
SEARCH_CACHE = {}  # query deduplication cache


# -----------------------------------------------------
# 1. Tool: Article Body Extraction
# -----------------------------------------------------
# pyrefly: ignore [missing-import]
from tavily import TavilyClient

@tool
def get_article_context(url: str) -> str:
    """Fetch and extract clean full article text directly from a URL using Trafilatura with anti-bot fallback."""
    CURRENT_RUN_PROVENANCE.append({"tool": "get_article_context", "url": url, "timestamp": time.time()})
    if not url or not url.startswith("http"):
        return "Invalid or missing URL."

    # 1. Realistic browser headers to bypass common bot checks
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }

    resp = None
    try:
        # http2=True helps prevent TLS/fingerprint 403s
        with httpx.Client(http2=True, follow_redirects=True, timeout=12.0) as client:
            resp = client.get(url.strip(), headers=headers)
            resp.raise_for_status()
    except Exception as http_err:
        logger.warning(f"⚠️ Direct fetch failed for {url} ({http_err}). Attempting Tavily extraction fallback...")
        
        # 2. Resilient Fallback: Tavily Extract API bypasses Cloudflare/Anti-bot
        api_key = os.getenv("TAVILY_API_KEY")
        if api_key:
            try:
                tavily = TavilyClient(api_key=api_key)
                res = tavily.extract(urls=[url.strip()])
                if res and res.get("results"):
                    raw_text = res["results"][0].get("raw_content", "")
                    if raw_text and len(raw_text.strip()) > 100:
                        logger.info(f"📄 Extracted {len(raw_text)} chars via Tavily fallback from {url}")
                        return raw_text[:10000]
            except Exception as tav_err:
                logger.warning(f"⚠️ Tavily extract fallback also failed: {tav_err}")

        # If fallback fails or not configured, return clean error message
        return f"Extraction failed: {http_err}"

    # 3. Extract text from HTML
    extracted = trafilatura.extract(
        resp.text,
        output_format="txt",
        include_comments=False,
        include_tables=False,
        favor_precision=True
    )

    if not extracted or len(extracted.strip()) < 100:
        soup = BeautifulSoup(resp.text, "html.parser")
        for elem in soup(["script", "style", "nav", "footer", "header", "aside"]):
            elem.decompose()
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 25]
        extracted = "\n\n".join(paragraphs)

    if not extracted:
        return "Could not extract readable article text from this URL."

    logger.info(f"📄 Extracted {len(extracted)} chars from {url}")
    return extracted[:10000]


# -----------------------------------------------------
# 2. Tool: Semantic Similarity / Novelty Search
# -----------------------------------------------------
@tool
def search_similar_articles(title: str, summary: str) -> dict:
    """Search the vector database for articles published within the last 30 days to measure novelty."""
    CURRENT_RUN_PROVENANCE.append({"tool": "search_similar_articles", "title": title, "timestamp": time.time()})
    try:
        from embeddings import generate_embedding
        from database import check_semantic_similarity

        text = f"{title} {summary}"
        emb = generate_embedding(text)
        is_dup, match = check_semantic_similarity(emb, threshold=0.75, day_window=30)

        if is_dup and match:
            sim = match.get("similarity", 0.85)
            return {
                "similar_found": True,
                "match_title": match.get("title"),
                "similarity": round(sim, 2),
                "message": f"Found similar article '{match.get('title')}' with {round(sim*100, 1)}% similarity. Factor this into score_substance."
            }
        return {"similar_found": False, "message": "No similar recent articles found. Topic is novel."}
    except Exception as e:
        logger.warning(f"⚠️ search_similar_articles warning: {e}")
        return {"similar_found": False, "message": f"Similarity search unavailable ({e}). Assume novel."}


# -----------------------------------------------------
# 3. Tool: Web Verification (Tavily Primary + Dedup Cache + DDG Fallback)
# -----------------------------------------------------
@tool
def search_web_verification(query: str) -> str:
    """Perform a web search to verify factual claims, release versions, benchmarks, or paper links."""
    q = query.strip()
    CURRENT_RUN_PROVENANCE.append({"tool": "search_web_verification", "query": q, "timestamp": time.time()})

    # Query Dedup Cache to prevent redundant loops
    if q in SEARCH_CACHE:
        return SEARCH_CACHE[q]

    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        try:
            resp = httpx.post(
                "https://api.tavily.com/search",
                json={"api_key": tavily_key, "query": q, "max_results": 3, "topic": "general"},
                timeout=8.0
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                snippets = [f"[{r.get('title', '')}]: {r.get('content', '')}" for r in results if r.get("content")]
                if snippets:
                    out = "\n".join(snippets[:3])
                    SEARCH_CACHE[q] = out
                    return out
        except Exception as e_tav:
            logger.warning(f"⚠️ Tavily verification search failed, trying fallback: {e_tav}")

    # Fallback to DuckDuckGo HTML scraping
    try:
        url = f"https://html.duckduckgo.com/html/?q={q}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = httpx.get(url, headers=headers, timeout=8.0, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        snippets = [a.get_text(strip=True) for a in soup.find_all("a", class_="result__snippet")[:3]]
        out = "\n".join(snippets) if snippets else "No search snippets found."
        SEARCH_CACHE[q] = out
        return out
    except Exception as e:
        return f"Web search verification failed: {e}"


# -----------------------------------------------------
# 4. Tool: Source Credibility Tier Assessment
# -----------------------------------------------------
@tool
def get_credibility_adjustment(source_name: str) -> dict:
    """Assess publisher tier (primary / secondary / opinion / unknown) as an evidence quality signal."""
    CURRENT_RUN_PROVENANCE.append({"tool": "get_credibility_adjustment", "source": source_name, "timestamp": time.time()})
    s = source_name.lower()
    primary = ["arxiv", "github", "nvd", "nist", "openai", "deepmind", "google", "anthropic", "microsoft", "meta", "pytorch", "kubernetes", "docker", "postgresql", "cve"]
    secondary = ["techcrunch", "the verge", "ars technica", "venturebeat", "infoq", "hacker news", "wired", "infoworld", "aws.amazon.com", "reuters"]
    opinion = ["dev.to", "medium", "substack", "blog", "reddit", "issuewire"]

    for key in primary:
        if key in s:
            return {"source": source_name, "source_tier": "primary", "note": "Primary source: official docs, repo, or paper."}
    for key in secondary:
        if key in s:
            return {"source": source_name, "source_tier": "secondary", "note": "Secondary source: reputable tech media or aggregator."}
    for key in opinion:
        if key in s:
            return {"source": source_name, "source_tier": "opinion", "note": "Opinion source: blog or community commentary."}
    return {"source": source_name, "source_tier": "unknown", "note": "Unclassified publisher."}


# -----------------------------------------------------
# 5. Tool: Submit Final Evaluation Schema & Tool
# -----------------------------------------------------
class FinalEvaluation(BaseModel):
    score_impact: int = Field(ge=0, le=100, description="Impact score integer 0-100: Real-world engineering consequence.")
    score_substance: int = Field(ge=0, le=100, description="Substance score integer 0-100: Technical novelty, depth, and significance.")
    score_practicality: int = Field(ge=0, le=100, description="Practicality score integer 0-100: Actionability and utility for engineers.")
    source_tier: Literal["primary", "secondary", "opinion", "unknown"] = Field(description="Publisher tier.")
    verification_status: Literal["verified", "partially_verified", "unverified", "contradicted"] = Field(description="Evidence verification state.")
    confidence: Literal["High", "Medium", "Low"] = Field(description="Confidence rating in the evidence.")
    justification: str = Field(description="Exactly two sentences: 1) Strongest technical merit; 2) Main limitation/weakness.")


@tool(args_schema=FinalEvaluation)
def submit_final_evaluation(
    score_impact: int,
    score_substance: int,
    score_practicality: int,
    source_tier: str,
    verification_status: str,
    confidence: str,
    justification: str
) -> str:
    """Submit the final evaluated scores and verdict after gathering evidence."""
    global CURRENT_EVALUATION
    CURRENT_RUN_PROVENANCE.append({"tool": "submit_final_evaluation", "timestamp": time.time()})
    CURRENT_EVALUATION = {
        "score_impact": int(score_impact),
        "score_substance": int(score_substance),
        "score_practicality": int(score_practicality),
        "source_tier": source_tier,
        "verification_status": verification_status,
        "confidence": confidence,
        "justification": justification.strip()
    }
    return "Evaluation successfully recorded."


judge_tools = [
    get_article_context,
    search_similar_articles,
    search_web_verification,
    get_credibility_adjustment,
    submit_final_evaluation
]
logger.info(f"✅ Registered {len(judge_tools)} ReAct tools: {[t.name for t in judge_tools]}")