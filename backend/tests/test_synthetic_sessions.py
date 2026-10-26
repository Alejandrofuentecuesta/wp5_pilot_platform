import asyncio
import json
import uuid
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from utils.synthetic_sessions import (
    BatchRequest, PROFILE_TRAITS, SyntheticBatches, build_items, fixed_participant,
    isolated_config, participant_delay, participant_prompt, parse_participant_action,
    resolve_batch_seed,
)


def request(**overrides):
    return BatchRequest(**{
        "source_experiment_id": "human-study", "groups": ["low", "high"],
        "participant_provider": "konstanz", "participant_model": "test-model",
        "confirm_api_usage": True, **overrides,
    })


def source():
    return {"simulation": {"random_seed": 42}, "experimental": {
        "redirect_url": "https://panel.example/complete", "safety": {"enabled": True},
        "groups": {"low": {"seed": {"template_id": "immigration"}}, "high": {}},
    }}


@pytest.mark.parametrize("changes", [
    {"concurrency": 5}, {"duration_minutes": 0}, {"max_participant_calls": 0},
    {"groups": ["low", "low"]}, {"groups": list(map(str, range(6))), "sessions_per_group": 100},
    {"confirm_api_usage": False}, {"participant_model": " "}, {"participant_interval_seconds": 1},
    {"seed_mode": "invalid"}, {"seed": -1}, {"seed": 2**31},
    {"participant_traits": {"style": "unknown"}}, {"participant_traits": {"unknown_trait": "low"}},
])
def test_request_bounds(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_config_isolation_preserves_source_and_safety():
    original = source()
    cfg = isolated_config(original, request(), "batch")
    assert original["experimental"]["redirect_url"] == "https://panel.example/complete"
    assert original["simulation"] == {"random_seed": 42}
    assert cfg["experimental"]["redirect_url"] == ""
    assert cfg["experimental"]["safety"] == original["experimental"]["safety"]
    assert cfg["synthetic"]["source_experiment_id"] == "human-study"
    assert cfg["simulation"]["synthetic_participant_config"]["participant_model"] == "test-model"
    assert "confirm_api_usage" not in cfg["synthetic"]["batch_request"]
    cfg["experimental"]["groups"]["high"]["changed"] = True
    assert "changed" not in original["experimental"]["groups"]["high"]


def test_automatic_profiles_are_seeded_balanced_and_matched_across_treatments():
    spec = request(vary_participants=True, sessions_per_group=17)
    records = build_items(spec)
    assert records == build_items(spec)
    assert records != build_items(request(vary_participants=True, sessions_per_group=17, seed=4201))
    participants = [r["participant"] for r in records[::2]]
    for low, high in zip(records[::2], records[1::2]):
        assert low["group"] == "low" and high["group"] == "high"
        assert low["participant"] == high["participant"]
        assert low["participant"] is not high["participant"]
        assert (low["stance"], low["seed"]) == (high["stance"], high["seed"])
    for trait, options in PROFILE_TRAITS.items():
        counts = Counter(p["traits"][trait] for p in participants)
        assert set(counts) == set(options)
        assert max(counts.values()) - min(counts.values()) <= 1
    assert all(p["base_profile"] == spec.participant_profile for p in participants)
    assert all("do not predetermine anger" in p["profile"] for p in participants)
    reordered = build_items(request(vary_participants=True, sessions_per_group=17, groups=["high", "low"]))
    assert [r["participant"] for r in reordered] == [r["participant"] for r in records]


def test_fixed_mode_is_backward_compatible():
    spec = request()
    assert spec.vary_participants is False
    records = build_items(spec)
    assert all(r["participant"] == fixed_participant(spec) for r in records)
    assert all(participant_delay(r["participant"], r["seed"], 1) == 45 for r in records)


def test_seeded_stance_can_start_on_either_side_and_is_matched_across_nine_treatments():
    first_stances = set()
    for seed in range(32):
        spec = request(groups=[f"t{i}" for i in range(9)], sessions_per_group=5,
                       stance="seeded_balanced", seed=seed, vary_participants=True)
        records = build_items(spec)
        assert records == build_items(spec)
        for repeat in range(5):
            matched = records[repeat * 9:(repeat + 1) * 9]
            assert len({r["stance"] for r in matched}) == 1
            assert len({r["seed"] for r in matched}) == 1
            assert all(r["participant"] == matched[0]["participant"] for r in matched)
        first_stances.add(records[0]["stance"])
        counts = Counter(r["stance"] for r in records[::9])
        assert abs(counts["pro_topic"] - counts["anti_topic"]) == 1
        single = build_items(request(stance="seeded_balanced", seed=seed, sessions_per_group=1))
        assert single[0]["stance"] == records[0]["stance"]
    assert first_stances == {"pro_topic", "anti_topic"}


@pytest.mark.parametrize("stance", ["pro_topic", "anti_topic"])
def test_explicit_stance_is_never_randomized(stance):
    assert all(r["stance"] == stance for r in build_items(request(stance=stance, sessions_per_group=7)))


def test_trait_overrides_apply_without_changing_other_automatic_assignments():
    baseline = build_items(request(vary_participants=True, sessions_per_group=12))
    spec = request(vary_participants=True, sessions_per_group=12,
                   participant_traits={"opinion_strength": "firm", "activity": "active"})
    overridden = build_items(spec)
    for before, after in zip(baseline, overridden):
        assigned = after["participant"]["traits"]
        assert assigned["opinion_strength"] == "firm"
        assert assigned["activity"] == "active"
        assert assigned["topic_knowledge"] == before["participant"]["traits"]["topic_knowledge"]
        assert assigned["style"] == before["participant"]["traits"]["style"]
        assert after["participant"]["interval_seconds"] == 31.5
        assert "Readily join" in after["participant"]["profile"]
    cfg = isolated_config(source(), spec, "batch")
    assert cfg["simulation"]["synthetic_participant_config"]["participant_traits"]["activity"] == "active"
    manual = build_items(request(vary_participants=False, participant_traits={"activity": "active"}))
    assert manual[0]["participant"]["traits"] == {}
    assert manual[0]["participant"]["interval_seconds"] == 45


@pytest.mark.asyncio
async def test_automatic_seed_skips_used_seeds_without_mutating_request():
    spec = request(seed_mode="automatic")
    conn = SimpleNamespace(fetchval=AsyncMock(side_effect=[True, False]))
    with patch("utils.synthetic_sessions.secrets.randbelow", side_effect=[4200, 12345]):
        resolved = await resolve_batch_seed(spec, conn)
    assert resolved.seed == 12345
    assert resolved.seed_mode == "automatic"
    assert spec.seed == 4200
    assert conn.fetchval.await_count == 2
    assert conn.fetchval.await_args_list[0].args[1:] == ("human-study", "4200")


@pytest.mark.asyncio
async def test_fixed_seed_does_not_consult_or_change_history():
    spec = request(seed=0)
    conn = SimpleNamespace(fetchval=AsyncMock())
    with patch("utils.synthetic_sessions.secrets.randbelow") as draw:
        assert await resolve_batch_seed(spec, conn) is spec
    conn.fetchval.assert_not_awaited()
    draw.assert_not_called()


@pytest.mark.parametrize("base", [10, 45, 300])
def test_automatic_timing_is_bounded_repeatable_and_varies(base):
    records = build_items(request(vary_participants=True, sessions_per_group=12, participant_interval_seconds=base))
    for record in records:
        participant = record["participant"]
        delays = [participant_delay(participant, record["seed"], n) for n in range(20)]
        assert all(10 <= delay <= 300 for delay in delays)
        assert len(set(delays)) > 1
        assert delays == [participant_delay(participant, record["seed"], n) for n in range(20)]
    for low, high in zip(records[::2], records[1::2]):
        assert participant_delay(low["participant"], low["seed"], 5) == participant_delay(high["participant"], high["seed"], 5)


def test_prompt_uses_public_transcript_without_treatment_details():
    visible = [{"sender": "[news]", "content": "Public article"},
               {"sender": "Alice", "content": "Public message", "message_id": "m1", "private_trait": "secret"}]
    prompt = participant_prompt(visible, "pro_topic", "Curious", True, "climate_change")
    assert "Public article" in prompt and "Public message" in prompt
    assert "secret" not in prompt and "private_trait" not in prompt
    assert "prioritizing renewable energy" in prompt


@pytest.mark.parametrize("stance,expected", [
    ("pro_topic", "stricter environmental regulations despite economic costs"),
    ("anti_topic", "opposes strict environmental regulations"),
])
def test_climate_participant_stance_matches_the_updated_policy_survey(stance, expected):
    prompt = json.loads(participant_prompt([], stance, "Curious", True, "climate_change"))
    assert expected in prompt["opinion"]
    assert "CO2 emission targets" in prompt["opinion"]
    assert "human-caused" not in prompt["opinion"]


@pytest.mark.parametrize("raw,initial", [
    ('{"action":"wait"}', True), ('{"action":"message","content":""}', False),
    ('{"action":"message","content":"ok","reply_to":"invisible"}', False),
    ('[]', False), ('not json', False),
    (json.dumps({"action": "message", "content": "a" * 601}), False),
    ('```json\n{"action":"wait"}\n```', True),
    ('```json\n{"action":"message","content":"ok","reply_to":"invisible"}\n```', False),
    ('```json\n{"action":"message","content":""}\n```', False),
    ('```json\n' + json.dumps({"action": "message", "content": "a" * 601}) + '\n```', False),
    ('```json\n{"action":"message","content":"truncated', False),
    ('Here is my response:\n```json\n{"action":"message","content":"ok"}\n```', False),
    ('```json\n{"action":"message","content":"ok"}\n```\nExtra commentary', False),
    ('```json\n{"action":"message","content":"ok"}\n```\n```json\n{}\n```', False),
    (None, True),
])
def test_bad_participant_outputs_are_not_posted(raw, initial):
    with pytest.raises((ValueError, TypeError)):
        parse_participant_action(raw, [], initial)


def test_wait_and_valid_reply():
    assert parse_participant_action('{"action":"wait"}', [], False) == {"action": "wait"}
    action = parse_participant_action('{"action":"message","content":" ok ","reply_to":"m1"}',
                                      [{"sender": "Alice", "message_id": "m1"}], False)
    assert action == {"action": "message", "content": "ok", "reply_to": "m1"}


@pytest.mark.parametrize("opening,closing", [
    ("```json\n", "\n```"), ("```\n", "\n```"),
    ("  ```JSON\r\n", "\r\n```  "),
])
def test_participant_accepts_a_single_fenced_json_object(opening, closing):
    content = "What about the glaciers?"
    raw = opening + json.dumps({"action": "message", "content": content, "reply_to": "m1"}) + closing
    action = parse_participant_action(raw, [{"sender": "Alice", "message_id": "m1"}], True)
    assert action == {"action": "message", "content": content, "reply_to": "m1"}
    assert parse_participant_action(opening + '{"action":"wait"}' + closing, [], False) == {"action": "wait"}


def item():
    return {"index": 0, "group": "low", "seed": 99, "stance": "anti_topic",
            "status": "queued", "participant_calls": 0, "messages": 0}


@pytest.fixture
def participant_run():
    session = SimpleNamespace(running=True, operator_held=False, clock_task=None,
                              _watchdog_task=None, logger=MagicMock())

    async def post(*args, **kwargs):
        session.running = False

    async def create(sid, receive, **kwargs):
        await receive({"message_id": "news", "sender": "[news]", "content": "Public article"})
        await receive({"message_id": "m1", "sender": "Alice", "content": "A public message"})
        return session

    session.handle_user_message = AsyncMock(side_effect=post)
    session.attach_websocket = AsyncMock()
    session.stop = AsyncMock()
    actor = SimpleNamespace(generate_response=AsyncMock())
    spec = request()
    context = SimpleNamespace(session=session, actor=actor, spec=spec, record=item(),
                              runner=SyntheticBatches(), cfg=isolated_config(source(), spec, "batch"))
    with patch("utils.synthetic_sessions.db_conn.get_pool", return_value="pool"), \
         patch("utils.synthetic_sessions.session_repo.create_session", new_callable=AsyncMock), \
         patch("utils.synthetic_sessions.session_repo.get_session", new_callable=AsyncMock, return_value={"end_reason": "duration_expired"}), \
         patch("utils.synthetic_sessions.session_manager.create_session", new_callable=AsyncMock, side_effect=create), \
         patch("utils.synthetic_sessions.LLMManager.from_simulation_config", return_value=actor):
        yield context


@pytest.mark.asyncio
@pytest.mark.parametrize("length", [613, 630, 659])
async def test_long_initial_message_is_rewritten_once_and_posted_via_normal_input(participant_run, length):
    ctx = participant_run
    rejected = "```json\n" + json.dumps({"action": "message", "content": "x" * length, "reply_to": "m1"}) + "\n```"
    repaired = json.dumps({"action": "message", "content": "A shorter opinion", "reply_to": "m1"})
    ctx.actor.generate_response.side_effect = [rejected, repaired]
    await ctx.runner._run_one("synthetic-batch", ctx.cfg, ctx.spec, {}, ctx.record)
    assert ctx.record["status"] == "completed"
    assert ctx.record["participant_calls"] == 2
    ctx.session.handle_user_message.assert_awaited_once_with("A shorter opinion", reply_to="m1")
    calls = ctx.actor.generate_response.await_args_list
    original, correction = (json.loads(call.args[0]) for call in calls)
    assert {key: value for key, value in correction.items() if key != "response_correction"} == original
    assert correction["response_correction"]["previous_response"] == rejected
    assert str(length) in correction["response_correction"]["reason"]
    assert "1-600 characters" in correction["response_correction"]["instruction"]
    assert all(call.kwargs["max_retries"] == 0 for call in calls)
    ctx.session.logger.log_event.assert_any_call("synthetic_participant_retry", {
        "reason": "message_too_long", "length": length, "limit": 600,
        "initial": True, "rejected_call": 1,
    })
    assert ctx.session.logger.log_llm_call.call_args_list[0].args[2] == rejected


@pytest.mark.asyncio
@pytest.mark.parametrize("quoted,fenced", [("molestar", True), ("en papel", False)])
async def test_unescaped_quotes_get_one_syntax_repair_with_unchanged_context(participant_run, quoted, fenced):
    ctx = participant_run
    content = f'No basta con decir "{quoted}" sin pensar en las consecuencias.'
    rejected = '{"action":"message","content":"' + content + '","reply_to":"m1"}'
    if fenced:
        rejected = "```json\n" + rejected + "\n```"
    ctx.actor.generate_response.side_effect = [
        rejected, json.dumps({"action": "message", "content": content, "reply_to": "m1"}),
    ]
    await ctx.runner._run_one("synthetic-batch", ctx.cfg, ctx.spec, {}, ctx.record)
    assert ctx.record["status"] == "completed"
    assert ctx.record["participant_calls"] == 2
    ctx.session.handle_user_message.assert_awaited_once_with(content, reply_to="m1")
    calls = ctx.actor.generate_response.await_args_list
    original, correction = (json.loads(call.args[0]) for call in calls)
    assert {key: value for key, value in correction.items() if key != "response_correction"} == original
    details = correction["response_correction"]
    assert details["previous_response"] == rejected
    assert "Correct only the JSON syntax" in details["instruction"]
    assert "Preserve the original message text, action and reply target" in details["instruction"]
    assert "Expecting ',' delimiter" in details["reason"]
    retry = [call.args[1] for call in ctx.session.logger.log_event.call_args_list
             if call.args[0] == "synthetic_participant_retry"]
    assert len(retry) == 1
    assert retry[0]["reason"] == "invalid_json"
    assert retry[0]["parse_error"] == details["reason"]
    assert all(call.kwargs["max_retries"] == 0 for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("first,second", [
    ('{"action":"message","content":"bad "quotes""}', json.dumps({"action": "message", "content": "x" * 601})),
    (json.dumps({"action": "message", "content": "x" * 601}), '{"action":"message","content":"bad "quotes""}'),
    ('not JSON', 'still not JSON'),
])
async def test_syntax_and_length_errors_share_one_repair_attempt(participant_run, first, second):
    ctx = participant_run
    ctx.actor.generate_response.side_effect = [first, second]
    await ctx.runner._run_one("synthetic-batch", ctx.cfg, ctx.spec, {}, ctx.record)
    assert ctx.record["status"] == "failed"
    assert ctx.record["participant_calls"] == 2
    ctx.session.handle_user_message.assert_not_awaited()
    assert len([call for call in ctx.session.logger.log_event.call_args_list
                if call.args[0] == "synthetic_participant_retry"]) == 1


@pytest.mark.asyncio
async def test_syntax_repair_cannot_exceed_call_budget(participant_run):
    ctx = participant_run
    ctx.spec.max_participant_calls = 1
    ctx.actor.generate_response.return_value = '{"action":"message","content":"bad "quotes""}'
    await ctx.runner._run_one("synthetic-batch", ctx.cfg, ctx.spec, {}, ctx.record)
    assert ctx.record["status"] == "failed"
    assert ctx.record["participant_calls"] == 1
    ctx.actor.generate_response.assert_awaited_once()
    ctx.session.handle_user_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    None, "", "  ",
    '{"action":"message","content":"ok","reply_to":"invisible"}',
    '{"action":"message","content":""}', '{"action":"wait"}', '[]',
])
async def test_empty_responses_and_semantic_validation_errors_do_not_get_a_syntax_retry(participant_run, raw):
    ctx = participant_run
    ctx.actor.generate_response.return_value = raw
    await ctx.runner._run_one("synthetic-batch", ctx.cfg, ctx.spec, {}, ctx.record)
    assert ctx.record["status"] == "failed"
    assert ctx.record["participant_calls"] == 1
    ctx.actor.generate_response.assert_awaited_once()
    ctx.session.handle_user_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("repair", [
    '{"action":"message","content":"ok","reply_to":"invisible"}',
    '{"action":"message","content":""}', '{"action":"wait"}', '[]',
])
async def test_syntax_repairs_must_still_pass_all_validations(participant_run, repair):
    ctx = participant_run
    ctx.actor.generate_response.side_effect = ['not JSON', repair]
    await ctx.runner._run_one("synthetic-batch", ctx.cfg, ctx.spec, {}, ctx.record)
    assert ctx.record["status"] == "failed"
    assert ctx.record["participant_calls"] == 2
    ctx.session.handle_user_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_success", [False, True])
