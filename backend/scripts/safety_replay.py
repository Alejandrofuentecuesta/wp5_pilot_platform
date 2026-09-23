"""Replay recorded chat sessions through the safety classifier.

Every message of every session is judged exactly as the live screen judges
it: the same policy, the same conversation excerpt (built from the messages
before it), the same client. Used to validate a classifier host and a policy
on real transcripts before they go live.

Input: a JSON list of sessions, each
``{"session_id": ..., "user_name": ..., "messages": [{"message_id", "sender",
"content", "reply_to"}, ...]}`` with messages in chat order. Output: JSONL,
one verdict per message. Resumable: messages already in the output are
skipped.

Environment: SAFETY_TRANSPORT (default ``openai_chat``), SAFETY_BASE_URL,
SAFETY_MODEL, SAFETY_API_KEY. For Ollama on the same host:

    SAFETY_BASE_URL=http://localhost:11434 SAFETY_MODEL=gpt-oss-safeguard:20b \\
    uv run python scripts/safety_replay.py sessions.json verdicts.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.safety import SafetyClient, load_policy, render_excerpt  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--agents-only", action="store_true", help="skip participant messages")
    args = ap.parse_args()

    sessions = json.loads(args.input.read_text(encoding="utf-8"))
    done = set()
    if args.output.exists():
        for line in args.output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["message_id"])

    client = SafetyClient.from_config({})
    policy = load_policy()
    print(f"{client.transport} {client.base_url} {client.model} policy={policy.version}", file=sys.stderr)

    counts: Counter = Counter()
    with args.output.open("a", encoding="utf-8") as out:
        for session in sessions:
            user_name = session["user_name"]
            history = []
            for raw in session["messages"]:
                message = SimpleNamespace(
                    message_id=str(raw["message_id"]),
                    sender=raw["sender"],
                    content=raw.get("content") or "",
                    reply_to=str(raw["reply_to"]) if raw.get("reply_to") else None,
                )
                role = "participant" if message.sender == user_name else "agent"
                skip = message.message_id in done or (args.agents_only and role == "participant")
                if not skip and message.content.strip():
                    excerpt = render_excerpt(message, history, user_name)
                    verdict = await client.classify(policy.text, excerpt)
                    counts[verdict.status] += 1
                    out.write(json.dumps({
                        "session_id": session["session_id"],
                        "message_id": message.message_id,
                        "role": role,
                        "sender": message.sender,
                        "content": message.content,
                        "excerpt": excerpt,
                        "status": verdict.status,
                        "categories": verdict.categories,
                        "rationale": verdict.rationale,
                        "reasoning": verdict.reasoning,
                        "raw": verdict.raw,
                        "latency_ms": verdict.latency_ms,
                        "error": verdict.error,
                        "model": verdict.model,
                        "policy_version": policy.version,
                    }, ensure_ascii=False) + "\n")
                    out.flush()
                    print(f"{sum(counts.values())} {dict(counts)}", file=sys.stderr, end="\r")
                history.append(message)
    print(f"\ndone: {dict(counts)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
