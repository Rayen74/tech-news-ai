"""
Judge Module for Tech News AI.

This module evaluates harvested technology articles using the Evidence-First
ReAct Judge Agent (see judge_agent.py / judge_tools.py / circuit_breaker.py),
which replaces the earlier single-call, 4-criteria LLM judge.

Scoring is now done against 3 pillars instead of 4:
    - score_impact (40%): real-world engineering/industry consequence.
    - score_substance (35%): technical depth and genuine novelty.
    - score_practicality (25%): reproducibility / actionability today.

The agent gathers evidence via tools (full article text, novelty search
against the vector DB, publisher credibility tier, web verification of
factual claims) before submitting scores, and every score is then run
through a deterministic Python formula (weighted average + tier ceilings +
weakest-link penalty) rather than trusted as-is from the model — see
evaluate_article_with_agent() in judge_agent.py for that logic.

Public API is unchanged from the old judge.py so callers (main.py) don't
need to change: judge_article() and judge_articles_batch().

NOTE: the enriched article dicts returned here now carry
score_substance / score_practicality / source_tier / verification_status /
confidence / decision instead of the old score_novelty / score_originality /
score_viralite. database.py's upsert_articles() still writes the old
column set and needs a matching update — tracked separately, not done here.
"""

from typing import Dict, List, Union

from judge_agent import evaluate_article_with_agent

# Type alias for article dictionary representation
ArticleDict = Dict[str, Union[str, int, float, bool]]


def judge_article(article: ArticleDict) -> ArticleDict:
    """
    Score a single article using the Evidence-First ReAct Judge Agent.

    Enriches the article dictionary with:
    - score_impact, score_substance, score_practicality (0-100 each)
    - score_global (deterministic weighted + penalized composite, 0-100)
    - base_score (weighted composite before the weakest-link penalty)
    - source_tier ("primary" | "secondary" | "opinion" | "unknown")
    - verification_status ("verified" | "partially_verified" | "unverified" | "contradicted")
    - confidence ("High" | "Medium" | "Low")
    - decision ("RECOMMEND" | "REVIEW" | "REJECT")
    - recommande (bool) — True only when decision == "RECOMMEND"
    - pipeline_error (bool) — True if this is a neutral fallback score
      because the agent itself failed to run, not a genuine low rating
    - justification (str)
    """
    return evaluate_article_with_agent(dict(article))


import concurrent.futures

def judge_articles_batch(articles: List[ArticleDict], max_workers: int = 4) -> List[ArticleDict]:
    """
    Evaluate a batch of articles with the Judge Agent concurrently using a
    thread pool, and sort results by score_global descending.

    Args:
        articles (List[ArticleDict]): List of article dictionaries.
        max_workers (int): Maximum concurrent evaluation workers. Defaults to 4.

    Returns:
        List[ArticleDict]: List of scored article dictionaries sorted by score_global descending.
    """
    print(f"\n⚖️ [ReAct Judge] Concurrently evaluating {len(articles)} articles (workers={max_workers})...")
    judged_articles: List[ArticleDict] = []

    if not articles:
        return []

    workers = min(max_workers, len(articles))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_article = {
            executor.submit(judge_article, art): art
            for art in articles
        }

        for i, future in enumerate(concurrent.futures.as_completed(future_to_article), 1):
            original_art = future_to_article[future]
            title = str(original_art.get("title", ""))[:50]
            try:
                scored = future.result()
                flag = " ⚠️ pipeline_error" if scored.get("pipeline_error") else ""
                print(f"  ⚖️ [{i}/{len(articles)}] Scored: {title} -> {scored.get('score_global')}/100 | {scored.get('decision')}{flag}")
                judged_articles.append(scored)
            except Exception as e:
                print(f"  ❌ [{i}/{len(articles)}] Evaluation failed for {title}: {e}")
                fallback_scored = dict(original_art)
                fallback_scored.update({
                    "score_impact": 50,
                    "score_substance": 50,
                    "score_practicality": 50,
                    "score_global": 50,
                    "base_score": 50.0,
                    "source_tier": "unknown",
                    "verification_status": "unverified",
                    "confidence": "Low",
                    "decision": "REVIEW",
                    "recommande": False,
                    "pipeline_error": True,
                    "justification": f"Batch worker execution error: {e}"
                })
                judged_articles.append(fallback_scored)

    # Sort articles by score_global descending
    judged_articles.sort(key=lambda x: int(x.get("score_global", 0)), reverse=True)

    if judged_articles:
        top = judged_articles[0]
        print(f"\n🏆 [Top Selection] '{top.get('title')}' with score {top.get('score_global')}/100 from {top.get('source')}")

    return judged_articles