async def test_later_malformed_json_is_repaired_or_skipped_without_aborting(participant_run, repair_success):
    ctx = participant_run
    ctx.spec.max_participant_calls = 3
    short = json.dumps({"action": "message", "content": "A short opinion"})
    ctx.actor.generate_response.side_effect = [short, 'not JSON', short if repair_success else 'not JSON']
    posts = []

    async def post(content, **kwargs):
        posts.append(content)
        ctx.session.running = len(posts) < 2

    async def finish_at_cap(*args):
        ctx.session.running = False

    ctx.session.handle_user_message.side_effect = post
    with patch("utils.synthetic_sessions.participant_delay", return_value=0), \
         patch("utils.synthetic_sessions.asyncio.sleep", new=AsyncMock(side_effect=finish_at_cap)):
        await ctx.runner._run_one("synthetic-batch", ctx.cfg, ctx.spec, {}, ctx.record)
    assert ctx.record["status"] == "completed"
    assert ctx.record["participant_calls"] == 3
    assert len(posts) == (2 if repair_success else 1)
    correction = json.loads(ctx.actor.generate_response.await_args_list[2].args[0])
    assert correction["initial_reaction"] is False
    assert correction["response_correction"]["previous_response"] == 'not JSON'


@pytest.mark.asyncio
async def test_length_rewrite_never_exceeds_the_session_call_cap(participant_run):
    ctx = participant_run
    ctx.spec.max_participant_calls = 1
    ctx.actor.generate_response.return_value = json.dumps({"action": "message", "content": "x" * 601})
    await ctx.runner._run_one("synthetic-batch", ctx.cfg, ctx.spec, {}, ctx.record)
    assert ctx.record["status"] == "failed"
    assert ctx.record["participant_calls"] == 1
    assert "600 characters" in ctx.record["error"]
    ctx.actor.generate_response.assert_awaited_once()
    ctx.session.handle_user_message.assert_not_awaited()
    ctx.session.stop.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("repair", [
    json.dumps({"action": "message", "content": "x" * 601}),
    '{"action":"message","content":"ok","reply_to":"invisible"}',
    '{"action":"message","content":""}', '{"action":"wait"}', 'not JSON',
])
async def test_invalid_length_rewrites_are_not_sent_or_retried_forever(participant_run, repair):
    ctx = participant_run
    ctx.actor.generate_response.side_effect = [json.dumps({"action": "message", "content": "x" * 601}), repair]
    await ctx.runner._run_one("synthetic-batch", ctx.cfg, ctx.spec, {}, ctx.record)
    assert ctx.record["status"] == "failed"
    assert ctx.record["participant_calls"] == 2
    ctx.session.handle_user_message.assert_not_awaited()
    ctx.session.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_length_rewrite_also_repairs_later_messages(participant_run):
    ctx = participant_run
    short = json.dumps({"action": "message", "content": "A short opinion"})
    ctx.actor.generate_response.side_effect = [short, json.dumps({"action": "message", "content": "x" * 601}), short]
    posts = []

    async def post(content, **kwargs):
        posts.append(content)
        ctx.session.running = len(posts) < 2

    ctx.session.handle_user_message.side_effect = post
    with patch("utils.synthetic_sessions.participant_delay", return_value=0):
        await ctx.runner._run_one("synthetic-batch", ctx.cfg, ctx.spec, {}, ctx.record)
    assert ctx.record["status"] == "completed"
    assert ctx.record["participant_calls"] == 3
    assert posts == ["A short opinion", "A short opinion"]
    assert json.loads(ctx.actor.generate_response.await_args_list[2].args[0])["initial_reaction"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["hold", "ended", "cancel"])
