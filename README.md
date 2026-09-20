# Tech News AI — Evidence-First Multi-Agent Architecture & Pipeline

## 1. Project Overview

Tech News AI is an automated editorial engine designed for software engineers, AI researchers, and technical leaders. It autonomously ingests technology news, eliminates duplicate coverage through vector embeddings, verifies technical claims using web-grounded ReAct tools, and scores articles using a multi-agent evaluation hierarchy.

The primary design principle is **Evidence-First Evaluation**: an LLM is never allowed to guess an editorial score from a headline or summary alone. It must extract the real article body, verify benchmarks and version numbers via web searches, evaluate publisher credibility, and apply deterministic scoring rules.

---
## 2. End-to-End System Pipeline Schema

```
+-----------------------------------------------------------------------------------+
|                            1. INGESTION & DISCOVERY                               |
|                                                                                   |
|         [ Today's Live News Discovery (Tavily Search API) / RSS Fallback ]        |
|                                   |                                               |
|                                   v                                               |
|                    Incoming Raw Articles Stream                                   |
+-----------------------------------------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------------------+
|                        2. FAST-PATH DEDUPLICATION ENGINE                          |
|                                                                                   |
|   Incoming Article URL & Content                                                  |
|                 |                                                                 |
|                 v                                                                 |
|     [ Layer 1: Canonical URL Match (Neon DB) ] ----> (Found in DB) -> [ DROP ]    |
|                 | (Unique)                                                        |
|                 v                                                                 |
|     [ Layer 2: SHA-256 Content Hash (Neon DB) ] ---> (Hash Match) ---> [ DROP ]    |
|                 | (Unique — No embeddings wasted!)                                |
|                 v                                                                 |
|     [ Ollama / nomic-embed-text (768-d Vector) ]                                  |
|                 |                                                                 |
|                 v                                                                 |
|     [ Layer 3: Cosine Similarity Search (pgvector) ]                              |
|       - Queries Neon pgvector (last 30 days)                                      |
|       - If similarity >= 88% --------------------------------------> [ DROP ]     |
|       - If similarity <  88% (Novel) ------------------------------> [ PASS ]     |
+-----------------------------------------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------------------+
|              3. CONCURRENT EVIDENCE-FIRST EVALUATION & SCORING PIPELINE           |
|                                                                                   |
|                 [ Bounded ThreadPool Concurrency (4 workers) ]                    |
|                                   |                                               |
|                                   v                                               |
|                 +-----------------------------------+                             |
|                 |    EVIDENCE-FIRST REACT JUDGE     |                             |
|                 |        gpt-oss:120b-cloud         |                             |
|                 |  - Reentrant EvaluationContext    |                             |
|                 |  - Circuit Breaker Protection     |                             |
|                 +-----------------+-----------------+                             |
|                                   |                                               |
|           +-----------------------+-----------------------+                       |
|           |                       |                       |                       |
|           v                       v                       v                       |
|   [ get_article_context ]  [ search_web_verification ]  [ get_credibility_adj ]   |
|   - SSRF-safe validation   - Tavily / DDG search       - Tier: Primary/Secondary/ |
|   - In-memory text cache   - Corroborates claims                Opinion/Unknown   |
|   - Trafilatura fallback                                                          |
|           |                       |                       |                       |
|           +-----------------------+-----------------------+                       |
|                                   |                                               |
|                                   v                                               |
|                     [ submit_final_evaluation ]                                   |
|                                   |                                               |
|                                   v                                               |
|                 +-----------------------------------+                             |
|                 |   DETERMINISTIC SCORING ENGINE    |                             |
|                 |         (Pure Python Code)        |                             |
|                 |  - Weighted formula (0.40 Impact, |                             |
|                 |    0.35 Substance, 0.25 Pract.)   |                             |
|                 |  - Programmatic Tier Ceilings     |                             |
|                 |  - Weakest-Link Penalty (<40)     |                             |
|                 +-----------------+-----------------+                             |
|                                   |                                               |
|                                   v                                               |
|                      [ Final Editorial Verdict ]                                  |
|                      RECOMMEND  /  REVIEW  /  REJECT                              |
+-----------------------------------------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------------------+
|                         4. EDITORIAL REWRITE & STORAGE                            |
|                                                                                   |
|  - Phase S3: Editorial LLM rewrites top RECOMMEND article headline & summary     |
|  - Phase S4: Thread-safe upsert to Neon PostgreSQL using connection pooling       |
+-----------------------------------------------------------------------------------+
```

