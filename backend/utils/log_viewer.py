"""
Log Viewer — generates a self-contained HTML report from a session JSONL log.

Usage:
    python -m backend.utils.log_viewer backend/logs/<session_id>.json
    python -m backend.utils.log_viewer backend/logs/<session_id>.json -o report.html
"""

import json
import sys
import html
import argparse
from pathlib import Path
from datetime import datetime


# ── HTML template pieces ─────────────────────────────────────────────────────

HTML_HEAD = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>STAGElab – Session Report – {session_id}</title>
<style>
  :root {{
    --bg: #f5f6fa;
    --card: #ffffff;
    --border: #e1e4e8;
    --accent: #4f46e5;
    --accent-light: #eef2ff;
    --text: #1f2937;
    --text-muted: #6b7280;
    --green: #059669;
    --green-light: #ecfdf5;
    --orange: #d97706;
    --orange-light: #fffbeb;
    --red: #dc2626;
    --red-light: #fef2f2;
    --blue: #2563eb;
    --blue-light: #eff6ff;
    --purple: #7c3aed;
    --purple-light: #f5f3ff;
    --gray: #6b7280;
    --gray-light: #f3f4f6;
    --mono: 'SF Mono', 'Cascadia Code', 'Fira Code', Consolas, monospace;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
    max-width: 1100px;
    margin: 0 auto;
  }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
  h2 {{ font-size: 1.15rem; margin-bottom: 0.5rem; }}
  h3 {{ font-size: 0.95rem; margin-bottom: 0.25rem; }}
  .subtitle {{ color: var(--text-muted); font-size: 0.9rem; margin-bottom: 1.5rem; }}

  /* ── Session header ─────────────────────────────────────── */
  .session-header {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
  }}
  .config-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 1rem;
    margin-top: 1rem;
  }}
  .config-section {{
    background: var(--bg);
    border-radius: 8px;
    padding: 1rem;
  }}
  .config-section h3 {{
    color: var(--accent);
    margin-bottom: 0.5rem;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  .config-row {{
    display: flex;
    justify-content: space-between;
    padding: 0.2rem 0;
    font-size: 0.85rem;
  }}
  .config-key {{ color: var(--text-muted); }}
  .config-val {{ font-family: var(--mono); font-size: 0.8rem; }}

  /* ── Timeline ───────────────────────────────────────────── */
  .timeline {{
    position: relative;
    padding-left: 2rem;
  }}
  .timeline::before {{
    content: '';
    position: absolute;
    left: 7px;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--border);
  }}
  .event {{
    position: relative;
    margin-bottom: 1rem;
  }}
  .event::before {{
    content: '';
    position: absolute;
    left: -2rem;
    top: 0.7rem;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 2px solid var(--border);
    background: var(--card);
  }}
  .event.ev-message::before {{ border-color: var(--green); background: var(--green-light); }}
  .event.ev-llm_call::before {{ border-color: var(--purple); background: var(--purple-light); }}
  .event.ev-session_start::before {{ border-color: var(--blue); background: var(--blue-light); }}
  .event.ev-websocket_detach::before {{ border-color: var(--gray); background: var(--gray-light); }}
  .event.ev-session_end::before {{ border-color: var(--red); background: var(--red-light); }}

  .event-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem 1.25rem;
    transition: box-shadow 0.15s;
  }}
  .event-card:hover {{
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  }}

  .event-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
  }}
  .event-badge {{
    display: inline-block;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
  }}
  .badge-message {{ background: var(--green-light); color: var(--green); }}
  .badge-llm_call {{ background: var(--purple-light); color: var(--purple); }}
  .badge-session_start {{ background: var(--blue-light); color: var(--blue); }}
  .badge-websocket_detach {{ background: var(--gray-light); color: var(--gray); }}
  .badge-session_end {{ background: var(--red-light); color: var(--red); }}
  .badge-like {{ background: var(--orange-light); color: var(--orange); }}

  .event-time {{
    font-size: 0.75rem;
    color: var(--text-muted);
    font-family: var(--mono);
  }}

  /* ── Chat message ───────────────────────────────────────── */
  .chat-msg {{
    display: flex;
    gap: 0.75rem;
    align-items: flex-start;
  }}
  .chat-avatar {{
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 0.85rem;
    color: white;
    flex-shrink: 0;
  }}
  .chat-body {{ flex: 1; min-width: 0; }}
  .chat-sender {{
    font-weight: 600;
    font-size: 0.9rem;
    margin-bottom: 0.15rem;
  }}
  .chat-content {{
    font-size: 0.9rem;
    line-height: 1.5;
  }}
  .chat-meta {{
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-top: 0.35rem;
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
  }}
  .chat-reply-quote {{
    border-left: 3px solid var(--border);
    padding: 0.3rem 0.6rem;
    margin-bottom: 0.5rem;
    font-size: 0.8rem;
    color: var(--text-muted);
    background: var(--bg);
    border-radius: 0 6px 6px 0;
  }}

  /* ── LLM call ───────────────────────────────────────────── */
  .llm-agent {{
    font-weight: 600;
    font-size: 0.9rem;
  }}
  .llm-agent.director {{ color: var(--purple); }}
  .llm-agent.performer {{ color: var(--orange); }}
  .llm-agent.moderator {{ color: var(--blue); }}
  .llm-sections {{ margin-top: 0.5rem; }}

  details {{
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-top: 0.5rem;
    overflow: hidden;
  }}
  details summary {{
    cursor: pointer;
    padding: 0.5rem 0.75rem;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--text-muted);
    background: var(--bg);
    user-select: none;
  }}
  details summary:hover {{ color: var(--text); }}
  details[open] summary {{ border-bottom: 1px solid var(--border); }}
  .detail-content {{
    padding: 0.75rem;
    font-size: 0.82rem;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: var(--mono);
    max-height: 500px;
    overflow-y: auto;
    background: var(--card);
  }}

  /* ── Response box (always visible) ─────────────────────── */
  .llm-response {{
    margin-top: 0.5rem;
    background: var(--bg);
    border-radius: 8px;
    padding: 0.75rem;
    font-size: 0.85rem;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
  }}
  .llm-response-label {{
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted);
    margin-bottom: 0.3rem;
  }}

  /* ── Parsed director JSON ──────────────────────────────── */
  .director-parsed {{
    margin-top: 0.5rem;
    display: grid;
    grid-template-columns: 1fr;
    gap: 0.5rem;
  }}
  .director-field {{
    background: var(--bg);
    border-radius: 8px;
    padding: 0.6rem 0.75rem;
    font-size: 0.82rem;
  }}
  .director-field-label {{
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted);
    margin-bottom: 0.15rem;
  }}
  .director-decision {{
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-top: 0.5rem;
  }}
  .director-chip {{
    display: inline-block;
    font-size: 0.78rem;
    font-weight: 600;
    padding: 0.2rem 0.6rem;
    border-radius: 6px;
    background: var(--accent-light);
    color: var(--accent);
  }}

  .error-box {{
    background: var(--red-light);
    color: var(--red);
    padding: 0.5rem 0.75rem;
    border-radius: 8px;
    font-size: 0.85rem;
    margin-top: 0.5rem;
  }}

  /* ── Footer ─────────────────────────────────────────────── */
  .footer {{
    text-align: center;
    color: var(--text-muted);
    font-size: 0.75rem;
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
  }}

  @media (max-width: 700px) {{
    body {{ padding: 1rem; }}
    .config-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
"""

HTML_TAIL = """
<div class="footer">Generated by log_viewer.py</div>
</body>
</html>
"""

# ── Colour palette for avatar circles ────────────────────────────────────────
AVATAR_COLOURS = [
    "#4f46e5", "#059669", "#d97706", "#dc2626", "#7c3aed",
    "#0891b2", "#be185d", "#65a30d", "#0d9488", "#c2410c",
]


def _colour_for(name: str, mapping: dict) -> str:
    if name not in mapping:
        mapping[name] = AVATAR_COLOURS[len(mapping) % len(AVATAR_COLOURS)]
    return mapping[name]


def _esc(text: str) -> str:
    return html.escape(str(text))


def _format_time(ts_str: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_str)
        return dt.strftime("%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
    except Exception:
        return ts_str


def _try_parse_director_json(text: str) -> dict | None:
    """Try to extract the JSON block from a director response."""
    # Strip markdown fences if present
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        # Remove first and last fence lines
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        stripped = "\n".join(lines)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


# ── Event renderers ──────────────────────────────────────────────────────────

def _config_row(label: str, value: str, *, mono: bool = True) -> str:
    val_class = 'config-val' if mono else 'config-val" style="font-family:inherit'
    return (
        f'<div class="config-row"><span class="config-key">{_esc(label)}</span>'
        f'<span class="{val_class}">{_esc(value)}</span></div>'
    )


def _llm_row(role: str, sim: dict) -> str:
    prefix = role.lower()
    provider = sim.get(f"{prefix}_llm_provider", "?")
    model = sim.get(f"{prefix}_llm_model", "?")
    temp = sim.get(f"{prefix}_temperature", "")
    top_p = sim.get(f"{prefix}_top_p", "")
    max_tok = sim.get(f"{prefix}_max_tokens", "")
    params = []
    if temp != "":
        params.append(f"temp={temp}")
    if top_p != "":
        params.append(f"top_p={top_p}")
    if max_tok != "":
        params.append(f"max={max_tok}")
    param_str = f' ({", ".join(params)})' if params else ""
    return (
        f'<div class="config-row">'
        f'<span class="config-key">{_esc(role)}</span>'
        f'<span class="config-val">{_esc(provider)} / {_esc(model)}{_esc(param_str)}</span>'
        f'</div>'
    )


# Keys handled explicitly in structured sections — skip when rendering leftovers.
_SIM_STRUCTURED_KEYS = {
    "session_duration_minutes", "num_agents", "agent_names",
    "messages_per_minute", "evaluate_interval", "random_seed",
    "director_llm_provider", "director_llm_model", "director_temperature",
    "director_top_p", "director_max_tokens",
    "performer_llm_provider", "performer_llm_model", "performer_temperature",
    "performer_top_p", "performer_max_tokens",
    "moderator_llm_provider", "moderator_llm_model", "moderator_temperature",
    "moderator_top_p", "moderator_max_tokens",
}

_EXP_STRUCTURED_KEYS = {"internal_validity_criteria", "features", "seed"}


def render_session_start(ev: dict) -> str:
    data = ev["data"]
    ts = _format_time(ev["timestamp"])
    sid = _esc(ev["session_id"])
    treatment_group = _esc(data.get("treatment_group", ""))
    experiment_id = _esc(data.get("experiment_id", ""))
    chatroom_context = data.get("chatroom_context", "")
    incivility_framework = data.get("incivility_framework", "")

    exp_cfg = data.get("experimental_config", {})
    sim_cfg = data.get("simulation_config", {})

    agent_names = sim_cfg.get("agent_names", [])
    agent_names_str = ", ".join(n for n in agent_names if n) or "auto"
    num_agents = sim_cfg.get("num_agents", len(agent_names))

    treatment_text = exp_cfg.get("internal_validity_criteria", "")
    features = exp_cfg.get("features", [])
    seed = exp_cfg.get("seed")

    parts = [
        '<div class="session-header">',
        '  <h1>Session Report</h1>',
        f'  <div class="subtitle">{sid}</div>',
        '  <div class="config-grid">',
        # ── Experiment section ──
        '    <div class="config-section">',
        '      <h3>Experiment</h3>',
    ]
    if experiment_id:
        parts.append(_config_row("ID", experiment_id))
    parts.append(_config_row("Treatment group", treatment_group))
    if chatroom_context:
        parts.append(_config_row("Chatroom context", chatroom_context, mono=False))
    if incivility_framework:
        parts.append(_config_row("Incivility framework", incivility_framework, mono=False))

    parts.append('    </div>')

    # ── Session section ──
    parts.append('    <div class="config-section">')
    parts.append('      <h3>Session</h3>')
    dur = sim_cfg.get("session_duration_minutes", "")
    parts.append(_config_row("Duration", f"{dur} min" if dur else "?"))
    parts.append(_config_row("Agents", f"{num_agents} ({agent_names_str})"))
    parts.append(_config_row("Messages/min", str(sim_cfg.get("messages_per_minute", "?"))))
    parts.append(_config_row("Evaluate interval", str(sim_cfg.get("evaluate_interval", "?"))))
    parts.append(_config_row("Random seed", str(sim_cfg.get("random_seed", "?"))))
    parts.append('    </div>')

    # ── LLM Pipeline section ──
    parts.append('    <div class="config-section">')
    parts.append('      <h3>LLM Pipeline</h3>')
    parts.append(_llm_row("Director", sim_cfg))
    parts.append(_llm_row("Performer", sim_cfg))
    parts.append(_llm_row("Moderator", sim_cfg))
    parts.append('    </div>')

    # ── Internal Validity section ──
    parts.append('    <div class="config-section">')
    parts.append('      <h3>Internal Validity Criteria</h3>')
    if treatment_text:
        parts.append(_config_row("Criteria", treatment_text, mono=False))
    if features:
        parts.append(_config_row("Features", ", ".join(features)))
    if seed and isinstance(seed, dict):
        parts.append(_config_row("Seed article", seed.get("headline", str(seed)), mono=False))
    parts.append('    </div>')

    # ── Any remaining keys not covered above ──
    extra_sim = {k: v for k, v in sim_cfg.items() if k not in _SIM_STRUCTURED_KEYS}
    extra_exp = {k: v for k, v in exp_cfg.items() if k not in _EXP_STRUCTURED_KEYS}
    if extra_sim or extra_exp:
        parts.append('    <div class="config-section">')
        parts.append('      <h3>Other</h3>')
        for k, v in extra_sim.items():
            display_v = ", ".join(v) if isinstance(v, list) else str(v)
            parts.append(_config_row(k, display_v))
        for k, v in extra_exp.items():
            display_v = ", ".join(v) if isinstance(v, list) else str(v)
            parts.append(_config_row(k, display_v))
        parts.append('    </div>')

    parts.append('  </div>')  # close config-grid
    parts.append('</div>')    # close session-header
    parts.append('')
    parts.append(f'<div class="subtitle">Timeline — started at {ts}</div>')
    parts.append('<div class="timeline">')
    return "\n".join(parts)


def render_message(ev: dict, colour_map: dict) -> str:
    data = ev["data"]
    ts = _format_time(ev["timestamp"])
    sender = data.get("sender", "Unknown")
    content = _esc(data.get("content", ""))
    colour = _colour_for(sender, colour_map)
    initial = _esc(sender[0].upper())

    meta_bits = []
    if data.get("message_id"):
        short_id = data["message_id"][:8]
        meta_bits.append(f"id: {short_id}")
    if data.get("reply_to"):
        short_reply = data["reply_to"][:8]
        meta_bits.append(f"reply to: {short_reply}")
    if data.get("mentions"):
        meta_bits.append(f"mentions: {', '.join(data['mentions'])}")
    if data.get("likes_count", 0) > 0:
        meta_bits.append(f"likes: {data['likes_count']}")
    if data.get("liked_by"):
        meta_bits.append(f"liked by: {', '.join(data['liked_by'])}")

    quote_html = ""
    if data.get("quoted_text"):
        quote_html = f'<div class="chat-reply-quote">{_esc(data["quoted_text"])}</div>'

    meta_html = ""
    if meta_bits:
        meta_html = '<div class="chat-meta">' + " · ".join(meta_bits) + '</div>'

    return f"""\
<div class="event ev-message">
  <div class="event-card">
    <div class="event-header">
      <span class="event-badge badge-message">message</span>
      <span class="event-time">{ts}</span>
    </div>
    <div class="chat-msg">
      <div class="chat-avatar" style="background:{colour}">{initial}</div>
      <div class="chat-body">
        <div class="chat-sender">{_esc(sender)}</div>
        {quote_html}
        <div class="chat-content">{content}</div>
        {meta_html}
      </div>
    </div>
  </div>
</div>"""


def render_llm_call(ev: dict) -> str:
    data = ev["data"]
    ts = _format_time(ev["timestamp"])
    agent = data.get("agent_name", "unknown")
    prompt = data.get("prompt", "")
    response = data.get("response", "")
    error = data.get("error")

    is_director = agent.startswith("__director")
    is_moderator = agent == "__moderator__"
    if is_director:
        # Distinguish the three Director sub-calls
        if agent == "__director_update__":
            role_label = "Director \u2192 Update"
        elif agent == "__director_evaluate__":
            role_label = "Director \u2192 Evaluate"
        elif agent == "__director_action__":
            role_label = "Director \u2192 Action"
        else:
            role_label = "Director"
        role_class = "director"
    elif is_moderator:
        role_label = "Moderator"
        role_class = "moderator"
    else:
        role_label = f"Performer \u2192 {agent}"
        role_class = "performer"
    badge_class = "badge-llm_call"

    # For director responses, try to parse the JSON for a nice display
    parsed_html = ""
    if is_director:
        parsed = _try_parse_director_json(response)
        if parsed:
            if agent == "__director_update__":
                parsed_html = _render_director_update_parsed(parsed)
            elif agent == "__director_evaluate__":
                parsed_html = _render_director_evaluate_parsed(parsed)
            else:
                parsed_html = _render_director_parsed(parsed)

    error_html = ""
    if error:
        error_html = f'<div class="error-box">Error: {_esc(str(error))}</div>'

    return f"""\
<div class="event ev-llm_call">
  <div class="event-card">
    <div class="event-header">
      <div>
        <span class="event-badge {badge_class}">llm call</span>
        <span class="llm-agent {role_class}" style="margin-left:0.5rem">{_esc(role_label)}</span>
      </div>
      <span class="event-time">{ts}</span>
    </div>
    {parsed_html}
    <div class="llm-sections">
      <details>
        <summary>Prompt ({len(prompt):,} chars)</summary>
        <div class="detail-content">{_esc(prompt)}</div>
      </details>
      <details>
        <summary>Raw response ({len(response):,} chars)</summary>
        <div class="detail-content">{_esc(response)}</div>
      </details>
    </div>
    {error_html}
  </div>
</div>"""


def _render_director_update_parsed(parsed: dict) -> str:
    """Render the Director Update step's JSON fields."""
    parts = ['<div class="director-parsed">']
    if "performer_profile_update" in parsed:
        parts.append(
            f'<div class="director-field">'
            f'<div class="director-field-label">Performer Profile Update</div>'
            f'{_esc(parsed["performer_profile_update"])}'
            f'</div>'
        )
    # Show any extra keys not explicitly handled
    for key, val in parsed.items():
        if key == "performer_profile_update":
            continue
        parts.append(
            f'<div class="director-field">'
            f'<div class="director-field-label">{_esc(key)}</div>'
            f'{_esc(str(val))}'
            f'</div>'
        )
    parts.append('</div>')
    return "\n".join(parts)


def _render_director_evaluate_parsed(parsed: dict) -> str:
    """Render the Director Evaluate step's JSON fields."""
    parts = ['<div class="director-parsed">']
    if "internal_validity_evaluation" in parsed:
        parts.append(
            f'<div class="director-field">'
            f'<div class="director-field-label">Internal Validity Evaluation</div>'
            f'{_esc(parsed["internal_validity_evaluation"])}'
            f'</div>'
        )
    if "ecological_validity_evaluation" in parsed:
        parts.append(
            f'<div class="director-field">'
            f'<div class="director-field-label">Ecological Validity Evaluation</div>'
            f'{_esc(parsed["ecological_validity_evaluation"])}'
            f'</div>'
        )
    # Show any extra keys not explicitly handled
    for key, val in parsed.items():
        if key in ("internal_validity_evaluation", "ecological_validity_evaluation"):
            continue
        parts.append(
            f'<div class="director-field">'
            f'<div class="director-field-label">{_esc(key)}</div>'
            f'{_esc(str(val))}'
            f'</div>'
        )
    parts.append('</div>')
    return "\n".join(parts)


def _render_director_parsed(parsed: dict) -> str:
    parts = ['<div class="director-parsed">']

    if "priority" in parsed:
        parts.append(
            f'<div class="director-field">'
            f'<div class="director-field-label">Priority</div>'
            f'{_esc(parsed["priority"])}'
            f'</div>'
        )
    if "performer_rationale" in parsed:
        parts.append(
            f'<div class="director-field">'
            f'<div class="director-field-label">Performer Rationale</div>'
            f'{_esc(parsed["performer_rationale"])}'
            f'</div>'
        )
    if "action_rationale" in parsed:
        parts.append(
            f'<div class="director-field">'
            f'<div class="director-field-label">Action Rationale</div>'
            f'{_esc(parsed["action_rationale"])}'
            f'</div>'
        )

    # Decision chips
    chips = []
    if "next_performer" in parsed:
        chips.append(f'Performer: {_esc(parsed["next_performer"])}')
    if "action_type" in parsed:
        chips.append(f'Action: {_esc(parsed["action_type"])}')
    if parsed.get("target_user"):
        chips.append(f'Target: {_esc(parsed["target_user"])}')
    if parsed.get("target_message_id"):
        short = parsed["target_message_id"][:8]
        chips.append(f'Msg: {short}')

    if chips:
        chip_html = " ".join(f'<span class="director-chip">{c}</span>' for c in chips)
        parts.append(f'<div class="director-decision">{chip_html}</div>')

    # Performer instruction
    pi = parsed.get("performer_instruction")
    if pi:
        for field in ("objective", "motivation", "directive"):
            if field in pi:
                parts.append(
                    f'<div class="director-field">'
                    f'<div class="director-field-label">{field}</div>'
                    f'{_esc(pi[field])}'
                    f'</div>'
                )

    parts.append('</div>')
    return "\n".join(parts)


def render_generic(ev: dict) -> str:
    ts = _format_time(ev["timestamp"])
    etype = ev.get("event_type", "unknown")
    badge_class = f"badge-{etype}" if etype in (
        "session_start", "session_end", "websocket_detach"
    ) else "badge-llm_call"

    data_str = json.dumps(ev.get("data", {}), indent=2)

    return f"""\
<div class="event ev-{_esc(etype)}">
  <div class="event-card">
    <div class="event-header">
      <span class="event-badge {badge_class}">{_esc(etype)}</span>
      <span class="event-time">{ts}</span>
    </div>
    <details>
      <summary>Event data</summary>
      <div class="detail-content">{_esc(data_str)}</div>
    </details>
  </div>
</div>"""


# ── Main ─────────────────────────────────────────────────────────────────────

def _render_events(events: list, session_id: str) -> str:
    """Shared rendering logic for a list of parsed event dicts."""
    colour_map: dict[str, str] = {}
    parts = [HTML_HEAD.format(session_id=_esc(session_id))]
    timeline_opened = False

    for ev in events:
        etype = ev.get("event_type")

        if etype == "session_start":
            parts.append(render_session_start(ev))
            timeline_opened = True
        elif etype == "message":
            if not timeline_opened:
                parts.append('<div class="timeline">')
                timeline_opened = True
            parts.append(render_message(ev, colour_map))
        elif etype == "llm_call":
            if not timeline_opened:
                parts.append('<div class="timeline">')
                timeline_opened = True
            parts.append(render_llm_call(ev))
        else:
            if not timeline_opened:
                parts.append('<div class="timeline">')
                timeline_opened = True
            parts.append(render_generic(ev))

    if timeline_opened:
        parts.append('</div>')  # close .timeline

    parts.append(HTML_TAIL)
    return "\n".join(parts)


def generate_html_from_lines(stream, session_id: str) -> str:
    """Generate an HTML report from a file-like JSONL stream.

    Used by the ``GET /session/{id}/report`` endpoint which builds the stream
    from DB query results rather than a file on disk.
    """
    events = []
    for line in stream:
        line = line.strip() if isinstance(line, str) else line.strip()
        if line:
            events.append(json.loads(line))

    if not events:
        return f"<html><body><p>No events for session {html.escape(session_id)}.</p></body></html>"

    return _render_events(events, session_id)


def generate_html(log_path: Path) -> str:
    events = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    if not events:
        return "<html><body><p>Empty log file.</p></body></html>"

    session_id = events[0].get("session_id", log_path.stem)
    return _render_events(events, session_id)


def main():
    parser = argparse.ArgumentParser(description="Generate HTML report from session log")
    parser.add_argument("log_file", type=Path, help="Path to the JSONL log file")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output HTML path (default: same name with .html extension)")
    args = parser.parse_args()

    if not args.log_file.exists():
        print(f"Error: {args.log_file} not found", file=sys.stderr)
        sys.exit(1)

    out_path = args.output or args.log_file.with_suffix(".html")
    html_content = generate_html(args.log_file)
    out_path.write_text(html_content)
    print(f"Report written to {out_path}")


if __name__ == "__main__":
    main()
