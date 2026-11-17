"""Phase 3.5 AC-1, AC-2 and the data half of AC-3: activity, village guide, activity tables.

Written from the Plan's acceptance criteria and Contract only.
"""

from __future__ import annotations

import re
import shutil

import pytest
from conftest import ROOT
from p2_helpers import act, add_structure, example, make_cfg, teleport

from ai_island.config import ConfigError, load_config
from ai_island.rng import Streams
from ai_island.rules.actions import ActionRequest
from ai_island.sim import Simulation
from ai_island.world.agents import ACTION_KINDS, JOBS, ActiveAction
from ai_island.world.engine import advance_to
from ai_island.world.view import ACTIVITY_KINDS, VillageEntry, frame_from_world

CFG = make_cfg()
BAL = CFG.balance
P1, P2 = "player_1", "player_2"


def wrap(world) -> Simulation:
    """A Simulation around an example world (no turn handler, as the Phase 2 tests)."""
    sim = Simulation(CFG, 1, Streams(1), world)
    world.turn_handler = None
    return sim


def fed_world():
    w = example(CFG)
    for p in w.players.values():
        p.body.hunger = p.body.thirst = p.body.cold = p.body.fatigue = 0.0
    return w


def agent(frame, ident):
    for a in (*frame.players, *frame.villagers):
        if a.id == ident:
            return a
    raise AssertionError(f"{ident} not in frame")


def detached(world, **kw):
    """Put a hand-built ActiveAction on player_1 and return its AgentView."""
    req = ActionRequest(**kw.pop("request"))
    p = world.players[P1]
    p.action = ActiveAction(
        id=1,
        request=req,
        start_tick=kw.pop("start_tick", world.tick),
        work_done=kw.pop("work_done", 0.0),
        route=kw.pop("route", []),
        route_index=kw.pop("route_index", 0),
        status=kw.pop("status", "working"),
        data=kw.pop("data", {}),
    )
    return agent(frame_from_world(wrap(world)), P1)


# ------------------------------------------------------------------ AC-1


def test_AC1_activity_kinds_is_the_derived_union_of_42():
    assert ACTIVITY_KINDS == tuple(sorted(set(ACTION_KINDS) | set(JOBS) | {"idle", "sleeping"}))
    assert len(ACTIVITY_KINDS) == 42


def test_AC1_every_player_and_villager_has_an_activity_in_a_real_run():
    sim = Simulation.new(CFG, 1, players="dummy")
    seen: set[str] = set()
    for _ in range(8):
        sim.run(120)
        frame = frame_from_world(sim)
        assert len(frame.players) == 4 and len(frame.villagers) >= 12
        for a in (*frame.players, *frame.villagers):
            assert a.activity in ACTIVITY_KINDS, a
            assert isinstance(a.activity_target, str)
            assert not re.fullmatch(r"[\d\s,()\[\]]+", a.activity_target) or a.activity_target == ""
            assert 0.0 <= a.activity_progress <= 1.0
            seen.add(a.activity)
    assert len(seen) >= 3, seen


def test_AC1_player_gathering_wood_shows_gather_wood_with_progress_rising_to_one():
    w = fed_world()
    sim = wrap(w)
    assert act(w, P1, kind="gather", item="wood", x=11, y=5)
    frames = [agent(frame_from_world(sim), P1)]
    for _ in range(1500):
        if w.players[P1].action is None:
            break
        advance_to(w, w.tick + 1)
        if w.players[P1].action is not None:
            frames.append(agent(frame_from_world(sim), P1))
    assert len(frames) >= 3
    assert all(f.activity == "gather" for f in frames)
    assert frames[-1].activity_target == "wood"
    assert frames[0].activity_progress <= 0.1
    prog = [f.activity_progress for f in frames]
    assert prog == sorted(prog), "progress must never decrease while the same action works"
    assert prog[-1] >= 0.9 and max(prog) <= 1.0
    assert prog[-1] > prog[0]


def test_AC1_want_got_worked_example_wood_yield_4_want_8():
    assert BAL.actions.gather_yield["wood"] == 4
    expect = [(0.0, 0.0), (5.0, 0.25), (10.0, 0.5)]
    for work_done, want_progress in expect:
        w = fed_world()
        a = detached(
            w,
            request={"kind": "gather", "item": None, "x": 11, "y": 5},
            work_done=work_done,
            data={"item": "wood", "want": 8, "got": 0, "need": 10},
        )
        assert a.activity == "gather" and a.activity_target == "wood"
        assert a.activity_progress == pytest.approx(want_progress)
    w = fed_world()
    a = detached(
        w,
        request={"kind": "gather", "item": None, "x": 11, "y": 5},
        work_done=10.0,
        data={"item": "wood", "want": 8, "got": 4, "need": 10},
    )
    assert a.activity_progress == pytest.approx(1.0)


