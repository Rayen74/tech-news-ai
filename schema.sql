-- ==========================================================
-- Schema for Tech News AI - Supabase (PostgreSQL + pgvector)
-- Extended with LLM Judge scores, content hash, and RPC functions.
-- ==========================================================

-- 1. Enable the pgvector extension for embedding storage
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create or update the articles table
CREATE TABLE IF NOT EXISTS articles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    summary TEXT,
    content_hash TEXT UNIQUE,
    embedding vector(768),
    score_novelty INT,
    score_impact INT,
    score_originality INT,
    score_viralite INT,
    score_global INT,
    justification TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Create indices for fast deduplication and vector search
CREATE INDEX IF NOT EXISTS articles_embedding_idx
ON articles USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE UNIQUE INDEX IF NOT EXISTS articles_url_unique_idx ON articles (url);
CREATE UNIQUE INDEX IF NOT EXISTS articles_content_hash_idx ON articles (content_hash) WHERE content_hash IS NOT NULL;

-- 4. Create Postgres RPC function for Cosine Similarity Search
CREATE OR REPLACE FUNCTION match_articles (
  query_embedding vector(768),
  match_threshold float,
  match_count int,
  day_window int DEFAULT 30
)
RETURNS TABLE (
  id UUID,
  title TEXT,
  url TEXT,
  source TEXT,
  summary TEXT,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    articles.id,
    articles.title,
    articles.url,
    articles.source,
    articles.summary,
    (1 - (articles.embedding <=> query_embedding))::float AS similarity
  FROM articles
  WHERE articles.created_at >= NOW() - (day_window || ' days')::interval
    AND articles.embedding IS NOT NULL
    AND (1 - (articles.embedding <=> query_embedding)) > match_threshold
  ORDER BY articles.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
