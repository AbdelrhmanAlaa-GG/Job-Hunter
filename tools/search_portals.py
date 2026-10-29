#!/usr/bin/env python3
"""Search the portals and prepare this run's postings.

One command replaces the whole front half of a run: it reads the search
contract, calls every enabled portal with the flags that portal documents,
merges and normalises the hits, drops the ones already seen, orders what is
left by how well it fits the persona, keeps only the first ``--limit``, fetches
the full posting text, and writes the store file that the scoring step
consumes.

Doing this in a tool rather than in the agent matters. The agent used to
assemble the raw JSON itself, which meant it could - and did - write its own
helper script and run it as if it were a portal. Every stage here is
deterministic, reviewable and testable, and the agent is left with the two
things that genuinely need judgement: scoring a posting and writing the
report.

Usage:
    python3 tools/search_portals.py --persona <slug> --limit <n>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import relevance  # noqa: E402
import scrape_state  # noqa: E402
from job_key import make_key  # noqa: E402
from market import matches_country  # noqa: E402
from paths import (  # noqa: E402
    ROOT,
    active_persona,
    list_personas,
    persona_yaml,
    profile_inputs_path,
    scratch_dir,
    seen_jobs_path,
    tracker_path,
)
from places import load_catalogue  # noqa: E402
from profile_query import (  # noqa: E402
    build_contract,
    build_queries,
    load_yaml,
)
from portal_map import flags_to_argv, load_portals  # noqa: E402
from rank_state import load_state, tracker_pairs  # noqa: E402
from web.posting_guard import guard  # noqa: E402

# How long one portal call may take before it is abandoned.
CALL_TIMEOUT = 180

# How many portal calls run at once.
MAX_WORKERS = 6

# A posting shorter than this still needs a detail fetch.
NEEDS_DETAIL = 120

# Portals whose `search` output does not already carry the full description.
NEEDS_DETAIL_PORTS = {"linkedin-search"}

# The capability matrix, read once.
PORTALS = load_portals()

# The place catalogue, read once.
CATALOGUE = load_catalogue()

# The facets that may be dropped when a search finds nothing, and in what
# order. Dropping a facet widens the search, so it is reported and never done
# quietly.
#
# The category is dropped first: it is this system's own guess at what the
# persona's field is, and in a small market it is the difference between
# everything and nothing. The seniority is dropped second: it is the user's
# own preference, and the title-level judgement in this module still applies
# it afterwards.
RELAXATION_LADDER = {
    "freehire-search": [
        ("category",),
        ("category", "seniority"),
    ],
    "jobicy-search": [
        ("industry",),
    ],
}


def cli_path(portal: str) -> Path:
    """Return the portal CLI's entry point."""
    return ROOT / ".agents" / "skills" / portal / "cli" / "src" / "cli.ts"


def build_calls(contract: dict) -> list[dict]:
    """Turn the contract into one CLI invocation per portal, target and query.

    Only flags a portal actually supports are used, and the flag each one
    uses comes from ``config/portals.yaml`` - never from a table kept here,
    which is how the old code ended up sending flags no CLI had.

    Each call carries the place it was made for. That is what lets a posting
    be checked against the market it was found in, and what lets the
    ordering know that a posting from the place the user asked for is worth
    more than a posting from somewhere else.
    """
    calls: list[dict] = []
    for target in contract.get("portal_targets", []) or []:
        portal = target.get("portal", "")
        if portal not in PORTALS:
            continue
        cli = cli_path(portal)
        if not cli.exists():
            continue

        flags = target.get("flags", {}) or {}
        for query in contract.get("search_queries", []) or []:
            text = str(query.get("query", "")).strip()
            if not text:
                continue

            argv = ["search"]
            argv += flags_to_argv(PORTALS, portal, flags)
            argv += flags_to_argv(PORTALS, portal, {"query": text})
            argv += ["--format", "json"]

            calls.append(
                {
                    "portal": portal,
                    "label": target.get("label", ""),
                    "query": text,
                    "scope": target.get("scope", ""),
                    "place": target.get("place", ""),
                    "place_name": target.get("place_name", ""),
                    "rung": target.get("rung", ""),
                    "work_mode": target.get("work_mode", ""),
                    "flags": dict(flags),
                    "argv": argv,
                }
            )
    return calls


