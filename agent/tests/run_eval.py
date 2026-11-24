"""Run the 12 evaluation questions against the live agent and record the answers.

    docker compose run --rm agent python -m tests.run_eval
    docker compose run --rm agent python -m tests.run_eval --only T09,T11   # re-run some, keep the rest
    docker compose run --rm agent python -m tests.run_eval --failed          # re-run only failures/errors

Writes eval_results/results.md + results.json and, if README_PATH exists, replaces the block
between <!-- EVAL_RESULTS:START --> and <!-- EVAL_RESULTS:END --> with the fresh results.
Each question runs in its own session so earlier questions cannot influence later ones.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import os
import re
from pathlib import Path

from app.config import get_settings
from app.graph import HelpdeskAgent
from tests.eval_cases import CASES, Case
import unicodedata

OUT_DIR = Path(os.getenv("EVAL_OUT_DIR", "/workspace/eval_results"))
README = Path(os.getenv("README_PATH", "/workspace/README.md"))
START, END = "<!-- EVAL_RESULTS:START -->", "<!-- EVAL_RESULTS:END -->"

def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)              
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)       
    return re.sub(r"\s+", " ", text).lower()
def check(case: Case, r: dict) -> list[str]:
    problems = []
    answer = r["answer"].lower()
    answer = _norm(r["answer"])
    if r["status"] not in case.expect_status:
        problems.append(f"status={r['status']} (expected {'/'.join(sorted(case.expect_status))})")
    problems += [f"missing '{s}'" for s in case.must_contain if _norm(s) not in answer]
    problems += [f"leaked '{s}'" for s in case.must_not_contain if _norm(s) in answer]
    problems += [f"tool {t} not called" for t in case.expect_tools if t not in r["tools_used"]]
    files = {s["doc_file"] for s in r["sources"]}
    problems += [f"no citation of {f}" for f in case.expect_source_files if f not in files]
    return problems


def to_markdown(rows: list[dict], model: str) -> str:
    passed = sum(1 for row in rows if not row["problems"])
    out = [f"_Run {dt.datetime.now():%Y-%m-%d %H:%M} · model `{model}` · **{passed}/{len(rows)} checks passed**_\n",
           "| # | Type | Status | Tools called | Check |", "|---|---|---|---|---|"]
    for row in rows:
        r = row["result"]
        out.append(f"| {row['id']} | {row['kind']} | `{r['status']}` | {', '.join(r['tools_used']) or '—'} | "
                   f"{'✅' if not row['problems'] else '❌ ' + '; '.join(row['problems'])} |")
    out.append("")
    for row in rows:
        r = row["result"]
        guard = r["guard"]
        guard_note = guard.get("rules") or guard.get("reason") or ""
        out.append(f"#### {row['id']} — {row['kind']}\n")
        out.append(f"**Q:** {row['question']}\n")
        out.append("**A:**\n")
        out.append("> " + r["answer"].replace("\n", "\n> ") + "\n")
        meta = [f"status `{r['status']}`", f"guard layer `{guard.get('layer', '-')}`"]
        if guard_note:
            meta.append(f"guard note: {guard_note}")
        if r["redactions"]:
            meta.append(f"redactions {r['redactions']}")
        if r["tickets"]:
            meta.append(f"ticket {r['tickets'][0]['ticket_id']} ({r['tickets'][0]['backend']})")
        meta.append(f"{r['latency_ms']} ms")
        out.append("<sub>" + " · ".join(meta) + "</sub>\n")
    return "\n".join(out)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="comma-separated case IDs to run, e.g. T09,T11")
    parser.add_argument("--failed", action="store_true", help="re-run cases that failed or errored last time")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    settings = get_settings()
    previous: dict[str, dict] = {}
    prev_file = OUT_DIR / "results.json"
    if prev_file.exists() and (args.only or args.failed):
        previous = {row["id"]: row for row in json.loads(prev_file.read_text(encoding="utf-8"))}

    selected = {c.id for c in CASES}
    if args.only:
        selected = {x.strip().upper() for x in args.only.split(",")}
    elif args.failed:
        selected = {cid for cid, row in previous.items() if row["problems"]} | {c.id for c in CASES if c.id not in previous}

    agent = await HelpdeskAgent.create(settings)
    rows = []
    for case in CASES:
        if case.id not in selected and case.id in previous:
            rows.append(previous[case.id])
            continue
        try:
            r = await agent.ask(case.question, session_id=f"eval-{case.id}")
        except Exception as exc:  # keep going; record the failure
            r = {"answer": f"ERROR: {type(exc).__name__}: {exc}", "status": "error", "guard": {}, "sources": [],
                 "tickets": [], "tools_used": [], "redactions": {}, "latency_ms": 0}
        problems = check(case, r)
        rows.append({"id": case.id, "kind": case.kind, "question": case.question, "result": r, "problems": problems})
        print(f"{case.id} {'PASS' if not problems else 'FAIL'} [{r['status']}] {case.question[:60]}")
        for p in problems:
            print("     -", p)

    md = to_markdown(rows, settings.llm_model)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "results.md").write_text(md, encoding="utf-8")
    (OUT_DIR / "results.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    if README.exists():
        text = README.read_text(encoding="utf-8")
        if START in text and END in text:
            new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: f"{START}\n{md}\n{END}", text, flags=re.S)
            README.write_text(new, encoding="utf-8")
            print(f"README updated: {README}")
    print(f"Results written to {OUT_DIR}/results.md")

if __name__ == "__main__":
    asyncio.run(main())
