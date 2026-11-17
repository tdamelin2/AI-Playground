"""Phase 5 judge tests: AC-1 (blind, full/short, on time, shown) and AC-2 (summaries, flags).

Written from the Plan's acceptance criteria and Contract C5/C6/C10.
"""

from __future__ import annotations

import json
import re
import sqlite3

import pytest
from p4_helpers import CFG, new_ai_sim, shared_week
from test_p3_observer import lines, make_obs, memory_controls
from test_p4_choices import force, slow_reply

from ai_island.measure.judge import blind_packet, blind_problems, day_flags, judge_detail
from ai_island.storage.db import ChoiceDetail, RunDB
from ai_island.storage.events import (
    Died,
    Event,
    Harm,
    PromiseBroken,
    PromiseMade,
    ReflectionCompleted,
)
from ai_island.storage.records import ChoicePointRecord
from ai_island.world.view import frame_from_world

PROVIDERS = ["Anthropic", "OpenAI", "Google", "xAI", "Mistral"]
HARM = {"steal", "sabotage", "attack", "chase_off", "pull_stakes", "capture", "poach"}


def forbidden_words() -> list[str]:
    words = list(CFG.balance.judge.blind_words) + PROVIDERS
    words += [r.model for r in CFG.models.roles.values()]
    return sorted(set(words))


@pytest.fixture(scope="module")
def judged(tmp_path_factory):
    """A one-seat fake run of 2 game days with a routine, a clash and a hooked-against choice."""
    path = tmp_path_factory.mktemp("p5judge") / "run.db"
    sim = new_ai_sim(seats=(1,), seed=3, db_path=path)
    sim.run(400)
    clash = {"served": ["honesty"], "violated": ["family"], "direction": "toward"}
    against = {"served": [], "violated": [], "direction": "against"}
    force(sim, "main", slow_reply(), "spoken")
    sim.run(3)
    force(sim, "main", slow_reply(label=clash), "spoken")
    sim.run(3)
    force(sim, "main", slow_reply(label=against), "spoken", pain=90.0)
    sim.run(2880 - sim.world.tick)
    sim.save()
    yield sim
    sim.db.close()


# ------------------------------------------------------------------------------- AC-1


def test_AC1_no_judge_prompt_contains_a_model_or_company_name(judged):
    con = sqlite3.connect(judged.db.path)
    rows = con.execute("SELECT prompt_json FROM ai_calls WHERE role = 'judge'").fetchall()
    con.close()
    assert len(rows) >= 5  # labels plus two daily summaries
    for word in forbidden_words():
        pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])", re.I)
        for (prompt,) in rows:
            assert not pattern.search(prompt), f"'{word}' found in a judge prompt"


def expected_detail(c: ChoiceDetail) -> str:
    opts = c.details.get("options") or []
    harmful = (
        c.action.get("kind") in HARM
        or c.action.get("kind") == "promise"
        or bool(c.self_label.get("violated"))
        or c.self_label.get("direction") == "against"
        or any(o.get("violates") for o in opts)
        or bool(c.details.get("value_violation"))
    )
    return "full" if harmful else "short"


def test_AC1_flagged_choices_get_the_full_label_and_routine_ones_the_short_label(judged):
    db = judged.db
    choices = {c.id: c for c in db.choice_details()}
    assert len(choices) >= 3
    con = sqlite3.connect(db.path)
    rows = con.execute(
        "SELECT choice_point_id, detail_level, tick FROM judge_labels "
        "WHERE json_extract(details_json, '$.key') LIKE '%/initial'"
    ).fetchall()
    con.close()
    first = {r[0]: r for r in rows}
    assert set(first) == set(choices), "every choice point needs an initial label"
    levels = {first[i][1] for i in first}
    assert levels == {"full", "short"}
    for cid, c in choices.items():
        assert first[cid][1] == expected_detail(c), (c.tick, c.self_label, c.action)


def test_AC1_each_choice_is_labelled_before_the_next_game_hour_ends(judged):
    db = judged.db
    choices = {c.id: c for c in db.choice_details()}
    con = sqlite3.connect(db.path)
    rows = con.execute(
        "SELECT choice_point_id, tick FROM judge_labels "
        "WHERE json_extract(details_json, '$.key') LIKE '%/initial'"
    ).fetchall()
    con.close()
    assert rows
    for cid, tick in rows:
        assert 0 <= tick - choices[cid].tick < 60, (choices[cid].tick, tick)


