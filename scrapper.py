"""
Scraper Core Module for Tech News AI.

This module encapsulates the asynchronous crawling utilities powered by Crawl4AI.
It configures the AI extraction strategies using standard Pydantic schemas, 
manages isolated single-page extraction routines, and applies fault handling 
and post-processing metadata corrections.

It also includes discover_todays_live_news_tavily(), a separate discovery
mechanism (migrated from the notebook) that finds today's tech news across
the whole web via the Tavily Search API instead of crawling a fixed list of
landing pages — no static source list, no LLM extraction, just real direct
publisher URLs.
"""

import json
import os
import sys
import asyncio
from datetime import datetime
from typing import Dict, List

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
# pyrefly: ignore [missing-import]
import feedparser
import httpx
# pyrefly: ignore [missing-import]
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode, LLMExtractionStrategy
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from crawl4ai.content_filter_strategy import PruningContentFilter
from models import TechNewsExtraction

import re

def fallback_rss_scrape(source_name: str, rss_url: str) -> list:
    """Fallback method to scrape using RSS if LLM extraction fails."""
    print(f"⚠️ [Fallback] Fetching RSS feed for {source_name} at {rss_url}")
    try:
        feed = feedparser.parse(rss_url)
        extracted_articles = []
        for entry in feed.entries[:2]: # Limit to exactly 2 articles
            summary = entry.get("summary", entry.get("description", "No summary available via RSS"))
            # Clean HTML tags from RSS summary
            clean_summary = re.sub(r'<[^>]+>', '', summary).strip()
            extracted_articles.append({
                "title": entry.get("title", "No Title"),
                "url": entry.get("link", ""),
                "source": source_name,
                "summary": clean_summary[:200] + "..." if len(clean_summary) > 200 else clean_summary
            })
        print(f"✅ [Success] Extracted {len(extracted_articles)} records from RSS for {source_name}")
        return extracted_articles
    except Exception as e:
        print(f"❌ [Failed] RSS Fallback also failed for {source_name}: {str(e)}")
        return []

async def scrape_single_source(crawler: AsyncWebCrawler, source_name: str, url: str, rss_url: str, llm_configs: list, css_selector: str = None) -> list:
    """
    Crawls a specific technology webpage and parses data resiliently regardless of JSON wrapper format.
    
    This function leverages an LLM-driven strategy to intelligently parse article links 
    and details out of raw unstructured Markdown without fragile CSS selectors.
    
    Args:
        crawler (AsyncWebCrawler): An active instances of the shared network crawler session.
        source_name (str): Human-readable identifier for the target site.
        url (str): The landing page URL string to crawl.
        llm_configs (list): List of instantiated connection profiles targeting the AI engine (for fallback).
        css_selector (str, optional): CSS selector to restrict scraping to main content areas.
        
    Returns:
        list: A collection of parsed raw dictionary articles matching ArticleInfo format, 
              or an empty list if an exception or failure occurs.
    """
    print(f"🔄 [Scraping] Initiating extraction for: {source_name} ({url})")
    
    # Ensure llm_configs is a list
    if not isinstance(llm_configs, list):
        llm_configs = [llm_configs]

    # Pre-configure Noise Reduction Strategies via DefaultMarkdownGenerator
    pruning_filter = PruningContentFilter(min_word_threshold=8, threshold_type="fixed")
    md_generator = DefaultMarkdownGenerator(
        content_filter=pruning_filter,
        options={"ignore_images": True, "ignore_links": False}
    )

    for attempt in range(1, 4):
        # Rotate through sub-LLMs: attempt 1 -> model 0, attempt 2 -> model 1, etc.
        current_llm_cfg = llm_configs[(attempt - 1) % len(llm_configs)]
        
        if getattr(current_llm_cfg, 'api_token', None) is None:
            print(f"❌ [Configuration Error] API token is missing for {getattr(current_llm_cfg, 'provider', 'unknown')}!")
            return []

        ai_strategy = LLMExtractionStrategy(
            llm_config=current_llm_cfg,
            schema=TechNewsExtraction.model_json_schema(),
            extraction_type="schema",
            instruction=(
                "Identify primary tech news articles, hot topics, or main headlines. "
                "Extract exactly 2 articles. "
                "For each item, extract the title, ensure the URL is absolute, and write a brief summary."
            ),
            input_format="markdown",
            chunk_token_threshold=800,
            overlap_rate=0.0
        )

        run_cfg_kwargs = {
            "cache_mode": CacheMode.BYPASS,
            "extraction_strategy": ai_strategy,
            "markdown_generator": md_generator,
            "word_count_threshold": 10,
            "page_timeout": 30000,
            "excluded_tags": ['nav', 'footer', 'aside', 'header', 'script', 'style', 'form', 'svg', 'iframe', 'button', 'input', 'dialog'],
            "excluded_selector": ".ad, .cookie-banner, .social-share, .comments, .sidebar, #comments, .menu",
            "remove_overlay_elements": True,
            "only_text": True
        }
        if css_selector:
            run_cfg_kwargs["css_selector"] = css_selector

        run_cfg = CrawlerRunConfig(**run_cfg_kwargs)

        try:
            print(f"🔍 [Attempt {attempt}/3] Scraping {source_name} via {current_llm_cfg.provider}...")
            result = await crawler.arun(url=url, config=run_cfg)
            
            if result.success and result.extracted_content:
                data = json.loads(result.extracted_content)
                
                # --- RESILIENT PARSING BLOCK ---
                # Detect internal litellm errors returned as successful JSON
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and data[0].get("error") is True:
                    raise Exception(f"LiteLLM Provider Error: {data[0].get('content')}")
                elif isinstance(data, dict) and data.get("error") is True:
                    raise Exception(f"LiteLLM Provider Error: {data.get('content')}")
                
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
                    extracted_articles = extracted_articles[:2] # Ensure exactly 2 articles
                    print(f"✅ [Success] Extracted {len(extracted_articles)} records from {source_name}")
                    return extracted_articles
                else:
                    print(f"⚠️ [Warning] Attempt {attempt} returned 0 articles for {source_name}.")
            else:
                print(f"❌ [Extraction Failed] Attempt {attempt} for {source_name} failed: {getattr(result, 'error_message', 'Unknown Error')}")
                
        except Exception as e:
            print(f"💥 [Runtime Exception] Error during processing of {source_name} on attempt {attempt}: {str(e)}")
            
        if attempt < 3:
            await asyncio.sleep(4)  # Backoff before retrying to respect Groq TPM rate limits
            
    print(f"⚠️ [Exhausted] All 3 attempts failed for {source_name}. Falling back to RSS.")
    return fallback_rss_scrape(source_name, rss_url)