---

## 3. Architecture Design Principles

The pipeline is built on senior engineering principles prioritizing correctness, efficiency, and reliability over agent bloat:

1. **Reordered Fast-Path Deduplication**:
   - $O(1)$ cheap checks (Canonical URL & SHA-256 Content Hash) execute **before** invoking expensive vector embedding models.
   - Duplicate articles are dropped immediately without spending GPU/CPU cycles or token quotas on embeddings.

2. **SSRF-Hardened Web Scraping**:
   - `url_security.py` verifies all target domains before fetching.
   - Blocks private subnets (RFC 1918), loopback (`127.0.0.1`), link-local/cloud-metadata (`169.254.169.254`), and multicast.
   - An in-memory article cache avoids re-fetching the same URL across tools and retries.

3. **Thread-Safe Concurrency & Connection Pooling**:
   - Replaced module-level evaluation globals with an isolated per-evaluation `EvaluationContext` using `contextvars`.
   - PostgreSQL connections are managed via `ThreadedConnectionPool` (2-10 connections), eliminating repeated connection handshakes.
   - Batch evaluation executes concurrently with bounded worker threads (`max_workers=4`).

4. **Agent Investigation + Deterministic Governance**:
   - The LLM ReAct agent is used strictly for **investigation** (reading the article, checking web benchmarks, corroborating claims).
   - The final score and publication decision are computed by a **deterministic Python scoring engine** enforcing mathematical weights, publisher tier caps, and weakest-link penalties.
   - Today's top-scoring recommended article is polished by the editorial stage before database persistence.``

---

## 5. Scoring Logic & Gatekeeper Schema

### The 3-Pillar Scoring Formula

```
ContentScore = (0.40 * Impact) + (0.35 * Substance) + (0.25 * Practicality)
```

- **Impact (40%)**: Real-world consequence for production systems, developer workflow, or architecture.
- **Substance (35%)**: Technical depth, documentation, and genuine novelty over existing solutions.
- **Practicality (25%)**: Reproducibility, availability of code/SDK, and immediate utility.

### Programmatic Ceiling & Bottleneck Rules

```
+---------------------------------------+-------------------------------------------------------------+
| Condition                             | Enforcement Rule                                            |
+---------------------------------------+-------------------------------------------------------------+
| Publisher Tier = "opinion"            | score_substance is hard-capped at 50                        |
| Publisher Tier = "unknown"            | score_substance is hard-capped at 60                        |
| Verification = "unverified"           | Confidence cannot be "High"; cannot be RECOMMENDED          |
| Verification = "contradicted"         | All scores hard-capped at 20; auto-REJECT                   |
| Critical Bottleneck Rule              | If min(Substance, Practicality) < 40:                       |
|                                       | score_global is scaled down (capped at max 58)              |
+---------------------------------------+-------------------------------------------------------------+
```

### 3-Way Gatekeeper Decision Tree

```
                          [ Evaluated Article ]
                                    |
                                    v
            +-----------------------------------------------+
            | Is status == "contradicted"                   |
            | OR ContentScore < 45                          |
            | OR Confidence == "Low"?                       |
            +-----------------------------------------------+
                               /         \
                             YES          NO
                             /              \
                            v                v
                       [ REJECT ]   +-----------------------------------------------+
                                    | Is ContentScore >= 65                         |
                                    | AND status in ("verified", "partially_verified")
                                    | AND Confidence in ("High", "Medium")          |
                                    | AND Substance >= 45                           |
                                    | AND Practicality >= 40?                       |
                                    +-----------------------------------------------+
                                                       /         \
                                                     YES          NO
                                                     /              \
                                                    v                v
                                             [ RECOMMEND ]      [ REVIEW ]
```