def test_AC1_walking_counts_as_zero_and_move_uses_the_route():
    w = fed_world()
    a = detached(
        w,
        request={"kind": "gather", "item": "wood", "x": 11, "y": 5},
        status="walking",
        data={"item": "wood", "want": 8, "got": 0, "need": 10},
    )
    assert a.activity_progress == 0.0
    w = fed_world()
    route = [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1)]
    a = detached(
        w,
        request={"kind": "move", "x": 5, "y": 1},
        status="walking",
        route=route,
        route_index=2,
    )
    assert a.activity == "move"
    assert a.activity_progress == pytest.approx(0.5)


def test_AC1_target_examples_gift_to_a_named_player_and_build_a_house():
    w = fed_world()
    w.players[P2].name = "Ben"
    a = detached(w, request={"kind": "gift", "target": P2}, data={})
    assert (a.activity, a.activity_target) == ("gift", "Ben")
    w = fed_world()
    house = add_structure(w, "house", 12, 12, P1, complete=False)
    a = detached(
        w,
        request={"kind": "build", "structure": "house", "x": 12, "y": 12},
        data={"structure": house.id, "need": 10},
    )
    assert (a.activity, a.activity_target) == ("build", "house")
    assert not a.activity_target.isdigit()


def test_AC1_build_progress_is_structure_progress_over_work_minutes():
    w = fed_world()
    house = add_structure(w, "house", 12, 12, P1, complete=False)
    house.progress = BAL.buildings.work_minutes["house"] / 4
    a = detached(
        w,
        request={"kind": "build", "structure": "house", "x": 12, "y": 12},
        data={"structure": house.id, "need": 10},
    )
    assert a.activity_progress == pytest.approx(0.25)


def test_AC1_player_without_action_is_idle_or_sleeping():
    w = fed_world()
    p = w.players[P1]
    p.action = None
    p.sleeping = False
    a = agent(frame_from_world(wrap(w)), P1)
    assert (a.activity, a.activity_target, a.activity_progress) == ("idle", "", 0.0)
    p.sleeping = True
    a = agent(frame_from_world(wrap(w)), P1)
    assert (a.activity, a.activity_target, a.activity_progress) == ("sleeping", "", 0.0)


def test_AC1_villagers_show_job_or_idle_by_day_and_sleeping_at_night():
    w = fed_world()
    sim = wrap(w)
    advance_to(w, 12 * 60)
    day = frame_from_world(sim)
    assert not day.is_night
    for v in day.villagers:
        assert v.activity == (v.job or "idle"), v
        assert v.activity_target == "" and v.activity_progress == 0.0
    guard = next(v for v in w.villagers.values() if v.leader == P1)
    guard.job = "guard"
    assert agent(frame_from_world(sim), guard.id).activity == "guard"
    for _ in range(40):
        if frame_from_world(sim).is_night:
            break
        advance_to(w, w.tick + 60)
    night = frame_from_world(sim)
    assert night.is_night
    assert night.villagers and all(v.activity == "sleeping" for v in night.villagers)


# ------------------------------------------------------------------ AC-2


def _expected_guide(w):
    alive = sorted((v for v in w.villagers.values() if v.alive), key=lambda v: v.id)
    out = []
    for pid, p in sorted(w.players.items()):
        out.append((pid, p.name, p.index, tuple((v.id, v.name) for v in alive if v.leader == pid)))
    out.append(("", "Wanderers", 0, tuple((v.id, v.name) for v in alive if v.leader is None)))
    return out


def _guide_tuples(frame):
    return [(e.leader_id, e.leader_name, e.color_index, e.members) for e in frame.village_guide]


def test_AC2_village_guide_lists_every_player_and_the_wanderers():
    w = example(CFG)
    frame = frame_from_world(wrap(w))
    assert all(isinstance(e, VillageEntry) for e in frame.village_guide)
    assert _guide_tuples(frame) == _expected_guide(w)
    assert [e.leader_id for e in frame.village_guide][-1] == ""
    assert frame.village_guide[-1].leader_name == "Wanderers"
    ids = [e.leader_id for e in frame.village_guide[:-1]]
    assert ids == sorted(w.players)
    total = sum(len(e.members) for e in frame.village_guide)
    assert total == sum(1 for v in w.villagers.values() if v.alive)


def test_AC2_real_run_guide_matches_the_world():
    sim = Simulation.new(CFG, 1, players="dummy")
    sim.run(600)
    assert _guide_tuples(frame_from_world(sim)) == _expected_guide(sim.world)
    assert len(frame_from_world(sim).village_guide[-1].members) > 0


def test_AC2_dead_villagers_are_not_listed():
    w = example(CFG)
    v = next(v for v in w.villagers.values() if v.leader == P1)
    v.alive = False
    frame = frame_from_world(wrap(w))
    assert v.id not in {m for e in frame.village_guide for m, _n in e.members}
    assert _guide_tuples(frame) == _expected_guide(w)


