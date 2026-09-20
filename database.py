"""
Database & Deduplication Module for Tech News AI.

This module encapsulates all interaction with the Neon PostgreSQL database.
It handles database connection initialization, layered hybrid deduplication
(URL normalization -> SHA-256 content hashing -> vector similarity search),
and persistence of scraped tech news items and LLM Judge scores.
"""

import os
import sys
import hashlib
import re
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# pyrefly: ignore [missing-import]
import psycopg2
import psycopg2.extras
from psycopg2 import pool
from contextlib import contextmanager
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv

load_dotenv()

# Module-level flag to ensure schema initialization only runs once per process.
_schema_initialized = False
_connection_pool = None


def _ensure_schema():
    """
    Ensure the pgvector extension, articles table, indexes, and
    match_articles() function exist in the Neon database.

    This runs once per process on the first call to _get_connection().
    It reads schema.sql from the project root and executes it.
    Extensions are created with autocommit=True (required by Postgres).
    """
    global _schema_initialized
    if _schema_initialized:
        return

    dsn = os.getenv("NEON_DATABASE_URL", "")
    if not dsn:
        return  # _get_connection will raise the proper error

    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
    if not os.path.exists(schema_path):
        print("⚠️ [Database] schema.sql not found — skipping auto-init.")
        _schema_initialized = True
        return

    conn = None
    try:
        conn = psycopg2.connect(dsn)

        # Extensions must be created outside a transaction block
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        # Run the full schema (table, indexes, function) in a transaction
        conn.autocommit = False
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()

        _schema_initialized = True
        print("✅ [Database] Schema initialized (extensions, table, indexes, function).")
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"⚠️ [Database] Schema init warning: {str(e)[:200]}")
        # Do NOT mark as initialized on failure — retry on next connection
    finally:
        if conn:
            conn.close()


def _get_pool():
    """Lazily initialize and return the global ThreadedConnectionPool."""
    global _connection_pool
    if _connection_pool is not None:
        return _connection_pool

    _ensure_schema()
    dsn = os.getenv("NEON_DATABASE_URL", "")
    if not dsn:
        raise EnvironmentError(
            "Missing NEON_DATABASE_URL in .env. "
            "Copy the connection string from your Neon project dashboard "
            "(Connect > Connection string) and add it, then restart."
        )

    _connection_pool = pool.ThreadedConnectionPool(
        minconn=2,
        maxconn=10,
        dsn=dsn
    )
    return _connection_pool


@contextmanager
def get_db_connection():
    """
    Context manager that checks out a connection from the ThreadedConnectionPool,
    registers the pgvector adapter, and returns it to the pool on exit.
    """
    p = _get_pool()
    conn = p.getconn()
    try:
        register_vector(conn)
        yield conn
    finally:
        p.putconn(conn)


def _get_connection():
    """
    Legacy helper for backwards compatibility. Returns an open standalone connection.
    Note: Prefer using the `get_db_connection()` context manager for connection pooling.
    """
    _ensure_schema()
    dsn = os.getenv("NEON_DATABASE_URL", "")
    if not dsn:
        raise EnvironmentError("Missing NEON_DATABASE_URL in .env.")
    conn = psycopg2.connect(dsn)
    register_vector(conn)
    return conn


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
    tracking_params = {
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_term',
        'utm_content', 'ref', 'gclid', 'fbclid', 'mc_eid'
    }

    query_params = parse_qs(parsed.query, keep_blank_values=True)
    filtered_params = {
        k: v for k, v in query_params.items()
        if k.lower() not in tracking_params
    }

    new_query = urlencode(filtered_params, doseq=True)

    normalized_parts = (
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip('/'),
        parsed.params,
        new_query,
        ''
    )

    return urlunparse(normalized_parts)


def calculate_content_hash(text: str, max_chars: int = 500) -> str:
    """
    Compute a SHA-256 cryptographic hash of normalized content prefix text.

    Args:
        text (str): Raw body text or concatenated title and summary.
        max_chars (int, optional): Number of prefix characters to hash. Defaults to 500.

    Returns:
        str: Hexadecimal SHA-256 digest string, or empty string if input text is empty.
    """
    if not text:
        return ""

    cleaned_text = re.sub(r'\s+', ' ', text.strip().lower())
    prefix = cleaned_text[:max_chars]

    return hashlib.sha256(prefix.encode('utf-8')).hexdigest()


