# Tech News AI — Evidence-First AI Editorial Pipeline

> An automated editorial engine that discovers technology news, removes duplicate coverage, investigates technical claims with a tool-using ReAct agent, applies deterministic scoring rules, and produces evidence-backed editorial outputs.

## Overview

**Tech News AI** is an automated editorial pipeline designed for:

* Software engineers
* AI engineers and researchers
* Technical leaders
* Software architects
* Developers tracking emerging technologies

The system continuously discovers technology news, filters duplicate coverage, investigates the underlying article and its technical claims, verifies important information against external sources, evaluates the article using deterministic scoring rules, and produces a grounded editorial verdict.

The core principle is:

> **Evidence First — never score an article from its headline or summary alone.**

The system attempts to retrieve the actual article content, investigate technical claims, verify important benchmarks and version numbers, assess source credibility, and preserve the evidence used during evaluation.

---

# Architecture

The project uses a **deterministic pipeline with one autonomous ReAct investigation agent**, rather than artificially splitting every task into a separate LLM agent.

This distinction is intentional.

Instead of creating multiple independent agents for extraction, scoring, verification, and rewriting, the system gives the ReAct agent the tools required to investigate an article and then uses deterministic Python code to govern the final decision.

### High-Level Architecture

```text
                    ┌──────────────────────────────┐
                    │      NEWS DISCOVERY           │
                    │                              │
                    │ RSS / Target Sites / Tavily  │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │       ARTICLE SCRAPING        │
                    │                              │
                    │ Crawl4AI / Playwright        │
                    │ Trafilatura / BeautifulSoup  │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │      FAST-PATH DEDUP          │
                    │                              │
                    │ 1. Canonical URL             │
                    │ 2. SHA-256 content hash      │
                    │ 3. Vector similarity         │
                    └──────────────┬───────────────┘
                                   │
                              Unique Article
                                   │
                                   ▼
             ┌──────────────────────────────────────────┐
             │      EVIDENCE-FIRST REACT AGENT          │
             │                                          │
             │  Investigates the article using tools    │
             │                                          │
             │  ┌────────────────────────────────────┐  │
             │  │ get_article_context                │  │
             │  │ search_web_verification            │  │
             │  │ get_credibility_adjustment         │  │
             │  │ search_similar_articles             │  │
             │  │ submit_final_evaluation             │  │
             │  └────────────────────────────────────┘  │
             └──────────────────────┬───────────────────┘
                                    │
                                    ▼
                       ┌────────────────────────┐
                       │  EVIDENCE DOSSIER      │
                       │                        │
                       │ Claims                 │
                       │ Sources                │
                       │ Verification status    │
                       │ Confidence             │
                       │ Provenance             │
                       └────────────┬───────────┘
                                    │
                                    ▼
                  ┌──────────────────────────────────┐
                  │ DETERMINISTIC SCORING ENGINE     │
                  │                                  │
                  │ Impact       40%                 │
                  │ Substance    35%                 │
                  │ Practicality 25%                 │
                  │                                  │
                  │ + ceilings                       │
                  │ + weakest-link rules             │
                  │ + verification constraints       │
                  └───────────────┬──────────────────┘
                                  │
                                  ▼
                   ┌────────────────────────────┐
                   │    EDITORIAL DECISION      │
                   │                            │
                   │ RECOMMEND / REVIEW / REJECT│
                   └──────────────┬─────────────┘
                                  │
                                  ▼
                   ┌────────────────────────────┐
                   │    EDITORIAL REWRITE       │
                   │                            │
                   │ LLM-assisted synthesis     │
                   │ of selected articles       │
                   └──────────────┬─────────────┘
                                  │
                                  ▼
                   ┌────────────────────────────┐
                   │     NEON POSTGRESQL         │
                   │        + pgvector           │
                   └────────────────────────────┘
```

---

# Why This Architecture?

The project deliberately avoids **agent bloat**.

A common approach to agentic systems is to create a separate LLM agent for every stage:

```text
Extraction Agent
      ↓
Evidence Agent
      ↓
Scoring Agent
      ↓
Judge Agent
      ↓
Escalation Agent
```

That can increase:

* latency
* token consumption
* failure points
* orchestration complexity
* duplicated reasoning

Tech News AI instead separates **agentic investigation** from **deterministic governance**.

The ReAct agent is responsible for answering:

> **"What evidence can I find about this article and its claims?"**

Python is responsible for answering:

> **"Given that evidence, what score and editorial decision should the system produce?"**

This separation makes the system easier to test, reproduce, and audit.

---

# 1. News Discovery