def relaxed_call(call: dict, drop: tuple[str, ...]) -> dict | None:
    """Return the same call with some flags removed, or None when nothing changes.

    Only the flags named in the relaxation ladder may go. The geography, the
    query and the recency stay: dropping those would answer a different
    question.
    """
    flags = {key: value for key, value in (call.get("flags") or {}).items() if key not in drop}
    if flags == call.get("flags"):
        return None

    argv = ["search"]
    argv += flags_to_argv(PORTALS, call["portal"], flags)
    argv += flags_to_argv(PORTALS, call["portal"], {"query": call["query"]})
    argv += ["--format", "json"]

    relaxed = dict(call)
    relaxed["flags"] = flags
    relaxed["argv"] = argv
    relaxed["dropped"] = list(drop)
    return relaxed


def normalise(item: dict, portal: str) -> dict | None:
    """Map one portal result onto the shared posting contract.

    Returns None when the hit lacks the fields every posting needs.
    """
    if not isinstance(item, dict):
        return None
    title = str(item.get("title") or "").strip()
    company = str(item.get("company") or "").strip()
    url = str(item.get("url") or "").strip()
    if not title or not company or not url:
        return None

    description = item.get("description")
    if not isinstance(description, str):
        description = ""

    return {
        "title": title,
        "company": company,
        "url": url,
        "location": str(item.get("location") or "").strip(),
        "posted_date": item.get("date") or item.get("posted_date") or None,
        "deadline": item.get("deadline") or None,
        "description": description,
        "work_mode": item.get("work_mode") or None,
        "skills": item.get("skills") or [],
        "portal": portal,
        "source": "cli",
        "portal_id": item.get("id"),
    }


def in_market(hit: dict, call: dict) -> bool:
    """Whether a posting's own location agrees with the place that was searched.

    Portals answer a country filter with postings from other countries. A
    posting from the wrong market is worse than no posting, because it looks
    like a hit - so it is dropped here, where it costs nothing, rather than
    in the scoring step, where it costs a fetch and a model's attention.

    Only an exact country target is checked, and only a posting that names a
    country is judged. A posting that says "Cairo" and no country is kept.
    """
    if str(call.get("scope") or "") != "exact":
        return True
    place_key = str(call.get("place") or "")
    place = CATALOGUE.get(place_key)
    if place is None or place.kind != "country":
        return True
    return matches_country(str(hit.get("location") or ""), place_key, CATALOGUE)


def run_call(call: dict) -> tuple[dict, list[dict]]:
    """Run one portal CLI call and return its log line and its hits."""
    cmd = ["bun", "run", str(cli_path(call["portal"]))] + call["argv"]
    try:
        proc = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, timeout=CALL_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return {"portal": call["portal"], "query": call["query"], "error": "timeout"}, []
    except OSError as exc:
        return {"portal": call["portal"], "query": call["query"], "error": str(exc)}, []

    # A portal can succeed and still have something to say. freehire answers an
    # unknown region with a warning on stderr and exit 0, so a check on the
    # exit code alone throws that away.
    warnings = _warnings_from(proc.stderr)

    if proc.returncode != 0:
        message = (proc.stderr or "").strip().splitlines()
        detail = message[-1][:300] if message else f"exit {proc.returncode}"
        return (
            {"portal": call["portal"], "query": call["query"], "error": detail, "warnings": warnings},
            [],
        )

    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return (
            {
                "portal": call["portal"],
                "query": call["query"],
                "error": f"bad json: {exc}",
                "warnings": warnings,
            },
            [],
        )

    results = doc.get("results") if isinstance(doc, dict) else doc
    if not isinstance(results, list):
        return (
            {
                "portal": call["portal"],
                "query": call["query"],
                "error": "no results array",
                "warnings": warnings,
            },
            [],
        )

    hits = []
    out_of_market = 0
    for item in results:
        hit = normalise(item, call["portal"])
        if not hit:
            continue
        hit["target_place"] = call.get("place", "")
        hit["target_place_name"] = call.get("place_name", "")
        hit["target_scope"] = call.get("scope", "")
        hit["target_rung"] = call.get("rung", "")
        if not in_market(hit, call):
            out_of_market += 1
            continue
        hits.append(hit)
    log = {"portal": call["portal"], "query": call["query"], "hits": len(hits)}
    if out_of_market:
        log["out_of_market"] = out_of_market
    if warnings:
        log["warnings"] = warnings
    if call.get("scope") and call["scope"] != "exact":
        log["scope"] = call["scope"]
    if call.get("dropped"):
        log["dropped"] = list(call["dropped"])
    return log, hits