def check_url_exists(url: str) -> bool:
    """
    Layer 1 Lexical Check: Check if an article with the normalized URL exists in Neon.

    Args:
        url (str): The article URL to verify.

    Returns:
        bool: True if the URL already exists in the database, False otherwise.
    """
def is_lexical_duplicate(url: str, text: str) -> tuple[bool, str]:
    """
    Fast-path Layer 1 & 2 lexical duplicate check using a single pooled DB connection.
    Checks URL existence (Layer 1) and SHA-256 content hash (Layer 2) before any embeddings are computed.

    Args:
        url (str): Article destination URL.
        text (str): Combined title + summary.

    Returns:
        tuple[bool, str]: (is_dup, reason)
    """
    clean_url = normalize_url(url)
    content_hash = calculate_content_hash(text)

    if not clean_url and not content_hash:
        return False, "Empty URL and content"

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if clean_url:
                    cur.execute("SELECT id FROM articles WHERE url = %s LIMIT 1;", (clean_url,))
                    if cur.fetchone() is not None:
                        return True, f"Layer 1 Duplicate: URL already exists ({clean_url})"

                if content_hash:
                    cur.execute("SELECT id FROM articles WHERE content_hash = %s LIMIT 1;", (content_hash,))
                    if cur.fetchone() is not None:
                        return True, f"Layer 2 Duplicate: SHA-256 hash match on text ({content_hash[:10]}...)"
    except Exception as e:
        print(f"⚠️ [Database Check] Lexical check warning: {str(e)[:100]}")

    return False, "Unique lexically"


def check_url_exists(url: str) -> bool:
    """
    Layer 1 Lexical Check: Check if an article with the normalized URL exists in Neon.

    Args:
        url (str): The article URL to verify.

    Returns:
        bool: True if the URL already exists in the database, False otherwise.
    """
    clean_url = normalize_url(url)
    if not clean_url:
        return False

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM articles WHERE url = %s LIMIT 1;", (clean_url,))
                return cur.fetchone() is not None
    except Exception as e:
        print(f"⚠️ [Database Check] Error checking URL existence: {str(e)[:100]}")
        return False


def check_content_hash_exists(content_hash: str) -> bool:
    """
    Layer 2 Lexical Check: Check if an article with the SHA-256 hash exists in Neon.

    Args:
        content_hash (str): The SHA-256 hash string.

    Returns:
        bool: True if an article matching this content hash exists, False otherwise.
    """
    if not content_hash:
        return False

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM articles WHERE content_hash = %s LIMIT 1;", (content_hash,))
                return cur.fetchone() is not None
    except Exception as e:
        print(f"⚠️ [Database Check] Error checking content_hash existence: {str(e)[:100]}")
        return False


def check_semantic_similarity(embedding: list[float], threshold: float = 0.88, day_window: int = 30) -> tuple[bool, dict | None]:
    """
    Layer 3 Semantic Check: Call the match_articles() Postgres function to find
    semantically similar articles.

    Args:
        embedding (list[float]): 768-dimensional vector representation.
        threshold (float, optional): Cosine similarity cutoff. Defaults to 0.88.
        day_window (int, optional): Rolling time window in days. Defaults to 30.

    Returns:
        tuple[bool, dict | None]: (True, match_dict) if a duplicate is found, otherwise (False, None).
    """
    if not embedding or all(v == 0.0 for v in embedding):
        return False, None

    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM match_articles(%s::vector(768), %s, %s, %s);",
                    (embedding, threshold, 1, day_window)
                )
                row = cur.fetchone()
                if row:
                    return True, dict(row)
    except Exception as e:
        print(f"⚠️ [Database Check] Error executing semantic search function: {str(e)[:100]}")

    return False, None


def is_duplicate(url: str, text: str, embedding: list[float] = None, threshold: float = 0.88, day_window: int = 30) -> tuple[bool, str]:
    """
    Perform a complete 3-layer hybrid deduplication check.
    Uses is_lexical_duplicate() first, and only tests semantic similarity if embedding is provided.

    Args:
        url (str): Article destination URL.
        text (str): Concatenated article text/summary.
        embedding (list[float], optional): Vector embedding array. Defaults to None.
        threshold (float, optional): Similarity threshold (0-1). Defaults to 0.88.
        day_window (int, optional): Sliding window in days. Defaults to 30.

    Returns:
        tuple[bool, str]: (is_dup, reason_explanation).
    """
    # 1 & 2. Cheap lexical checks
    is_lex_dup, lex_reason = is_lexical_duplicate(url, text)
    if is_lex_dup:
        return True, lex_reason

    # 3. Expensive semantic similarity check
    if embedding:
        is_semantic_dup, match = check_semantic_similarity(embedding, threshold=threshold, day_window=day_window)
        if is_semantic_dup:
            sim_pct = match.get("similarity", 0.0) * 100
            return True, f"Layer 3 Duplicate: Semantic similarity {sim_pct:.1f}% > {threshold*100}% with '{match.get('title')}'"

    return False, "Unique article"