The pipeline can ingest technology news through:

* RSS feeds
* Targeted technology websites
* Tavily live search
* RSS fallback mechanisms

The discovery layer produces a stream of candidate articles.

```text
RSS / Websites / Tavily
          ↓
     Raw Articles
```

---

# 2. Article Extraction

Candidate articles are processed through the scraping layer.

The system attempts to retrieve the actual article content rather than relying exclusively on:

* RSS summaries
* Search snippets
* Headlines
* Metadata

Supported extraction mechanisms include:

* Crawl4AI
* Playwright
* Trafilatura
* BeautifulSoup

This provides the ReAct investigation stage with the actual technical content whenever possible.

---

# 3. Fast-Path Deduplication

Duplicate detection is intentionally performed before expensive embedding operations.

### Layer 1 — Canonical URL

The system first checks whether the canonical URL already exists.

```text
URL already exists?
        │
       YES ──→ DROP
        │
       NO
        ↓
```

### Layer 2 — SHA-256 Content Hash

A content hash is then used to detect exact duplicates.

```text
Hash already exists?
        │
       YES ──→ DROP
        │
       NO
        ↓
```

### Layer 3 — Semantic Similarity

Only articles that survive the cheap checks are embedded using:

```text
Ollama
└── nomic-embed-text
    └── 768-dimensional vector
```

The vector is compared against recent articles stored in PostgreSQL/pgvector.

If similarity exceeds the configured threshold, the article is treated as duplicate coverage.

This ordering prevents unnecessary embedding computation.

---

# 4. Evidence-First ReAct Investigation

This is the **agentic core of the system**.

The ReAct agent does not simply receive an article and produce a score.

Instead, it can use tools to investigate the article.

### Agent Responsibilities

The agent can:

1. Retrieve the actual article context.
2. Identify important technical claims.
3. Search external sources.
4. Corroborate benchmarks and technical statements.
5. Examine source credibility.
6. Investigate potentially conflicting information.
7. Build an evidence-backed evaluation.
8. Submit structured evaluation data.

### Available Tools

#### `get_article_context`

Retrieves the article's actual content.

Responsibilities include:

* SSRF-safe URL validation
* Article extraction
* text cleaning
* caching
* fallback extraction

---

#### `search_web_verification`

Searches external sources to verify technical claims.

Typical targets include:

* official documentation
* GitHub repositories
* research papers
* vendor announcements
* technical benchmarks
* independent technical sources

The goal is **corroboration**, not simply finding another article repeating the same claim.

---

#### `search_similar_articles`

Checks whether similar coverage already exists.

This provides additional context for determining whether a story contains meaningful novelty.

---

#### `get_credibility_adjustment`

Classifies the source according to its role, such as:

```text
Primary
Secondary
Opinion
Unknown
```

The credibility information is used as part of the evaluation constraints rather than allowing the LLM to arbitrarily assign a final score.

---

#### `submit_final_evaluation`

The agent submits structured investigation results containing information such as:

```text
claims
verification_status
confidence
source_tier
impact
substance
practicality
justification
provenance
```

---

# 5. Deterministic Scoring Engine

The LLM does **not** have unrestricted authority over the final editorial decision.

After investigation, the system applies deterministic Python rules.

## Scoring Formula

```text
ContentScore =
    0.40 × Impact
  + 0.35 × Substance
  + 0.25 × Practicality
```

### Impact — 40%

Measures the potential real-world significance for:

* production systems
* developer workflows
* software architecture
* engineering practices

### Substance — 35%

Measures:

* technical depth
* implementation details
* documentation
* genuine novelty
* technical evidence

### Practicality — 25%

Measures:

* reproducibility
* availability of code or SDKs
* accessibility
* immediate engineering utility

---

# 6. Programmatic Guardrails

The scoring engine applies additional constraints after the agent evaluation.

Examples include:

| Condition                                 | Rule                                |
| ----------------------------------------- | ----------------------------------- |
| Opinion source                            | Substance capped                    |
| Unknown source                            | Substance capped                    |
| Unverified claim                          | Cannot receive High confidence      |
| Unverified article                        | Cannot be automatically recommended |
| Contradicted evidence                     | Strong score restrictions           |
| Substance or Practicality below threshold | Weakest-link penalty                |

These rules ensure that the LLM cannot bypass the editorial policy simply by producing a persuasive explanation.

---

# 7. Editorial Decision

The final system produces one of three decisions:

```text
RECOMMEND
REVIEW
REJECT
```

The decision is based on the deterministic scoring and verification rules.

For example:

