"""
Execution Orchestrator for Tech News AI Pipeline.

Discovers today's tech news via the Tavily Search API (scrapper.py's
discover_todays_live_news_tavily), then runs the same downstream pipeline
as before: 3-layer deduplication -> Evidence-First ReAct Judge scoring ->
Neon Postgres storage.

This replaces the previous fixed-source-list + crawl4ai/Groq landing-page
scraping approach (scrape_single_source over a hardcoded `test_sources`
dict). That function still exists in scrapper.py if a fixed-source
approach is needed again later, but this entry point no longer uses it —
so a headless browser (crawl4ai/Playwright) is no longer required to run
this script.

Nothing is written to disk here (no run_summary.json, no
extracted_articles.json) — every stage's results are only printed to the
console. The only persistence is the Neon database upsert itself
(upsert_articles), which is the actual point of a run.
"""

import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
from scrapper import discover_todays_live_news_tavily
from embeddings import generate_embedding
from database import upsert_articles, is_lexical_duplicate, check_semantic_similarity, normalize_url
from judge import judge_articles_batch
from editorial import editorial_top_article

# Load environment configurations
load_dotenv()


def run_pipeline(query: str = None, max_results: int = None):
    """
    Orchestrates one full pipeline run: discovery -> dedup -> judge -> storage.

    Args:
        query: Search query passed to Tavily. Defaults to
            discover_todays_live_news_tavily()'s own default if None.
        max_results: Max number of articles Tavily should return. Defaults
            to discover_todays_live_news_tavily()'s own default if None.
    """
    print("🚀 Initializing Tech News AI Pipeline Run (Tavily Discovery)...")

    discover_kwargs = {}
    if query is not None:
        discover_kwargs["query"] = query
    if max_results is not None:
        discover_kwargs["max_results"] = max_results

    all_articles = discover_todays_live_news_tavily(**discover_kwargs)

    if not all_articles:
        print("\n⚠️ [Discovery] 0 articles discovered — check TAVILY_API_KEY and network connectivity.")
        print("\n================ RUN COMPLETED ================")
        print("Total articles discovered: 0")
        print("=================================================")
        return {
            "status": "empty",
            "top_article": None,
            "articles": [],
            "discovered_count": 0,
            "unique_count": 0,
            "db_result": {"inserted": 0, "skipped": 0, "errors": []},
            "message": "0 articles discovered. Check search query or network connectivity."
        }

    # ── Phase S1: Layered Deduplication (Cheap Filters First) ──
    print(f"\n🔍 [Deduplication] Checking {len(all_articles)} discovered articles for duplicates (Layers 1-3)...")
    surviving_lexical = []

    # Step 1: Cheap O(1) Lexical checks (URL + SHA-256 content hash) — NO embeddings computed yet!
    for i, article in enumerate(all_articles):
        title = article.get("title", "")
        summary = article.get("summary", "")
        url = normalize_url(article.get("url", ""))
        combined_text = f"{title}. {summary}"

        is_lex_dup, lex_reason = is_lexical_duplicate(url, combined_text)
        if is_lex_dup:
            print(f"  🚫 [{i+1}/{len(all_articles)}] [Duplicate Filtered] {lex_reason}")
        else:
            surviving_lexical.append(article)

    print(f"  ⚡ Lexical check: {len(surviving_lexical)}/{len(all_articles)} candidates passed to semantic evaluation.")

    # Step 2: Semantic check — only novel candidates incur embedding compute
    unique_articles = []
    for i, article in enumerate(surviving_lexical):
        title = article.get("title", "")
        summary = article.get("summary", "")
        combined_text = f"{title}. {summary}"

        print(f"  📐 [{i+1}/{len(surviving_lexical)}] Generating embedding & vector check: {title[:50]}...")
        embedding = generate_embedding(combined_text)
        article["embedding"] = embedding

        is_semantic_dup, match = check_semantic_similarity(embedding, threshold=0.88, day_window=30)
        if is_semantic_dup and match:
            sim_pct = match.get("similarity", 0.0) * 100
            print(f"  🚫 [Duplicate Filtered] Layer 3 Duplicate: Semantic similarity {sim_pct:.1f}% > 88% with '{match.get('title')}'")
        else:
            print(f"  ✨ [Accepted] Unique article: {title[:60]}")
            unique_articles.append(article)

    print(f"\n📊 [Deduplication Summary] Kept {len(unique_articles)}/{len(all_articles)} unique articles.")

    db_result = {"inserted": 0, "skipped": len(all_articles), "errors": []}

    if unique_articles:
        # Phase S2: Evidence-First ReAct Judge Scoring
        unique_articles = judge_articles_batch(unique_articles)

        # Phase S3: Editorial Rewrite (today's single best-scoring RECOMMEND article only)
        unique_articles = editorial_top_article(unique_articles)

        # Step 4: Upsert unique scored (+ rewritten, where applicable) articles to Database
        db_result = upsert_articles(unique_articles)

        # Full per-article results to console
        print("\n" + "=" * 70)
        print("JUDGED ARTICLES")
        print("=" * 70)
        for r in unique_articles:
            flag = "  ⚠️ pipeline_error" if r.get("pipeline_error") else ""
            print(f"""
Title:               {r.get('title')}
Source:               {r.get('source')} (tier: {r.get('source_tier')})
Decision:             {r.get('decision')}{flag}
Score Global:         {r.get('score_global')}/100  (base_score: {r.get('base_score')})
  - Impact:           {r.get('score_impact')}
  - Substance:        {r.get('score_substance')}
  - Practicality:     {r.get('score_practicality')}
Verification status:  {r.get('verification_status')}
Confidence:           {r.get('confidence')}
Justification:        {r.get('justification')}""")
            if "rewritten_title" in r:
                editorial_flag = "  ⚠️ editorial_error (fallback to original text)" if r.get("editorial_error") else ""
                print(f"""Rewritten Title:      {r.get('rewritten_title')}{editorial_flag}
Rewritten Summary:    {r.get('rewritten_summary')}
Editor Notes:         {r.get('editor_notes') or '(none)'}""")
        print("=" * 70)
    else:
        print("ℹ️ [Database] All discovered articles were duplicates. No new database writes performed.")

    print("\n================ RUN COMPLETED ================")
    print(f"Total articles discovered: {len(all_articles)}")
    print(f"Unique articles after dedup: {len(unique_articles)}")
    print(f"Database upserts: {db_result['inserted']} inserted, {db_result['skipped']} skipped, {len(db_result['errors'])} errors")
    print("=================================================")

    # Select the highest-ranked article (top pick)
    top_article = unique_articles[0] if unique_articles else None

    return {
        "status": "success",
        "top_article": top_article,
        "articles": unique_articles,
        "discovered_count": len(all_articles),
        "unique_count": len(unique_articles),
        "db_result": db_result,
    }


if __name__ == "__main__":
    run_pipeline()