@pytest.mark.parametrize("rejection", ["length", "syntax"])
async def test_rewrite_respects_safety_holds_session_end_and_cancellation(participant_run, interruption, rejection):
    ctx = participant_run
    calls = 0

    async def generate(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return json.dumps({"action": "message", "content": "x" * 601}) if rejection == "length" else 'not JSON'
        if interruption == "cancel":
            raise asyncio.CancelledError()
        ctx.session.operator_held = interruption == "hold"
        ctx.session.running = interruption != "ended"
        return '{"action":"message","content":"A short opinion"}'

    ctx.actor.generate_response.side_effect = generate
    if interruption == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await ctx.runner._run_one("synthetic-batch", ctx.cfg, ctx.spec, {}, ctx.record)
        assert ctx.record["status"] == "cancelled"
    else:
        await ctx.runner._run_one("synthetic-batch", ctx.cfg, ctx.spec, {}, ctx.record)
        assert ctx.record["end_reason"] == ("synthetic_safety_or_operator_hold" if interruption == "hold" else "duration_expired")
    assert ctx.record["participant_calls"] == 2
    ctx.session.handle_user_message.assert_not_awaited()
    ctx.session.stop.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["message", "fenced_message", "invalid", "cancel", "hold"])
async def test_runner_uses_real_session_input_and_always_cleans_up(outcome):
    session = SimpleNamespace(running=True, operator_held=outcome == "hold", clock_task=None,
                              _watchdog_task=None, logger=MagicMock())
    async def post(*args, **kwargs):
        session.running = False
    async def stop(**kwargs):
        session.running = False
    session.handle_user_message = AsyncMock(side_effect=post)
    session.attach_websocket = AsyncMock()
    session.stop = AsyncMock(side_effect=stop)
    actor = SimpleNamespace(generate_response=AsyncMock(return_value='{"action":"message","content":"My initial opinion"}'))
    if outcome == "fenced_message":
        actor.generate_response.return_value = "```json\n" + actor.generate_response.return_value + "\n```"
    if outcome == "invalid":
        actor.generate_response.return_value = "not json"
    if outcome == "cancel":
        actor.generate_response.side_effect = asyncio.CancelledError()
    spec = request(vary_participants=True)
    cfg = isolated_config(source(), spec, "batch")
    record = dict(build_items(spec)[0], seed=99)
    async def create(sid, receive, **kwargs):
        assert kwargs["synthetic_config"]["simulation"]["random_seed"] == 99
        assert kwargs["synthetic_config"]["synthetic"]["batch_id"] == "batch"
        assert kwargs["synthetic_config"]["simulation"]["synthetic_participant_config"]["assigned_participant"] == record["participant"]
        await receive({"message_id": "news", "sender": "[news]", "content": "An article"})
        return session
    with patch("utils.synthetic_sessions.db_conn.get_pool", return_value="pool"), \
         patch("utils.synthetic_sessions.session_repo.create_session", new_callable=AsyncMock), \
         patch("utils.synthetic_sessions.session_repo.get_session", new_callable=AsyncMock, return_value={"end_reason": "duration_expired"}), \
         patch("utils.synthetic_sessions.session_manager.create_session", new_callable=AsyncMock, side_effect=create), \
         patch("utils.synthetic_sessions.LLMManager.from_simulation_config", return_value=actor):
        runner = SyntheticBatches()
        if outcome == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await runner._run_one("synthetic-batch", cfg, spec, {}, record)
        else:
            await runner._run_one("synthetic-batch", cfg, spec, {}, record)
    session.stop.assert_awaited_once()
    if outcome in ("message", "fenced_message"):
        session.handle_user_message.assert_awaited_once_with("My initial opinion", reply_to=None)
        assert record["status"] == "completed"
        assert "An article" in actor.generate_response.call_args.args[0]
        assert json.loads(actor.generate_response.call_args.args[0])["profile"] == record["participant"]["profile"]
        session.logger.log_event.assert_called_once_with("synthetic_participant", {
            "batch_id": "batch", "seed": 99, "stance": record["stance"], **record["participant"],
        })
    else:
        session.handle_user_message.assert_not_awaited()
    assert cfg["simulation"]["random_seed"] == 42