def _warnings_from(stderr: str) -> list[str]:
    """Pull the warning lines out of a portal's stderr.

    A portal that exits 0 but wrote to stderr has told us something the exit
    code hides.
    """
    if not stderr:
        return []
    warnings: list[str] = []
    for line in stderr.strip().splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            warnings.append(text[:300])
            continue
        if isinstance(payload, dict):
            message = payload.get("warning") or payload.get("error") or payload.get("message")
            if message:
                warnings.append(str(message)[:300])
    return warnings


def fetch_detail(job: dict) -> tuple[str, dict]:
    """Fetch a posting's full text. Returns the text and any extra fields.

    The portal's own ``detail`` command is preferred. When it is not
    available or fails, the posting's URL is fetched with the page reader,
    which respects robots.txt.
    """
    portal = job.get("portal", "")
    portal_id = job.get("portal_id")
    extra: dict = {}

    if portal in NEEDS_DETAIL_PORTS and portal_id:
        cmd = [
            "bun",
            "run",
            str(cli_path(portal)),
            "detail",
            str(portal_id),
            "--format",
            "json",
        ]
        try:
            proc = subprocess.run(
                cmd, cwd=ROOT, capture_output=True, text=True, timeout=CALL_TIMEOUT
            )
            if proc.returncode == 0:
                doc = json.loads(proc.stdout)
                payload = doc.get("job") if isinstance(doc, dict) and "job" in doc else doc
                if isinstance(payload, dict):
                    body = payload.get("description")
                    if isinstance(body, str):
                        extra["description"] = body
                    for field in ("deadline", "location", "posted_date", "work_mode"):
                        if payload.get(field):
                            extra[field] = payload[field]
                    if payload.get("isActive") is False:
                        extra["is_active"] = False
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
            pass

    description = extra.get("description") or job.get("description") or ""
    if len(description) >= NEEDS_DETAIL:
        return description, extra

    # Fall back to reading the posting's own page.
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "web" / "fetch_page.py"),
                job["url"],
                "--text",
                "--max-chars",
                "12000",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=CALL_TIMEOUT,
        )
        if proc.returncode == 0:
            text = proc.stdout.strip()
            # fetch_page prints a header before the text.
            if "---" in text:
                text = text.split("---", 1)[1].strip()
            if len(text) > len(description):
                extra["description"] = text
    except (subprocess.TimeoutExpired, OSError):
        pass

    return extra.get("description") or description, extra


def guard_body(body: str) -> tuple[str, str]:
    """Run a posting body through the guard. Returns the cleaned text and verdict."""
    if not body:
        return "", "empty"
    cleaned, findings = guard(body, "text")
    return cleaned, str(findings.get("verdict", "unknown"))


def fit_of(job: dict, terms: dict) -> str:
    """A quick fit label from the relevance score.

    This is the cheap label stored with the posting. The model's own verdict
    is the one that ends up in the report.
    """
    value, _ = relevance.score(job, terms)
    if value >= 18:
        return "high"
    if value >= 6:
        return "medium"
    return "low"


def run_batch(calls: list[dict]) -> tuple[list[dict], list[list[dict]]]:
    """Run a set of portal calls at once.

    Returns the logs and the hits **per call**, so that a caller can match a
    call to its own hits.
    """
    logs: list[dict] = []
    hits: list[list[dict]] = []
    if not calls:
        return logs, hits
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for log, found in pool.map(run_call, calls):
            logs.append(log)
            hits.append(found)
    return logs, hits


