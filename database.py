"""
Database & Deduplication Module for Tech News AI.

This module encapsulates all interaction with the Supabase PostgreSQL database.
It handles database connection initialization, layered hybrid deduplication 
(URL normalization -> SHA-256 content hashing -> vector similarity search),
and persistence of scraped tech news items and LLM Judge scores.
"""

import os
import sys
import json
import hashlib
import re
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# pyrefly: ignore [missing-import]
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


def _get_supabase_client() -> Client:
    """
    Initialize and return a Supabase client using environment variables.

    Reads `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (or `SUPABASE_ANON_KEY`)
    from the environment. Ensures trailing REST path artifacts are removed.

    Returns:
        Client: An instantiated Supabase client connection object.

    Raises:
        EnvironmentError: If required credentials are missing from `.env`.
    """
    url = os.getenv("SUPABASE_URL", "")
    url = url.rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[:-len("/rest/v1")]

    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")

    if not url or not key:
        raise EnvironmentError(
            "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY/SUPABASE_ANON_KEY in .env. "
            "Please add them and restart."
        )

    return create_client(url, key)


def normalize_url(raw_url: str) -> str:
    """
    Normalize a web URL by stripping common marketing/tracking query parameters.

    Removes parameters like `utm_source`, `utm_medium`, `utm_campaign`, `ref`, `gclid`, etc.

    Args:
        raw_url (str): The original full URL string.

    Returns:
        str: A clean, canonicalized URL string.
    """
    if not raw_url:
        return ""

    parsed = urlparse(raw_url.strip())
    # Tracking parameters to drop
    tracking_params = {
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_term',
        'utm_content', 'ref', 'gclid', 'fbclid', 'mc_eid'
    }

    query_params = parse_qs(parsed.query, keep_blank_values=True)
    filtered_params = {
        k: v for k, v in query_params.items()
        if k.lower() not in tracking_params
    }

    # Reconstruct normalized query string sorted for consistency
    new_query = urlencode(filtered_params, doseq=True)

    normalized_parts = (
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip('/'),
        parsed.params,
        new_query,
        ''  # strip fragments (hash target anchors)
    )

    return urlunparse(normalized_parts)


def calculate_content_hash(text: str, max_chars: int = 500) -> str:
    """
    Compute a SHA-256 cryptographic hash of normalized content prefix text.

    Cleans extra whitespace and takes the first `max_chars` characters
    to identify exact or near-exact text duplicates.

    Args:
        text (str): Raw body text or concatenated title and summary.
        max_chars (int, optional): Number of prefix characters to hash. Defaults to 500.

    Returns:
        str: Hexadecimal SHA-256 digest string, or empty string if input text is empty.
    """
    if not text:
        return ""

    # Normalize whitespace (replace multiple spaces/newlines with a single space)
    cleaned_text = re.sub(r'\s+', ' ', text.strip().lower())
    prefix = cleaned_text[:max_chars]

    return hashlib.sha256(prefix.encode('utf-8')).hexdigest()


def check_url_exists(url: str) -> bool:
    """
    Layer 1 Lexical Check: Check if an article with the normalized URL exists in Supabase.

    Args:
        url (str): The article URL to verify.

    Returns:
        bool: True if the URL already exists in the database, False otherwise.
    """
    clean_url = normalize_url(url)
    if not clean_url:
        return False

    client = _get_supabase_client()
    try:
        res = client.table("articles").select("id").eq("url", clean_url).limit(1).execute()
        return len(res.data) > 0
    except Exception as e:
        print(f"⚠️ [Database Check] Error checking URL existence: {str(e)[:100]}")
        return False


def check_content_hash_exists(content_hash: str) -> bool:
    """
    Layer 2 Lexical Check: Check if an article with the SHA-256 hash exists in Supabase.

    Args:
        content_hash (str): The SHA-256 hash string.

    Returns:
        bool: True if an article matching this content hash exists, False otherwise.
    """
    if not content_hash:
        return False

    client = _get_supabase_client()
    try:
        res = client.table("articles").select("id").eq("content_hash", content_hash).limit(1).execute()
        return len(res.data) > 0
    except Exception as e:
        print(f"⚠️ [Database Check] Error checking content_hash existence: {str(e)[:100]}")
        return False


def check_semantic_similarity(embedding: list[float], threshold: float = 0.88, day_window: int = 30) -> tuple[bool, dict | None]:
    """
    Layer 3 Semantic Check: Query Supabase pgvector RPC to find semantically similar articles.

    Searches for existing articles within the last `day_window` days whose cosine
    similarity score exceeds `threshold`.

    Args:
        embedding (list[float]): 768-dimensional vector representation.
        threshold (float, optional): Cosine similarity cutoff. Defaults to 0.88.
        day_window (int, optional): Rolling time window in days. Defaults to 30.

    Returns:
        tuple[bool, dict | None]: (True, match_dict) if a duplicate is found, otherwise (False, None).
    """
    if not embedding or all(v == 0.0 for v in embedding):
        return False, None

    client = _get_supabase_client()
    try:
        res = client.rpc("match_articles", {
            "query_embedding": embedding,
            "match_threshold": threshold,
            "match_count": 1,
            "day_window": day_window
        }).execute()

        if res.data and len(res.data) > 0:
            match = res.data[0]
            return True, match
    except Exception as e:
        print(f"⚠️ [Database Check] Error executing semantic search RPC: {str(e)[:100]}")

    return False, None