@pytest.mark.asyncio
async def test_batch_lock_prevents_overlapping_batches():
    lease = SimpleNamespace(fetchval=AsyncMock(return_value=False))
    pool = SimpleNamespace(acquire=AsyncMock(return_value=lease), release=AsyncMock())
    with patch("utils.synthetic_sessions.db_conn.get_pool", return_value=pool):
        with pytest.raises(ValueError, match="already running"):
            await SyntheticBatches().start(request())
    pool.release.assert_awaited_once_with(lease)


@pytest.mark.asyncio
async def test_batch_workers_obey_concurrency_and_persist_results():
    runner = SyntheticBatches()
    spec = request(concurrency=2)
    records = [dict(item(), index=i) for i in range(5)]
    data = {"request": spec.model_dump(), "items": records}
    lease = SimpleNamespace(fetchval=AsyncMock(return_value="running"), execute=AsyncMock())
    pool = SimpleNamespace(release=AsyncMock())
    current = peak = 0
    async def run_one(*args):
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0)
        args[-1]["status"] = "completed"
        current -= 1
    runner._run_one = AsyncMock(side_effect=run_one)
    runner._save = AsyncMock()
    with patch("utils.synthetic_sessions.db_conn.get_pool", return_value=pool):
        await runner._run(str(uuid.uuid4()), "synthetic-test", {}, data, {}, lease)
    assert peak == 2
    assert all(r["status"] == "completed" for r in records)
    pool.release.assert_awaited_once_with(lease)


