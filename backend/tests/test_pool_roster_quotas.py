"""The immigration preset pool must let every 3x3 treatment get its exact
roster: with 8 agents per room, up to 6 like-minded/opposite agents and up to
4 civil or 4 uncivil agents per side are needed. The pretest pool (2 civil +
2 uncivil per side) could not, so every room got all 8 agents (50% uncivil)
whatever the condition."""
from types import SimpleNamespace

import pytest

from platforms.chatroom import SimulationSession

# Mirrors IMMIGRATION_AGENT_POOL in frontend/lib/agent-pool-presets.ts.
POOL = [
    *({"id": f"pt_c{i}", "name": n, "incivility": "civil", "ideology": "left", "alignment_cell": "pro_topic", "persona": ""}
      for i, n in enumerate(["Lucia", "Diego", "Elena", "Andres"])),
    *({"id": f"pt_u{i}", "name": n, "incivility": "uncivil", "ideology": "left", "alignment_cell": "pro_topic", "persona": ""}
      for i, n in enumerate(["Nuria", "Sergio", "Paula", "Victor"])),
    *({"id": f"at_c{i}", "name": n, "incivility": "civil", "ideology": "right", "alignment_cell": "anti_topic", "persona": ""}
      for i, n in enumerate(["Cristina", "Oscar", "Teresa", "Fernando"])),
    *({"id": f"at_u{i}", "name": n, "incivility": "uncivil", "ideology": "right", "alignment_cell": "anti_topic", "persona": ""}
      for i, n in enumerate(["Carlos", "Irene", "Rocio", "Gonzalo"])),
]


def _roster(like_target, incivility_target, stance):
    fake = SimpleNamespace(
        experimental_config={"pool_agent_ids": [a["id"] for a in POOL]},
        simulation_config={"num_agents": 8},
        internal_validity_criteria=(
            f"INCIVILITY_TARGET = {incivility_target}\nLIKEMINDED_TARGET = {like_target}"
        ),
        _pool_agent_traits=SimulationSession._pool_agent_traits,
    )
    names, _, traits = SimulationSession._select_pool_agents(
        fake, experimental_full={"agent_pool": POOL}, participant_stance_hint=stance,
    )
    cell = {a["name"]: a["alignment_cell"] for a in POOL}
    like = sum(1 for n in names if cell[n] == stance)
    uncivil = sum(1 for n in names if traits[n]["incivility"] == "uncivil")
    return len(names), like, uncivil


@pytest.mark.parametrize("stance", ["pro_topic", "anti_topic"])
@pytest.mark.parametrize("like_target,expected_like", [(20, 2), (50, 4), (80, 6)])
@pytest.mark.parametrize("incivility_target,expected_uncivil", [(20, 2), (50, 4), (80, 6)])
def test_every_treatment_gets_its_exact_roster(
    stance, like_target, expected_like, incivility_target, expected_uncivil,
):
    assert _roster(like_target, incivility_target, stance) == (8, expected_like, expected_uncivil)