---

## 6. Circuit Breaker Fault Isolation Schema

To protect against external API rate limits, HTTP 500 errors, and authentication failures, each model role possesses an independent circuit breaker:

```
                          +------------------------+
                          |        CLOSED          | <----+
                          |   (Normal Operation)   |      |
                          +------------------------+      |
                                      |                   |
                     Failure count >= 3 or HTTP 403       | Request succeeds
                                      |                   | (Reset count)
                                      v                   |
                          +------------------------+      |
                          |          OPEN          |      |
                          | (Calls Blocked for 30s)|      |
                          +------------------------+      |
                                      |                   |
                           Cooldown window expired        |
                                      |                   |
                                      v                   |
                          +------------------------+      |
                          |       HALF_OPEN        |      |
                          | (1 Canary Test Request)| -----+
                          +------------------------+
                                      |
                              Canary test fails
                                      |
                                      +----> Return to OPEN (30s)
```

- **Failure Isolation**: A service failure on `judge` will not block `extraction` or `evidence_agent`.
- **Fast Failover**: Permanent errors (e.g., HTTP 403 Subscription Required) bypass the retry count and trip immediately to fail fast.
- **Graceful Degradation**: If an article fails due to a network outage, it is tagged with `pipeline_error=True` and routed to `REVIEW` instead of halting the batch.

---

## 7. Database Structure Schema (Neon PostgreSQL + pgvector)

```
Table: articles
+-----------------------+--------------------------+--------------------------------------------------+
| Column Name           | Data Type                | Description                                      |
+-----------------------+--------------------------+--------------------------------------------------+
| id                    | UUID (PRIMARY KEY)       | Unique article identifier (gen_random_uuid())    |
| title                 | TEXT NOT NULL            | Cleaned headline                                 |
| url                   | TEXT UNIQUE NOT NULL     | Canonicalized source URL                         |
| source                | TEXT NOT NULL            | Publisher name (e.g. github.com, arxiv.org)     |
| summary               | TEXT                     | Extracted technical summary                      |
| content_hash          | TEXT UNIQUE              | SHA-256 hash of title + summary for deduplication|
| embedding             | vector(768)              | Ollama nomic-embed-text dense vector representation|
| score_impact          | INT                      | Impact sub-score (0-100)                         |
| score_substance       | INT                      | Technical substance sub-score (0-100)            |
| score_practicality    | INT                      | Practical engineering utility sub-score (0-100)  |
| score_global          | INT                      | Final weighted composite score (0-100)           |
| decision              | TEXT                     | Editorial verdict: RECOMMEND, REVIEW, REJECT     |
| source_tier           | TEXT                     | Classification: primary, secondary, opinion, etc.|
| verification_status   | TEXT                     | Evidence status: verified, unverified, etc.      |
| confidence            | TEXT                     | Agent confidence rating: High, Medium, Low       |
| justification         | TEXT                     | Two-sentence grounded editorial explanation      |
| rewritten_title       | TEXT                     | Synthesized editorial headline (editorial LLM)   |
| rewritten_summary     | TEXT                     | Synthesized editorial summary (editorial LLM)    |
| editor_notes          | TEXT                     | Editorial caveats and verification notes         |
| provenance            | JSONB                    | Real-time ReAct tool execution log trace         |
| claims                | JSONB                    | Audited technical claims and verification proof  |
| created_at            | TIMESTAMP WITH TIME ZONE | Creation timestamp (DEFAULT NOW())               |
+-----------------------+--------------------------+--------------------------------------------------+

Indexes:
- articles_embedding_idx   : HNSW index using vector_cosine_ops
- articles_url_unique_idx  : Unique B-tree index on url
- articles_content_hash_idx: Unique B-tree index on content_hash
```

