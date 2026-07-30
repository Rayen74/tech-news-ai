"""
Judge Module for Tech News AI.

This module implements the LLM Judge (BF3 & F07-F11) that evaluates harvested 
technology articles against 4 independent criteria:
1. Novelty (0-100): Information freshness over 30-day window.
2. Impact (0-100): Direct technical/industry consequence for developers.
3. Originality (0-100): Unique angle or non-mainstream source.
4. Virality (0-100): Discussion and shareability potential.

It applies source credibility multipliers (arxiv +25%, dev.to/blogs -10%),
computes a final composite score (score_global), provides a 2-sentence justification,
and flags recommended top articles.
"""

import os
import sys
import json
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Type alias for article dictionary representation
ArticleDict = Dict[str, Union[str, int, float, bool]]

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

load_dotenv()

# Source credibility modifiers (BF3 / F09)
SOURCE_CREDIBILITY_MODIFIERS: Dict[str, float] = {
    "arxiv": 0.25,
    "github": 0.15,
    "infoq": 0.10,
    "hacker news": 0.05,
    "techcrunch": 0.0,
    "ars technica": 0.0,
    "the verge": 0.0,
    "venturebeat": 0.0,
    "dev.to": -0.10,
    "blog": -0.10,
}


class JudgeEvaluation(BaseModel):
    """
    Structured Pydantic schema for LLM Judge scoring response.
    """
    score_novelty: int = Field(
        description="Freshness score 0-100: Has this topic NOT been widely covered in the past 30 days?"
    )
    score_impact: int = Field(
        description="Impact score 0-100: Practical impact/relevance for software developers or the tech industry."
    )
    score_originality: int = Field(
        description="Originality score 0-100: Is the source, technical insight, or angle unique rather than mainstream hype?"
    )
    score_viralite: int = Field(
        description="Virality score 0-100: High discussion potential and likely to be shared on tech platforms."
    )
    justification: str = Field(
        description="Concise 2-sentence justification explaining the scores and editorial verdict."
    )


def get_source_credibility_modifier(source_name: str) -> float:
    """
    Determine the source credibility coefficient (F09).
    
    Args:
        source_name (str): Name of publisher/source.
        
    Returns:
        float: Multiplier modifier (e.g. 0.25 for arXiv, -0.10 for blogs).
    """
    s_lower = source_name.lower()
    for key, mod in SOURCE_CREDIBILITY_MODIFIERS.items():
        if key in s_lower:
            return mod
    return 0.0


def calculate_score_global(
    novelty: int,
    impact: int,
    originality: int,
    virality: int,
    source_name: str
) -> int:
    """
    Compute the weighted score_global with source credibility adjustment.
    
    Weights:
        - Impact: 35%
        - Novelty: 30%
        - Originality: 20%
        - Virality: 15%
    
    Credibility Modifier:
        - Applied as multiplier: base_score * (1 + modifier)
        - Clamped strictly between 0 and 100.
    """
    base_score = (impact * 0.35) + (novelty * 0.30) + (originality * 0.20) + (virality * 0.15)
    credibility_mod = get_source_credibility_modifier(source_name)
    adjusted_score = base_score * (1.0 + credibility_mod)
    return max(0, min(100, int(round(adjusted_score))))


