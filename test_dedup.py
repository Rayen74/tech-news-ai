"""
Automated Test Suite for 3-Layer Hybrid Deduplication Pipeline.

Tests:
    1. Layer 1 Lexical URL Deduplication (including query parameter normalization)
    2. Layer 2 Lexical Content-Hash SHA-256 Deduplication
    3. Layer 3 Semantic Embedding Cosine Similarity Deduplication (threshold > 0.88)
"""

import sys
import os

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

from database import normalize_url, calculate_content_hash, is_duplicate
from embeddings import generate_embedding

def test_url_normalization():
    print("\n--- Test 1: URL Normalization ---")
    raw_url = "https://techcrunch.com/2026/07/27/article?utm_source=twitter&utm_medium=social&ref=tech#section1"
    clean_url = normalize_url(raw_url)
    expected = "https://techcrunch.com/2026/07/27/article"
    print(f"Original : {raw_url}")
    print(f"Cleaned  : {clean_url}")
    assert clean_url == expected, f"Expected {expected}, got {clean_url}"
    print("✅ URL Normalization Passed!")

def test_content_hash():
    print("\n--- Test 2: SHA-256 Content Hash ---")
    text1 = "  Artificial Intelligence Companies are   collecting data for new LLM benchmarks.  "
    text2 = "Artificial Intelligence Companies are collecting data for new LLM benchmarks."
    hash1 = calculate_content_hash(text1)
    hash2 = calculate_content_hash(text2)
    print(f"Text 1 Hash: {hash1[:16]}...")
    print(f"Text 2 Hash: {hash2[:16]}...")
    assert hash1 == hash2, "Hashes for whitespace-normalized text should match"
    print("✅ SHA-256 Content Hashing Passed!")

def test_layered_dedup_live():
    print("\n--- Test 3: Live Layered Deduplication Check ---")
    # Test article that exists in DB
    existing_url = "https://news.ycombinator.com/item?id=44685023" # Should be in DB
    existing_text = "Should you wash your solar panels? Details on solar panel maintenance and efficiency."

    print("Checking existing article in DB...")
    is_dup, reason = is_duplicate(existing_url, existing_text)
    print(f"Result: Duplicate={is_dup} -> '{reason}'")

    # Test brand new unique article
    new_url = "https://example.com/unique-test-article-2026"
    new_text = "Quantum computing breakthrough achieved at National Lab using topological qubits."
    print("\nChecking brand new article...")
    new_emb = generate_embedding(new_text)
    is_dup_new, reason_new = is_duplicate(new_url, new_text, embedding=new_emb, threshold=0.88)
    print(f"Result: Duplicate={is_dup_new} -> '{reason_new}'")

if __name__ == "__main__":
    test_url_normalization()
    test_content_hash()
    test_layered_dedup_live()