@pytest.mark.asyncio
async def test_cancellation_stops_workers_and_releases_the_batch_lock():
    runner = SyntheticBatches()
    spec = request(concurrency=1)
    records = [dict(item(), index=i) for i in range(2)]
    data = {"request": spec.model_dump(), "items": records}
    lease = SimpleNamespace(fetchval=AsyncMock(return_value="cancelling"), execute=AsyncMock())
    pool = SimpleNamespace(release=AsyncMock())
    async def run_one(*args):
        args[-1]["status"] = "running"
        await asyncio.sleep(60)
    runner._run_one = AsyncMock(side_effect=run_one)
    runner._save = AsyncMock()
    with patch("utils.synthetic_sessions.db_conn.get_pool", return_value=pool):
        await runner._run(str(uuid.uuid4()), "synthetic-test", {}, data, {}, lease)
    assert all(r["status"] == "cancelled" for r in records)
    pool.release.assert_awaited_once_with(lease)


@pytest.mark.asyncio(loop_scope="session")
async def test_synthetic_schema_and_recovery_only_end_synthetic_sessions(db_pool, clean_tables):
    batch_id = uuid.uuid4()
    source_id = "synthetic-test-source-" + batch_id.hex
    destination_id = "synthetic-" + str(batch_id)
    human_sid, synthetic_sid = uuid.uuid4(), uuid.uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO experiments(experiment_id,config) VALUES($1,'{}'),($2,'{}')", source_id, destination_id)
        await conn.execute("INSERT INTO synthetic_batches(batch_id,source_experiment_id,experiment_id,status,data) VALUES($1,$2,$3,'running','{}')", batch_id, source_id, destination_id)
        for sid, eid in [(human_sid, source_id), (synthetic_sid, destination_id)]:
            await conn.execute("INSERT INTO sessions(session_id,experiment_id,treatment_group,user_name,status) VALUES($1,$2,'group','test','active')", sid, eid)
        await SyntheticBatches()._recover_locked(conn)
        assert await conn.fetchval("SELECT status FROM sessions WHERE session_id=$1", human_sid) == "active"
        assert await conn.fetchval("SELECT status FROM sessions WHERE session_id=$1", synthetic_sid) == "ended"
        assert await conn.fetchval("SELECT status FROM synthetic_batches WHERE batch_id=$1", batch_id) == "interrupted"
        await conn.execute("DELETE FROM sessions WHERE session_id=ANY($1::uuid[])", [human_sid, synthetic_sid])
        await conn.execute("DELETE FROM experiments WHERE experiment_id=ANY($1::text[])", [source_id, destination_id])


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("seed_mode", ["fixed", "automatic"])
async def test_batch_start_persists_an_isolated_experiment_and_matched_seeds(db_pool, clean_tables, seed_mode):
    runner = SyntheticBatches()
    source_id = "synthetic-source-" + uuid.uuid4().hex
    original = source()
    await db_pool.execute("INSERT INTO experiments(experiment_id,config,paused) VALUES($1,$2::jsonb,TRUE)", source_id, json.dumps(original))
    captured = {}
    async def fake_run(batch_id, experiment_id, cfg, data, actor_config, conn):
        captured.update(cfg=cfg, data=data)
        await conn.execute("UPDATE synthetic_batches SET status='completed' WHERE batch_id=$1", uuid.UUID(batch_id))
        await conn.execute("SELECT pg_advisory_unlock($1)", 842705)
        await db_pool.release(conn)
        runner.tasks.pop(batch_id, None)
    try:
        with patch("utils.synthetic_sessions.db_conn.get_pool", return_value=db_pool), \
             patch("utils.synthetic_sessions.LLMManager.from_simulation_config", return_value=MagicMock()), \
             patch("utils.synthetic_sessions.secrets.randbelow", return_value=12345), \
             patch.object(runner, "_run", side_effect=fake_run):
            result = await runner.start(request(source_experiment_id=source_id, vary_participants=True, seed_mode=seed_mode))
            await runner.tasks[result["batch_id"]]
        row = await db_pool.fetchrow("SELECT paused,config FROM experiments WHERE experiment_id=$1", result["experiment_id"])
        assert row["paused"] is True
        assert json.loads(row["config"])["synthetic"]["source_experiment_id"] == source_id
        assert json.loads(await db_pool.fetchval("SELECT config FROM experiments WHERE experiment_id=$1", source_id)) == original
        records = captured["data"]["items"]
        base_seed = 12345 if seed_mode == "automatic" else 4200
        assert captured["data"]["request"]["seed"] == base_seed
        assert captured["data"]["request"]["seed_mode"] == seed_mode
        assert captured["cfg"]["synthetic"]["batch_request"]["seed"] == base_seed
        assert [(r["group"], r["seed"], r["stance"]) for r in records] == [
            ("low", base_seed, "pro_topic"), ("high", base_seed, "pro_topic"),
            ("low", base_seed + 1, "anti_topic"), ("high", base_seed + 1, "anti_topic"),
        ]
        persisted = json.loads(await db_pool.fetchval("SELECT data FROM synthetic_batches WHERE batch_id=$1", uuid.UUID(result["batch_id"])))
        assert persisted["items"] == records
        assert records[0]["participant"] == records[1]["participant"]
        assert records[0]["participant"]["mode"] == "automatic"
        assert await db_pool.fetchval("SELECT COUNT(*) FROM tokens WHERE experiment_id=$1", result["experiment_id"]) == 0
        await db_pool.execute("DELETE FROM experiments WHERE experiment_id=$1", result["experiment_id"])
    finally:
        await db_pool.execute("DELETE FROM experiments WHERE experiment_id=$1", source_id)


