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
|  [ Tech RSS Feeds ]        [ Target Sites ]        [ Today's Live News (Tavily) ] |
|            |                      |                              |                |
|            +----------------------+------------------------------+                |
|                                   |                                               |
|                                   v                                               |
|               [ Web Scraper: Crawl4AI / Playwright ]                              |
|                                   |                                               |
|                                   v                                               |
|             [ Trafilatura / BeautifulSoup Text Extraction ]                       |
+-----------------------------------------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------------------+
|                        2. 3-LAYER DEDUPLICATION ENGINE                            |
|                                                                                   |
|   Incoming Article URL & Content                                                  |
|                 |                                                                 |
|                 v                                                                 |
|     [ Layer 1: Canonical URL Match ] -------------> (Found in DB) -> [ DROP ]     |
|                 | (Unique)                                                        |
|                 v                                                                 |
|     [ Layer 2: SHA-256 Content Hash ] -----------> (Hash Match) ---> [ DROP ]     |
|                 | (Unique)                                                        |
|                 v                                                                 |
|     [ Local Ollama: nomic-embed-text (768-d Vector) ]                             |
|                 |                                                                 |
|                 v                                                                 |
|     [ Layer 3: Cosine Similarity Search ]                                         |
|       - Queries Neon pgvector (last 30 days)                                      |
|       - If similarity >= 88% --------------------------------------> [ DROP ]     |
|       - If similarity <  88% (Novel) ------------------------------> [ PASS ]     |
+-----------------------------------------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------------------+
|                     3. MULTI-AGENT EVALUATION PIPELINE                            |
|                                                                                   |
|                      [ Clean Deduplicated Article ]                               |
|                                   |                                               |
|                                   v                                               |
|                 +-----------------------------------+                             |
|                 |        1. EXTRACTION AGENT        |                             |
|                 |      nemotron-3-nano:30b-cloud    |                             |
|                 |  - Cleans raw HTML boilerplate    |                             |
|                 |  - Extracts claims & benchmarks   |                             |
|                 +-----------------+-----------------+                             |
|                                   |                                               |
|                                   v                                               |
|                 +-----------------------------------+                             |
|                 |     2. EVIDENCE GATHERING AGENT   |                             |
|                 |       nemotron-3-super:cloud      |                             |
|                 |  - Executes ReAct Tool Loop       |                             |
|                 +-----------------+-----------------+                             |
|                                   |                                               |
|           +-----------------------+-----------------------+                       |
|           |                       |                       |                       |
|           v                       v                       v                       |
|   [ get_article_context ]  [ search_web_verification ]  [ get_credibility_adj ]   |
|   - Trafilatura full text  - Tavily / DDG search       - Tier: Primary/Secondary/ |
|                            - Corroborates claims                Opinion/Unknown   |
|           |                       |                       |                       |
|           +-----------------------+-----------------------+                       |
|                                   |                                               |
|                                   v                                               |
|                      [ Verified Evidence Dossier ]                                |
|                                   |                                               |
|                                   v                                               |
|                 +-----------------------------------+                             |
|                 |     3. EDITORIAL JUDGE AGENT      |                             |
|                 |         gpt-oss:120b-cloud        |                             |
|                 |  - Assesses technical depth       |                             |
|                 |  - Evaluates Impact / Substance   |                             |
|                 |  - Generates 2-sentence rationale |                             |
|                 +-----------------+-----------------+                             |
|                                   |                                               |
|                                   v                                               |
|                 +-----------------------------------+                             |
|                 |     4. DETERMINISTIC SCORER       |                             |
|                 |      nemotron-3-nano:30b-cloud    |                             |
|                 |  - Mathematical formula (0.40/    |                             |
|                 |    0.35/0.25)                     |                             |
|                 |  - Applies weakest-link penalty   |                             |
|                 |  - Enforces tier ceilings         |                             |
|                 +-----------------+-----------------+                             |
|                                   |                                               |
|                       Is Borderline or Disputed?                                  |
|                                   |                                               |
|                  +----------------+----------------+                              |
|                  | No                              | Yes (Score 60-70 or          |
|                  |                                 |      unverified claim)       |
|                  |                                 v                              |
|                  |               +-----------------------------------+            |
|                  |               |       5. ESCALATION AGENT         |            |
|                  |               |      nemotron-3-ultra:cloud       |            |
|                  |               |  - Resolves edge cases            |            |
|                  |               |  - Editorial tie-breaker          |            |
|                  |               +-----------------+-----------------+            |
|                  |                                 |                              |
|                  +----------------+----------------+                              |
|                                   |                                               |
|                                   v                                               |
|                      [ Final Editorial Verdict ]                                  |
|                      RECOMMEND  /  REVIEW  /  REJECT                              |
+-----------------------------------------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------------------+
|                        4. STORAGE & PERSISTENCE LAYER                             |
|                                                                                   |
|           [ Upsert Article + Vector Embedding into Neon PostgreSQL ]              |
|           [ Record Execution Latencies and Metrics into run_summary.json ]        |
+-----------------------------------------------------------------------------------+
```

---

## 3. Multi-Agent Roles and Responsibilities

The system decouples responsibilities across five distinct agent roles to ensure high accuracy, low latency, and zero single-point-of-failure:

```
+------------------+---------------------------+------------------------------------------------------+
| Agent Role       | Assigned Model            | Primary Responsibility                               |
+------------------+---------------------------+------------------------------------------------------+
| 1. Extraction    | nemotron-3-nano:30b-cloud | High-speed cleaning of scraped HTML. Extracts core   |
|                  |                           | technical claims, code snippets, and release data.   |
|                  |                           |                                                      |
| 2. Evidence      | nemotron-3-super:cloud    | Tool execution specialist. Runs search queries,      |
|                  |                           | novelty checks, and publisher tier classifications.  |
|                  |                           |                                                      |
| 3. Judge         | gpt-oss:120b-cloud        | High-reasoning editorial lead. Assesses production   |
|                  |                           | impact, technical substance, and engineering utility.|
|                  |                           |                                                      |
| 4. Scorer        | nemotron-3-nano:30b-cloud | Deterministic auditor running at temperature=0.0.    |
|                  |                           | Enforces formula weights, ceilings, and penalties.   |
|                  |                           |                                                      |
| 5. Escalation    | nemotron-3-ultra:cloud    | Senior arbitrator invoked only for contentious edge  |
|                  |                           | cases (e.g. high impact but unverified claims).      |
+------------------+---------------------------+------------------------------------------------------+
```

---

## 4. Multi-Agent Execution Flow

```
[ Orchestrator: main.py ]
         |
         | 1. Dispatches raw scraped content
         v
[ Extraction Agent ] ------------------------------------+
         |                                               |
         | 2. Passes clean technical structure           |
         v                                               v
[ Evidence Agent ] <---> [ Tool: get_article_context ]   |
         |         <---> [ Tool: search_similar_articles ] (Uses pgvector)
         |         <---> [ Tool: search_web_verification ] (Uses Tavily/DDG)
         |         <---> [ Tool: get_credibility_adjustment ]
         |
         | 3. Compiles verified evidence dossier
         v
[ Editorial Judge Agent ]
         |
         | 4. Generates: Impact (0-100), Substance (0-100),
         |               Practicality (0-100), Justification
         v
[ Deterministic Scorer ]
         |
         +-----------------------------------------------+
         | Check for conflicts / borderline criteria:    |
         | - Verification is unverified/contradicted     |
         | - Score falls in ambiguous zone (60-70)       |
         +-----------------------------------------------+
                 |                               |
                 | Clear Verdict                 | Edge Case Detected
                 v                               v
         [ Apply Final Decision ]        [ Escalation Agent ]
                 |                               |
                 |                               | Final Arbitrated Decision
                 +---------------+---------------+
                                 |
                                 v
                     [ Output: Scored Article ]
```

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
| score_novelty         | INT                      | Novelty sub-score (0-100)                        |
| score_impact          | INT                      | Impact sub-score (0-100)                         |
| score_substance       | INT                      | Technical substance sub-score (0-100)            |
| score_practicality    | INT                      | Practical engineering utility sub-score (0-100)  |
| score_global          | INT                      | Final weighted composite score (0-100)           |
| decision              | TEXT                     | Editorial verdict: RECOMMEND, REVIEW, REJECT     |
| source_tier           | TEXT                     | Classification: primary, secondary, opinion, etc.|
| verification_status   | TEXT                     | Evidence status: verified, unverified, etc.      |
| confidence            | TEXT                     | Agent confidence rating: High, Medium, Low       |
| justification         | TEXT                     | Two-sentence grounded editorial explanation      |
| created_at            | TIMESTAMP WITH TIME ZONE | Creation timestamp (DEFAULT NOW())               |
+-----------------------+--------------------------+--------------------------------------------------+

Indexes:
- articles_embedding_idx   : HNSW index using vector_cosine_ops
- articles_url_unique_idx  : Unique B-tree index on url
- articles_content_hash_idx: Unique B-tree index on content_hash
```
