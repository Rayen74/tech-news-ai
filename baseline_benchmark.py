"""
baseline_benchmark.py
=====================
Run this script to measure baseline latency and database operations
BEFORE any optimizations (deduplication reordering, concurrency, connection pooling).

Usage:
    python baseline_benchmark.py
"""

import time
import sys
import os

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from scrapper import discover_todays_live_news_tavily
from database import normalize_url, is_duplicate
from embeddings import generate_embedding

def measure_baseline(sample_size: int = 5):
    print("=" * 65)
    print(f"📊 TECH NEWS AI — BASELINE PERFORMANCE BENCHMARK (SAMPLE: {sample_size})")
    print("=" * 65)

    # 1. Measure Discovery Time
    t0 = time.perf_counter()
    print("\n[1/3] Measuring Discovery (Tavily)...")
    articles = discover_todays_live_news_tavily(max_results=sample_size)
    t_discovery = time.perf_counter() - t0
    print(f"⏱️ Discovery time: {t_discovery:.2f}s for {len(articles)} articles")

    if not articles:
        print("❌ No articles fetched. Check TAVILY_API_KEY.")
        return

    # 2. Measure Current Ingestion & Deduplication (BEFORE reordering)
    # In current code: Embedding is generated for EVERY article BEFORE checking URL/hash duplicate!
    print("\n[2/3] Measuring Current Sequential Deduplication...")
    print("      (Current flow: ALWAYS generate embedding first -> then query DB)")
    
    t_dedup_start = time.perf_counter()
    embedding_times = []
    db_check_times = []
    
    for i, article in enumerate(articles):
        title = article.get("title", "")
        summary = article.get("summary", "")
        url = normalize_url(article.get("url", ""))
        combined_text = f"{title}. {summary}"

        # Embedding call
        t_emb_0 = time.perf_counter()
        embedding = generate_embedding(combined_text)
        t_emb = time.perf_counter() - t_emb_0
        embedding_times.append(t_emb)

        # 3-layer is_duplicate (opens and closes DB connection each time)
        t_db_0 = time.perf_counter()
        is_dup, reason = is_duplicate(url, combined_text, embedding=embedding, threshold=0.88, day_window=30)
        t_db = time.perf_counter() - t_db_0
        db_check_times.append(t_db)

        status_str = "DUPLICATE" if is_dup else "UNIQUE"
        print(f"  [{i+1}/{len(articles)}] {status_str} | Emb: {t_emb:.2f}s | DB Check: {t_db:.2f}s | {title[:40]}...")

    t_dedup_total = time.perf_counter() - t_dedup_start

    # Summary
    avg_emb = sum(embedding_times) / len(embedding_times) if embedding_times else 0
    avg_db = sum(db_check_times) / len(db_check_times) if db_check_times else 0

    print("\n" + "=" * 65)
    print("BASELINE PERFORMANCE REPORT (BEFORE CHANGES)")
    print("=" * 65)
    print(f"• Total articles processed:         {len(articles)}")
    print(f"• Total Discovery latency:           {t_discovery:.2f}s")
    print(f"• Total Deduplication latency:       {t_dedup_total:.2f}s (sequential)")
    print(f"• Average Embedding latency:         {avg_emb:.2f}s per article")
    print(f"• Average DB Check latency:          {avg_db:.2f}s per article (no pool, connect->close)")
    print(f"• Wasted embedding calls on duplicates: All duplicate articles paid {avg_emb:.2f}s penalty")
    print(f"• Evaluation concurrency:            1 (Sequential - 0% parallelization)")
    print("=" * 65)

if __name__ == "__main__":
    measure_baseline(sample_size=4)