def test_AC2_after_a_poach_the_villager_is_in_the_new_village_next_frame():
    w = fed_world()
    sim = wrap(w)
    v = next(v for v in sorted(w.villagers.values(), key=lambda q: q.id) if v.leader == P2)
    before = frame_from_world(sim)
    assert v.id in {m for m, _n in before.village_guide[1].members}
    v.loyalty = (BAL.villagers.leave_below + BAL.villagers.poach_loyalty) / 2
    done = False
    for _ in range(8):
        teleport(w, P1, v.x - 1, v.y)
        act(w, P1, kind="poach", target=v.id)
        for _ in range(1500):
            if w.players[P1].action is None:
                break
            advance_to(w, w.tick + 1)
        if v.leader == P1:
            done = True
            break
    assert done, "the poach never succeeded in 8 tries"
    after = frame_from_world(sim)
    members = {e.leader_id: {m for m, _n in e.members} for e in after.village_guide}
    assert v.id in members[P1] and v.id not in members[P2]
    assert _guide_tuples(after) == _expected_guide(w)


def test_AC2_after_a_villager_leaves_it_is_listed_in_its_new_place():
    w = example(CFG)
    sim = wrap(w)
    v = next(v for v in sorted(w.villagers.values(), key=lambda q: q.id) if v.leader == P2)
    v.loyalty = BAL.villagers.leave_below + 1
    v.job = None
    interval = BAL.body.interval_ticks
    from ai_island.rules import body

    for _ in range(int(3 * CFG.world.clock.ticks_per_day / interval)):
        v.body.hunger = v.body.thirst = 80.0
        v.body.health = 100.0
        body.update_bodies(w, w.tick + interval)
        w.tick += interval
    assert v.leader != P2
    frame = frame_from_world(sim)
    members = {e.leader_id: {m for m, _n in e.members} for e in frame.village_guide}
    where = v.leader or ""
    assert v.id in members[where]
    assert sum(v.id in m for m in members.values()) == 1
    assert _guide_tuples(frame) == _expected_guide(w)


def test_AC2_a_villager_with_no_leader_is_under_wanderers():
    w = example(CFG)
    v = next(v for v in sorted(w.villagers.values(), key=lambda q: q.id) if v.leader == P1)
    v.leader = None
    frame = frame_from_world(wrap(w))
    assert v.id in {m for m, _n in frame.village_guide[-1].members}
    assert v.id not in {m for m, _n in frame.village_guide[0].members}


# ------------------------------------------------------------------ AC-3 (config half)


def _config_copy(tmp_path):
    dst = tmp_path / "config"
    shutil.copytree(ROOT / "config", dst)
    return dst


def _edit_assets(dst, fn):
    path = dst / "assets.toml"
    text = path.read_text(encoding="utf-8-sig")
    new = fn(text)
    assert new != text
    path.write_bytes(new.encode("utf-8"))


def test_AC3_activity_icons_has_an_entry_for_every_activity_kind():
    assets = CFG.assets
    assert set(assets.activity_icons) == set(ACTIVITY_KINDS)
    for kind, value in assets.activity_icons.items():
        assert value == "word" or value in assets.items, (kind, value)
        if value == "word":
            word = assets.activity_words[kind]
            assert 0 < len(word) <= 10
    assert set(assets.activity_words) == {
        k for k, v in assets.activity_icons.items() if v == "word"
    }
    assert assets.activity_words["pray"] == "Praying"
    assert assets.activity_words["guard"] == "Guarding"
    assert assets.activity_words["idle"] == "Idle"
    assert assets.activity_words["sleeping"] == "Sleeping"
    assert assets.activity_icons["gather"] == "item_wood"
    assert assets.activity_icons["fish"] == "tool_fishing_rod"
    assert assets.activity_icons["drink"] == "item_water"
    assert assets.activity_icons["eat"] == "item_cooked_meat"
    assert assets.colors.flash.lower() == "#ffd23f"
    assert assets.colors.wanderer.lower() == "#cfc6b8"


def test_AC3_a_missing_activity_icon_fails_at_load_naming_file_and_key(tmp_path):
    dst = _config_copy(tmp_path)
    _edit_assets(dst, lambda t: re.sub(r'(?m)^gather\s*=\s*"item_wood".*\n', "", t))
    with pytest.raises(ConfigError) as err:
        load_config(dst)
    msg = str(err.value)
    assert "assets.toml" in msg and "activity_icons.gather" in msg


@pytest.mark.parametrize(
    ("edit", "key"),
    [
        (lambda t: t.replace('fish = "tool_fishing_rod"', 'fish = "no_such_item"'), "fish"),
        (
            lambda t: t.replace(
                "\n[activity_words]\n", '\nbogus_kind = "word"\n[activity_words]\n'
            ),
            "bogus_kind",
        ),
        (lambda t: t.replace('pray = "Praying"', 'pray = "Praying for a long time"'), "pray"),
        (lambda t: re.sub(r'(?m)^pray = "Praying".*\n', "", t), "pray"),
    ],
)
def test_AC3_other_bad_activity_entries_fail_naming_the_file(tmp_path, edit, key):
    dst = _config_copy(tmp_path)
    _edit_assets(dst, edit)
    with pytest.raises(ConfigError) as err:
        load_config(dst)
    assert "assets.toml" in str(err.value)
    assert key in str(err.value)