---

## 8. Frontend Interface & Agent Observability

Tech News AI includes a modern Next.js 16 + React 19 web application providing real-time visibility into the autonomous ReAct agent pipeline:

```
+-----------------------------------------------------------------------------------------+
|                                TECH NEWS AI DASHBOARD                                   |
+-----------------------------------------------------------------------------------------+
| [ Top Banner ]                                                                          |
| Topic Radar: [ "Quantum Computing Advances"                  ] [ RUN PIPELINE ]         |
+-----------------------------------------------------------------------------------------+
| [ Real-Time Streaming Terminal ]                                                        |
| > [DISCOVERY] Fetching live news articles via Tavily API...                             |
| > [DEDUP] Fast-path canonical URL & SHA-256 hash checks passed.                        |
| > [JUDGE] Starting ReAct investigation on: "IBM Unveils Condor Quantum Chip..."         |
| > [TOOL: get_article_context] SSRF validation passed. Extracted 4,200 chars.           |
| > [TOOL: search_web_verification] Corroborating benchmark error-rate claims...          |
| > [SCORER] Impact: 85 | Substance: 78 | Practicality: 70 -> RECOMMEND (Score: 78)       |
+-----------------------------------------------------------------------------------------+
| [ Winner Spotlight Card ]                                                               |
| ⭐ TOP RECOMMENDATION: "IBM Unveils 1,121-Qubit Condor Processor"                      |
| [Impact: 85] [Substance: 78] [Practicality: 70] [Confidence: High] [Tier: Primary]     |
| Rewritten Summary: Synthesized technical breakdown with verified benchmark citations... |
+-----------------------------------------------------------------------------------------+
| [ Evaluated News Feed / Archive ]                                [ Filter: RECOMMEND ]  |
| - Article Card 1: Status: Verified | Score: 82 | [Inspect Claims & Provenance ->]       |
| - Article Card 2: Status: Partially Verified | Score: 68 | [Inspect Claims ->]          |
+-----------------------------------------------------------------------------------------+
```

### Key Frontend Features

1. **On-Demand Topic Evaluator (`/`)**:
   - Enter any technical domain or emerging event (e.g., `Kubernetes Security`, `Gemini 2.5 Pro`, `Agentic AI`).
   - Trigger the end-to-end pipeline on demand via `POST /api/pipeline/run`.
   - Highlights the evaluated winner in a dynamic spotlight card with weighted score gauges and editorial synthesis.

2. **Live ReAct Execution Terminal (`/api/pipeline/stream`)**:
   - Streaming **Server-Sent Events (SSE)** telemetry terminal embedded directly into the homepage.
   - Watch the agent invoke tools in real time (`get_article_context`, `search_web_verification`, `search_similar_articles`).
   - Observe deduplication fast-path skips, token consumption, and deterministic scoring calculations live.

3. **Audited Claims & Evidence Dossier (`/articles` Inspect Drawer)**:
   - Click **"Inspect →"** on any evaluated article to reveal a side-drawer displaying:
     - **Verification Status**: `verified`, `partially_verified`, `unverified`, or `contradicted`.
     - **Audited Claims Table**: Claims extracted by the judge paired directly with web citations, corroborated metrics, and confidence badges.
     - **ReAct Tool Provenance Trace**: The exact sequence of tools executed, inputs passed, and tool outputs returned during evaluation.
     - **Editorial Synthesis Comparison**: Side-by-side view comparing the raw scraped headline/summary with the LLM editorial rewrite.

4. **Historical Digest Archive (`/archive`)**:
   - Chronological archive grouping historical evaluations by date.
   - Highlights the top 2 highest-scoring standout articles per day.

---

## 9. Backend API Interface (`api.py`)