def test_AC1_the_choice_points_tab_shows_the_judge_label(judged):
    judged.flush()
    frame = frame_from_world(judged)
    obs = make_obs(CFG, judged.db, memory_controls(CFG))
    obs.draw(frame, 0.0)
    rows = lines(obs.tab_text("Choice points"))
    assert len(rows) >= 3
    shown = [r for r in rows if re.search(r"judge \((full|short)\): ", r)]
    assert len(shown) == len(rows), rows
    assert any("judge (full): " in r for r in rows) and any("judge (short): " in r for r in rows)
    assert not any("judge: pending" in r for r in rows)


def test_AC1_the_tab_words_for_a_hand_made_label(tmp_path):
    db = RunDB.create(tmp_path / "run.db")
    db.insert_choice_point(
        ChoicePointRecord(
            decision_key="d1", tick=495, player_id="player_1", situation="Hungry", x=50.0,
            feeling="ok", tier="slow", thought="hmm", action={"kind": "rest", "minutes": 5},
            self_label={"served": ["honesty"], "violated": [], "direction": "toward"},
        )
    )  # fmt: skip
    label = {
        "served": ["family", "honesty"], "violated": ["loyalty"], "direction": "against",
        "harm": False, "promise": "none", "betrayal": False, "superstition": False,
        "new_belief": "", "rationale": "he left them", "evidence": ["left"],
    }  # fmt: skip
    db.insert_judge_label(1, 500, None, "full", label, {"key": "k/1"})
    obs = make_obs(CFG, db, memory_controls(CFG))
    import dataclasses

    from ai_island.sim import Simulation

    base = frame_from_world(Simulation.new(CFG, 1, players="none"))
    obs.draw(dataclasses.replace(base, names=(("player_1", "Ana"),)), 0.0)
    row = lines(obs.tab_text("Choice points"))[0]
    assert re.search(r"judge \(full\): served Family, Honesty; broke Loyalty; against", row), row
    db.insert_judge_label(
        1, 510, None, "full", {"status": "failed", "reason": "format"}, {"key": "k/2"}
    )
    obs.draw(dataclasses.replace(base, names=(("player_1", "Ana"),)), 0.0)
    assert "judge: failed" in lines(obs.tab_text("Choice points"))[0]
    db.close()


def _choice(**kw) -> ChoiceDetail:
    base = dict(
        id=1, tick=100, player_id="player_1", situation="Hungry", x=50.0, feeling="ok",
        tier="slow", thought="hmm", noticer_read=None, advisor_said=None, advisor_followed=None,
        action={"kind": "gather", "resource": "berries"}, self_label={
            "served": ["family"], "violated": [], "direction": "toward"},
        outcome=None, insight=None, ai_call_id=None, details={"decision_key": "k1"},
    )  # fmt: skip
    base.update(kw)
    return ChoiceDetail(**base)


def test_AC1_judge_detail_examples():
    assert judge_detail(_choice(), set()) == "short"
    steal = _choice(action={"kind": "steal", "target": "player_2"})
    assert judge_detail(steal, set()) == "full"
    assert judge_detail(_choice(action={"kind": "promise"}), set()) == "full"
    against = _choice(self_label={"served": [], "violated": [], "direction": "against"})
    assert judge_detail(against, set()) == "full"
    assert judge_detail(_choice(), {"k1"}) == "full"  # a mistake was flagged for it
    opt = {"action": {"kind": "rest"}, "serves": [], "violates": ["honesty"], "feel_now": 0}
    assert judge_detail(_choice(details={"decision_key": "k1", "options": [opt]}), set()) == "full"


def test_AC1_blind_packet_hides_the_self_label_ids_and_company_names():
    choice = _choice(
        thought="Claude from Anthropic told me to share with player_2",
        self_label={"served": ["family"], "violated": ["SELFLABELMARK"], "direction": "toward"},
        details={
            "decision_key": "k1",
            "options": [
                {"action": {"kind": "rest"}, "serves": ["SERVESMARK"], "violates": [],
                 "feel_now": 1, "feel_later": 2}
            ],
        },
    )  # fmt: skip
    packet = blind_packet(choice, {"player_1": "Ana", "player_2": "Ben"}, [])
    text = json.dumps(packet)
    assert "Ana" in text
    for hidden in ("player_1", "player_2", "SELFLABELMARK", "SERVESMARK", "self_label"):
        assert hidden not in text, hidden
    assert not blind_problems(text, forbidden_words())