```text
                    Evaluated Article
                           │
                           ▼
              ┌────────────────────────┐
              │ Contradicted?           │
              │ Score < threshold?      │
              │ Confidence too low?     │
              └────────────┬───────────┘
                           │
                     YES   │   NO
                      ↓    │
                   REJECT  │
                           ▼
              ┌────────────────────────┐
              │ Meets recommendation    │
              │ requirements?           │
              └────────────┬───────────┘
                           │
                     YES   │   NO
                      ↓    │
                RECOMMEND  REVIEW
```

---

# 8. Editorial Rewrite

After evaluation, the selected article can be passed to an LLM-based editorial stage.

The editorial model is used for **content synthesis and presentation**, not for bypassing the evidence and scoring system.

It can generate:

* rewritten headline
* technical summary
* editorial notes

The original evidence and evaluation remain available for auditing.

---

# 9. Evidence & Provenance

A major goal of the system is **auditability**.

Instead of storing only:

```text
Score: 82
Decision: RECOMMEND
```

the system can retain information about:

```text
Article
   │
   ├── Claims
   │     ├── Claim 1
   │     ├── Claim 2
   │     └── Claim 3
   │
   ├── Sources
   │     ├── Official documentation
   │     ├── Research paper
   │     └── Technical article
   │
   ├── Verification status
   │
   ├── Confidence
   │
   └── Tool execution provenance
```

This makes the final decision inspectable instead of being a black-box LLM output.

---

# 10. Reliability & Performance

The pipeline includes several engineering safeguards.

### SSRF Protection

External URLs are validated before fetching.

The system protects against dangerous targets including:

* private network ranges
* loopback addresses
* link-local addresses
* cloud metadata endpoints
* multicast addresses

### Thread-Safe Evaluation

Batch article evaluation can execute concurrently using bounded worker threads.

```text
Article 1 ──┐
Article 2 ──┤
Article 3 ──┼──→ Bounded Worker Pool
Article 4 ──┤
Article 5 ──┘
```

### Connection Pooling

PostgreSQL connections are pooled to avoid repeatedly creating database connections.

### Circuit Breaker

External model/API failures are isolated through circuit-breaker protection.

The system can:

```text
CLOSED
  ↓ failure threshold
OPEN
  ↓ cooldown
HALF-OPEN
  ↓
CLOSED / OPEN
```

A temporary external service failure should not bring down the entire news-processing pipeline.

---

# 11. Database

The project uses:

* PostgreSQL
* Neon
* pgvector

The database stores article metadata, embeddings, evaluation results, verification information, claims, and provenance.

The vector database is used primarily for semantic duplicate detection and historical article comparison.

---

# 12. Frontend

The project includes a web dashboard built with:

* Next.js
* React
* FastAPI backend
* Server-Sent Events (SSE)

The interface provides visibility into the pipeline rather than hiding the AI processing behind a single loading screen.

### Dashboard Capabilities

#### On-Demand Evaluation

Users can enter a topic and trigger the pipeline.

```text
Kubernetes Security
        ↓
RUN PIPELINE
        ↓
Discovery
        ↓
Deduplication
        ↓
Investigation
        ↓
Scoring
        ↓
Editorial Result
```

#### Live Agent Terminal

The frontend can display pipeline events such as:

```text
[DISCOVERY] Searching technology news...
[DEDUP] URL check passed
[JUDGE] Investigating article...
[TOOL] get_article_context
[TOOL] search_web_verification
[TOOL] get_credibility_adjustment
[SCORER] Applying deterministic rules
[RESULT] REVIEW
```

#### Evidence Dossier

An article can expose:

* verification status
* audited claims
* supporting sources
* confidence
* tool provenance
* editorial synthesis

---

# 13. Project Structure

```text
tech-news-ai/
│
├── main.py
│
├── judge_agent.py
├── judge_tools.py
├── judge.py
│
├── editorial.py
│
├── embeddings.py
├── scrapper.py
├── database.py
├── models.py
├── circuit_breaker.py
│
├── schema.sql
├── requierments.txt
├── .env.example
│
└── frontend/
```

### Core Components

| File                 | Responsibility                      |
| -------------------- | ----------------------------------- |
| `main.py`            | Pipeline orchestration              |
| `judge_agent.py`     | ReAct agent definition              |
| `judge_tools.py`     | Tools available to the agent        |
| `judge.py`           | Evaluation/scoring logic            |
| `editorial.py`       | Editorial LLM synthesis             |
| `scrapper.py`        | Article discovery and extraction    |
| `embeddings.py`      | Embedding generation and similarity |
| `database.py`        | PostgreSQL/pgvector persistence     |
| `models.py`          | Shared data models                  |
| `circuit_breaker.py` | External service fault isolation    |
| `schema.sql`         | Database schema                     |

