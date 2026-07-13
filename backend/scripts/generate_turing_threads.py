#!/usr/bin/env python3
"""Regenerate Turing-test synthetic threads with the current STAGE pipeline.

This runner scrapes the existing static Turing page JSON files, generates one
new 16-message synthetic thread per old item, then writes the matching 8-message
prefix files. It is intended to be run from the backend Docker image so it uses
the same LLM dependencies and environment variables as the platform.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.STAGE.classifier import DEFAULT_CLASSIFIER_PROMPT_TEMPLATE
from agents.STAGE.orchestrator import Orchestrator, TurnResult
from models import Agent, Message, SessionState
from utils.llm.provider.llm_bsc import BSCClient
from utils.llm.llm_manager import LLMManager


BASE_URL = "https://alexcasadevall.github.io/proves-posts-turing-test/Turing%20Final"
THREADS: tuple[tuple[str, range], ...] = (
    ("clim", range(1, 9)),
    ("imm", range(1, 14)),
)
TARGET_LEN = 16
PREFIX_LEN = 8

REAL_LENGTH_JITTER = (0.82, 1.18)
LONG_MESSAGE_WORD_CAP = 220
SIGLA_WORDS = {
    "AEMET", "BOE", "CEOE", "CIS", "CO2", "DANA", "EEUU", "EPA", "ERC",
    "ETA", "INE", "IPCC", "IRPF", "IVA", "ONG", "ONU", "OTAN", "PACMA",
    "PNV", "PP", "PSOE", "RENFE", "TVE", "UE", "UCI", "VOX",
}
ELLIPSIS_RE = re.compile(r"(?:\.{3,}|…+)")
ABBREV_REPLACEMENTS = (
    (re.compile(r"\bxq\b", re.I), "porque"),
    (re.compile(r"\bpq\b", re.I), "porque"),
    (re.compile(r"\btb\b", re.I), "también"),
    (re.compile(r"\bq\b", re.I), "que"),
    (re.compile(r"\bx\b", re.I), "por"),
)
POLITICAL_CLICHE_REPLACEMENTS = (
    (re.compile(r"\bAgenda(?:\s+2030)?\b", re.I), ("esa agenda", "las políticas de siempre", "Bruselas")),
    (re.compile(r"\bMoncloa\b", re.I), ("el Gobierno", "el ministerio", "los de arriba")),
    (re.compile(r"\bbuenismo\b", re.I), ("postureo", "buenas palabras", "ingenuidad")),
    (re.compile(r"\bbuenistas\b", re.I), ("los de siempre", "los ingenuos", "los que van de buenos")),
    (re.compile(r"\bprogres\s+de\s+sal[oó]n\b", re.I), ("los que dan lecciones", "los de las frases hechas", "los de superioridad moral")),
)
STOCK_FORMULA_RE = re.compile(
    r"\b(menuda\s+sarta|vaya\s+pel[ií]cula|vaya\s+nivel|qu[eé]\s+nivel|"
    r"vaya\s+drama|buenismo\s+mata|"
    r"hay\s+que\s+leer\s+un\s+poco|no\s+tienes\s+ni\s+idea|hablas\s+sin\s+saber|"
    r"te\s+falta\s+contexto|cogido\s+con\s+pinzas|argumento\s+flojo|barra\s+de\s+bar|"
    r"tertulia\s+de\s+sobremesa|te\s+compras\s+cualquier\s+titular|"
    r"te\s+tragas\s+cualquier\s+titular|repites\s+lo\s+primero\s+que\s+lees|"
    r"lectura\s+fin[ií]sima|qu[eé]\s+pereza\s+de\s+argumento|"
    r"menuda\s+pedaz[ao]\s+de|no\s+ten(?:eis|[eé]is|emos|en)\s+ni\s+idea|"
    r"\w+\s+de\s+manual|chiringuito\s+clim[aá]tico|control\s+absoluto|"
    r"venir\s+de\s+ecologista|"
    r"vendido\s+la\s+moto|cerebro\s+de\s+\w+|agenda(?:\s+2030)?|"
    r"manual\s+de\s+ecologista|progres\s+de\s+sal[oó]n|"
    r"ecologista(?:s)?\s+de\s+sal[oó]n|Moncloa|Brussels|Bruselas|"
    r"controlarnos)\b",
    re.I,
)
ODD_CAPS_RE = re.compile(r"\b(?:DE|QUE|CON|POR|PARA|LOS|LAS|UNA|UNO|UN|EL|LA|ES|SON|DEL|AL)\b")


class FinalQualityError(RuntimeError):
    """Raised when a generated thread fails corpus-level quality checks."""
OPENING_REWRITES = (
    (re.compile(r"^Vaya[, ]+", re.I), ("A ver, ", "Bueno, ", "", "Eso de ")),
    (re.compile(r"^Menuda\s+", re.I), ("Eso es ", "Otra ", "", "Buen ")),
    (re.compile(r"^Menudo\s+", re.I), ("Eso es ", "Otro ", "", "Buen ")),
    (re.compile(r"^Qu[eé]\s+nivel[,. ]*", re.I), ("", "Bueno, ", "A ver, ")),
    (re.compile(r"^Joder[, ]*", re.I), ("", "A ver, ", "Bueno, ")),
    (re.compile(r"^Vale[, ]+", re.I), ("Bueno, ", "A ver, ", "")),
    (re.compile(r"^Es increíble que\s+", re.I), ("No me creo que ", "Lo fuerte es que ", "Al final ")),
    (re.compile(r"^Es que\s+", re.I), ("", "Pero ", "A ver, ")),
)
THEATRICAL_REWRITES = (
    (re.compile(r"\bmenuda\s+sarta\s+de\s+estupideces\b", re.I), ("eso no hay por dónde cogerlo", "estás mezclando cosas", "eso no se sostiene")),
    (re.compile(r"\bqu[eé]\s+sarta\s+de\s+(?:mentiras|estupideces|tonter[ií]as)\b", re.I), ("eso no cuela", "estás mezclando cosas", "eso no se sostiene")),
    (re.compile(r"\bsarta\s+de\s+(?:mentiras|estupideces|tonter[ií]as)\b", re.I), ("mezcla de cosas", "argumento flojo", "película propia")),
    (re.compile(r"\bvaya\s+pel[ií]cula\b", re.I), ("eso no cuela", "te has montado una historia", "ese argumento flojea")),
    (re.compile(r"\bqu[eé]\s+nivel\b", re.I), ("hay que leer un poco", "argumento flojo", "no cuela")),
    (re.compile(r"\bbuenismo\s+mata\b", re.I), ("las buenas palabras no arreglan nada", "eso tiene consecuencias", "la ingenuidad sale cara")),
    (re.compile(r"\bvaya\s+paso\s+por\s+el\s+foro\b", re.I), ("qué gestión más pobre", "control bastante flojo", "gestión de saldo")),
    (re.compile(r"\bvaya\s+pasote\b", re.I), ("qué gestión más pobre", "control bastante flojo", "gestión de saldo")),
    (re.compile(r"\bblasfemia\b", re.I), ("disparate", "salida de tono", "ocurrencia")),
    (re.compile(r"\bputa\s+mierda\b", re.I), ("basura", "chapuza", "desastre")),
    (re.compile(r"\bde\s+cuñao\b", re.I), ("sin mucho análisis", "bastante flojo", "de tertulia mala")),
    (re.compile(r"\bbuenas\s+palabras\s+nos\s+va[n]?\s+a\s+acabar\s+matando\b", re.I), ("tantas buenas palabras salen caras", "las buenas palabras no arreglan nada", "tanta frase bonita sale cara")),
    (re.compile(r"\bbuen\s+an[aá]lisis\s+de\s+barra\s+de\s+bar\b", re.I), ("razonamiento cogido con pinzas", "argumento bastante pobre", "lectura muy de tertulia")),
    (re.compile(r"\bque\s+no\s+hay\s+ni\s+idea\b", re.I), ("no tienes ni idea", "hay poca idea detrás", "vas bastante perdido")),
    (re.compile(r"\bno\s+tienes\s+ni\s+idea\b", re.I), ("vas bastante perdido", "hablas sin saber", "estás mezclando cosas", "te falta contexto")),
    (re.compile(r"\bmenudo\s+an[aá]lisis(?:\s+de\s+barra\s+de\s+bar)?\b", re.I), ("ese razonamiento hace aguas", "lectura finísima, sí", "eso está cogido con pinzas", "vaya lectura")),
    (re.compile(r"\bbarra\s+de\s+bar\b", re.I), ("tertulia de sobremesa", "comentario de cuñado", "análisis de servilleta", "frase hecha")),
    (re.compile(r"\bargumento\s+flojo\b", re.I), ("eso está cogido con pinzas", "ese argumento hace aguas", "argumento bastante pobre", "eso no se sostiene")),
    (re.compile(r"\bte\s+compras\s+cualquier\s+titular\b", re.I), ("te tragas cualquier titular", "repites lo primero que lees", "vas con el titular en la boca", "te crees cualquier titular")),
    (re.compile(r"\bqu[eé]\s+pereza\s+de\s+(?:argumento|comentario)\b", re.I), ("otra vez con lo mismo", "cansa bastante leer eso", "ese argumento ya viene gastado")),
    (re.compile(r"\bsangre\s+espa[nñ]ola\b", re.I), ("gente de aquí", "vecinos de Madrid", "gente del barrio")),
    (re.compile(r"\bm[aá]s\s+huevos\s+que\s+todo\s+el\s+Gobierno\s+junto\b", re.I), ("más calle que todo el Gobierno junto", "más hartazgo que medio Gobierno", "más ganas de protestar que los de arriba")),
)
OPTIONAL_DIVERSITY_REWRITES = (
    (re.compile(r"\bcuento\b", re.I), ("relato", "historia", "milonga", "excusa", "rollo"), 0.62),
    (re.compile(r"\bcuentos\b", re.I), ("historias", "milongas", "excusas", "rollos"), 0.62),
)
VISIBLE_INCIVILITY_RE = re.compile(
    r"\b(joder|mierda|gilipoll|imb[eé]cil|idiota|tonter[ií]a|cuñao|cuñado|"
    r"cansinos|rid[ií]culo|verg[uü]enza|disparate|burrada|chorrada|farsa|"
    r"vendehumos|payasada|panda|listillo|ignorante|racista|facha|progre|"
    r"buenista|negacionista|menudo nivel|qué nivel|no tienes ni idea|no cuela|"
    r"hay que leer|argumento flojo|te compras cualquier|barra de bar)\b",
    re.I,
)
INCIVILITY_PREFIXES = (
    "Eso no cuela. ",
    "Hay que leer un poco. ",
    "Eso está cogido con pinzas. ",
    "Repites lo primero que lees. ",
    "Eso es muy de tertulia. ",
)
INCIVILITY_SUFFIXES = (
    ", y no cuela",
    ", hay que leer un poco",
    ", cogido con pinzas",
    ", repites lo primero que lees",
    ", muy de tertulia",
)
COMPACT_DIRECTOR_ACTION_TEMPLATE = """
You are the Director of a Spanish chatroom simulation. Select exactly one next action.

