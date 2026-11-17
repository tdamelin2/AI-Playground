"""Phase 2 AC-7..AC-10: villagers."""

from __future__ import annotations

from conftest import cfg  # noqa: F401
from p2_helpers import act, evs, example, make_cfg, run, teleport

from ai_island.rules import body, wellbeing
from ai_island.sim import Simulation
from ai_island.world.agents import HarmRecord

CFG = make_cfg()
BAL = CFG.balance
DAY = CFG.world.clock.ticks_per_day


def zero_body(v):
    b = v.body
    b.hunger = b.thirst = b.cold = b.fatigue = b.pain = 0.0
    b.health = 100.0


def mine(w, pid="player_1"):
    return [v for v in sorted(w.villagers.values(), key=lambda q: q.id) if v.leader == pid]


def step_days(w, days, per_step=None):
    interval = BAL.body.interval_ticks
    for _ in range(int(days * DAY / interval)):
        if per_step:
            per_step(w)
        body.update_bodies(w, w.tick + interval)
        w.tick += interval


# ----------------------------------------------------------------------------------- AC-7


def test_AC7_start_with_three_villagers_each_and_never_more_than_fifty():
    sim = Simulation.new(CFG, 1, "dummy")
    w = sim.world
    for pid in w.players:
        assert len(mine(w, pid)) == 3
    assert len(w.villagers) == 50
    assert sum(1 for v in w.villagers.values() if v.leader is None) == 38
    sim.run(3 * DAY)
    assert len(w.villagers) <= 50
    ids = {v.id for v in w.villagers.values()}
    assert len(ids) == len(w.villagers)


def test_AC7_example_world_has_no_births():
    w = example(CFG)
    n = len(w.villagers)
    run(w, 3 * DAY)
    assert len(w.villagers) <= n


# ----------------------------------------------------------------------------------- AC-8


def test_AC8_loyalty_starts_at_70():
    w = Simulation.new(CFG, 1, "none").world  # controller none has no people; use the example map
    w = example(CFG)
    assert all(v.loyalty == BAL.villagers.start_loyalty == 70 for v in mine(w))


def test_AC8_loyalty_rises_when_fed_and_falls_when_neglected():
    w = example(CFG)
    fed, starved = mine(w, "player_1")[0], mine(w, "player_2")[0]
    for v in (fed, starved):
        v.loyalty = 60.0
        v.job = None

    def keep(w):
        zero_body(fed)
        starved.body.hunger = 90.0
        starved.body.thirst = 90.0
        starved.body.health = 100.0

    step_days(w, 1, keep)
    assert fed.loyalty > 60.0
    assert starved.loyalty < 60.0 or starved.leader != "player_2"


def test_AC8_neglected_villager_leaves_below_threshold_to_another_player_or_wanders():
    w = example(CFG)
    v = mine(w, "player_2")[0]
    v.loyalty = BAL.villagers.leave_below + 1
    v.job = None

    def keep(w):
        v.body.hunger = v.body.thirst = 80.0
        v.body.health = 100.0

    step_days(w, 3, keep)
    left = evs(w, "villager_left", villager=v.id)
    assert left, "villager must leave when loyalty falls below the threshold"
    assert v.leader != "player_2"
    assert left[0].payload.to is None or left[0].payload.to in w.players


def test_AC8_bond_and_loyalty_change_independently():
    w = example(CFG)
    v = mine(w, "player_1")[0]
    v.bond["player_2"] = 33.0
    v.loyalty = 90.0
    v.bond["player_1"] = 10.0
    zero_body(v)
    v.body.hunger = 90.0
    step_days(w, 0.5, lambda w: setattr(v.body, "hunger", 90.0))
    assert v.loyalty != 90.0
    assert v.bond["player_2"] == 33.0, "a third player's bond is untouched by neglect"
    # raising bond without touching loyalty
    l_before = v.loyalty
    v.bond["player_1"] = 95.0
    assert v.loyalty == l_before


