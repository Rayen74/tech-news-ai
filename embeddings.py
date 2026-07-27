"""
Embeddings Module for Tech News AI.

Generates 768-dimensional vector embeddings using local Ollama (nomic-embed-text model).
"""

import os
import sys
import json
import time

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# pyrefly: ignore [missing-import]
import httpx

OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"
OLLAMA_EMBED_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768


def generate_embedding(text: str, retries: int = 3) -> list[float]:
    """
    Generate a single 768-dim embedding vector for the given text via local Ollama.

    Args:
        text: The input string (title + summary concatenation).
        retries: Number of retry attempts on transient failures.

    Returns:
        A list of 768 floats representing the embedding vector.
    """
    payload = {
        "model": OLLAMA_EMBED_MODEL,
        "prompt": text.strip()[:8000],
    }

    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(OLLAMA_EMBED_URL, json=payload)

            resp.raise_for_status()
            data = resp.json()
            embedding = data.get("embedding", [])

            if len(embedding) != EMBEDDING_DIM:
                print(f"⚠️ [Embedding] Expected {EMBEDDING_DIM} dims, got {len(embedding)}. Padding/truncating.")
                embedding = (embedding + [0.0] * EMBEDDING_DIM)[:EMBEDDING_DIM]

            return embedding

        except Exception as e:
            print(f"❌ [Embedding] Error via Ollama on attempt {attempt}: {str(e)}")
            if attempt < retries:
                time.sleep(1)

    print("❌ [Embedding] All retry attempts exhausted. Returning zero vector.")
    return [0.0] * EMBEDDING_DIM


def generate_embeddings_batch(articles: list[dict]) -> list[dict]:
    """
    Enrich a list of article dicts with 'embedding' field using local Ollama.
    """
    total = len(articles)
    print(f"\n🧠 [Embeddings] Generating {total} embeddings via local Ollama ({OLLAMA_EMBED_MODEL})...")

    for i, article in enumerate(articles):
        title = article.get("title", "")
        summary = article.get("summary", "")
        combined_text = f"{title}. {summary}".strip()

        if not combined_text or combined_text == ".":
            print(f"  ⚠️ [{i+1}/{total}] Skipping empty article — zero vector assigned.")
            article["embedding"] = [0.0] * EMBEDDING_DIM
            continue

        print(f"  📐 [{i+1}/{total}] Embedding: {title[:60]}...")
        article["embedding"] = generate_embedding(combined_text)

    print(f"✅ [Embeddings] All {total} embeddings generated.\n")
    return articles