Rules:
- Use only performer labels shown in AGENT_PROFILES.
- Output only valid JSON. No markdown.
- Keep mix_mix balanced: about half civil/uncivil and half like-minded/not-like-minded.
- Do not choose the human participant as next_performer.
- Avoid same-cell attacks. If targeting another agent, pick an opposing alignment cell.
- Prefer natural conversation: some plain messages, some replies to older messages, occasional @mentions/likes.
- Let arguments develop between the same people sometimes; occasional double turns and sustained dyads are realistic.
- For reply/like, target_message_id must be an id present in CHAT_LOG.
- For @mention, target_user must be a visible label.
- In performer_instruction.directive, describe the conversational move, not exact wording. Do not ask for stock phrases.
- Vary openings. Do not repeatedly push performers toward "No...", "Pero...", "Claro...", "Ay...", "Vaya...", "Menuda...", "Menudo...", or "Joder...".
- Avoid these exact formulas in directives: "hay que leer un poco", "no tienes ni idea", "no teneis ni idea", "hablas sin saber", "te falta contexto", "cogido con pinzas", "argumento flojo", "barra de bar", "tertulia de sobremesa", "te compras cualquier titular", "te tragas cualquier titular", "repites lo primero que lees", "lectura finisima", "que pereza de argumento", "menuda sarta", "menuda pedaza", "vaya pelicula", "vaya nivel", "que nivel", "vaya drama", "buenismo mata", "de manual", "chiringuito climatico", "control absoluto", "ecologista de salon", "agenda 2030", "Moncloa", "Brussels", "Bruselas".
{PARTICIPANT_NAME_NOTE}

