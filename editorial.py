"""
editorial.py
============
Editorial Rewrite stage: Decision -> Editorial Rewrite -> Storage.

Takes articles the Judge has already marked "RECOMMEND" and produces a
publication-ready rewritten title + short "why this matters" blurb.

This is new code, not a migration — no editorial-rewrite logic existed in
the original repo or notebook (confirmed by grep before writing this).

Scope, by design:
- Two entry points, different scope:
    - editorial_top_article(articles): rewrites ONLY the single
      highest-score_global article, and only if its decision is
      "RECOMMEND". This is what main.py uses — one best pick per run.
    - editorial_articles_batch(articles): rewrites every RECOMMEND-decision
      article in the batch. Kept available for cases where you want more
      than one article published per run; not used by main.py by default.
  REVIEW/REJECT articles (and, for editorial_top_article, any non-top
  RECOMMEND article) pass through untouched either way.
- The rewrite is grounded in the article's full body text, fetched via
  judge_tools.get_article_context (the same extraction capability the
  Judge uses) plus the title/summary/justification the Judge already
  produced. Fetching is done deterministically in code, not by letting the
  model decide to call a tool — this is still a single LLM call, not a
  ReAct loop. If extraction fails, the rewrite falls back to the original
  summary/justification, same as before.
- Uses its own lazily-warmed-up model client, independent of
  judge_agent.py's MODEL_REGISTRY/circuit breakers, so this module has no
  coupling to the judge module (single responsibility per article).
"""

import logging
import os
from typing import List, Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from judge_tools import get_article_context

load_dotenv()

logger = logging.getLogger(__name__)

ollama_api_key = os.getenv("OLLAMA_API_KEY")

# A lighter/cheaper model than the judge's — this is a rewrite task, not
# multi-step evidence-based reasoning.
EDITORIAL_MODEL = "nemotron-3-nano:30b-cloud"

_editorial_llm = None


def get_editorial_llm() -> ChatOllama:
    """Build + warm up the editorial rewrite model on first use (cached afterwards)."""
    global _editorial_llm
    if _editorial_llm is not None:
        return _editorial_llm

    client = ChatOllama(
        model=EDITORIAL_MODEL,
        base_url="https://ollama.com",
        temperature=0.4,  # a bit of writing latitude, unlike the judge's near-zero temp
        keep_alive=-1,
        client_kwargs={"headers": {"Authorization": f"Bearer {ollama_api_key}"}},
    )

    logger.info(f"🔥 Warming up editorial model -> {EDITORIAL_MODEL}...")
    try:
        client.invoke([SystemMessage(content="ping")])
        logger.info("✅ Editorial model warm-up complete.")
    except Exception as e_warm:
        logger.error(f"🛑 Editorial model warm-up failed: {e_warm}")
        raise

    _editorial_llm = client
    return _editorial_llm


EDITORIAL_SYSTEM_PROMPT = """You are a technical editor writing a post for a daily
tech-news digest read by software engineers, AI researchers, and technical leads.

You are given the article's full body text (when available), its original title/summary,
and a judge's justification for why it was recommended. Base your rewrite on the full
article text as the primary source — the title/summary/justification are supporting
context, not a substitute for it. Never invent facts, numbers, or claims that aren't
present in what you were given. If the full article text is unavailable or extraction
failed, don't mention that in the post itself — just write the best grounded post you
can from the summary/justification alone, and use editor_notes to flag that the full
text wasn't available.

CRITICAL FORMAT REQUIREMENT:
You MUST return ONLY a valid JSON object matching this schema:
{
  "rewritten_title": "string (under 12 words, punchy and factual)",
  "rewritten_summary": "string (3-5 sentences explaining what happened and why it matters)",
  "editor_notes": "string (one short caveat sentence, or empty string)"
}
Do NOT output YAML, markdown code blocks, or explanatory commentary outside the JSON object.

Produce:
1. rewritten_title: A clear, punchy headline (under 12 words). No clickbait, no hype
   words ("revolutionary", "game-changing"), no emoji. State what actually happened.
2. rewritten_summary: A short post (3-5 sentences) explaining what happened, the concrete
   technical detail that makes it real, and why it matters to a technical reader. Lead
   with the concrete fact, not commentary.
3. editor_notes: One short sentence flagging any caveat a reader should know (e.g. full
   article text wasn't available, or a claim was only partially verified), or an empty
   string if none."""


class EditorialRewrite(BaseModel):
    rewritten_title: str = Field(description="Punchy, factual headline, under 12 words.")
    rewritten_summary: str = Field(description="2-3 sentence rewrite explaining what happened and why it matters.")
    editor_notes: str = Field(default="", description="One short caveat sentence, or empty string if none.")


