"""
Scraper Core Module for Tech News AI.

This module encapsulates the asynchronous crawling utilities powered by Crawl4AI.
It configures the AI extraction strategies using standard Pydantic schemas, 
manages isolated single-page extraction routines, and applies fault handling 
and post-processing metadata corrections.
"""

import json
# pyrefly: ignore [missing-import]
import feedparser
# pyrefly: ignore [missing-import]
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode, LLMExtractionStrategy
from models import TechNewsExtraction

def fallback_rss_scrape(source_name: str, rss_url: str) -> list:
    """Fallback method to scrape using RSS if LLM extraction fails."""
    print(f"⚠️ [Fallback] Fetching RSS feed for {source_name} at {rss_url}")
    try:
        feed = feedparser.parse(rss_url)
        extracted_articles = []
        for entry in feed.entries[:10]: # Limit to top 10 articles
            summary = entry.get("summary", entry.get("description", "No summary available via RSS"))
            extracted_articles.append({
                "title": entry.get("title", "No Title"),
                "url": entry.get("link", ""),
                "source": source_name,
                "summary": summary[:200] + "..." if len(summary) > 200 else summary
            })
        print(f"✅ [Success] Extracted {len(extracted_articles)} records from RSS for {source_name}")
        return extracted_articles
    except Exception as e:
        print(f"❌ [Failed] RSS Fallback also failed for {source_name}: {str(e)}")
        return []

async def scrape_single_source(crawler: AsyncWebCrawler, source_name: str, url: str, rss_url: str, llm_config) -> list:
    """
    Crawls a specific technology webpage and parses data resiliently regardless of JSON wrapper format.
    
    This function leverages an LLM-driven strategy to intelligently parse article links 
    and details out of raw unstructured Markdown without fragile CSS selectors.
    
    Args:
        crawler (AsyncWebCrawler): An active instances of the shared network crawler session.
        source_name (str): Human-readable identifier for the target site.
        url (str): The landing page URL string to crawl.
        llm_config (LLMConfig): Instantiated connection profile targeting the AI engine.
        
    Returns:
        list: A collection of parsed raw dictionary articles matching ArticleInfo format, 
              or an empty list if an exception or failure occurs.
    """
    print(f"🔄 [Scraping] Initiating extraction for: {source_name} ({url})")
    
    if getattr(llm_config, 'api_token', None) is None:
        print(f"❌ [Configuration Error] API token is missing!")
        return []

    ai_strategy = LLMExtractionStrategy(
        llm_config=llm_config,
        schema=TechNewsExtraction.model_json_schema(),
        extraction_type="schema",
        instruction=(
            "Identify primary tech news articles, hot topics, or main headlines. "
            "For each item, extract the title, ensure the URL is absolute, and write a brief summary."
        ),
        input_format="markdown"
    )

    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=ai_strategy,
        word_count_threshold=20,
        page_timeout=30000,
        excluded_tags=['nav', 'footer', 'aside', 'header'],
        remove_overlay_elements=True
    )

    try:
        result = await crawler.arun(url=url, config=run_cfg)
        
        if result.success and result.extracted_content:
            data = json.loads(result.extracted_content)
            
            # --- RESILIENT PARSING BLOCK ---
            # If Groq returns a raw list directly
            if isinstance(data, list):
                extracted_articles = data
            # If Groq wraps it inside the dictionary schema structure
            elif isinstance(data, dict):
                extracted_articles = data.get("articles", [])
            else:
                extracted_articles = []
            # --------------------------------
            
            for article in extracted_articles:
                article["source"] = source_name
                
            if extracted_articles:
                print(f"✅ [Success] Extracted {len(extracted_articles)} records from {source_name}")
                return extracted_articles
            else:
                print(f"⚠️ [Warning] Extraction succeeded but returned 0 articles for {source_name}.")
                return fallback_rss_scrape(source_name, rss_url)
        else:
            print(f"❌ [Extraction Failed] {source_name} failed instantly: {result.error_message}")
            return fallback_rss_scrape(source_name, rss_url)
            
    except Exception as e:
        print(f"💥 [Runtime Exception] Fatal error during processing of {source_name}: {str(e)}")
        return fallback_rss_scrape(source_name, rss_url)