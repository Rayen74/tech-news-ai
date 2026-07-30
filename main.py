"""
Execution Orchestrator for Tech News AI Test Pipeline.

Equipped with dynamic JSON structure normalization and Groq API targeting.
"""

import os
import sys
import json
import asyncio
import random

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from crawl4ai import BrowserConfig, LLMConfig, AsyncWebCrawler, CrawlerRunConfig, CacheMode, LLMExtractionStrategy
from models import TechNewsExtraction
from scrapper import scrape_single_source
from embeddings import generate_embeddings_batch, generate_embedding
from database import upsert_articles, is_duplicate, normalize_url, calculate_content_hash
from judge import judge_articles_batch

# A list of standard User-Agents to rotate per run
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/114.0",
]

# Load environment configurations
load_dotenv()

async def test_pipeline():
    """
    Orchestrates the sequential source execution block.
    """
    groq_key = os.getenv("GROQ_API_KEY")
    
    # Define primary LLM and sub-LLMs (fallbacks) via litellm/Crawl4AI
    llm_cfgs = [
        LLMConfig(
            provider="groq/llama-3.3-70b-versatile",
            api_token=groq_key
        ),
        LLMConfig(
            provider="groq/llama-3.1-8b-instant",
            api_token=groq_key
        )
    ]

    test_sources = {
    "Hacker News": {
        "url": "https://news.ycombinator.com/",
        "rss_url": "https://hnrss.org/frontpage",
        "css_selector": "#hnmain"
    },

    "OpenAI News": {
        "url": "https://openai.com/news/",
        "rss_url": "https://openai.com/news/rss.xml",
        "css_selector": "main"
    },

    "Google AI Blog": {
        "url": "https://blog.google/technology/ai/",
        "rss_url": "https://blog.google/feeds/posts/default",
        "css_selector": "main"
    },

    "InfoQ": {
        "url": "https://www.infoq.com/",
        "rss_url": "https://feed.infoq.com/",
        "css_selector": "main"
    },

    "arXiv AI": {
        "url": "https://arxiv.org/list/cs.AI/recent",
        "rss_url": "https://rss.arxiv.org/rss/cs.AI",
        "css_selector": "main"
    },

    "GitHub Releases": {
        "url": "https://github.blog/changelog/",
        "rss_url": "https://github.blog/changelog/feed/",
        "css_selector": "main"
    },

    "NVD": {
        "url": "https://nvd.nist.gov/",
        "rss_url": "https://nvd.nist.gov/feeds/xml/cve/misc/nvd-rss.xml",
        "css_selector": "main"
    },

    "TechCrunch": {
        "url": "https://techcrunch.com/",
        "rss_url": "https://techcrunch.com/feed/",
        "css_selector": "main"
    }
}

    browser_cfg = BrowserConfig(
        headless=True,
        user_agent=random.choice(USER_AGENTS)
    )
    
    print("🚀 Initializing Resilient Test Run via Groq API...")
    
    # Structured logging state
    run_summary = {
        "sources_ok": [],
        "sources_ko": [],
        "total_articles": 0,
        "errors": []
    }
    
    try:
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            all_articles = []
            semaphore = asyncio.Semaphore(2)
            
            async def bounded_scrape(name, urls):
                """
                Wraps the scraper with a concurrency limit and random delay for rate limiting.
                """
                async with semaphore:
                    delay = random.uniform(1, 3)
                    print(f"⏳ Sleeping {delay:.2f}s before scraping {name}...")
                    await asyncio.sleep(delay)
                    try:
                        articles = await scrape_single_source(
                            crawler, 
                            name, 
                            urls["url"], 
                            urls["rss_url"], 
                            llm_cfgs, 
                            css_selector=urls.get("css_selector")
                        )
                        return name, articles, None
                    except Exception as e:
                        return name, [], str(e)
            
            tasks = [
                bounded_scrape(name, urls) 
                for name, urls in test_sources.items()
            ]
            results = await asyncio.gather(*tasks)
            
            seen_urls = set()
            seen_titles = set()
            
            for name, source_articles, error in results:
                if error:
                    run_summary["sources_ko"].append(name)
                    run_summary["errors"].append({name: error})
                elif not source_articles:
                    run_summary["sources_ko"].append(name)
                    run_summary["errors"].append({name: "No articles extracted (even with RSS fallback)"})
                else:
                    run_summary["sources_ok"].append(name)
                    for article in source_articles:
                        url = article.get("url", "").strip()
                        title = article.get("title", "").strip()
                        
                        # Deduplicate based on URL or exact title match
                        if (url and url in seen_urls) or (title and title in seen_titles):
                            continue
                            
                        if url:
                            seen_urls.add(url)
                        if title:
                            seen_titles.add(title)
                            
                        all_articles.append(article)
            
            run_summary["total_articles"] = len(all_articles)
            
            # Persist local JSON backups
            with open("run_summary.json", "w", encoding="utf-8") as f:
                json.dump(run_summary, f, indent=2)
            
            with open("extracted_articles.json", "w", encoding="utf-8") as f:
                json.dump(all_articles, f, indent=2)
            
            # ── Phase S1: Layered Deduplication + Embeddings + Supabase Storage ──
            if all_articles:
                print(f"\n🔍 [Deduplication] Checking {len(all_articles)} extracted articles for duplicates (Layers 1-3)...")
                unique_articles = []

                for i, article in enumerate(all_articles):
                    title = article.get("title", "")
                    summary = article.get("summary", "")
                    url = normalize_url(article.get("url", ""))
                    combined_text = f"{title}. {summary}"

                    # Step 1: Generate embedding for Layer 3 semantic check
                    print(f"  📐 [{i+1}/{len(all_articles)}] Generating embedding & checking dedup: {title[:50]}...")
                    embedding = generate_embedding(combined_text)
                    article["embedding"] = embedding

                    # Step 2: Perform 3-Layer Deduplication Check (URL -> SHA-256 Hash -> Semantic Similarity > 0.88)
                    dup_status, reason = is_duplicate(url, combined_text, embedding=embedding, threshold=0.88, day_window=30)

                    if dup_status:
                        print(f"  🚫 [Duplicate Filtered] {reason}")
                    else:
                        print(f"  ✨ [Accepted] Unique article: {title[:60]}")
                        unique_articles.append(article)

                print(f"\n📊 [Deduplication Summary] Kept {len(unique_articles)}/{len(all_articles)} unique articles.")

                if unique_articles:
                    # Phase S2: LLM Judge Scoring (BF3 & F07-F11)
                    unique_articles = judge_articles_batch(unique_articles)

                    # Step 3: Upsert unique scored articles to Database
                    db_result = upsert_articles(unique_articles)
                    run_summary["database"] = db_result
                else:
                    print("ℹ️ [Database] All harvested articles were duplicates. No new database writes performed.")
                    run_summary["database"] = {"inserted": 0, "skipped": len(all_articles), "errors": []}

                # Re-save run_summary with DB results
                with open("run_summary.json", "w", encoding="utf-8") as f:
                    json.dump(run_summary, f, indent=2)
            # ─────────────────────────────────────────────────────────────────────
            
            print("\n================ TEST RUN COMPLETED ================")
            print(f"Total unique articles extracted: {len(all_articles)}")
            if 'db_result' in dir():
                print(f"Database upserts: {db_result['inserted']} inserted, {db_result['skipped']} skipped, {len(db_result['errors'])} errors")
            print(f"Run Summary persisted to run_summary.json: {json.dumps(run_summary, indent=2)}")
            print("====================================================")
            
    except Exception as master_error:
        print(f"\n❌ [Fatal Browser Error] Playwright or Crawler collapsed: {str(master_error)}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
    asyncio.run(test_pipeline())