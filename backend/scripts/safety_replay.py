"""Replay a set of messages through the safety classifier and record verdicts.

Used to validate a safety host (SAL Ollama during development, Konstanz vLLM
before fielding) against the same prompt rendering the platform uses, and to
compare two hosts on identical input.

Input: a JSON file containing either a list of strings, or a list of objects
with at least ``content`` (optionally ``user_turn`` for the participant
message it replied to, and ``id``). Output: JSONL, one verdict per input, in
order. Resumable: existing output lines are skipped.

Environment: SAFETY_BASE_URL, SAFETY_MODEL, SAFETY_TRANSPORT
(``ollama_raw`` | ``openai_completions``), SAFETY_API_KEY.

    SAFETY_TRANSPORT=ollama_raw SAFETY_BASE_URL=http://localhost:11434 \\
    SAFETY_MODEL=llama-guard3:8b SAFETY_API_KEY=... \\
    uv run python scripts/safety_replay.py messages.json verdicts.jsonl --mode agent

``--mode agent`` (default) classifies each message as an Agent turn replying
to ``user_turn`` (or a placeholder when absent); ``--mode user`` classifies
each message as a lone User turn.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.safety import NEUTRAL_USER_TURN, SafetyClient, render_prompt  # noqa: E402
from utils.safety.prompt import categories_from_config  # noqa: E402

PLACEHOLDER_USER_TURN = "(no participant message yet)"


def _load(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for i, entry in enumerate(data):
        if isinstance(entry, str):
            items.append({"id": i, "content": entry, "user_turn": None})
        else:
            items.append({
                "id": entry.get("id", i),
                "content": entry["content"],
                "user_turn": entry.get("user_turn"),
            })
    return items


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--mode", choices=("agent", "user"), default="agent")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--categories", type=Path, help="JSON list of {code,title,definition?,enabled?}")
    ap.add_argument("--policy", type=Path,
                    help="a saved experimental.safety block (as returned by GET /admin/safety/policy); "
                         "sets categories and context_mode, overriding --categories/--mode")
    args = ap.parse_args()

    cfg = {
        "transport": os.getenv("SAFETY_TRANSPORT"),
        "base_url": os.getenv("SAFETY_BASE_URL"),
        "model": os.getenv("SAFETY_MODEL"),
        "timeout_s": float(os.getenv("SAFETY_TIMEOUT_S", "30")),
    }
    client = SafetyClient.from_config(cfg)
    context_mode = None
    if args.policy:
        policy = json.loads(args.policy.read_text())
        categories = categories_from_config(policy.get("categories"))
        context_mode = policy.get("context_mode", "conditional")
    else:
        categories = categories_from_config(
            json.loads(args.categories.read_text()) if args.categories else None
        )

    items = _load(args.input)
    done = set()
    if args.output.exists():
        for line in args.output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["id"])
    todo = [it for it in items if it["id"] not in done]
    print(f"{len(items)} messages, {len(done)} already done, {len(todo)} to classify "
          f"via {client.transport} {client.model} at {client.base_url}", file=sys.stderr)

    sem = asyncio.Semaphore(max(1, args.concurrency))
    lock = asyncio.Lock()
    counts = Counter()

    async def one(item):
        user_turn = item["user_turn"] or PLACEHOLDER_USER_TURN
        async with sem:
            if context_mode == "none":
                conv = [("user", NEUTRAL_USER_TURN), ("assistant", item["content"])]
            elif context_mode == "conditional":
                # Mirror the live screen: include the participant turn only
                # when that turn is itself unsafe under the same policy.
                uv = await client.classify(render_prompt([("user", user_turn)], categories))
                ctx = user_turn if uv.status == "unsafe" else NEUTRAL_USER_TURN
                conv = [("user", ctx), ("assistant", item["content"])]
            elif context_mode == "always" or args.mode == "agent":
                conv = [("user", user_turn), ("assistant", item["content"])]
            else:
                conv = [("user", item["content"])]
            prompt = render_prompt(conv, categories)
            v = await client.classify(prompt)
        row = {
            "id": item["id"],
            "content": item["content"],
            "status": v.status,
            "categories": v.categories,
            "raw": v.raw,
            "unsafe_prob": v.unsafe_prob,
            "latency_ms": v.latency_ms,
            "error": v.error,
            "model": v.model,
            "prompt_hash": v.prompt_hash,
        }
        async with lock:
            with args.output.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            counts[v.status] += 1
            n = sum(counts.values())
            if n % 25 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}  {dict(counts)}", file=sys.stderr)

    await asyncio.gather(*(one(it) for it in todo))

    all_rows = [json.loads(l) for l in args.output.read_text(encoding="utf-8").splitlines() if l.strip()]
    status = Counter(r["status"] for r in all_rows)
    cats = Counter(c for r in all_rows for c in r["categories"])
    print(f"\n{len(all_rows)} verdicts: {dict(status)}", file=sys.stderr)
    print(f"categories: {dict(cats.most_common())}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
