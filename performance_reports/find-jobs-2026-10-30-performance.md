# /find-jobs Performance Report — 2026-10-30

## Overview
- **Persona**: ai-llm-rag (AI / LLM / RAG Engineer, junior)
- **Total wall time**: ~22 minutes (16:30–16:52 UTC)
- **Search rounds**: 2 (first interrupted after store, second fresh)
- **Postings scored**: 20 (10 per round)
- **Report written**: reports/ai-llm-rag/jobs-2026-10-30-165000.md + .html

---

## Time Breakdown by Step

| Step | Description | Wall Time | Notes |
|------|-------------|-----------|-------|
| 1 | Resolve persona + `profile_build --check` | <5 sec | Cached, instant |
| 2 | `profile_query` (JSON + markdown) | <5 sec | Instant |
| 3 | `query_guard` validation | <3 sec | 2 extra queries accepted |
| 4a | **First `search_portals` (interrupted run)** | ~4 min | 132 calls, 362 hits, 10 prepared, stored |
| 4b | **Second `search_portals` (fresh run)** | ~6 min | 132 calls, 371 hits, 10 prepared, stored |
| 5 | `scrape_state store` (×2) | <2 sec each | Verified `added=10` each round |
| 6a | **Scoring batch 1 (10 postings, 2 subagents)** | ~4 min | Parallel posting-scorer tasks |
| 6b | **Scoring batch 2 (10 postings, 2 subagents)** | ~4 min | Parallel posting-scorer tasks |
| 7 | `rank_state apply` (×2) | <2 sec each | Instant |
| 8 | `rank_state sweep` | <1 sec | No closing-soon |
| 9 | **Report writing (markdown + HTML)** | ~3 min | Manual composition |

**Slowest steps**:
1. **`search_portals` (12 min total)** — 264 portal CLI calls (132 × 2 rounds), network-bound, rate-limited by jobicy errors
2. **Posting scoring via subagents (8 min total)** — 4 parallel LLM calls reading 20 body files, model-bound
3. **Report composition (3 min)** — Human-authored detail for 10 top matches

---

## Steps Requiring User Verification / Intervention

| Step | Verification Needed | Why |
|------|---------------------|-----|
| **Profile freshness** | `profile_build --check` output | Must confirm resume hash matches; stale resume → stop and `/profile-build` |
| **Extra query validation** | `query_guard` output (accepted/rejected) | User must see rejected queries with reasons; cannot auto-correct |
| **Portal errors** | `search_portals` errors list | 24 jobicy `tag` length errors — user decides if query style needs change |
| **Relaxed/widened searches** | `search_portals` summary | 69 relaxations, 26 widened — user must know searches were broader than contract |
| **Store verification** | `scrape_state store` `added` count | If `prepared>0` but `added=0` → silent failure, must report and stop |
| **Score veto review** | `rank_state apply` vetoed jobs | 2 vetoed (language + location) — user sees quoted requirement, decides to contest |
| **Sweep results** | `rank_state sweep` closing-soon | User sees deadlines within 7 days; none this run |
| **Report content** | Tailored CV suggestions | Must not invent experience; user reviews before applying |

---

## Bottleneck Analysis

| Bottleneck | Root Cause | Mitigation |
|------------|------------|------------|
| Portal CLI latency | 132 calls × 2 rounds, sequential per portal | Batch calls per portal; cache results across runs |
| Jobicy `tag` errors | Queries >20 chars rejected | `query_guard` already caps at 4 words; truncate or split |
| Subagent scoring serialisation | 4 batches × ~2 min each | Increase batch size (5→10) if model context allows |
| Manual report writing | 10 detailed match cards | Template-driven generation for standard sections |

---

## Recommendations for Next Run

1. **Reuse first-round artifacts** — The interrupted round's 10 postings were valid; continuing saved one search round.
2. **Monitor jobicy health** — 100% failure on long-tag queries; consider shortening base queries or disabling jobicy for verbose queries.
3. **Increase `--limit` if deferred pool is large** — 650+ deferred; a larger limit (e.g., 20) would clear more per run.
4. **Automate report scaffold** — Only the "Key matches/Gaps/Why apply/CV suggestions" need human input; rest is template.