def run_with_relaxation(calls: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Run the calls, and retry the empty ones with fewer facets.

    A portal's facets are ANDed, and in a small market the stack can be
    empty: freehire with ``--category ml_ai --seniority junior`` returns
    nothing at all for Egypt, Germany, the UAE and Saudi Arabia, and plenty
    for the United States. A search that finds nothing is not the same as a
    market that has nothing, so the facets are dropped one at a time until
    something comes back.

    Every relaxation is recorded. A widened search is never a silent one.
    """
    logs, hit_lists = run_batch(calls)
    hits: list[dict] = [hit for group in hit_lists for hit in group]
    relaxations: list[dict] = []

    for rung in range(1, 4):
        retries: list[tuple[int, dict, tuple[str, ...]]] = []
        for index, call in enumerate(calls):
            log = logs[index]
            if log.get("error") or log.get("hits"):
                continue
            ladder = RELAXATION_LADDER.get(call["portal"], [])
            if rung > len(ladder):
                continue
            drop = ladder[rung - 1]
            relaxed = relaxed_call(call, drop)
            if relaxed is None:
                continue
            retries.append((index, relaxed, drop))

        if not retries:
            break

        retry_logs, retry_hit_lists = run_batch([item[1] for item in retries])
        for (index, relaxed, drop), log, found in zip(retries, retry_logs, retry_hit_lists):
            log["relaxed"] = list(drop)
            logs[index] = log
            relaxations.append(
                {
                    "portal": relaxed["portal"],
                    "query": relaxed["query"],
                    "place": relaxed.get("place", ""),
                    "dropped": list(drop),
                    "hits": len(found),
                }
            )
            hits.extend(found)

    return logs, hits, relaxations


def merge_hits(hits: list[dict]) -> list[dict]:
    """Merge the postings that more than one search found.

    A posting in Egypt comes back from the Egypt search *and* from the MENA
    one, because MENA holds Egypt. The two copies carry different places, and
    the tightest one is the honest one: the market check and the ordering
    both want to know where a posting really was found.

    A copy with a longer description wins over one without, so a portal that
    carries the full text is not overwritten by one that does not.
    """
    merged: dict[str, dict] = {}
    order: list[str] = []

    for hit in hits:
        key = make_key(str(hit.get("company") or ""), str(hit.get("title") or ""), str(hit.get("url") or ""))
        current = merged.get(key)
        if current is None:
            merged[key] = dict(hit)
            order.append(key)
            continue

        if _specificity(hit) > _specificity(current):
            # Keep the tighter place, but do not lose the richer description.
            if len(str(current.get("description") or "")) > len(str(hit.get("description") or "")):
                hit = dict(hit, description=current.get("description"))
            merged[key] = hit
        elif len(str(hit.get("description") or "")) > len(str(current.get("description") or "")):
            merged[key] = dict(current, description=hit.get("description"))

    return [merged[key] for key in order]


def _specificity(hit: dict) -> tuple:
    """Rank two copies of the same posting by how tight their place is."""
    scope = str(hit.get("target_scope") or "")
    scope_rank = {"exact": 3, "wider": 2, "floor": 1}.get(scope, 0)
    place = CATALOGUE.get(str(hit.get("target_place") or ""))
    kind_rank = 2 if place is not None and place.kind == "country" else 1 if place is not None else 0
    return (scope_rank, kind_rank)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--persona", help="persona slug (default: the active persona)")
    parser.add_argument("--limit", type=int, default=10, help="postings to prepare for scoring")
    parser.add_argument("--out-dir", type=Path, help="directory for the run files")
    parser.add_argument("--date", help="today's date (YYYY-MM-DD), for first_seen")
    args = parser.parse_args()

    persona_slug = args.persona or active_persona()
    known = list_personas()
    if known and persona_slug not in known:
        print(
            f"search_portals: unknown persona '{persona_slug}'. Known: {', '.join(known)}",
            file=sys.stderr,
        )
        return 1

    persona = load_yaml(persona_yaml(persona_slug))
    if not persona:
        print(
            f"search_portals: no persona file at {persona_yaml(persona_slug)}.",
            file=sys.stderr,
        )
        return 1
    inputs = load_yaml(profile_inputs_path())

    contract = build_contract(persona, inputs)
    contract["search_queries"] = build_queries(persona, inputs)

    calls = build_calls(contract)
    if not calls:
        print(
            json.dumps(
                {
                    "calls": 0,
                    "hits": 0,
                    "selected": 0,
                    "note": (
                        "no portal produced a call - check preferences.locations in "
                        "profiles/inputs.yaml"
                    ),
                    "locations_defaulted": contract.get("locations_defaulted", False),
                    "skipped_targets": contract.get("portal_skipped", []) or [],
                    "unresolved_locations": contract.get("locations_unresolved", []) or [],
                },
                indent=2,
            )
        )
        return 0

    logs, hits, relaxations = run_with_relaxation(calls)
    raw_hits = len(hits)
    hits = merge_hits(hits)

    # Drop what has already been seen.
    state_path = seen_jobs_path(persona_slug)
    if state_path.exists():
        _, seen = load_state(state_path)
    else:
        seen = {}
    selected, counts = scrape_state.select(hits, seen, tracker_pairs(tracker_path(persona_slug)))

    terms = relevance.build_terms(persona, inputs)
    ordered = relevance.order(selected, terms)

    # Only what will actually be scored this run is kept. The rest stay
    # unseen, so a later run picks them up instead of losing them.
    kept = ordered[: args.limit] if args.limit > 0 else ordered
    deferred = len(ordered) - len(kept)

    out_dir = args.out_dir or scratch_dir(persona_slug)
    bodies_dir = out_dir / "bodies"
    bodies_dir.mkdir(parents=True, exist_ok=True)

    today = args.date or ""
    if not today:
        from datetime import date

        today = date.today().isoformat()

    store_entries = []
    prepared = []
    for job in kept:
        body, extra = fetch_detail(job)
        body, verdict = guard_body(body)
        merged = dict(job)
        merged.update({key: value for key, value in extra.items() if value is not None})
        merged["description"] = body
        merged["guard"] = verdict

        key = make_key(merged["company"], merged["title"], merged["url"])
        body_path = bodies_dir / f"{key}.txt"
        body_path.write_text(body, encoding="utf-8")

        entry = {
            "title": merged["title"],
            "company": merged["company"],
            "url": merged["url"],
            "location": merged.get("location") or "",
            "first_seen": today,
            "posted_date": merged.get("posted_date") or None,
            "deadline": merged.get("deadline") or None,
            "fit": fit_of(merged, terms),
            "status": "new",
            "portal": merged.get("portal") or "",
            "source": merged.get("source") or "cli",
        }
        store_entries.append(entry)
        prepared.append(
            {
                "key": key,
                "title": merged["title"],
                "company": merged["company"],
                "url": merged["url"],
                "location": merged.get("location") or "",
                "portal": merged.get("portal") or "",
                "target_place": merged.get("target_place") or "",
                "target_place_name": merged.get("target_place_name") or "",
                "posted_date": merged.get("posted_date") or None,
                "deadline": merged.get("deadline") or None,
                "work_mode": merged.get("work_mode"),
                "relevance": merged.get("relevance"),
                "relevance_reasons": merged.get("relevance_reasons", []),
                "guard": verdict,
                "body_file": str(body_path.relative_to(ROOT)),
                "body_chars": len(body),
            }
        )

    (out_dir / "raw.json").write_text(
        json.dumps(hits, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "store.json").write_text(
        json.dumps(store_entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "prepared.json").write_text(
        json.dumps(prepared, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    errors = [log for log in logs if log.get("error")]
    warnings = [
        {"portal": log.get("portal", ""), "query": log.get("query", ""), "messages": log["warnings"]}
        for log in logs
        if log.get("warnings")
    ]
    widened = [
        {
            "portal": log.get("portal", ""),
            "query": log.get("query", ""),
            "scope": log.get("scope", ""),
        }
        for log in logs
        if log.get("scope") and log.get("scope") != "exact"
    ]
    out_of_market = sum(int(log.get("out_of_market", 0) or 0) for log in logs)
    summary = {
        "calls": len(calls),
        "hits": len(hits),
        "hits_raw": raw_hits,
        "already_seen": counts.get("already_seen", 0),
        "already_applied": counts.get("already_applied", 0),
        "repeated_in_batch": counts.get("repeated_in_batch", 0),
        "invalid": len(counts.get("invalid", []) or []),
        "out_of_market": out_of_market,
        "new": len(ordered),
        "prepared": len(prepared),
        "deferred": deferred,
        "store_file": str((out_dir / "store.json").relative_to(ROOT)),
        "prepared_file": str((out_dir / "prepared.json").relative_to(ROOT)),
        "errors": errors,
        "warnings": warnings,
        "widened_searches": widened,
        "relaxed_searches": relaxations,
        "locations_defaulted": contract.get("locations_defaulted", False),
        "home_place": (contract.get("filters", {}) or {}).get("home_place"),
        "skipped_targets": contract.get("portal_skipped", []) or [],
        "unresolved_locations": contract.get("locations_unresolved", []) or [],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