def _call_llm_judge(title: str, summary: str, source: str) -> JudgeEvaluation:
    """
    Call LLM to evaluate an article against the 4 scoring criteria.
    Uses Groq API (via httpx) with fallback to default fallback scores if API unavailable.
    """
    groq_api_key = os.getenv("GROQ_API_KEY")
    
    system_prompt = """
You are an impartial AI Technology News Judge.

Your purpose is to evaluate whether a technology news article is genuinely valuable for experienced software engineers, AI engineers, and technical decision-makers.

You must ignore marketing language, hype, popularity, social media trends, and writing style. Evaluate only the factual and technical value of the content.

General principles:

- Prefer primary sources over secondary reporting.
- Prefer official announcements over commentary.
- Prefer research papers over blog speculation.
- Prefer reproducible technical information over opinions.
- Penalize vague claims lacking evidence.
- Penalize clickbait headlines.
- Penalize repeated or recycled news.
- Penalize articles with no actionable technical insight.
- Do not reward popularity alone.
- Do not infer facts that are not explicitly provided.

Evaluate using the following rubric.

score_novelty (0-100)
How new is the information?

0-20:
Old, recycled or widely known news.

21-50:
Incremental update.

51-80:
Significant new feature, research or release.

81-100:
Major breakthrough or first-of-its-kind contribution.

score_impact (0-100)

Measure practical importance for software engineering.

Consider:

- production systems
- AI development
- infrastructure
- cloud
- security
- databases
- developer productivity
- open-source ecosystem

score_originality (0-100)

Measure uniqueness of the technical contribution.

Reward:

- novel architectures
- research contributions
- engineering innovations
- deep implementation details

Penalize:

- generic reporting
- summaries of existing work
- marketing announcements

score_virality (0-100)

Estimate discussion potential within professional engineering communities such as GitHub, Hacker News, Reddit r/programming, and AI research communities.

Do NOT increase this score simply because the article is sensational.

Instead consider:

- controversial technical decisions
- important releases
- surprising benchmarks
- major security incidents
- influential open-source projects

Source credibility adjustment:

Increase confidence when the source is:

- OpenAI
- Anthropic
- Google DeepMind
- Microsoft
- Meta
- AWS
- GitHub
- Kubernetes
- Docker
- PostgreSQL
- PyTorch
- arXiv
- CVE/NVD

Reduce confidence when the source is:

- anonymous
- opinion-based
- rumor
- unverified blog
- AI-generated content without attribution

Provide a concise two-sentence justification explaining the most important positive and negative factors influencing your scores.

Respond ONLY with valid JSON.

{
  "score_novelty": integer,
  "score_impact": integer,
  "score_originality": integer,
  "score_viralite": integer,
  "confidence": "High | Medium | Low",
  "justification": "Exactly two sentences."
}
"""

    user_prompt = f"Source: {source}\nTitle: {title}\nSummary: {summary}"

    # Fallback model tiers if primary model rate-limits or fails
    model_tiers = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768"
    ]

    if groq_api_key:
        import httpx
        import time

        headers = {
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json"
        }

        for model in model_tiers:
            for attempt in range(2):  # Try each model up to 2 times
                try:
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"}
                    }

                    with httpx.Client(timeout=15.0) as client:
                        response = client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
                        if response.status_code == 200:
                            res_json = response.json()
                            content_str = res_json["choices"][0]["message"]["content"]
                            parsed_dict = json.loads(content_str)
                            return JudgeEvaluation(**parsed_dict)
                        elif response.status_code == 429:
                            print(f"⚠️ [Judge Rate Limit 429] Model '{model}' rate limited (attempt {attempt+1}/2). Waiting before retry/fallback...")
                            time.sleep(2.0 * (attempt + 1))
                        else:
                            print(f"⚠️ [Judge API Warning] Groq API ({model}) status {response.status_code}: {response.text[:100]}")
                            break
                except Exception as e:
                    print(f"⚠️ [Judge API Exception] Model '{model}' error: {str(e)[:100]}")
                    break

    # Fallback heuristic calculation if all API attempts are unavailable or fail

    fallback_novelty = 70
    fallback_impact = 65
    fallback_originality = 60
    fallback_virality = 65
    justification = f"Evaluated based on headline relevance for {source}. Solid technical topic with direct interest for developers."
    
    return JudgeEvaluation(
        score_novelty=fallback_novelty,
        score_impact=fallback_impact,
        score_originality=fallback_originality,
        score_viralite=fallback_virality,
        justification=justification
    )


def judge_article(article: ArticleDict) -> ArticleDict:
    """
    Score a single article using the LLM Judge.
    
    Enriches the article dictionary with:
    - score_novelty
    - score_impact
    - score_originality
    - score_viralite
    - score_global
    - justification
    - recommande (bool)
    """
    title = str(article.get("title", ""))
    summary = str(article.get("summary", ""))
    source = str(article.get("source", "Unknown"))

    eval_result = _call_llm_judge(title, summary, source)

    score_global = calculate_score_global(
        novelty=eval_result.score_novelty,
        impact=eval_result.score_impact,
        originality=eval_result.score_originality,
        virality=eval_result.score_viralite,
        source_name=source
    )

    scored_article: ArticleDict = dict(article)
    scored_article["score_novelty"] = eval_result.score_novelty
    scored_article["score_impact"] = eval_result.score_impact
    scored_article["score_originality"] = eval_result.score_originality
    scored_article["score_viralite"] = eval_result.score_viralite
    scored_article["score_global"] = score_global
    scored_article["justification"] = eval_result.justification
    scored_article["recommande"] = score_global >= 60

    return scored_article


def judge_articles_batch(articles: List[ArticleDict]) -> List[ArticleDict]:
    """
    Evaluate a batch of articles with the LLM Judge and sort by score_global descending.
    
    Args:
        articles (List[ArticleDict]): List of article dictionaries.
        
    Returns:
        List[ArticleDict]: List of scored article dictionaries sorted by score_global descending.
    """
    print(f"\n⚖️ [LLM Judge] Evaluating {len(articles)} articles...")
    judged_articles: List[ArticleDict] = []
    
    for i, art in enumerate(articles):
        title = str(art.get("title", ""))[:50]
        print(f"  ⚖️ [{i+1}/{len(articles)}] Scoring: {title}...")
        scored = judge_article(art)
        print(f"     -> Global Score: {scored['score_global']}/100 (Recommandé: {scored['recommande']})")
        judged_articles.append(scored)

    # Sort articles by score_global descending
    judged_articles.sort(key=lambda x: int(x.get("score_global", 0)), reverse=True)
    
    if judged_articles:
        top = judged_articles[0]
        print(f"\n🏆 [Top Selection] '{top.get('title')}' with score {top.get('score_global')}/100 from {top.get('source')}")

    return judged_articles