def test_AC8_death_lowers_leader_x_more_with_higher_bond():
    drops = []
    for bond in (0.0, 100.0):
        w = example(CFG)
        v = mine(w, "player_1")[0]
        v.bond["player_1"] = bond
        p = w.players["player_1"]
        p.b = 0.0
        p.b_tick = w.tick
        before = wellbeing.x_of(w, "player_1", w.tick)
        body.kill_villager(w, v, "test", w.tick)
        after = wellbeing.x_of(w, "player_1", w.tick)
        drops.append(before - after)
        assert evs(w, "villager_died", villager=v.id)
    assert drops[1] > drops[0] > 0.0 or drops[1] > drops[0]


# ----------------------------------------------------------------------------------- AC-9


def output_after(level, days=2):
    w = example(CFG)
    for y in range(4, 8):  # plenty of trees so the output is not capped by local supply
        for x in range(3, 13):
            if w.terrain[y][x] == "grass":
                w.terrain[y][x] = "tree"
    w.trees_alive["home_0"] = 99
    p = w.players["player_1"]
    v = mine(w)[0]
    teleport(w, "player_1", 8, 8)
    assert act(w, "player_1", kind="assign_villager", target=v.id, job="gather", work_level=level)
    run(w, 5)

    def total():
        inv = [p.inventory, p.home_store]
        inv += [s.store for s in w.structures.values() if s.store is not None]
        return sum(i.total_items() for i in inv) + sum(vv.inventory.total_items() for vv in mine(w))

    start = total()
    for _ in range(days * DAY // 10):
        run(w, 10)
        for vv in mine(w):
            vv.body.hunger = vv.body.thirst = vv.body.cold = 0.0
    return total() - start, v, w


def test_AC9_hard_work_outproduces_normal_outproduces_light_and_costs_loyalty():
    light, vl, _ = output_after("light")
    normal, vn, _ = output_after("normal")
    hard, vh, _ = output_after("hard")
    assert hard > normal > light >= 0, (light, normal, hard)
    assert vh.loyalty < vn.loyalty
    assert vh.body.health < vn.body.health


# ----------------------------------------------------------------------------------- AC-10


def _gossip_world(harm_pos):
    w = example(CFG)
    a, b, *_ = mine(w, "player_1")
    teleport(w, "player_1", 8, 8)
    for v in mine(w, "player_1"):
        v.x = v.from_x = v.to_x = 8
        v.y = v.from_y = v.to_y = 8
    w.harm_log.append(HarmRecord(w.next("harm"), 0, "steal", "player_2", "player_1", *harm_pos))
    run(w, 3 * DAY // 2)
    return w, [e for e in evs(w, "chat_spoken") if e.payload.kind == "gossip"]


def test_AC10_gossip_comes_only_from_villagers_who_witnessed_something():
    w, gossip = _gossip_world((9, 8))  # right next to the villagers: they see it
    rec = w.harm_log[0]
    witnesses = set(rec.saw) | set(rec.heard)
    assert gossip, "villagers who saw the theft should be able to talk about it"
    for e in gossip:
        assert e.payload.speaker in witnesses, (
            "a villager that witnessed nothing has nothing to tell"
        )
        assert e.payload.speaker in w.villagers


def test_AC10_nobody_gossips_about_an_event_nobody_saw():
    w, gossip = _gossip_world((22, 22))  # far from every villager (sight is about 7 tiles)
    assert not gossip, "no villager witnessed anything, so none may gossip"


def test_AC10_a_villager_with_nothing_witnessed_never_gossips_in_a_full_run():
    sim = Simulation.new(CFG, 1, "dummy")
    sim.run(2 * DAY)
    w = sim.world
    for e in evs(w, "chat_spoken"):
        if e.payload.kind != "gossip":
            continue
        assert e.payload.speaker in w.villagers
        assert w.villagers[e.payload.speaker].witnessed
        assert not e.payload.speaker.startswith("animal")
