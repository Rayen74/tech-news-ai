"""
Unit & Integration Test Script for LLM Judge (Phase S2 / BF3).

Tests:
1. Source credibility coefficient calculation (F09).
2. Global score weighting & clamping logic.
3. Scoring of single article with LLM Judge.
4. Batch article evaluation and sorting.
"""

import sys
from judge import (
    get_source_credibility_modifier,
    calculate_score_global,
    judge_article,
    judge_articles_batch
)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def test_credibility_modifiers():
    print("🧪 [Test 1] Testing Source Credibility Modifiers (F09)...")
    assert get_source_credibility_modifier("arXiv CS") == 0.25
    assert get_source_credibility_modifier("Dev.to Community") == -0.10
    assert get_source_credibility_modifier("GitHub Trending") == 0.15
    assert get_source_credibility_modifier("TechCrunch") == 0.0
    print("  ✅ All source credibility modifiers verified!")


def test_score_global_calculation():
    print("\n🧪 [Test 2] Testing score_global Weighted Formula...")
    # Base calculation: (80*0.35) + (90*0.30) + (70*0.20) + (60*0.15) = 28 + 27 + 14 + 9 = 78
    # arXiv modifier +25%: 78 * 1.25 = 97.5 -> 98
    score_arxiv = calculate_score_global(novelty=90, impact=80, originality=70, virality=60, source_name="arXiv")
    assert score_arxiv == 98, f"Expected 98, got {score_arxiv}"

    # Dev.to modifier -10%: 78 * 0.90 = 70.2 -> 70
    score_devto = calculate_score_global(novelty=90, impact=80, originality=70, virality=60, source_name="Dev.to")
    assert score_devto == 70, f"Expected 70, got {score_devto}"
    
    print("  ✅ Weighted formula and source adjustment verified!")


def test_judge_scoring():
    print("\n🧪 [Test 3] Static Sample Article Scoring...")
    sample_articles = [
        {
            "title": "Quantum Supremacy Achieved in New Topological Qubit Demonstration",
            "url": "https://arxiv.org/abs/2401.99999",
            "source": "arXiv",
            "summary": "Researchers demonstrate fault-tolerant quantum error correction using non-Abelian anyons in a topological semiconductor device."
        },
        {
            "title": "10 CSS Tricks Every Web Developer Should Know in 2026",
            "url": "https://dev.to/example/10-css-tricks",
            "source": "Dev.to",
            "summary": "A roundup of helpful CSS properties including container queries, subgrid, and popover API examples."
        }
    ]

    results = judge_articles_batch(sample_articles)

    assert len(results) == 2
    assert "score_global" in results[0]
    assert "justification" in results[0]
    assert results[0]["source"] == "arXiv"

    print("  ✅ Static sample scoring verified!")


def test_scraped_articles_scoring():
    print("\n🧪 [Test 4] Scoring Dynamically Harvested Articles (from extracted_articles.json)...")
    import os
    import json

    json_path = "extracted_articles.json"
    assert os.path.exists(json_path), f"File {json_path} not found. Run scrapper first!"

    with open(json_path, "r", encoding="utf-8") as f:
        scraped_articles = json.load(f)

    assert len(scraped_articles) > 0, "extracted_articles.json is empty!"

    # Take a sample of top 3 scraped articles to test dynamic evaluation
    test_batch = scraped_articles[:3]
    print(f"  📥 Loaded {len(scraped_articles)} scraped articles from disk. Scoring batch of {len(test_batch)}...")

    results = judge_articles_batch(test_batch)

    assert len(results) == len(test_batch)
    for article in results:
        assert "score_global" in article, f"Missing score_global in {article.get('title')}"
        assert "justification" in article, f"Missing justification in {article.get('title')}"
        assert 0 <= article["score_global"] <= 100, f"Score out of bounds: {article['score_global']}"
        assert isinstance(article["recommande"], bool)

    print(f"  ✅ Dynamic evaluation of scraped articles verified! Top Scored: '{results[0]['title']}' ({results[0]['score_global']}/100)")


if __name__ == "__main__":
    test_credibility_modifiers()
    test_score_global_calculation()
    test_judge_scoring()
    test_scraped_articles_scoring()