---

# 14. Technology Stack

### AI

* LLM-based ReAct agent
* Ollama / Ollama Cloud
* `nomic-embed-text`
* Tool calling

### Agentic AI

* ReAct investigation
* Tool-based web verification
* Evidence gathering
* Structured evaluation
* Provenance tracking

### Backend

* Python
* FastAPI
* PostgreSQL
* Neon
* pgvector

### Data Processing

* RSS
* Tavily
* Crawl4AI
* Playwright
* Trafilatura
* BeautifulSoup

### Frontend

* Next.js
* React
* Server-Sent Events

---

# 15. Installation

## Prerequisites

* Python 3.10+
* Node.js 18+
* PostgreSQL/Neon with pgvector
* Ollama or Ollama Cloud
* Tavily API key

For local embeddings:

```bash
ollama pull nomic-embed-text
```

## Clone

```bash
git clone https://github.com/Rayen74/tech-news-ai.git

cd tech-news-ai
```

## Python Environment

### Windows

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
```

## Install Dependencies

```bash
pip install -r requierments.txt
```

## Environment Variables

Create `.env`:

```env
NEON_DATABASE_URL=postgresql://user:password@host/database?sslmode=require

TAVILY_API_KEY=your-tavily-api-key

OLLAMA_API_KEY=your-ollama-api-key

OLLAMA_BASE_URL=http://localhost:11434

FRONTEND_ORIGIN=http://localhost:3000
```

## Start Backend

```bash
uvicorn api:app --reload --port 8000
```

Backend:

```text
http://localhost:8000
```

Swagger:

```text
http://localhost:8000/docs
```

## Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend:

```text
http://localhost:3000
```

---

# 16. Running the Pipeline

The pipeline can also be executed directly:

```bash
python main.py
```

Optional benchmark:

```bash
python baseline_benchmark.py
```

---

# 17. Design Philosophy

The project follows five principles:

### 1. Evidence Before Evaluation

The system investigates the underlying article and important claims before producing an editorial assessment.

### 2. Agentic Where Reasoning Helps

The ReAct agent handles investigation and tool selection.

### 3. Deterministic Where Rules Matter

Scoring, thresholds, penalties, and final decision rules are enforced programmatically.

### 4. Cheap Operations Before Expensive Operations

URL and hash deduplication happen before embedding generation.

### 5. Auditable AI

The system attempts to preserve claims, evidence, confidence, and provenance rather than returning an unexplained score.

---

# 18. What Makes the Project Agentic?

The project should **not** be described as five independent autonomous agents unless those components are actually implemented as such.

The current architecture is better described as:

```text
                 TECH NEWS AI
                      │
        ┌─────────────┴─────────────┐
        │                           │
 Deterministic Pipeline       Autonomous Component
        │                           │
        │                    ReAct Investigation
        │                           │
        │                    ┌──────┴──────┐
        │                    │    Tools    │
        │                    ├─────────────┤
        │                    │ Article     │
        │                    │ Web Search  │
        │                    │ Credibility │
        │                    │ Similarity  │
        │                    └─────────────┘
        │
        ▼
 Deterministic Scoring
        │
        ▼
 Editorial Decision
```

This gives the system a clear separation between:

**Autonomous investigation → Evidence → Deterministic governance → Editorial output**

---

# 19. Future Multi-Agent Evolution

A true multi-agent architecture could be introduced later if the project requires independent specialist reasoning.

For example:

```text
                    SUPERVISOR
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    EXTRACTION       EVIDENCE        EDITORIAL
      AGENT            AGENT           AGENT
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                  DETERMINISTIC
                     SCORER
                         │
                         ▼
                  FINAL DECISION
```

However, this should only be introduced when independent agent reasoning provides a measurable benefit over the current ReAct investigation architecture.

The goal is not to maximize the number of agents.

The goal is to maximize:

```text
Evidence Quality
      +
Reliability
      +
Auditability
      +
Performance
```

---

# 20. Status

**Architecture:** Evidence-first agentic pipeline

**Agent model:** Tool-using ReAct investigation agent

**Decision model:** Deterministic Python scoring engine

**Database:** Neon PostgreSQL + pgvector

**Backend:** FastAPI

**Frontend:** Next.js + React

**Primary objective:** Reliable, evidence-backed technical news evaluation

---

## License

Add the project's license information here when a license is selected.