def upsert_articles(articles: list[dict]) -> dict:
    """
    Upsert a batch of parsed articles into the Neon 'articles' table.

    Args:
        articles (list[dict]): List of article dicts (title, url, source, summary,
            embedding, score_impact, score_substance, score_practicality,
            score_global, source_tier, verification_status, confidence,
            decision, justification, rewritten_title, rewritten_summary,
            editor_notes — all optional except title/url/source/summary).

    Returns:
        dict: Operation summary with counts of inserted/updated, skipped, and error messages.
    """
    if not articles:
        print("⚠️ [Database] No articles to upsert.")
        return {"inserted": 0, "skipped": 0, "errors": []}

    result = {"inserted": 0, "skipped": 0, "errors": []}
    print(f"\n💾 [Database] Upserting {len(articles)} articles to Neon...")

    try:
        with get_db_connection() as conn:
            for i, article in enumerate(articles):
                try:
                    clean_url = normalize_url(article.get("url", ""))
                    title = article.get("title", "Untitled")
                    summary = article.get("summary", "")
                    combined_text = f"{title}. {summary}"
                    content_hash = article.get("content_hash") or calculate_content_hash(combined_text)

                    if not clean_url:
                        print(f"  ⚠️ [{i+1}] Skipping article with empty URL: {title[:50]}")
                        result["skipped"] += 1
                        continue

                    embedding = article.get("embedding")
                    has_embedding = bool(embedding) and any(v != 0.0 for v in embedding)

                    import json
                    provenance_json = json.dumps(article.get("provenance") or [])
                    claims_json = json.dumps(article.get("claims") or [])

                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO articles (
                                title, url, source, summary, content_hash, embedding,
                                score_impact, score_substance, score_practicality,
                                score_global, source_tier, verification_status,
                                confidence, decision, justification,
                                rewritten_title, rewritten_summary, editor_notes,
                                provenance, claims
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (url) DO UPDATE SET
                                title = EXCLUDED.title,
                                source = EXCLUDED.source,
                                summary = EXCLUDED.summary,
                                content_hash = EXCLUDED.content_hash,
                                embedding = COALESCE(EXCLUDED.embedding, articles.embedding),
                                score_impact = COALESCE(EXCLUDED.score_impact, articles.score_impact),
                                score_substance = COALESCE(EXCLUDED.score_substance, articles.score_substance),
                                score_practicality = COALESCE(EXCLUDED.score_practicality, articles.score_practicality),
                                score_global = COALESCE(EXCLUDED.score_global, articles.score_global),
                                source_tier = COALESCE(EXCLUDED.source_tier, articles.source_tier),
                                verification_status = COALESCE(EXCLUDED.verification_status, articles.verification_status),
                                confidence = COALESCE(EXCLUDED.confidence, articles.confidence),
                                decision = COALESCE(EXCLUDED.decision, articles.decision),
                                justification = COALESCE(EXCLUDED.justification, articles.justification),
                                rewritten_title = COALESCE(EXCLUDED.rewritten_title, articles.rewritten_title),
                                rewritten_summary = COALESCE(EXCLUDED.rewritten_summary, articles.rewritten_summary),
                                editor_notes = COALESCE(EXCLUDED.editor_notes, articles.editor_notes),
                                provenance = COALESCE(EXCLUDED.provenance, articles.provenance),
                                claims = COALESCE(EXCLUDED.claims, articles.claims);
                            """,
                            (
                                title, clean_url, article.get("source", "Unknown"), summary,
                                content_hash, embedding if has_embedding else None,
                                article.get("score_impact"), article.get("score_substance"),
                                article.get("score_practicality"), article.get("score_global"),
                                article.get("source_tier"), article.get("verification_status"),
                                article.get("confidence"), article.get("decision"),
                                article.get("justification"),
                                article.get("rewritten_title"), article.get("rewritten_summary"),
                                article.get("editor_notes"),
                                provenance_json, claims_json
                            )
                        )
                    conn.commit()
                    result["inserted"] += 1
                    print(f"  ✅ [{i+1}/{len(articles)}] Upserted: {title[:60]}")

                except Exception as e:
                    conn.rollback()
                    error_msg = str(e)[:200]
                    result["errors"].append(f"{article.get('title', 'Unknown')}: {error_msg}")
                    print(f"  ❌ [{i+1}/{len(articles)}] Failed: {error_msg}")

    except Exception as e:
        print(f"❌ [Database] Connection error during upsert: {str(e)[:200]}")

    print(f"\n📊 [Database] Upsert complete — "
          f"Inserted/Updated: {result['inserted']}, "
          f"Skipped: {result['skipped']}, "
          f"Errors: {len(result['errors'])}")

    return result


def get_article_count() -> int:
    """
    Return the total number of articles stored in the Neon 'articles' table.

    Returns:
        int: The number of rows in the articles table, or -1 on error.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM articles;")
                row = cur.fetchone()
                return row[0] if row else -1
    except Exception as e:
        print(f"⚠️ [Database] Error fetching article count: {str(e)[:100]}")
        return -1


def inspect_articles(limit: int = 5) -> list[dict]:
    """
    Retrieve a sample of stored articles with metadata and embedding dimensions.

    Args:
        limit (int, optional): Number of articles to retrieve. Defaults to 5.

    Returns:
        list[dict]: List of article dicts with title, source, url, and embedding length.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT title, source, url, embedding FROM articles LIMIT %s;", (limit,))
                rows = cur.fetchall()
                results = []
                for item in rows:
                    embedding = item.get("embedding")
                    results.append({
                        "title": item["title"],
                        "source": item["source"],
                        "url": item.get("url", ""),
                        "embedding_dims": len(embedding) if embedding is not None else 0,
                    })
                return results
    except Exception as e:
        print(f"⚠️ [Database] Error inspecting articles: {str(e)[:100]}")
        return []


def get_latest_editorial_pick() -> dict | None:
    """
    Retrieve the single most recent article with a rewritten editorial title and summary,
    or the highest-scoring RECOMMEND article.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = """
                    SELECT 
                        id::text, title, url, source, summary,
                        score_impact, score_substance, score_practicality, score_global,
                        source_tier, verification_status, confidence, decision,
                        justification, rewritten_title, rewritten_summary, editor_notes,
                        provenance, claims,
                        to_char(created_at, 'YYYY-MM-DD"T"HH24:MI:SSZ') as created_at
                    FROM articles
                    WHERE (rewritten_title IS NOT NULL AND rewritten_title != '')
                       OR decision = 'RECOMMEND'
                    ORDER BY created_at DESC, score_global DESC NULLS LAST
                    LIMIT 1;
                """
                cur.execute(query)
                row = cur.fetchone()
                return dict(row) if row else None
    except Exception as e:
        print(f"⚠️ [Database] Error fetching top editorial pick: {str(e)[:100]}")
        return None


def get_articles(
    limit: int = 50, 
    offset: int = 0, 
    decision: str | None = None,
    query: str | None = None,
) -> list[dict]:
    """
    Retrieve paginated articles ordered by newest first, with optional decision and theme/keyword search.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                conditions = []
                params = []

                if decision:
                    conditions.append("decision = %s")
                    params.append(decision)

                if query and query.strip():
                    q_wildcard = f"%{query.strip()}%"
                    conditions.append(
                        "(title ILIKE %s OR summary ILIKE %s OR source ILIKE %s OR rewritten_title ILIKE %s OR rewritten_summary ILIKE %s)"
                    )
                    params.extend([q_wildcard, q_wildcard, q_wildcard, q_wildcard, q_wildcard])

                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

                sql = f"""
                    SELECT 
                        id::text, title, url, source, summary,
                        score_impact, score_substance, score_practicality, score_global,
                        source_tier, verification_status, confidence, decision,
                        justification, rewritten_title, rewritten_summary, editor_notes,
                        provenance, claims,
                        to_char(created_at, 'YYYY-MM-DD"T"HH24:MI:SSZ') as created_at
                    FROM articles
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s;
                """
                params.extend([limit, offset])
                cur.execute(sql, tuple(params))

                rows = cur.fetchall()
                return [dict(r) for r in rows]
    except Exception as e:
        print(f"⚠️ [Database] Error fetching articles: {str(e)[:100]}")
        return []