@pytest.mark.asyncio
async def test_session_manager_only_bypasses_public_pause_for_marked_synthetic_configs():
    from utils.session_manager import SessionManager
    cfg = isolated_config(source(), request(), "batch")
    session = MagicMock(start=AsyncMock())
    manager = SessionManager()
    with patch("utils.session_manager.db_conn.get_pool", return_value="pool"), \
         patch("utils.session_manager.config_repo.get_experiment_config", new=AsyncMock(return_value=cfg)), \
         patch("utils.session_manager.SimulationSession", return_value=session) as constructor, \
         patch("utils.session_manager.redis_client.get_redis", return_value="redis"), \
         patch("utils.session_manager.redis_client.cache_session", new_callable=AsyncMock), \
         patch.object(manager, "_apply_experiment_pause", new_callable=AsyncMock) as apply_pause:
        result = await manager.create_session("sid", AsyncMock(), treatment_group="low", synthetic_config=cfg)
    assert result is session
    assert constructor.call_args.kwargs["_config"] is cfg
    apply_pause.assert_not_awaited()
    with patch("utils.session_manager.db_conn.get_pool", return_value="pool"), \
         patch("utils.session_manager.config_repo.get_experiment_config", new=AsyncMock(return_value=source())):
        with pytest.raises(ValueError, match="isolated synthetic"):
            await manager.create_session("sid2", AsyncMock(), treatment_group="low", synthetic_config=cfg)