The FastAPI backend exposes the following REST and SSE endpoints for the frontend and external integrations:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/articles` | List evaluated articles with filtering by `decision`, `limit`, and `days`. |
| `GET` | `/api/articles/{article_id}` | Retrieve full article dossier including `claims`, `provenance`, and scores. |
| `GET` | `/api/archive` | Group historical articles by publication date with daily top picks. |
| `POST` | `/api/pipeline/run` | Execute on-demand pipeline for an optional `topic` and return the top-scoring article. |
| `GET` | `/api/pipeline/stream` | Real-time Server-Sent Events (SSE) log stream for live ReAct terminal visualization. |
| `GET` | `/api/stats` | Pipeline health metrics: counts of RECOMMEND, REVIEW, REJECT, and average scores. |

---

## 10. Installation & Quickstart Guide

### Prerequisites
- **Python 3.10+**
- **Node.js 18+** and **npm**
- **[Ollama](https://ollama.com/)** running locally (or an Ollama Cloud API key) with `nomic-embed-text` installed:
  ```bash
  ollama pull nomic-embed-text
  ```
- **[Tavily API Key](https://tavily.com/)** (for live web discovery and claim corroboration)
- **[Neon PostgreSQL](https://neon.tech/)** database with the `vector` extension enabled

---

### Step 1: Backend Setup (FastAPI & Agent Pipeline)

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Rayen74/tech-news-ai.git
   cd tech-news-ai
   ```

2. **Create and activate a virtual environment**:
   ```bash
   # Windows (PowerShell)
   python -m venv venv
   .\venv\Scripts\Activate.ps1

   # Linux / macOS
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install all Python dependencies**:
   ```bash
   pip install -r requierments.txt
   ```

4. **Configure Environment Variables (`.env`)**:
   Create a `.env` file in the project root:
   ```env
   # Neon PostgreSQL Connection String (requires sslmode=require)
   NEON_DATABASE_URL=postgresql://user:password@ep-sample.neon.tech/neondb?sslmode=require

   # Tavily Search API Key (for web discovery & ReAct tool verification)
   TAVILY_API_KEY=tvly-your-api-key

   # Ollama Cloud API Key (for ReAct Judge LLM & Editorial Rewrite)
   OLLAMA_API_KEY=your-ollama-api-key

   # Ollama Base URL (defaults to http://localhost:11434 for local embeddings)
   OLLAMA_BASE_URL=http://localhost:11434

   # Frontend Origin for CORS security
   FRONTEND_ORIGIN=http://localhost:3000
   ```

5. **Initialize Database Tables**:
   The database tables, indices, and extensions (`pgvector`, `claims JSONB`, `provenance JSONB`) are auto-created when the API or pipeline boots. Alternatively, run `schema.sql` directly in your Neon SQL console:
   ```bash
   # (Optional) manual check
   python database.py
   ```

6. **Start the FastAPI Backend Server**:
   ```bash
   uvicorn api:app --reload --port 8000
   ```
   - API is live at: `http://localhost:8000`
   - Interactive Swagger API Documentation: `http://localhost:8000/docs`

---

### Step 2: Frontend Setup (Next.js 16 Dashboard)

1. **Open a new terminal and navigate to the frontend directory**:
   ```bash
   cd frontend
   ```

2. **Install Node.js dependencies**:
   ```bash
   npm install
   ```

3. **Configure Frontend Environment (`frontend/.env.local`)**:
   Create a `.env.local` file inside `frontend/`:
   ```env
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```

4. **Start the Next.js Development Server**:
   ```bash
   npm run dev
   ```
   - Open [http://localhost:3000](http://localhost:3000) in your browser.

---

### Step 3: Running Pipeline via CLI (Optional)

You can also run automated batch runs directly from the terminal without the web UI:

```bash
# Ingest live news for today, deduplicate, judge, score, and persist
python main.py

# Run standard baseline benchmarks
python baseline_benchmark.py
```