{#SYSTEM}
Context: Spanish online discussion about a news article.
{CHATROOM_CONTEXT}
{/SYSTEM}

{#USER}
AGENT_PROFILES:
{AGENT_PROFILES}

Participation: {PARTICIPATION_SUMMARY}
Actions: {ACTION_SUMMARY}
Target constraints:
{TARGET_CONSTRAINTS_BY_SPEAKER}

CHAT_LOG:
{CHAT_LOG}

Return this JSON shape:
{
  "next_performer": "exact visible performer label",
  "action_type": "message | reply | @mention | like",
  "target_user": "visible label or null",
  "target_message_id": "message id or null",
  "performer_instruction": {
    "objective": "one short sentence",
    "motivation": "one short sentence",
    "directive": "one short sentence; specify civil or visibly uncivil plus a natural conversational move, without exact catchphrases"
  },
  "priority": "low | medium | high",
  "performer_rationale": "short",
  "action_rationale": "short"
}
{/USER}
"""
COMPACT_DIRECTOR_EVALUATE_TEMPLATE = """
You evaluate whether the simulated chat is staying on treatment.
Output only valid JSON. No markdown.

{#SYSTEM}
Targets: mix_mix means INCIVILITY_TARGET = 50 and LIKEMINDED_TARGET = 50.
Use this compact context: {CHATROOM_CONTEXT}
{/SYSTEM}

{#USER}
Previous internal: {PREVIOUS_INTERNAL_VALIDITY_EVALUATION}
Previous ecological: {PREVIOUS_ECOLOGICAL_VALIDITY_EVALUATION}
Actions: {ACTION_SUMMARY}
Participation: {PARTICIPATION_SUMMARY}
Recent chat:
{RECENT_CHAT_LOG}

Return:
{
  "internal_validity_evaluation": "short balance assessment and what to correct next",
  "ecological_validity_evaluation": "short realism assessment and what to correct next"
}
{/USER}
"""


@dataclass(frozen=True)
class ThreadSpec:
    category: str
    number: int

    @property
    def file_id(self) -> str:
        return f"{self.category}_{self.number}"

    @property
    def topic_id(self) -> str:
        return "climate_change" if self.category == "clim" else "immigration"


class BatchLogger:
    """Small logger compatible with Orchestrator without DB writes."""

    def __init__(self) -> None:
        self.errors: list[dict[str, Any]] = []

    def log_event(self, event_type: str, data: Any) -> None:
        del event_type, data

    def log_llm_call(
        self,
        agent_name: str,
        prompt: str,
        response: str | None,
        error: str | None = None,
    ) -> None:
        del agent_name, prompt, response, error

    def log_error(
        self,
        error_type: str,
        error_message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.errors.append(
            {
                "type": error_type,
                "message": error_message,
                "context": context or {},
            }
        )
        print(f"[pipeline:{error_type}] {error_message}", flush=True)

    async def drain(self) -> None:
        return None


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def fetch_json(url: str, retries: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def fetch_text(url: str, retries: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def load_old_thread(kind: str, length: int, spec: ThreadSpec) -> dict[str, Any]:
    return fetch_json(f"{BASE_URL}/{kind}/{length}/{spec.file_id}.json")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def local_index_html() -> str:
    html = fetch_text(f"{BASE_URL}/index.html")
    html = html.replace("<!-- 6 Mode tabs -->", "<!-- 4 Mode tabs -->")
    html = re.sub(
        r'\n\s*<button class="tab-btn" id="btn-reals-30".*?</button>',
        "",
        html,
        flags=re.S,
    )
    html = re.sub(
        r'\n\s*<button class="tab-btn" id="btn-ficticis-30".*?</button>',
        "",
        html,
        flags=re.S,
    )
    html = re.sub(
        r",\s*'30':\s*\{\s*clim:\s*\[2\],\s*imm:\s*\[11\]\s*\}",
        "",
        html,
        flags=re.S,
    )
    html = html.replace("grid-template-columns: repeat(3, 1fr);", "grid-template-columns: repeat(2, 1fr);")
    html = html.replace("Turing Test (Final)", "Turing Test (Regenerated)")
    html = html.replace(
        "Explore the real and fictitious posts selected for the Turing Test experiment, classified by length and topic.",
        "Explore the real posts and regenerated fictitious posts for the Turing Test experiment, classified by length and topic.",
    )
    return html


def prepare_static_viewer(out_dir: Path) -> None:
    write_text(out_dir / "index.html", local_index_html())
    write_text(out_dir / "viewer.html", fetch_text(f"{BASE_URL}/viewer.html"))
    write_text(out_dir / "estils.css", fetch_text(f"{BASE_URL}/estils.css"))


def write_run_notes(out_dir: Path, args: argparse.Namespace) -> None:
    notes = {
        "output": str(out_dir),
        "base_source": BASE_URL,
        "models": {
            "director": {
                "provider": "bsc" if args.all_bsc else "anthropic",
                "model": args.performer_model if args.all_bsc else args.director_model,
            },
            "performer": {
                "provider": "bsc",
                "model": args.performer_model,
                "bsc_model_version": args.bsc_model_version,
            },
            "moderator": {
                "provider": "bsc" if args.all_bsc else "anthropic",
                "model": args.performer_model if args.all_bsc else args.haiku_model,
            },
            "classifier": {
                "provider": "bsc" if args.all_bsc else "anthropic",
                "model": args.performer_model if args.all_bsc else args.haiku_model,
            },
        },
        "all_bsc": args.all_bsc,
        "incivility_boost": args.incivility_boost,
        "changes_vs_first_regeneration": [
            "Output folder renamed to results/turing_test_regenerated_2.",
            "Per-turn target lengths are sampled from the paired real 16-message thread with jitter, capped at 220 words.",
            "Performer max tokens raised to allow occasional long comments.",
            "Surface calibration reduces ellipses, expands q/xq/tb-style abbreviations, normalizes emotional ALL-CAPS, and replaces repeated political cliches.",
            "Reply metadata and timestamps are calibrated to each paired real thread.",
            "A small probability of forced same-author double turns was added.",
            "Light personal hooks are appended to some agent personas without editing shared platform prompts.",
            "Humanizer can be enabled with abbreviation substitutions disabled.",
            "Optional all-BSC mode uses the BSC Gemma endpoint for Director, Performer, Moderator, and Classifier.",
            "Optional incivility boost adds ordinary visible contempt only to messages already classified as incivil.",
            "Turing v3 calibration reduces theatrical insults and stock political slogans while preserving low-key incivility.",
        ],
    }
    write_json(out_dir / "run_manifest.json", notes)
    write_text(out_dir / "generation_script_snapshot.py", Path(__file__).read_text(encoding="utf-8"))
    write_text(
        out_dir / "README.md",
        "# Turing regenerated _2\n\n"
        "Self-contained static package with copied real threads, regenerated fictitious threads, "
        "viewer assets, diagnostics, run manifest, and a snapshot of the generation script.\n",
    )


def write_self_contained_html(out_dir: Path, filename: str = "turing_autocontenido.html") -> Path:
    order = {
        "clim": [f"clim_{i}" for i in range(1, 9)],
        "imm": [f"imm_{i}" for i in range(1, 14)],
    }
    threads: dict[str, dict[str, dict[str, Any]]] = {
        "reals": {"8": {}, "16": {}},
        "ficticis": {"8": {}, "16": {}},
    }
    for kind in ("reals", "ficticis"):
        for length in ("8", "16"):
            for category, ids in order.items():
                del category
                for file_id in ids:
                    path = out_dir / kind / length / f"{file_id}.json"
                    if path.exists():
                        threads[kind][length][file_id] = json.loads(path.read_text(encoding="utf-8"))
    payload = {
        "order": order,
        "labels": {
            "reals": "Reales",
            "ficticis": "Ficticios",
            "8": "8 mensajes",
            "16": "16 mensajes",
            "clim": "Cambio climatico",
            "imm": "Inmigracion",
        },
        "threads": threads,
    }
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Turing Test Regenerado</title>
<style>
:root {{ color-scheme: light; --bg:#f5f5f2; --fg:#171717; --muted:#666; --line:#d8d6ce; --panel:#fff; --accent:#245c54; --reply:#f0eee7; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:Arial, Helvetica, sans-serif; background:var(--bg); color:var(--fg); }}
header {{ padding:22px 20px 14px; border-bottom:1px solid var(--line); background:#fbfaf6; position:sticky; top:0; z-index:2; }}
h1 {{ margin:0 0 6px; font-size:24px; line-height:1.2; letter-spacing:0; }}
.subtitle {{ margin:0; color:var(--muted); font-size:14px; }}
.tabs {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:14px; }}
button {{ border:1px solid var(--line); background:var(--panel); color:var(--fg); padding:8px 10px; border-radius:6px; cursor:pointer; font-size:14px; }}
button.active {{ background:var(--accent); color:white; border-color:var(--accent); }}
.wrap {{ max-width:1180px; margin:0 auto; padding:20px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:10px; }}
.card {{ display:block; text-decoration:none; color:inherit; background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; min-height:116px; }}
.card:hover {{ border-color:var(--accent); }}
.card small {{ color:var(--muted); display:block; margin-bottom:8px; }}
.card strong {{ display:block; font-size:15px; line-height:1.25; }}
.card span {{ display:block; color:var(--muted); font-size:13px; margin-top:8px; }}
.viewer {{ display:none; }}
.viewer.active {{ display:block; }}
.back {{ margin-bottom:14px; }}
.post {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; margin-bottom:14px; }}
.agency {{ color:var(--accent); font-weight:bold; font-size:12px; text-transform:uppercase; }}
.post h2 {{ margin:6px 0 8px; font-size:22px; line-height:1.25; letter-spacing:0; }}
.body {{ color:#333; font-size:14px; line-height:1.45; max-height:190px; overflow:auto; white-space:pre-wrap; border-top:1px solid var(--line); padding-top:10px; }}
.meta {{ color:var(--muted); font-size:13px; margin-top:8px; }}
.messages {{ display:grid; gap:9px; }}
.msg {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }}
.msg-head {{ display:flex; justify-content:space-between; gap:10px; color:var(--muted); font-size:12px; margin-bottom:5px; }}
.sender {{ color:var(--accent); font-weight:bold; font-size:14px; }}
.quote {{ background:var(--reply); border-left:3px solid var(--accent); padding:7px 8px; margin:7px 0; color:#555; font-size:13px; line-height:1.3; }}
.text {{ font-size:15px; line-height:1.38; white-space:pre-wrap; }}
.likes {{ color:var(--muted); font-size:12px; margin-top:6px; }}
@media (max-width:640px) {{ header {{ position:static; }} .wrap {{ padding:14px; }} .grid {{ grid-template-columns:1fr; }} .post h2 {{ font-size:19px; }} }}
</style>
</head>
<body>
<header>
  <h1>Turing Test Regenerado</h1>
  <p class="subtitle">HTML autocontenido con hilos reales y ficticios para longitudes 8 y 16.</p>
  <div class="tabs" id="tabs"></div>
</header>
<main class="wrap">
  <section id="list"></section>
  <section id="viewer" class="viewer"></section>
</main>
<script id="embedded-data" type="application/json">{data_json}</script>
<script>
const STORE = JSON.parse(document.getElementById('embedded-data').textContent);
let mode = {{kind:'ficticis', len:'16'}};
const $ = (sel) => document.querySelector(sel);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
const words = (txt, n=28) => {{
  const arr = String(txt || '').trim().split(/\\s+/).filter(Boolean);
  return arr.length > n ? arr.slice(0, n).join(' ') + '...' : arr.join(' ');
}};
function threadIds() {{
  return [...STORE.order.clim, ...STORE.order.imm].filter(id => STORE.threads[mode.kind][mode.len][id]);
}}
function renderTabs() {{
  const tabs = $('#tabs');
  tabs.innerHTML = '';
  for (const kind of ['reals','ficticis']) for (const len of ['8','16']) {{
    const btn = document.createElement('button');
    btn.textContent = `${{STORE.labels[kind]}} · ${{STORE.labels[len]}}`;
    btn.className = kind === mode.kind && len === mode.len ? 'active' : '';
    btn.onclick = () => {{ mode={{kind,len}}; location.hash=''; renderList(); renderTabs(); }};
    tabs.appendChild(btn);
  }}
}}
function renderList() {{
  $('#viewer').classList.remove('active');
  const list = $('#list');
  const ids = threadIds();
  list.innerHTML = `<div class="grid">${{ids.map(id => {{
    const t = STORE.threads[mode.kind][mode.len][id];
    const p = t.post_original || {{}};
    const cat = id.startsWith('clim') ? 'clim' : 'imm';
    return `<a class="card" href="#${{mode.kind}}/${{mode.len}}/${{id}}">
      <small>${{STORE.labels[cat]}} · ${{esc(p.agency || '')}}</small>
      <strong>${{esc(p.title || id)}}</strong>
      <span>${{esc((t.messages || []).length)}} mensajes · ${{esc(id)}}</span>
    </a>`;
  }}).join('')}}</div>`;
}}
function renderThread(kind, len, id) {{
  const t = STORE.threads?.[kind]?.[len]?.[id];
  if (!t) return renderList();
  mode = {{kind, len}};
  renderTabs();
  $('#list').innerHTML = '';
  const p = t.post_original || {{}};
  const viewer = $('#viewer');
  viewer.classList.add('active');
  viewer.innerHTML = `
    <button class="back" onclick="location.hash=''; renderList(); renderTabs();">Volver</button>
    <article class="post">
      <div class="agency">${{esc(p.agency || '')}}</div>
      <h2>${{esc(p.title || id)}}</h2>
      <div class="meta">${{esc(STORE.labels[kind])}} · ${{esc(STORE.labels[len])}} · ${{esc(id)}}</div>
      <div class="body">${{esc(p.body || '')}}</div>
    </article>
    <section class="messages">
      ${{(t.messages || []).map((m, i) => `
        <article class="msg">
          <div class="msg-head"><span class="sender">${{esc(m.sender || 'Usuario')}}</span><span>#${{i+1}}</span></div>
          ${{m.reply_to ? `<div class="quote"><strong>${{esc(m.reply_to)}}:</strong> ${{esc(words(m.reply_text || '', 34))}}</div>` : ''}}
          <div class="text">${{esc(m.text || '')}}</div>
          ${{m.likes ? `<div class="likes">${{esc(m.likes)}} like${{m.likes === 1 ? '' : 's'}}</div>` : ''}}
        </article>
      `).join('')}}
    </section>`;
  window.scrollTo({{top:0, behavior:'instant'}});
}}
function route() {{
  const parts = location.hash.replace(/^#/, '').split('/');
  if (parts.length === 3) renderThread(parts[0], parts[1], parts[2]);
  else renderList();
}}
window.addEventListener('hashchange', route);
renderTabs();
route();
</script>
</body>
</html>
"""
    output = out_dir / filename
    write_text(output, html)
    return output


def write_self_contained_html(out_dir: Path, filename: str = "turing_autocontenido.html") -> Path:
    """Write a single-file viewer with the same visual language as the original page."""
    order = {
        "clim": [f"clim_{i}" for i in range(1, 9)],
        "imm": [f"imm_{i}" for i in range(1, 14)],
    }
    threads: dict[str, dict[str, dict[str, Any]]] = {
        "reals": {"8": {}, "16": {}},
        "ficticis": {"8": {}, "16": {}},
    }
    for kind in ("reals", "ficticis"):
        for length in ("8", "16"):
            for ids in order.values():
                for file_id in ids:
                    path = out_dir / kind / length / f"{file_id}.json"
                    if path.exists():
                        threads[kind][length][file_id] = json.loads(path.read_text(encoding="utf-8"))
    payload = {
        "order": order,
        "labels": {
            "reals": "Reals",
            "ficticis": "Ficticis",
            "8": "Length 8",
            "16": "Length 16",
            "clim": "Climate Change Threads (Canvi Climàtic)",
            "imm": "Immigration Threads (Immigració)",
        },
        "threads": threads,
    }
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = """<!DOCTYPE html>
<html lang="ca">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Turing Test - Final Posts</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            line-height: 1.6;
            color: #1e293b;
            background-color: #f8fafc;
            margin: 0;
        }
        body.list-mode {
            padding: 30px 20px;
        }
        body.thread-mode {
            padding: 0;
            height: 100vh;
            overflow: hidden;
            background-color: #f1f5f9;
            display: flex;
            justify-content: center;
        }
        .list-shell {
            max-width: 950px;
            margin: 0 auto;
        }
        .back-link {
            text-decoration: none;
            color: #6366f1;
            font-weight: 600;
            font-size: 0.95em;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: color 0.2s;
            margin-bottom: 20px;
        }
        .back-link:hover { color: #4f46e5; }
        header { margin-bottom: 35px; }
        h1 {
            color: #0f172a;
            font-size: 2.2em;
            font-weight: 800;
            margin: 0 0 8px 0;
            letter-spacing: -0.025em;
        }
        .subtitle {
            color: #64748b;
            font-size: 1.1em;
            margin: 0;
        }
        .tabs-container {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            background: #e2e8f0;
            padding: 6px;
            border-radius: 14px;
            margin-bottom: 30px;
            gap: 6px;
        }
        .tab-btn {
            padding: 12px 16px;
            border: none;
            background: transparent;
            color: #475569;
            font-weight: 600;
            font-size: 0.95em;
            cursor: pointer;
            border-radius: 10px;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            text-align: center;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 2px;
        }
        .tab-btn span.label-type {
            font-size: 0.75em;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #64748b;
        }
        .tab-btn span.label-len { font-size: 1.05em; }
        .tab-btn:hover {
            color: #0f172a;
            background: rgba(255, 255, 255, 0.5);
        }
        .tab-btn.active {
            background: white;
            color: #6366f1;
            box-shadow: 0 4px 12px -2px rgba(0,0,0,0.05), 0 2px 4px -1px rgba(0,0,0,0.03);
        }
        .tab-btn.active span.label-type { color: #6366f1; }
        .category-title {
            font-size: 1.3em;
            color: #0f172a;
            margin: 25px 0 15px 0;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 8px;
        }
        .post-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 12px;
            margin-bottom: 30px;
        }
        .post-card {
            background: white;
            padding: 18px 20px;
            border-radius: 12px;
            border: 1px solid #e2e8f0;
            text-decoration: none;
            color: inherit;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 1px 3px rgba(0,0,0,0.02);
        }
        .post-card:hover {
            border-color: #6366f1;
            transform: translateY(-2px);
            box-shadow: 0 10px 15px -3px rgba(99,102,241,0.05), 0 4px 6px -2px rgba(99,102,241,0.03);
        }
        .post-info {
            display: flex;
            flex-direction: column;
            gap: 4px;
            flex: 1;
            padding-right: 15px;
            min-width: 0;
        }
        .post-tag {
            font-size: 0.75em;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #6366f1;
        }
        .post-title {
            font-weight: 600;
            color: #1e293b;
            font-size: 1.05em;
            line-height: 1.4;
        }
        .post-meta {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 0.8em;
            color: #64748b;
            margin-top: 2px;
            flex-wrap: wrap;
        }
        .meta-item {
            display: flex;
            align-items: center;
            gap: 4px;
        }
        .arrow-icon {
            color: #cbd5e1;
            transition: transform 0.2s, color 0.2s;
            flex-shrink: 0;
        }
        .post-card:hover .arrow-icon {
            color: #6366f1;
            transform: translateX(3px);
        }
        #session-wrapper {
            width: 100%;
            max-width: 800px;
            background: white;
            border-left: 1px solid #e2e8f0;
            border-right: 1px solid #e2e8f0;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .header {
            padding: 16px 20px;
            background: white;
            border-bottom: 1px solid #e2e8f0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }
        .back-btn {
            text-decoration: none;
            color: #64748b;
            font-weight: 600;
            font-size: 13px;
            display: flex;
            align-items: center;
            gap: 4px;
            padding: 6px 12px;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
            margin-right: 8px;
            transition: all 0.2s;
            background: white;
            cursor: pointer;
        }
        .back-btn:hover {
            background: #f1f5f9;
            color: #0f172a;
            border-color: #cbd5e1;
        }
        #messages-container {
            flex: 1;
            overflow-y: auto;
            padding: 12px 12px 24px 12px;
            background-color: #f8fafc;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .news-card {
            position: relative;
            background: white;
            border: 1px solid #e2e8f0;
            border-top: 5px solid #6366f1;
            border-radius: 8px;
            padding: 24px 24px 20px 24px;
            margin: 0px 72px 10px 58px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            display: block;
            height: auto;
            clear: both;
        }
        .news-title {
            font-size: 20px;
            font-weight: 800;
            color: #1e293b;
            line-height: 1.25;
            margin: 10px 0;
            display: block;
        }
        .news-body {
            font-size: 14px;
            color: #64748b;
            line-height: 1.6;
            display: block;
            white-space: pre-wrap;
        }
        .message-card {
            background: white;
            border: 1px solid #e2e8f0;
            border-left: 4px solid #ddd;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 20px;
        }
        .msg-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .av {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: 700;
        }
        .un { font-size: 14px; font-weight: 600; }
        .ts { font-size: 11px; color: #94a3b8; }
        .quote {
            margin: 8px 0 12px 0;
            padding: 8px 12px;
            background: #f8f9fa;
            border-left: 3px solid #cbd5e1;
            border-radius: 6px;
        }
        .quote-user {
            font-weight: 600;
            font-size: 13px;
            margin-bottom: 2px;
        }
        .quote-text {
            font-size: 13px;
            color: #64748be9;
            font-style: normal;
            line-height: 1.4;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .msg-body {
            font-size: 14px;
            line-height: 1.5;
            color: #1e293b;
            white-space: pre-wrap;
        }
        .msg-footer {
            margin-top: 14px;
            display: flex;
            gap: 18px;
            flex-wrap: wrap;
        }
        .btn {
            font-size: 12px;
            color: #94a3b8;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        .btn svg { width: 14px; height: 14px; }
        .date-pill {
            display: flex;
            justify-content: center;
            margin: 0 0 8px 0;
        }
        .date-pill span {
            background: #e2e8f0;
            color: #64748b;
            font-size: 11px;
            font-weight: 400;
            padding: 4px 12px;
            border-radius: 99px;
            text-transform: uppercase;
        }
        .hidden { display: none !important; }
        @media (max-width: 768px) {
            .tabs-container { grid-template-columns: repeat(2, 1fr); }
            .news-card { margin: 0 0 10px 0; }
            .header { padding: 12px 14px; }
        }
        @media (max-width: 480px) {
            body.list-mode { padding: 22px 14px; }
            .tabs-container { grid-template-columns: 1fr; }
            h1 { font-size: 1.75em; }
            .post-card { padding: 15px 16px; }
            .msg-footer { gap: 12px; }
        }
    </style>
</head>
<body class="list-mode">
    <div id="list-view" class="list-shell">
        <a href="#" class="back-link" onclick="return false;">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="19" y1="12" x2="5" y2="12"></line>
                <polyline points="12 19 5 12 12 5"></polyline>
            </svg>
            Back to Portal
        </a>
        <header>
            <h1>Turing Test (Regenerated)</h1>
            <p class="subtitle">Explore the real posts and regenerated fictitious posts for the Turing Test experiment, classified by length and topic.</p>
        </header>
        <div class="tabs-container" id="tabs"></div>
        <div>
            <div class="category-title"><span>🌍</span> Climate Change Threads (Canvi Climàtic)</div>
            <div class="post-grid" id="grid-clim"></div>
            <div class="category-title"><span>👥</span> Immigration Threads (Immigració)</div>
            <div class="post-grid" id="grid-imm"></div>
        </div>
    </div>

    <div id="thread-view" class="hidden">
        <div id="session-wrapper">
            <div class="header">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <a href="#" class="back-btn" id="back-to-list">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <line x1="19" y1="12" x2="5" y2="12"></line>
                            <polyline points="12 19 5 12 12 5"></polyline>
                        </svg>
                        Back
                    </a>
                    <div style="background: #f1f5f9; padding: 8px; border-radius: 8px; display: flex;">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2">
                            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                        </svg>
                    </div>
                    <div>
                        <div style="font-weight: 600; font-size: 14px; color: #1e293b;">Discussion Room</div>
                        <div id="p-count" style="font-size: 12px; color: #64748b;">0 participants</div>
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #64748b;">
                    <span style="height: 8px; width: 8px; background: #22c55e; border-radius: 50%;"></span> Connected
                </div>
            </div>
            <div id="messages-container">
                <div class="date-pill"><span>Today</span></div>
                <div class="news-card">
                    <div id="news-agency" style="font-size: 11px; color: #94a3b8; margin-bottom: 4px; text-transform: uppercase; font-weight: 600;"></div>
                    <div id="news-title" class="news-title"></div>
                    <div id="news-body" class="news-body"></div>
                    <div id="news-time" style="text-align: right; font-size: 11px; color: #94a3b8; margin-top: 10px;"></div>
                </div>
                <div id="reddit-messages"></div>
            </div>
        </div>
    </div>

    <script id="embedded-data" type="application/json">__DATA__</script>
    <script>
        const STORE = JSON.parse(document.getElementById('embedded-data').textContent);
        const COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#0ea5e9', '#ec4899', '#8b5cf6'];
        let currentType = 'reals';
        let currentLen = '8';

        function esc(value) {
            return String(value ?? '').replace(/[&<>"']/g, ch => ({
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            }[ch]));
        }

        function switchMode(type, length) {
            currentType = type;
            currentLen = length;
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            const active = document.getElementById(`btn-${type}-${length}`);
            if (active) active.classList.add('active');
            renderLists();
        }

        function renderTabs() {
            const tabs = document.getElementById('tabs');
            tabs.innerHTML = '';
            [['reals', '8'], ['reals', '16'], ['ficticis', '8'], ['ficticis', '16']].forEach(([type, len]) => {
                const btn = document.createElement('button');
                btn.className = 'tab-btn';
                btn.id = `btn-${type}-${len}`;
                btn.innerHTML = `<span class="label-type">${type === 'reals' ? 'Reals' : 'Ficticis'}</span><span class="label-len">Length ${len}</span>`;
                btn.addEventListener('click', () => {
                    history.replaceState(null, '', '#');
                    switchMode(type, len);
                });
                tabs.appendChild(btn);
            });
        }

        function makeCard(type, len, category, fileId) {
            const data = STORE.threads[type]?.[len]?.[fileId];
            const post = data?.post_original || {};
            const a = document.createElement('a');
            a.href = `#${type}/${len}/${fileId}`;
            a.className = 'post-card';
            a.innerHTML = `
                <div class="post-info">
                    <span class="post-tag">${esc(fileId.replace('_', ' #'))}</span>
                    <span class="post-title">${esc(post.title || fileId)}</span>
                    <div class="post-meta">
                        <span class="meta-item">${esc(post.agency || '')}</span>
                        <span class="meta-item">${esc((data?.messages || []).length)} messages</span>
                    </div>
                </div>
                <svg class="arrow-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="5" y1="12" x2="19" y2="12"></line>
                    <polyline points="12 5 19 12 12 19"></polyline>
                </svg>`;
            return a;
        }

        function renderLists() {
            document.body.className = 'list-mode';
            document.getElementById('list-view').classList.remove('hidden');
            document.getElementById('thread-view').classList.add('hidden');
            const clim = document.getElementById('grid-clim');
            const imm = document.getElementById('grid-imm');
            clim.innerHTML = '';
            imm.innerHTML = '';
            STORE.order.clim.forEach(id => {
                if (STORE.threads[currentType]?.[currentLen]?.[id]) clim.appendChild(makeCard(currentType, currentLen, 'clim', id));
            });
            STORE.order.imm.forEach(id => {
                if (STORE.threads[currentType]?.[currentLen]?.[id]) imm.appendChild(makeCard(currentType, currentLen, 'imm', id));
            });
        }

        function showThread(type, len, fileId) {
            const data = STORE.threads[type]?.[len]?.[fileId];
            if (!data) {
                renderLists();
                return;
            }
            currentType = type;
            currentLen = len;
            document.body.className = 'thread-mode';
            document.getElementById('list-view').classList.add('hidden');
            document.getElementById('thread-view').classList.remove('hidden');

            const post = data.post_original || {};
            document.getElementById('news-agency').innerText = post.agency || '';
            document.getElementById('news-title').innerText = post.title || '';
            document.getElementById('news-body').innerText = post.body || '';
            document.getElementById('news-time').innerText = post.timestamp ? new Date(post.timestamp * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : '';
            document.getElementById('p-count').innerText = `${data.num_participants || new Set((data.messages || []).map(m => m.sender)).size} participants`;

            const list = document.getElementById('reddit-messages');
            list.innerHTML = '';
            const userColors = {};
            let cIdx = 0;
            let lastSender = null;
            (data.messages || []).forEach(m => {
                if (!userColors[m.sender]) userColors[m.sender] = COLORS[cIdx++ % COLORS.length];
                const col = userColors[m.sender];
                if (m.reply_to && !userColors[m.reply_to]) userColors[m.reply_to] = COLORS[cIdx++ % COLORS.length];
                const replyCol = m.reply_to ? userColors[m.reply_to] : null;
                const card = document.createElement('div');
                card.className = 'message-card';
                card.style.borderLeftColor = col;
                const quote = (m.reply_to && m.reply_to !== lastSender) ? `
                    <div class="quote" style="border-left-color: ${replyCol}">
                        <div class="quote-user" style="color: ${replyCol}">${esc(m.reply_to)}</div>
                        <div class="quote-text">${esc(m.reply_text || '...')}</div>
                    </div>` : '';
                const t = m.timestamp ? new Date(m.timestamp * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : '';
                card.innerHTML = `
                    <div class="msg-header">
                        <div style="display:flex; align-items:center; gap:12px;">
                            <div class="av" style="background:${col}">${esc(String(m.sender || '?').slice(0,1))}</div>
                            <span class="un" style="color:${col}">${esc(m.sender || '')}</span>
                        </div>
                        <span class="ts">${esc(t)}</span>
                    </div>
                    ${quote}
                    <div class="msg-body">${esc(m.text || '')}</div>
                    <div class="msg-footer">
                        <span class="btn"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6"/></svg> Reply</span>
                        <span class="btn" style="${Number(m.likes || 0) > 0 ? 'color:#ef4444' : ''}"><svg fill="${Number(m.likes || 0) > 0 ? '#ef4444' : 'none'}" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"/></svg> ${Number(m.likes || 0) > 0 ? esc(m.likes) : 'Like'}</span>
                        <span class="btn"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><circle cx="12" cy="12" r="4"></circle><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94"></path></svg> Mention</span>
                        <span class="btn"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"></path><line x1="4" y1="22" x2="4" y2="15"></line></svg> Report</span>
                    </div>`;
                list.appendChild(card);
                lastSender = m.sender;
            });
            const container = document.getElementById('messages-container');
            container.scrollTop = 0;
        }

        function route() {
            const parts = location.hash.replace(/^#/, '').split('/').filter(Boolean);
            if (parts.length === 3) showThread(parts[0], parts[1], parts[2]);
            else renderLists();
        }

        document.getElementById('back-to-list').addEventListener('click', event => {
            event.preventDefault();
            history.pushState(null, '', '#');
            renderLists();
            switchMode(currentType, currentLen);
        });
        window.addEventListener('hashchange', route);
        renderTabs();
        switchMode(currentType, currentLen);
        route();
    </script>
</body>
</html>
""".replace("__DATA__", data_json)
    output = out_dir / filename
    write_text(output, html)
    return output


def _short_error(error: Exception) -> str:
    text = str(error).replace("\n", " ")
    text = re.sub(r"(?i)(api[_-]?key['\"]?\s*[:=]\s*)['\"]?[^'\"\s,}]+", r"\1[redacted]", text)
    if len(text) > 450:
        return text[:447] + "..."
    return text


def preflight_bsc_performer(args: argparse.Namespace) -> None:
    client = BSCClient(
        model_name=args.performer_model,
        temperature=args.performer_temperature,
        top_p=args.performer_top_p,
        max_tokens=8,
        bsc_model_version=args.bsc_model_version,
    )
    errors: list[str] = []
    kwargs = client._build_kwargs("Responde solamente OK.")

    try:
        for base_url in client._iter_candidate_base_urls():
            api = OpenAI(base_url=base_url, api_key=client.api_key)
            try:
                completion = api.chat.completions.create(**kwargs)
                if completion.choices:
                    print(
                        f"BSC preflight ok: {base_url} "
                        f"model={args.performer_model} version={args.bsc_model_version}",
                        flush=True,
                    )
                    return
                errors.append(f"{base_url}: empty completion")
            except Exception as exc:
                errors.append(f"{base_url}: {_short_error(exc)}")
            finally:
                try:
                    api.close()
                except Exception:
                    pass
    finally:
        client.close()

    joined = "; ".join(errors) or "no endpoint tried"
    raise RuntimeError(
        "BSC performer preflight failed before generation. "
        f"Requested model={args.performer_model}, version={args.bsc_model_version}. "
        f"Errors: {joined}"
    )


def extract_template_const(source: str, name: str) -> str:
    match = re.search(rf"export const {re.escape(name)}\s*=\s*`(.*?)`", source, re.S)
    if not match:
        raise ValueError(f"Could not find template const {name}")
    return match.group(1)


def extract_mix_mix_criteria(source: str) -> str:
    match = re.search(r'\["mix_mix",\s*`(.*?)`,\s*\]', source, re.S)
    if not match:
        raise ValueError("Could not find mix_mix criteria in treatment presets")
    return match.group(1)


def load_treatment_config(root: Path) -> dict[str, str]:
    source = (root / "frontend/lib/treatment-presets.ts").read_text(encoding="utf-8")
    return {
        "chatroom_context": extract_template_const(source, "CHATROOM_CONTEXT_3X3"),
        "incivility_framework": extract_template_const(source, "INCIVILITY_FRAMEWORK_3X3"),
        "ecological_criteria": extract_template_const(source, "ECOLOGICAL_VALIDITY_3X3"),
        "internal_validity_criteria": extract_mix_mix_criteria(source),
    }


def _decode_ts_string(raw: str) -> str:
    return json.loads(f'"{raw}"')


def _extract_pool_section(source: str, const_name: str, next_marker: str) -> str:
    start = source.index(f"export const {const_name}")
    end = source.index(next_marker, start)
    return source[start:end]


def load_agent_pool(root: Path, topic_id: str) -> list[dict[str, Any]]:
    source = (root / "frontend/lib/agent-pool-presets.ts").read_text(encoding="utf-8")
    if topic_id == "climate_change":
        section = _extract_pool_section(
            source,
            "CLIMATE_CHANGE_AGENT_POOL",
            "export const IMMIGRATION_AGENT_POOL",
        )
    else:
        section = _extract_pool_section(
            source,
            "IMMIGRATION_AGENT_POOL",
            "export const DEFAULT_AGENT_POOL",
        )

    pattern = re.compile(
        r'buildAgent\(\s*'
        r'"(?P<id>[^"]+)"\s*,\s*'
        r'"(?P<name>[^"]+)"\s*,\s*'
        r'"(?P<incivility>[^"]+)"\s*,\s*'
        r'"(?P<ideology>[^"]+)"\s*,\s*'
        r'"(?P<alignment_cell>[^"]+)"\s*,\s*'
        r'"(?P<persona>(?:\\.|[^"\\])*)"\s*,?\s*'
        r"\)",
        re.S,
    )
    pool: list[dict[str, Any]] = []
    for match in pattern.finditer(section):
        item = match.groupdict()
        incivility = item["incivility"]
        if incivility == "uncivil":
            length_min, length_max = 3, 22
        else:
            length_min, length_max = 5, 28
        pool.append(
            {
                "id": item["id"],
                "source_name": item["name"],
                "incivility": incivility,
                "ideology": item["ideology"],
                "topic_stance": item["alignment_cell"],
                "alignment_cell": item["alignment_cell"],
                "persona": _decode_ts_string(item["persona"]),
                "message_length_min": length_min,
                "message_length_max": length_max,
            }
        )
    if not pool:
        raise ValueError(f"No pool agents parsed for {topic_id}")
    return pool


def load_narratives(root: Path, topic_id: str) -> list[dict[str, str]]:
    source = (root / "frontend/lib/narrative-presets.ts").read_text(encoding="utf-8")
    const_name = (
        "DEFAULT_NARRATIVES_CLIMATE_CHANGE"
        if topic_id == "climate_change"
        else "DEFAULT_NARRATIVES_IMMIGRATION"
    )
    match = re.search(
        rf"export const {re.escape(const_name)}: NarrativePoolCell\[\] = (\[.*?\]);",
        source,
        re.S,
    )
    if not match:
        return []
    return json.loads(match.group(1))


def visible_senders(thread: dict[str, Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for message in thread.get("messages", []):
        sender = str(message.get("sender", "")).strip()
        if sender and sender not in seen:
            names.append(sender)
            seen.add(sender)
    return names


def choose_names(
    old_real: dict[str, Any],
    old_fictic: dict[str, Any],
    names_source: str,
) -> list[str]:
    if names_source == "real":
        names = visible_senders(old_real)
    else:
        names = visible_senders(old_fictic) or visible_senders(old_real)
    if not names:
        raise ValueError("No visible sender names found")
    return names


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\wáéíóúÁÉÍÓÚñÑüÜ]+\b", str(text)))


def sampled_visible_lengths(old_real: dict[str, Any], rng: random.Random) -> list[int]:
    lengths = [word_count(m.get("text", "")) for m in old_real.get("messages", [])[:TARGET_LEN]]
    if len(lengths) < TARGET_LEN:
        fallback = lengths or [32]
        lengths.extend(rng.choice(fallback) for _ in range(TARGET_LEN - len(lengths)))
    rng.shuffle(lengths)
    sampled: list[int] = []
    for length in lengths[:TARGET_LEN]:
        jittered = round(length * rng.uniform(*REAL_LENGTH_JITTER))
        sampled.append(max(4, min(LONG_MESSAGE_WORD_CAP, jittered)))
    return sampled


def set_turn_length_target(traits: dict[str, dict[str, Any]], target_words: int) -> None:
    low = max(3, round(target_words * 0.90))
    high = max(low, round(target_words * 1.10))
    for item in traits.values():
        item["message_length_min"] = low
        item["message_length_max"] = high


def append_personal_hooks(agents: list[Agent], spec: ThreadSpec, rng: random.Random) -> None:
    """Add light biographical texture without editing the shared prompt files."""
    climate_hooks = [
        "De vez en cuando habla desde experiencia cotidiana: calor en casa, transporte, trabajo o facturas.",
        "Puede mencionar una vivencia personal breve con sequía, aire acondicionado, campo, ciudad o veranos recientes.",
        "Si encaja, usa ejemplos de familia, barrio o trabajo en vez de sonar como un informe.",
    ]
    immigration_hooks = [
        "De vez en cuando habla desde experiencia cotidiana: alquiler, empleo, barrio, escuela, sanidad o trámites.",
        "Puede mencionar una vivencia personal breve con compañeros, vecinos, familiares o clientes inmigrantes.",
        "Si encaja, usa ejemplos de familia, barrio o trabajo en vez de sonar como un informe.",
    ]
    hooks = climate_hooks if spec.topic_id == "climate_change" else immigration_hooks
    for agent in agents:
        if rng.random() < 0.45:
            agent.persona = f"{agent.persona}\n{rng.choice(hooks)}"


def _replace_preserving_case(match: re.Match[str], replacement: str) -> str:
    original = match.group(0)
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def clean_surface_text(text: str, rng: random.Random) -> str:
    text = str(text).strip()

    def ellipsis_sub(_: re.Match[str]) -> str:
        return "..." if rng.random() < 0.08 else rng.choice((".", ",", ""))

    text = ELLIPSIS_RE.sub(ellipsis_sub, text)

    for pattern, replacement in ABBREV_REPLACEMENTS:
        text = pattern.sub(lambda m, r=replacement: _replace_preserving_case(m, r), text)

    text = re.sub(r"\bla\s+las\b", "las", text, flags=re.I)
    text = re.sub(r"\bde\s+la\s+los\b", "de los", text, flags=re.I)
    text = re.sub(r"\bdel\s+el\b", "del", text, flags=re.I)

    def normalize_caps(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in SIGLA_WORDS or len(token) <= 2:
            return token
        if rng.random() < 0.98:
            return token.lower()
        return token

    text = re.sub(r"\b[A-ZÁÉÍÓÚÑ]{3,}\b", normalize_caps, text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([.?,])\s*$", r"\1", text)
    return text.strip()


def calibrate_replies(payload: dict[str, Any], old_real: dict[str, Any], rng: random.Random) -> None:
    real_messages = old_real.get("messages", [])[:TARGET_LEN]
    target_count = (
        sum(1 for m in real_messages if m.get("reply_to"))
        if real_messages else round(len(payload.get("messages", [])) * 0.90)
    )
    messages = payload.get("messages", [])
    for index, message in enumerate(messages):
        if index > 0 and message.get("reply_to"):
            target = next(
                (
                    previous for previous in reversed(messages[:index])
                    if previous.get("sender") == message.get("reply_to")
                ),
                messages[index - 1],
            )
            message["reply_text"] = target.get("text")
        if index == 0 or message.get("reply_to"):
            continue
        current_count = sum(1 for m in messages if m.get("reply_to"))
        if current_count >= target_count:
            break
        back = 1 if rng.random() < 0.70 else rng.randint(1, min(5, index))
        target = messages[index - back]
        if target.get("sender") == message.get("sender") and index > 1:
            target = messages[index - 2]
        message["reply_to"] = target.get("sender")
        message["reply_text"] = target.get("text")
        message["is_mention"] = bool(message.get("is_mention"))


def calibrate_questions(payload: dict[str, Any], old_real: dict[str, Any], rng: random.Random) -> None:
    # Do not synthesize questions post-hoc. It creates repeated, detectable
    # tails across adjacent messages; questions should come from prompts/model.
    return


def calibrate_ellipsis(payload: dict[str, Any], old_real: dict[str, Any], rng: random.Random) -> None:
    messages = payload.get("messages", [])
    real_messages = old_real.get("messages", [])[: len(messages)]
    if not messages or not real_messages:
        return
    target = sum(1 for message in real_messages if ELLIPSIS_RE.search(str(message.get("text", ""))))
    current = sum(1 for message in messages if ELLIPSIS_RE.search(str(message.get("text", ""))))
    if current >= target:
        return
    candidates = [
        message for message in messages
        if not ELLIPSIS_RE.search(str(message.get("text", "")))
        and 8 <= word_count(message.get("text", "")) <= 95
    ]
    rng.shuffle(candidates)
    for message in candidates[: max(0, target - current)]:
        text = str(message.get("text", "")).rstrip()
        if not text:
            continue
        if "," in text and rng.random() < 0.55:
            message["text"] = text.replace(",", "...", 1)
        else:
            message["text"] = re.sub(r"[.!?]+$", "", text).rstrip() + "..."


def boost_visible_incivility(payload: dict[str, Any], rng: random.Random) -> None:
    """Deprecated: incivility should come from the performer prompt, not post-hoc text edits."""
    del payload, rng


def calibrate_timestamps(payload: dict[str, Any], old_real: dict[str, Any], rng: random.Random) -> None:
    messages = payload.get("messages", [])
    real_messages = old_real.get("messages", [])[: len(messages)]
    if not messages:
        return
    base = float(payload.get("post_original", {}).get("timestamp") or time.time())
    if real_messages:
        first_gap = max(5.0, float(real_messages[0].get("timestamp", base + 20)) - float(old_real.get("post_original", {}).get("timestamp") or base))
    else:
        first_gap = rng.uniform(12, 45)
    current = base + max(5.0, first_gap * rng.uniform(0.75, 1.25))
    messages[0]["timestamp"] = current
    for index in range(1, len(messages)):
        if index < len(real_messages):
            prev = float(real_messages[index - 1].get("timestamp", current))
            nxt = float(real_messages[index].get("timestamp", prev + 35))
            gap = max(4.0, nxt - prev)
        else:
            gap = rng.uniform(8, 70)
        current += max(4.0, gap * rng.uniform(0.75, 1.25))
        messages[index]["timestamp"] = current


def calibrate_payload(payload: dict[str, Any], old_real: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    for message in payload.get("messages", []):
        message["text"] = clean_surface_text(message.get("text", ""), rng)
    if (payload.get("generation_metadata") or {}).get("incivility_boost"):
        boost_visible_incivility(payload, rng)
    calibrate_questions(payload, old_real, rng)
    calibrate_ellipsis(payload, old_real, rng)
    calibrate_replies(payload, old_real, rng)
    calibrate_timestamps(payload, old_real, rng)
    return payload


def final_quality_issue(payload: dict[str, Any]) -> str | None:
    return None


def prefix_payload(payload16: dict[str, Any], length: int) -> dict[str, Any]:
    payload = json.loads(json.dumps(payload16, ensure_ascii=False))
    payload["messages"] = payload["messages"][:length]
    payload["generation_metadata"] = dict(payload.get("generation_metadata") or {})
    payload["generation_metadata"]["derived_from_16"] = True
    return payload


def ordered_templates(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = [
        ("pro_topic", "civil"),
        ("anti_topic", "civil"),
        ("pro_topic", "uncivil"),
        ("anti_topic", "uncivil"),
        ("pro_topic", "civil"),
        ("anti_topic", "civil"),
        ("pro_topic", "uncivil"),
        ("anti_topic", "uncivil"),
    ]
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    for cell, incivility in order:
        for agent in pool:
            if agent["id"] in used:
                continue
            if agent["alignment_cell"] == cell and agent["incivility"] == incivility:
                selected.append(agent)
                used.add(agent["id"])
                break
    selected.extend(agent for agent in pool if agent["id"] not in used)
    return selected


def assign_agents(names: list[str], pool: list[dict[str, Any]]) -> tuple[list[Agent], dict[str, dict[str, Any]]]:
    templates = ordered_templates(pool)
    agents: list[Agent] = []
    traits: dict[str, dict[str, Any]] = {}
    for index, name in enumerate(names):
        template = dict(templates[index % len(templates)])
        source_name = template["source_name"]
        persona = template["persona"].replace(source_name, name)
        agents.append(Agent(name=name, persona=persona))
        traits[name] = {
            "incivility": template["incivility"],
            "ideology": template["ideology"],
            "topic_stance": template["topic_stance"],
            "alignment_cell": template["alignment_cell"],
            "message_length_min": template["message_length_min"],
            "message_length_max": template["message_length_max"],
        }
    return agents, traits


SHORT_PERSONA_BANK = (
    "{name}, 33. Habla con calma y suele apoyarse en hechos.",
    "{name}, 46. Le sale un tono sereno, algo pragmatico, y trata de rebajar exageraciones sin negar el problema.",
    "{name}, 38. Usa un tono hostil y descalificador cuando siente que le estan tomando el pelo.",
    "{name}, 29. Cuando le provocan salta rapido, con tono bronco y poca paciencia.",
    "{name}, 33. Habla de forma pulcra y esceptica.",
    "{name}, 29. Su estilo es incisivo pero todavia bastante contenido.",
    "{name}, 46. Tiene un tono bronco y condescendiente.",
    "{name}, 38. Discute con sarcasmo, impaciencia y ganas de pinchar al otro.",
)


def apply_short_personas(agents: list[Agent]) -> None:
    for index, agent in enumerate(agents):
        agent.persona = SHORT_PERSONA_BANK[index % len(SHORT_PERSONA_BANK)].format(name=agent.name)


def _truncate_words(text: str, max_words: int) -> str:
    if max_words <= 0:
        return text
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip() + "..."


def build_article_context(
    config: dict[str, str],
    post_original: dict[str, Any],
    max_body_words: int = 0,
) -> str:
    headline = str(post_original.get("title", "")).strip()
    body = _truncate_words(str(post_original.get("body", "")).strip(), max_body_words)
    agency = str(post_original.get("agency", "")).strip()
    article_block = "\n\nThe following news article has been shown to the participant:"
    if headline:
        article_block += f"\nHeadline: {headline}"
    if agency:
        article_block += f"\nSource: {agency}"
    if body:
        article_block += f"\n\nArticle text:\n{body}"
    return config["chatroom_context"].rstrip() + article_block


def compact_bsc_config(config: dict[str, str]) -> dict[str, str]:
    compact = dict(config)
    compact["chatroom_context"] = (
        "Spanish Telegram-style discussion about a news article. "
        "Agents have fixed stance, ideology, incivility level, and alignment cell. "
        "Keep the debate realistic, conversational, politically situated in Spain, and balanced for mix_mix."
    )
    compact["incivility_framework"] = (
        "Incivil means visibly impolite, contemptuous, mocking, insulting, vulgar, or belittling. "
        "Civil means disagreement without personal contempt. No threats or dehumanization."
    )
    compact["ecological_criteria"] = (
        "Realism: varied lengths, some questions, many replies, occasional double turns, sustained dyads, "
        "no repetitive templates, no stock contempt phrases, no postprocessed-sounding wording."
    )
    compact["internal_validity_criteria"] = (
        "INCIVILITY_TARGET = 50\n"
        "LIKEMINDED_TARGET = 50\n"
        "NOT_LIKEMINDED_TARGET = 50\n"
        "Keep mix_mix balanced and do not change percentages."
    )
    return compact


def build_simulation_config(seed: int, agent_names: list[str], args: argparse.Namespace) -> dict[str, Any]:
    director_provider = "bsc" if args.all_bsc else "anthropic"
    director_model = args.performer_model if args.all_bsc else args.director_model
    moderator_provider = "bsc" if args.all_bsc else "anthropic"
    moderator_model = args.performer_model if args.all_bsc else args.haiku_model
    classifier_provider = "bsc" if args.all_bsc else "anthropic"
    classifier_model = args.performer_model if args.all_bsc else args.haiku_model
    return {
        "random_seed": seed,
        "session_duration_minutes": 30,
        "num_agents": len(agent_names),
        "agent_names": agent_names,
        "agent_personas": ["" for _ in agent_names],
        "messages_per_minute": 6,
        "director_llm_provider": director_provider,
        "director_llm_model": director_model,
        "director_temperature": args.performer_temperature if args.all_bsc else 0.7,
        "director_top_p": args.performer_top_p if args.all_bsc else None,
        "director_max_tokens": 1536 if args.all_bsc else 1024,
        "performer_llm_provider": "bsc",
        "performer_llm_model": args.performer_model,
        "performer_temperature": args.performer_temperature,
        "performer_top_p": args.performer_top_p,
        "performer_max_tokens": args.performer_max_tokens,
        "moderator_llm_provider": moderator_provider,
        "moderator_llm_model": moderator_model,
        "moderator_temperature": args.performer_temperature if args.all_bsc else 0.2,
        "moderator_top_p": args.performer_top_p if args.all_bsc else None,
        "moderator_max_tokens": 512,
        "classifier_llm_provider": classifier_provider,
        "classifier_llm_model": classifier_model,
        "classifier_temperature": args.performer_temperature if args.all_bsc else 0.2,
        "classifier_top_p": args.performer_top_p if args.all_bsc else None,
        "classifier_max_tokens": 512 if args.all_bsc else 256,
        "evaluate_interval": 5,
        "action_window_size": 5,
        "performer_memory_size": 3,
        "parallel_turns": 1,
        "agent_mode": "pool",
        "boost_replies_mentions": True,
        "ten_messages_mode": False,
        "humanize_output": args.humanize,
        "humanize_strip_hashtags": 100,
        "humanize_strip_inverted_punct": 100,
        "humanize_word_subs": args.humanize_word_subs,
        "humanize_drop_accents": args.humanize_drop_accents,
        "humanize_comma_spacing": args.humanize_comma_spacing,
        "humanize_max_emoji": 1,
        "humanize_lowercase_initial": args.humanize_lowercase_initial,
        "humanize_drop_final_punct": args.humanize_drop_final_punct,
        "bsc_model_version": args.bsc_model_version,
        "classifier_prompt_template": DEFAULT_CLASSIFIER_PROMPT_TEMPLATE,
    }


def message_to_static_json(message: Message, state: SessionState) -> dict[str, Any]:
    reply_sender = None
    reply_text = None
    if message.reply_to:
        target = next((m for m in state.messages if m.message_id == message.reply_to), None)
        if target is not None:
            reply_sender = target.sender
            reply_text = target.content
    elif message.mentions:
        reply_sender = message.mentions[0]
        target = next((m for m in reversed(state.messages) if m.sender == reply_sender), None)
        reply_text = target.content if target else None

    return {
        "id": message.message_id,
        "sender": message.sender,
        "text": message.content,
        "timestamp": message.timestamp.timestamp(),
        "reply_to": reply_sender,
        "reply_text": reply_text,
        "is_mention": bool(message.mentions),
        "likes": len(message.liked_by or set()),
        "is_incivil": message.is_incivil,
        "is_like_minded": message.is_like_minded,
        "inferred_participant_stance": message.inferred_participant_stance,
        "classification_rationale": message.classification_rationale,
    }


def apply_like(result: TurnResult, state: SessionState) -> None:
    if not result.target_message_id:
        return
    target = next((m for m in state.messages if m.message_id == result.target_message_id), None)
    if target is not None:
        target.liked_by.add(result.agent_name)


def thread_payload(
    old_real: dict[str, Any],
    old_fictic: dict[str, Any],
    state: SessionState,
    length: int,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    post_original = dict(old_real.get("post_original") or {})
    old_fictic_post = old_fictic.get("post_original") or {}
    if old_fictic_post.get("author"):
        post_original["author"] = old_fictic_post["author"]
    post_original["timestamp"] = metadata["post_timestamp"]

    messages = [message_to_static_json(message, state) for message in state.messages[:length]]
    return {
        "post_original": post_original,
        "num_participants": old_fictic.get("num_participants", len({m["sender"] for m in messages})),
        "messages": messages,
        "generation_metadata": metadata,
    }


async def generate_one(
    spec: ThreadSpec,
    old_real: dict[str, Any],
    old_fictic: dict[str, Any],
    config: dict[str, str],
    root: Path,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    seed = args.seed + (1000 if spec.category == "imm" else 0) + spec.number
    rng = random.Random(seed)
    names = choose_names(old_real, old_fictic, args.names_source)
    pool = load_agent_pool(root, spec.topic_id)
    narratives = load_narratives(root, spec.topic_id)
    agents, traits = assign_agents(names, pool)
    if args.persona_style == "short":
        apply_short_personas(agents)
    else:
        append_personal_hooks(agents, spec, rng)
    simulation_config = build_simulation_config(seed, names, args)
    session_id = f"turing_{spec.file_id}_{uuid.uuid4().hex[:8]}"
    logger = BatchLogger()

    state = SessionState(
        session_id=session_id,
        agents=agents,
        duration_minutes=30,
        user_name=args.participant_name,
        participant_stance_hint=args.participant_stance,
        experimental_config={"internal_validity_criteria": config["internal_validity_criteria"]},
        simulation_config=simulation_config,
        treatment_group="mix_mix",
    )

    chatroom_context = build_article_context(
        config,
        old_real.get("post_original") or {},
        max_body_words=args.bsc_article_words if args.all_bsc else 0,
    )
    orchestrator = Orchestrator(
        director_llm=LLMManager.from_simulation_config(simulation_config, role="director"),
        performer_llm=LLMManager.from_simulation_config(simulation_config, role="performer"),
        moderator_llm=LLMManager.from_simulation_config(simulation_config, role="moderator"),
        classifier_llm=LLMManager.from_simulation_config(simulation_config, role="classifier"),
        state=state,
        logger=logger,
        evaluate_interval=simulation_config["evaluate_interval"],
        action_window_size=simulation_config["action_window_size"],
        performer_memory_size=simulation_config["performer_memory_size"],
        chatroom_context=chatroom_context,
        incivility_framework=config["incivility_framework"],
        ecological_criteria=config["ecological_criteria"],
        classifier_prompt_template=simulation_config["classifier_prompt_template"],
        director_action_prompt_template=COMPACT_DIRECTOR_ACTION_TEMPLATE if args.all_bsc else None,
        director_evaluate_prompt_template=COMPACT_DIRECTOR_EVALUATE_TEMPLATE if args.all_bsc else None,
        humanize_output=simulation_config["humanize_output"],
        humanize_rules={
            "strip_hashtags": simulation_config["humanize_strip_hashtags"],
            "strip_inverted_punct": simulation_config["humanize_strip_inverted_punct"],
            "word_subs": simulation_config["humanize_word_subs"],
            "drop_accents": simulation_config["humanize_drop_accents"],
            "comma_spacing": simulation_config["humanize_comma_spacing"],
            "max_emoji": simulation_config["humanize_max_emoji"],
            "lowercase_initial": simulation_config["humanize_lowercase_initial"],
            "drop_final_punct": simulation_config["humanize_drop_final_punct"],
        },
        boost_replies_mentions=simulation_config["boost_replies_mentions"],
        ten_messages_mode=simulation_config["ten_messages_mode"],
        rng=rng,
        agent_traits=traits,
        narrative_pool=narratives,
    )
    orchestrator.auto_like_probability = args.auto_like_probability

    max_attempts = args.max_turn_attempts
    attempts = 0
    forced_double_turns = 0
    wait_blocked_performers: set[str] = set()
    length_targets = sampled_visible_lengths(old_real, rng)
    print(f"[{spec.file_id}] generating {TARGET_LEN} messages with {len(names)} names", flush=True)
    while len(state.messages) < TARGET_LEN and attempts < max_attempts:
        attempts += 1
        target_words = length_targets[min(len(state.messages), TARGET_LEN - 1)]
        set_turn_length_target(traits, target_words)
        allowed_performers = None
        forced_double_candidate = False
        if wait_blocked_performers and len(wait_blocked_performers) < len(names):
            allowed_performers = {name for name in names if name not in wait_blocked_performers}
        if (
            allowed_performers is None
            and state.messages
            and forced_double_turns < args.max_double_turns
            and len(state.messages) >= 2
            and state.messages[-1].sender != state.messages[-2].sender
            and rng.random() < args.double_turn_probability
        ):
            allowed_performers = {state.messages[-1].sender}
            forced_double_candidate = True
        result = await orchestrator.execute_turn(
            config["internal_validity_criteria"],
            allowed_performers=allowed_performers,
        )
        if result is None:
            continue
        if result.action_type == "wait":
            if result.agent_name:
                wait_blocked_performers.add(result.agent_name)
            if len(wait_blocked_performers) >= len(names):
                wait_blocked_performers.clear()
            continue
        if result.action_type == "like":
            apply_like(result, state)
            continue
        if result.message is not None:
            message_content = result.message.content or ""
            if STOCK_FORMULA_RE.search(message_content) or ODD_CAPS_RE.search(message_content):
                logger.log_error(
                    "stock_formula_seen",
                    f"Stock formula seen from '{result.message.sender}'",
                    {"content": message_content[:220]},
                )
            if (
                forced_double_candidate
                and len(state.messages) > 0
                and result.message.sender == state.messages[-1].sender
            ):
                forced_double_turns += 1
            state.add_message(result.message)
            wait_blocked_performers.clear()
            print(
                f"[{spec.file_id}] message {len(state.messages)}/{TARGET_LEN}: "
                f"{result.message.sender}",
                flush=True,
            )

    if len(state.messages) < TARGET_LEN:
        raise RuntimeError(
            f"{spec.file_id}: generated {len(state.messages)} messages after {attempts} attempts"
        )

    metadata = {
        "source": BASE_URL,
        "file_id": spec.file_id,
        "topic_id": spec.topic_id,
        "treatment_group": "mix_mix",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "post_timestamp": time.time(),
        "seed": seed,
        "names_source": args.names_source,
        "agent_names": names,
        "models": {
            "director": {
                "provider": simulation_config["director_llm_provider"],
                "model": simulation_config["director_llm_model"],
                "bsc_model_version": args.bsc_model_version if simulation_config["director_llm_provider"] == "bsc" else None,
            },
            "performer": {
                "provider": "bsc",
                "model": args.performer_model,
                "bsc_model_version": args.bsc_model_version,
            },
            "moderator": {
                "provider": simulation_config["moderator_llm_provider"],
                "model": simulation_config["moderator_llm_model"],
                "bsc_model_version": args.bsc_model_version if simulation_config["moderator_llm_provider"] == "bsc" else None,
            },
            "classifier": {
                "provider": simulation_config["classifier_llm_provider"],
                "model": simulation_config["classifier_llm_model"],
                "bsc_model_version": args.bsc_model_version if simulation_config["classifier_llm_provider"] == "bsc" else None,
            },
        },
        "all_bsc": args.all_bsc,
        "incivility_boost": args.incivility_boost,
        "length_policy": {
            "source": "thread_real_lengths_with_jitter",
            "jitter": list(REAL_LENGTH_JITTER),
            "cap": LONG_MESSAGE_WORD_CAP,
            "targets": length_targets,
            "performer_max_tokens": args.performer_max_tokens,
        },
        "surface_calibration": {
            "expand_abbreviations": True,
            "reduce_ellipsis": True,
            "normalize_emotional_all_caps": True,
            "replace_repeated_political_cliches": True,
            "calibrate_reply_metadata_to_real_thread": True,
            "calibrate_timestamps_to_real_thread": True,
            "persona_style": args.persona_style,
            "personal_hooks_added_to_personas": args.persona_style == "pool",
            "double_turn_probability": args.double_turn_probability,
            "max_double_turns": args.max_double_turns,
        },
        "errors": logger.errors,
    }
    payload16 = thread_payload(old_real, old_fictic, state, TARGET_LEN, metadata)
    payload16 = calibrate_payload(payload16, old_real, rng)
    issue = final_quality_issue(payload16)
    if issue:
        raise FinalQualityError(f"{spec.file_id}: {issue}")
    payload8 = prefix_payload(payload16, PREFIX_LEN)
    diagnostics = {
        "file_id": spec.file_id,
        "attempts": attempts,
        "message_count": len(state.messages),
        "unique_senders": sorted({m.sender for m in state.messages}),
        "incivil_count": sum(1 for m in state.messages if m.is_incivil is True),
        "like_count": sum(len(m.liked_by or set()) for m in state.messages),
        "forced_double_turns": forced_double_turns,
        "length_targets": length_targets,
        "errors": logger.errors,
    }
    return payload16, payload8, diagnostics


def scrape_inputs(specs: list[ThreadSpec], out_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    scraped: dict[str, dict[str, dict[str, Any]]] = {}
    for spec in specs:
        scraped[spec.file_id] = {}
        for kind in ("reals", "ficticis"):
            for length in (PREFIX_LEN, TARGET_LEN):
                payload = load_old_thread(kind, length, spec)
                scraped[spec.file_id][f"{kind}_{length}"] = payload
                write_json(out_dir / "scraped" / kind / str(length) / f"{spec.file_id}.json", payload)
                if kind == "reals":
                    write_json(out_dir / kind / str(length) / f"{spec.file_id}.json", payload)
    return scraped


def check_prefixes(scraped: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    mismatches: list[str] = []
    for file_id, items in scraped.items():
        for kind in ("reals", "ficticis"):
            short = items[f"{kind}_{PREFIX_LEN}"].get("messages", [])
            long = items[f"{kind}_{TARGET_LEN}"].get("messages", [])
            is_prefix = all(
                i < len(long)
                and message.get("id") == long[i].get("id")
                and message.get("sender") == long[i].get("sender")
                and message.get("text") == long[i].get("text")
                for i, message in enumerate(short)
            )
            if not is_prefix:
                mismatches.append(f"{kind}/{file_id}")
    return {
        "checked_files": len(scraped),
        "prefix_len": PREFIX_LEN,
        "target_len": TARGET_LEN,
        "all_prefixes": not mismatches,
        "mismatches": mismatches,
    }


async def run(args: argparse.Namespace) -> None:
    root = repo_root()
    out_dir = Path(args.output_dir).resolve()
    specs = [ThreadSpec(category, n) for category, nums in THREADS for n in nums]
    if args.only:
        wanted = set(args.only.split(","))
        specs = [spec for spec in specs if spec.file_id in wanted]
    if args.limit:
        specs = specs[: args.limit]

    out_dir.mkdir(parents=True, exist_ok=True)
    print("Preparing local static viewer", flush=True)
    prepare_static_viewer(out_dir)
    write_run_notes(out_dir, args)
    print(f"Output dir: {out_dir}", flush=True)
    print(f"Scraping {len(specs)} old thread pairs", flush=True)
    scraped = scrape_inputs(specs, out_dir)
    prefix_report = check_prefixes(scraped)
    write_json(out_dir / "prefix_report.json", prefix_report)
    print(f"Prefix check: {prefix_report}", flush=True)
    if args.scrape_only:
        return

    if not args.skip_bsc_preflight:
        preflight_bsc_performer(args)

    config = load_treatment_config(root)
    if args.all_bsc:
        config = compact_bsc_config(config)
    all_diagnostics: list[dict[str, Any]] = []
    for idx, spec in enumerate(specs, start=1):
        output16 = out_dir / "ficticis" / str(TARGET_LEN) / f"{spec.file_id}.json"
        output8 = out_dir / "ficticis" / str(PREFIX_LEN) / f"{spec.file_id}.json"
        if output16.exists() and output8.exists() and not args.force:
            print(f"[{idx}/{len(specs)}] skip existing {spec.file_id}", flush=True)
            diagnostics_path = out_dir / "diagnostics" / f"{spec.file_id}.json"
            if diagnostics_path.exists():
                try:
                    all_diagnostics.append(json.loads(diagnostics_path.read_text(encoding="utf-8")))
                    write_json(out_dir / "diagnostics_summary.json", {"threads": all_diagnostics})
                except (OSError, json.JSONDecodeError):
                    pass
            continue

        old_real = scraped[spec.file_id][f"reals_{TARGET_LEN}"]
        old_fictic = scraped[spec.file_id][f"ficticis_{TARGET_LEN}"]
        print(f"[{idx}/{len(specs)}] start {spec.file_id}", flush=True)
        last_quality_error: FinalQualityError | None = None
        for quality_attempt in range(args.final_quality_retries + 1):
            run_args = argparse.Namespace(**vars(args))
            run_args.seed = args.seed + quality_attempt * 100000
            try:
                if quality_attempt:
                    print(
                        f"[{idx}/{len(specs)}] retry {quality_attempt}/{args.final_quality_retries} "
                        f"{spec.file_id} after quality failure",
                        flush=True,
                    )
                payload16, payload8, diagnostics = await generate_one(
                    spec=spec,
                    old_real=old_real,
                    old_fictic=old_fictic,
                    config=config,
                    root=root,
                    args=run_args,
                )
                break
            except FinalQualityError as exc:
                last_quality_error = exc
                print(f"[{idx}/{len(specs)}] quality reject {spec.file_id}: {exc}", flush=True)
        else:
            raise last_quality_error or FinalQualityError(f"{spec.file_id}: final quality failed")
        write_json(output16, payload16)
        write_json(output8, payload8)
        write_json(out_dir / "diagnostics" / f"{spec.file_id}.json", diagnostics)
        all_diagnostics.append(diagnostics)
        write_json(out_dir / "diagnostics_summary.json", {"threads": all_diagnostics})
        html_path = write_self_contained_html(out_dir)
        print(f"[{idx}/{len(specs)}] updated HTML {html_path}", flush=True)
        print(f"[{idx}/{len(specs)}] saved {spec.file_id}", flush=True)

    html_path = write_self_contained_html(out_dir)
    print(f"Self-contained HTML: {html_path}", flush=True)
    print("Done", flush=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(repo_root() / "results/turing_test_regenerated_2"))
    parser.add_argument("--seed", type=int, default=5200)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only", default="", help="Comma-separated file ids, e.g. clim_1,imm_11")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--scrape-only", action="store_true")
    parser.add_argument("--names-source", choices=["fictic", "real"], default="fictic")
    parser.add_argument("--participant-name", default="Alex")
    parser.add_argument("--participant-stance", default="pro_topic")
    parser.add_argument("--director-model", default="claude-sonnet-4-6")
    parser.add_argument("--haiku-model", default="claude-haiku-4-5")
    parser.add_argument("--performer-model", default="incivility")
    parser.add_argument("--bsc-model-version", choices=["v1", "v2"], default="v1")
    parser.add_argument("--all-bsc", action="store_true", help="Use BSC Gemma for Director, Performer, Moderator, and Classifier")
    parser.add_argument("--persona-style", choices=["pool", "short"], default="pool")
    parser.add_argument("--bsc-article-words", type=int, default=140)
    parser.add_argument("--performer-temperature", type=float, default=1.1)
    parser.add_argument("--performer-top-p", type=float, default=0.92)
    parser.add_argument("--performer-max-tokens", type=int, default=512)
    parser.add_argument("--auto-like-probability", type=float, default=0.12)
    parser.add_argument("--double-turn-probability", type=float, default=0.18)
    parser.add_argument("--max-double-turns", type=int, default=4)
    parser.add_argument("--max-turn-attempts", type=int, default=120)
    parser.add_argument("--final-quality-retries", type=int, default=3)
    parser.add_argument("--humanize", action="store_true")
    parser.add_argument("--humanize-word-subs", type=int, default=0)
    parser.add_argument("--humanize-drop-accents", type=int, default=8)
    parser.add_argument("--humanize-comma-spacing", type=int, default=8)
    parser.add_argument("--humanize-lowercase-initial", type=int, default=6)
    parser.add_argument("--humanize-drop-final-punct", type=int, default=18)
    parser.add_argument("--incivility-boost", action="store_true", help="Deprecated no-op; incivility is controlled by prompts/instructions")
    parser.add_argument("--skip-bsc-preflight", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
