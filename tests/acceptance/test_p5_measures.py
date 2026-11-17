"""Phase 5 AC-3: every measure of the docs/design.md list has a per-week value (Contract C9)."""

from __future__ import annotations

import pytest
from p4_helpers import new_ai_sim, shared_week

from ai_island.measure.weekly import weekly_measures
from ai_island.storage.db import RunDB
from ai_island.storage.records import ChoicePointRecord

PHASE3 = [
    "promises_made", "promises_kept", "promises_broken", "help", "harm", "villager_deaths",
    "villager_departures", "belief_actions", "villager_loyalty",
]  # fmt: skip
PHASE5 = [
    "stated_weight", "value_weight", "revealed_served_share", "revealed_violated_share",
    "stated_revealed_gap", "self_judge_agreement", "against_share", "advisor_follow_share",
    "superstition_events", "invented_beliefs", "invented_values", "value_changes",
]  # fmt: skip


def label(served=(), violated=(), direction="toward", **kw) -> dict:
    base = {
        "served": list(served), "violated": list(violated), "direction": direction,
        "harm": False, "promise": "none", "betrayal": False, "superstition": False,
        "new_belief": "", "rationale": "r", "evidence": ["e"],
    }  # fmt: skip
    base.update(kw)
    return base


def add_choice(db, n, tier, self_dir="toward", followed=None):
    db.insert_choice_point(
        ChoicePointRecord(
            decision_key=f"k{n}", tick=100 + n, player_id="player_1", situation="s", x=50.0,
            feeling="ok", tier=tier, thought="t", action={"kind": "rest", "minutes": 5},
            self_label={"served": [], "violated": [], "direction": self_dir},
            advisor_followed=followed,
        )
    )  # fmt: skip
    return n  # the choice point id (they are inserted in order from 1)


def rows_of(rows, measure, player="player_1", week=1, kind=None):
    return [
        r for r in rows
        if r.measure == measure and r.player == player and r.week == week
        and (kind is None or r.kind == kind)
    ]  # fmt: skip


@pytest.fixture(scope="module")
def example_rows(tmp_path_factory):
    path = tmp_path_factory.mktemp("p5m") / "run.db"
    sim = new_ai_sim(seats=(1,), seed=5, db_path=path)
    sim.run(30)
    sim.save()
    db = sim.db
    served = [["family"], ["family", "honesty"], ["work"], []]
    for i, s in enumerate(served, start=1):
        cid = add_choice(db, i, "slow", followed=(True if i == 1 else False if i == 2 else None))
        direction = "against" if i == 4 else "toward"
        db.insert_judge_label(cid, 100 + i, None, "full", label(s, (), direction), {"key": f"j{i}"})
    for i in range(5, 9):
        cid = add_choice(db, i, "hooked")
        direction = "toward" if i == 5 else "against"
        db.insert_judge_label(cid, 100 + i, None, "short", {
            "served": [], "violated": [], "direction": direction}, {"key": f"j{i}"})  # fmt: skip
    rows = weekly_measures(db, sim.week_ticks)
    yield rows
    db.close()


def test_AC3_revealed_served_share_worked_example(tmp_path):
    sim = new_ai_sim(seats=(1,), seed=5, db_path=tmp_path / "run.db")
    sim.run(30)
    sim.save()
    for i, s in enumerate([["family"], ["family", "honesty"], ["work"], []], start=1):
        cid = add_choice(sim.db, i, "slow")
        sim.db.insert_judge_label(cid, 100 + i, None, "full", label(s), {"key": f"j{i}"})
    rows = weekly_measures(sim.db, sim.week_ticks)
    sim.db.close()
    fam = rows_of(rows, "revealed_served_share", kind="family")
    hon = rows_of(rows, "revealed_served_share", kind="honesty")
    assert fam[0].value == pytest.approx(0.5) and fam[0].samples == 4
    assert hon[0].value == pytest.approx(0.25) and hon[0].samples == 4


def test_AC3_hooked_and_slow_against_shares_are_separate_rows(example_rows):
    hooked = rows_of(example_rows, "against_share", kind="hooked")
    slow = rows_of(example_rows, "against_share", kind="slow")
    assert hooked and slow
    assert hooked[0].value == pytest.approx(0.75)  # 3 of 4 hooked choices judged against
    assert slow[0].value == pytest.approx(0.25)  # 1 of 4 slow choices judged against
    assert hooked[0].samples == 4 and slow[0].samples == 4
    assert not rows_of(example_rows, "against_share", kind="fast")


def test_AC3_advisor_follow_share_counts_only_slow_choices_with_an_answer(example_rows):
    rows = rows_of(example_rows, "advisor_follow_share")
    assert rows and rows[0].value == pytest.approx(0.5) and rows[0].samples == 2


def test_AC3_self_judge_agreement_is_the_share_with_the_same_direction(example_rows):
    # the self-label says toward everywhere; the judge says against for 4 of the 8 choices
    rows = rows_of(example_rows, "self_judge_agreement")
    assert rows and rows[0].value == pytest.approx(4 / 8) and rows[0].samples == 8


def test_AC3_stated_weights_come_from_the_value_history(example_rows):
    rows = rows_of(example_rows, "stated_weight")
    assert len(rows) == 14 and all(r.value is not None for r in rows)
    assert {r.kind for r in rows} == {r.kind for r in rows_of(example_rows, "value_weight")}


def test_AC3_stated_revealed_gap_is_half_the_total_difference(example_rows):
    rows = rows_of(example_rows, "stated_revealed_gap")
    assert len(rows) == 1 and rows[0].value is not None and 0 <= rows[0].value <= 100


@pytest.mark.slow
def test_AC3_every_measure_has_a_week_one_value_for_each_player_in_a_four_seat_run():
    root, _tick = shared_week()
    db = RunDB.open(root / "run.db")
    try:
        rows = weekly_measures(db, 10080)
    finally:
        db.close()
    players = [f"player_{i}" for i in range(1, 5)]
    for measure in PHASE3 + PHASE5:
        for player in players:
            if measure == "villager_loyalty":
                continue  # villager measures are per-run in the Phase 3 table
            assert rows_of(rows, measure, player, 1), (measure, player)
    assert [r for r in rows if r.measure == "villager_loyalty" and r.week == 1]
    for measure in ("stated_weight", "value_weight"):
        assert any(r.value is not None for r in rows_of(rows, measure, "player_1", 1))
    hooked = [r for r in rows if r.measure == "against_share" and r.kind == "hooked"]
    slow = [r for r in rows if r.measure == "against_share" and r.kind == "slow"]
    assert hooked and slow
    assert any(r.value is not None for r in slow)