def rewrite_article(article: dict) -> dict:
    """
    Rewrite a single RECOMMEND-decision article's title/summary into a
    publication-ready post, grounded in the article's full body text.

    Does not check article["decision"] itself — that's editorial_articles_batch()'s
    job. Calling this directly on any article dict will rewrite it regardless of
    decision, which is useful for testing.

    Fetches the full article body via judge_tools.get_article_context (a plain
    function call, not agent tool-calling) before writing. If extraction fails,
    falls back to writing from the summary/justification alone.

    Returns the article dict enriched with:
        rewritten_title (str)
        rewritten_summary (str)
        editor_notes (str)
        editorial_error (bool) — True if the rewrite model itself failed and the
            original title/summary were used as a fallback instead. Does NOT
            include extraction failures — those are a normal, expected case
            handled by writing from the summary/justification instead.
    """
    title = article.get("title", "")
    summary = article.get("summary", "")
    justification = article.get("justification", "")
    url = article.get("url", "")

    full_text = get_article_context.invoke({"url": url}) if url else "No URL provided."
    extraction_failed = full_text.startswith(("Invalid or missing URL", "Could not extract", "Extraction failed"))
    if extraction_failed:
        logger.warning(f"⚠️ Editorial: article body unavailable for '{title[:60]}' ({full_text[:80]}). "
                        f"Falling back to summary/justification only.")
        full_text_block = "[Full article text unavailable — write from the summary and justification below.]"
    else:
        full_text_block = full_text[:8000]  # keep the prompt bounded

    user_msg = f"""Title: {title}
Original summary: {summary}
Judge's justification: {justification}

Full article text:
{full_text_block}"""

    result = dict(article)
    try:
        structured_llm = get_editorial_llm().with_structured_output(EditorialRewrite, method="json_mode")
        rewrite: EditorialRewrite = structured_llm.invoke([
            SystemMessage(content=EDITORIAL_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ])
        result["rewritten_title"] = rewrite.rewritten_title.strip()
        result["rewritten_summary"] = rewrite.rewritten_summary.strip()
        editor_notes = rewrite.editor_notes.strip()
        if extraction_failed and not editor_notes:
            editor_notes = "Full article text was unavailable; written from summary only."
        result["editor_notes"] = editor_notes
        result["editorial_error"] = False
    except Exception as e:
        logger.error(f"⚠️ Editorial rewrite failed for '{title[:60]}': {e}")
        result["rewritten_title"] = title
        result["rewritten_summary"] = summary
        result["editor_notes"] = ""
        result["editorial_error"] = True

    return result


def editorial_articles_batch(articles: List[dict]) -> List[dict]:
    """
    Rewrite every RECOMMEND-decision article in a batch. REVIEW/REJECT
    articles are returned unchanged (no rewritten_title/rewritten_summary
    fields added), so downstream storage/publishing can tell rewritten
    articles apart by checking for those keys or by decision.

    Args:
        articles: List of judged article dicts (must have a "decision" key
            — i.e. already passed through judge_articles_batch()).

    Returns:
        The same list, with RECOMMEND articles enriched in place.
    """
    to_rewrite = [a for a in articles if a.get("decision") == "RECOMMEND"]
    print(f"\n✍️  [Editorial] Rewriting {len(to_rewrite)}/{len(articles)} RECOMMEND article(s)...")

    rewritten_by_url = {}
    for i, art in enumerate(to_rewrite):
        title = str(art.get("title", ""))[:50]
        print(f"  ✍️  [{i+1}/{len(to_rewrite)}] Rewriting: {title}...")
        rewritten = rewrite_article(art)
        flag = " ⚠️ editorial_error (fallback to original text)" if rewritten.get("editorial_error") else ""
        print(f"     -> \"{rewritten['rewritten_title']}\"{flag}")
        rewritten_by_url[art.get("url")] = rewritten

    return [rewritten_by_url.get(a.get("url"), a) for a in articles]


def editorial_top_article(articles: List[dict]) -> List[dict]:
    """
    Rewrite only the single best-scoring article in the batch — "today's
    pick" — instead of every RECOMMEND article. All other articles are
    returned unchanged.

    The best article is the one with the highest score_global, regardless
    of order in the input list. It is only actually rewritten if its
    decision is "RECOMMEND" — if today's top-scoring article was a REVIEW
    or REJECT, nothing gets rewritten (there's no good article to publish
    today), and that's printed clearly rather than silently rewriting a
    REJECT article.

    Args:
        articles: List of judged article dicts (must have "score_global"
            and "decision" keys — i.e. already passed through
            judge_articles_batch()).

    Returns:
        The same list, with only the top-scoring article enriched (if it
        qualified).
    """
    if not articles:
        print("\n✍️  [Editorial] No articles to consider — nothing to rewrite.")
        return articles

    top_article = max(articles, key=lambda a: a.get("score_global", 0))
    top_title = str(top_article.get("title", ""))[:60]
    top_score = top_article.get("score_global", 0)

    if top_article.get("decision") != "RECOMMEND":
        print(f"\n✍️  [Editorial] Today's top-scoring article ({top_score}/100, "
              f"decision={top_article.get('decision')}) — '{top_title}' — "
              f"isn't a RECOMMEND, so nothing is being rewritten today.")
        return articles

    print(f"\n✍️  [Editorial] Rewriting today's top pick ({top_score}/100): {top_title}...")
    rewritten = rewrite_article(top_article)
    flag = " ⚠️ editorial_error (fallback to original text)" if rewritten.get("editorial_error") else ""
    print(f"     -> \"{rewritten['rewritten_title']}\"{flag}")

    return [rewritten if a.get("url") == top_article.get("url") else a for a in articles]