def is_duplicate(url: str, text: str, embedding: list[float] = None, threshold: float = 0.88, day_window: int = 30) -> tuple[bool, str]:
    """
    Perform a complete 3-layer hybrid deduplication check.

    Pipeline execution order:
        1. Layer 1 (Lexical URL): Check if normalized URL exists.
        2. Layer 2 (Lexical Hash): Check if SHA-256 hash of text prefix exists.
        3. Layer 3 (Semantic Vector): Check if cosine similarity > `threshold` in the last `day_window` days.

    Args:
        url (str): Article destination URL.
        text (str): Concatenated article text/summary.
        embedding (list[float], optional): Vector embedding array. Defaults to None.
        threshold (float, optional): Similarity threshold (0-1). Defaults to 0.88.
        day_window (int, optional): Sliding window in days. Defaults to 30.

    Returns:
        tuple[bool, str]: (is_dup, reason_explanation).
    """
    # Layer 1: URL check
    clean_url = normalize_url(url)
    if check_url_exists(clean_url):
        return True, f"Layer 1 Duplicate: URL already exists ({clean_url})"

    # Layer 2: Content Hash check
    content_hash = calculate_content_hash(text)
    if content_hash and check_content_hash_exists(content_hash):
        return True, f"Layer 2 Duplicate: SHA-256 hash match on text content ({content_hash[:10]}...)"

    # Layer 3: Semantic embedding check
    if embedding:
        is_semantic_dup, match = check_semantic_similarity(embedding, threshold=threshold, day_window=day_window)
        if is_semantic_dup:
            sim_pct = match.get("similarity", 0.0) * 100
            return True, f"Layer 3 Duplicate: Semantic similarity {sim_pct:.1f}% > {threshold*100}% with '{match.get('title')}'"

    return False, "Unique article"


def upsert_articles(articles: list[dict]) -> dict:
    """
    Upsert a batch of parsed articles into the Supabase 'articles' table.

    Normalizes URLs, computes content hashes, and stores optional embeddings
    and LLM Judge metrics.

    Args:
        articles (list[dict]): List of article dictionary objects containing:
            - title (str)
            - url (str)
            - source (str)
            - summary (str)
            - embedding (list[float], optional)
            - score_novelty (int, optional)
            - score_impact (int, optional)
            - score_originality (int, optional)
            - score_viralite (int, optional)
            - score_global (int, optional)
            - justification (str, optional)

    Returns:
        dict: Operation summary containing count of inserted/updated, skipped, and error messages.
    """
    if not articles:
        print("⚠️ [Database] No articles to upsert.")
        return {"inserted": 0, "skipped": 0, "errors": []}

    client = _get_supabase_client()
    result = {"inserted": 0, "skipped": 0, "errors": []}

    print(f"\n💾 [Database] Upserting {len(articles)} articles to Supabase...")

    for i, article in enumerate(articles):
        try:
            clean_url = normalize_url(article.get("url", ""))
            title = article.get("title", "Untitled")
            summary = article.get("summary", "")
            combined_text = f"{title}. {summary}"
            content_hash = article.get("content_hash") or calculate_content_hash(combined_text)

            row = {
                "title": title,
                "url": clean_url,
                "source": article.get("source", "Unknown"),
                "summary": summary,
                "content_hash": content_hash,
            }

            # Attach vector embedding if present
            embedding = article.get("embedding")
            if embedding and any(v != 0.0 for v in embedding):
                row["embedding"] = embedding

            # Attach optional LLM Judge score columns if present
            for score_field in ["score_novelty", "score_impact", "score_originality", "score_viralite", "score_global"]:
                if score_field in article:
                    row[score_field] = article[score_field]

            if "justification" in article:
                row["justification"] = article["justification"]

            if not row["url"]:
                print(f"  ⚠️ [{i+1}] Skipping article with empty URL: {title[:50]}")
                result["skipped"] += 1
                continue

            response = (
                client.table("articles")
                .upsert(row, on_conflict="url")
                .execute()
            )

            result["inserted"] += 1
            print(f"  ✅ [{i+1}/{len(articles)}] Upserted: {title[:60]}")

        except Exception as e:
            error_msg = str(e)[:200]
            result["errors"].append(f"{article.get('title', 'Unknown')}: {error_msg}")
            print(f"  ❌ [{i+1}/{len(articles)}] Failed: {error_msg}")

    print(f"\n📊 [Database] Upsert complete — "
          f"Inserted/Updated: {result['inserted']}, "
          f"Skipped: {result['skipped']}, "
          f"Errors: {len(result['errors'])}")

    return result


def get_article_count() -> int:
    """
    Return the total number of articles stored in the Supabase 'articles' table.

    Useful for quick health checks and verifying database connectivity.

    Returns:
        int: The number of rows in the articles table, or -1 on error.
    """
    client = _get_supabase_client()
    try:
        res = client.table("articles").select("id", count="exact").execute()
        return res.count if res.count is not None else len(res.data)
    except Exception as e:
        print(f"⚠️ [Database] Error fetching article count: {str(e)[:100]}")
        return -1


def inspect_articles(limit: int = 5) -> list[dict]:
    """
    Retrieve a sample of stored articles with metadata and embedding dimensions.

    Useful for debugging and verifying that embeddings are stored correctly.

    Args:
        limit (int, optional): Number of articles to retrieve. Defaults to 5.

    Returns:
        list[dict]: List of article dicts with title, source, url, and embedding length.
    """
    client = _get_supabase_client()
    try:
        res = client.table("articles").select("title, source, url, embedding").limit(limit).execute()
        results = []
        for item in res.data:
            embedding = item.get("embedding") or []
            results.append({
                "title": item["title"],
                "source": item["source"],
                "url": item.get("url", ""),
                "embedding_dims": len(embedding) if isinstance(embedding, list) else 0,
            })
        return results
    except Exception as e:
        print(f"⚠️ [Database] Error inspecting articles: {str(e)[:100]}")
        return []