def test_AC1_blind_problems_uses_word_boundaries_and_ignores_case():
    assert blind_problems("I asked CLAUDE about it", ["Claude"])
    assert not blind_problems("Claudette waved", ["Claude"])
    assert not blind_problems("a plain sentence", forbidden_words())


# ------------------------------------------------------------------------------- AC-2


def test_AC2_a_two_day_run_has_two_daily_summaries(judged):
    rows = judged.db.judge_summaries(kind="daily_summary")
    assert sorted(r.period for r in rows) == [1, 2]
    assert all(r.text.strip() for r in rows)
    assert not any(r.period == 0 for r in judged.db.judge_summaries())


@pytest.mark.slow
def test_AC2_a_game_week_has_one_profile_per_player():
    root, tick = shared_week()
    db = RunDB.open(root / "run.db")
    try:
        profiles = db.judge_summaries(kind="weekly_profile")
        assert sorted(p.player_id for p in profiles) == [f"player_{i}" for i in range(1, 5)]
        assert all(p.period == 1 and p.text.strip() for p in profiles)
        days = db.judge_summaries(kind="daily_summary")
        assert sorted(d.period for d in days) == list(range(1, 8))
    finally:
        db.close()


def test_AC2_deaths_broken_promises_and_new_beliefs_are_flagged():
    db = RunDB.memory()
    db.append_events(
        [
            Event(tick=10, payload=PromiseMade(id=1, maker="player_1", to="player_2", kind="help")),
            Event(tick=50, payload=PromiseBroken(id=1, maker="player_1", to="player_2")),
            Event(tick=60, payload=Died(player="player_3", cause="hunger", x=1, y=1)),
            Event(
                tick=70,
                payload=ReflectionCompleted(
                    player="player_4", week=1, changes={}, invented="Quiet Hours"
                ),
            ),
            Event(tick=2000, payload=Died(player="player_2", cause="cold", x=1, y=1)),
        ]
    )
    day1 = day_flags(db, 1, 1440)
    kinds = {f.kind for f in day1}
    assert {"betrayal", "death", "new_belief"} <= kinds
    assert [f for f in day1 if f.kind == "death"][0].player == "player_3"
    assert [f for f in day1 if f.kind == "betrayal"][0].player == "player_1"
    assert "player_2" in [f for f in day1 if f.kind == "betrayal"][0].others
    assert [f.player for f in day_flags(db, 2, 1440) if f.kind == "death"] == ["player_2"]
    db.close()


def test_AC2_a_harm_against_someone_promised_is_a_betrayal_and_labels_add_flags():
    db = RunDB.memory()
    db.append_events(
        [
            Event(tick=10, payload=PromiseMade(id=1, maker="player_1", to="player_2", kind="help")),
            Event(
                tick=20,
                payload=Harm(id=2, kind="steal", actor="player_1", victim="player_2", x=1, y=1),
            ),
        ]
    )
    db.insert_choice_point(
        ChoicePointRecord(
            decision_key="d1", tick=30, player_id="player_3", situation="s", x=50.0,
            feeling="ok", tier="slow", thought="t", action={"kind": "rest", "minutes": 5},
            self_label={"served": [], "violated": [], "direction": "toward"},
        )
    )  # fmt: skip
    label = {
        "served": [], "violated": ["honesty"], "direction": "against", "harm": False,
        "promise": "none", "betrayal": True, "superstition": True, "new_belief": "the lake listens",
        "rationale": "r", "evidence": ["e"],
    }  # fmt: skip
    db.insert_judge_label(1, 35, None, "full", label, {"key": "k/1"})
    kinds = {(f.kind, f.player) for f in day_flags(db, 1, 1440)}
    assert ("betrayal", "player_1") in kinds
    assert ("betrayal", "player_3") in kinds
    assert ("new_belief", "player_3") in kinds
    assert ("superstition", "player_3") in kinds
    db.close()
