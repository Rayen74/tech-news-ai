"""
Scraper Core Module for Tech News AI.

This module encapsulates the asynchronous crawling utilities powered by Crawl4AI.
It configures the AI extraction strategies using standard Pydantic schemas, 
manages isolated single-page extraction routines, and applies fault handling 
and post-processing metadata corrections.
"""

import json
import sys
import asyncio

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
# pyrefly: ignore [missing-import]
import feedparser
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