"""
Execution Orchestrator for Tech News AI Test Pipeline.

Equipped with dynamic JSON structure normalization and Groq API targeting.
"""

import os
import sys
import json
import asyncio
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from crawl4ai import BrowserConfig, LLMConfig, AsyncWebCrawler, CrawlerRunConfig, CacheMode, LLMExtractionStrategy
from models import TechNewsExtraction
from scrapper import scrape_single_source

# Load environment configurations
load_dotenv()

async def test_pipeline():
    """
    Orchestrates the sequential source execution block.
    """
    groq_key = os.getenv("GROQ_API_KEY")
    llm_cfg = LLMConfig(
        provider="groq/openai/gpt-oss-120b",
        api_token=groq_key
    )

    test_sources = {
        "Hacker News": {
            "url": "https://news.ycombinator.com/",
            "rss_url": "https://hnrss.org/frontpage"
        },
        "TechCrunch": {
            "url": "https://techcrunch.com/",
            "rss_url": "https://techcrunch.com/feed/"
        }
    }

    browser_cfg = BrowserConfig(headless=True)
    
    print("🚀 Initializing Resilient Test Run via Groq API...")
    
    try:
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            all_articles = []
            
            for name, urls in test_sources.items():
                source_articles = await scrape_single_source(crawler, name, urls["url"], urls["rss_url"], llm_cfg)
                all_articles.extend(source_articles)
                await asyncio.sleep(1)
            
            print("\n================ TEST RUN COMPLETED ================")
            print(f"Total articles extracted: {len(all_articles)}")
            print("====================================================")
            print(json.dumps(all_articles, indent=2))
            
    except Exception as master_error:
        print(f"\n❌ [Fatal Browser Error] Playwright or Crawler collapsed: {str(master_error)}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
    asyncio.run(test_pipeline())