def discover_todays_live_news_tavily(
    query: str = "artificial intelligence software engineering cybersecurity cloud computing",
    max_results: int = 5
) -> List[Dict[str, str]]:
    """
    Dynamically discovers today's live tech news articles across the web via
    the Tavily Search API. Returns real, direct publisher URLs (no
    hardcoded/static sites, no redirects) — unlike scrape_single_source(),
    which crawls a fixed list of landing pages.

    Args:
        query (str): Search query passed to Tavily.
        max_results (int): Max number of articles to return.

    Returns:
        list[dict]: Article dicts with title/url/source/summary, or an empty
        list if the request fails for any reason (network error, bad API key,
        etc.) — this never raises, matching the resilient/degrade-gracefully
        behavior of scrape_single_source() and fallback_rss_scrape().
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        print("❌ [Discovery] TAVILY_API_KEY is missing from environment. Please add it to .env.")
        return []

    payload = {
        "api_key": api_key,
        "query": query,
        "topic": "news",          # Restricts strictly to journalistic/news publications
        "days": 1,                 # Strictly published within the past 24 hours (today)
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False
    }

    today_str = datetime.now().strftime("%Y-%m-%d")
    print(f"🌐 [Dynamic Search API] Querying live web news for today ({today_str})...")
    print(f'   Query: "{query}"')

    try:
        resp = httpx.post("https://api.tavily.com/search", json=payload, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"❌ [Discovery] Tavily Search API request failed: {e}")
        return []

    articles = []
    for item in data.get("results", []):
        raw_url = item.get("url", "").strip()
        title = item.get("title", "").strip()
        content = item.get("content", "").strip()

        # Derive publisher source domain dynamically from the real URL
        domain = raw_url.split("/")[2].replace("www.", "") if "//" in raw_url else "Web"

        if raw_url and title:
            articles.append({
                "title": title,
                "url": raw_url,           # Exact, real direct article URL
                "source": domain,          # Real publisher name (e.g. reuters.com, arstechnica.com)
                "summary": content[:300] + "..." if len(content) > 300 else content
            })

    print(f"✅ Discovered {len(articles)} fresh articles with real direct URLs from today:")
    for i, a in enumerate(articles, 1):
        print(f"   [{i}] {a['title'][:65]}... ({a['source']})")
        print(f"       🔗 Real Link: {a['url']}")

    return articles