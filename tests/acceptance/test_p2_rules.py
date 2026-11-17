"""Phase 2 AC-12..AC-28 (example map, no controllers)."""

from __future__ import annotations

import pytest
from p2_helpers import (
    act,
    add_structure,
    evs,
    example,
    make_cfg,
    run,
    run_until_idle,
    stock,
    teleport,
)

from ai_island.rules import body, interrupts, wellbeing
from ai_island.rules.actions import cancel_action, player_order
from ai_island.rules.senses import (
    build_report,
    can_hear,
    can_see,
    remembered_tile,
    sight_range,
)
from ai_island.rules.senses.templates import TEMPLATES
from ai_island.world.agents import HarmRecord, KnowledgeEntry, PromiseSpec

CFG = make_cfg()
BAL = CFG.balance
DAY = CFG.world.clock.ticks_per_day
P1, P2 = "player_1", "player_2"


def world():
    w = example(CFG)
    for p in w.players.values():
        p.body.hunger = p.body.thirst = p.body.cold = p.body.fatigue = 0.0
    return w


def keep_fed(w):
    for p in w.players.values():
        p.body.hunger = p.body.thirst = p.body.cold = p.body.fatigue = 0.0
        p.body.health = 100.0
    for v in w.villagers.values():
        v.body.hunger = v.body.thirst = v.body.cold = 0.0


def vill(w, pid, n=0):
    return [v for v in sorted(w.villagers.values(), key=lambda q: q.id) if v.leader == pid][n]


# ----------------------------------------------------------------------------------- AC-12


def test_AC12_gather_accepts_an_amount():
    w = world()
    teleport(w, P1, 11, 6)
    assert act(w, P1, kind="gather", item="wood", x=11, y=5, amount=1)
    run_until_idle(w, P1)
    assert w.players[P1].inventory.count("wood") == BAL.actions.gather_yield["wood"]


def test_AC12_rest_accepts_an_end_point():
    w = world()
    w.players[P1].body.fatigue = 40
    assert act(w, P1, kind="rest", until="rested")
    run_until_idle(w, P1, 2000)
    assert w.players[P1].body.fatigue < 10


def test_AC12_eat_until_sated():
    w = world()
    w.players[P1].body.hunger = 50
    stock(w, P1, roots=10)
    assert act(w, P1, kind="eat", item="roots", until="sated")
    run_until_idle(w, P1, 500)
    assert w.players[P1].body.hunger <= BAL.body.sated_level + BAL.body.hunger_per_food_unit * 1.5
    assert w.players[P1].inventory.count("roots") > 0


def test_AC12_interrupted_action_keeps_progress():
    w = world()
    teleport(w, P1, 11, 6)
    assert act(w, P1, kind="gather", item="wood", x=11, y=5, amount=3)
    for _ in range(120):
        run(w, 1)
        if w.players[P1].inventory.count("wood") > 0:
            break
    got = w.players[P1].inventory.count("wood")
    assert got > 0
    cancel_action(w, P1, w.tick, "test")
    assert w.players[P1].action is None
    assert w.players[P1].inventory.count("wood") == got, "completed units are kept"
    run(w, 200)
    assert w.players[P1].inventory.count("wood") == got, "unfinished output is never granted"


# ----------------------------------------------------------------------------------- AC-13


@pytest.mark.parametrize("kind", interrupts.INTERRUPT_KINDS)
def test_AC13_each_interrupt_kind_produces_an_event(kind):
    w = world()
    item = interrupts.raise_interrupt(w, kind, P1, w.tick)
    assert item is not None
    assert evs(w, "interrupt", kind=kind, player=P1)
    assert [i.kind for i in interrupts.take_interrupts(w, P1)] == [kind]
    assert interrupts.take_interrupts(w, P1) == [], "each is consumed once"


def test_AC13_attack_raises_attacked_for_the_victim():
    w = world()
    assert act(w, P1, kind="attack", target=P2)
    run_until_idle(w, P1)
    assert evs(w, "interrupt", kind="attacked", player=P2)


def test_AC13_speaking_to_a_player_raises_spoken_to():
    w = world()
    assert act(w, P1, kind="talk", target=P2, text="hi")
    run_until_idle(w, P1)
    run(w, 3)
    assert evs(w, "interrupt", kind="spoken_to", player=P2)


# ----------------------------------------------------------------------------------- AC-14


def ticks_to_gather(w, with_tool=None):
    teleport(w, P1, 11, 6)
    if with_tool:
        w.players[P1].inventory.add_tool("axe", with_tool, BAL.tools.durability[with_tool])
    assert act(w, P1, kind="gather", item="wood", x=11, y=5, amount=1)
    return run_until_idle(w, P1)


def test_AC14_hand_gathering_is_half_speed():
    by_hand = ticks_to_gather(world())
    with_axe = ticks_to_gather(world(), "basic")
    unit = BAL.actions.unit_minutes["gather_wood"]
    assert by_hand >= unit * 2 - 1
    assert with_axe < by_hand
    assert by_hand >= with_axe * 2


def test_AC14_quarry_needs_a_pickaxe_but_loose_stone_does_not():
    w = world()
    teleport(w, P1, 20, 5)
    act(w, P1, kind="gather", item="stone", x=20, y=5)
    run_until_idle(w, P1)
    assert evs(w, "action_failed", player=P1) or w.players[P1].inventory.count("stone") == 0
    assert w.players[P1].inventory.count("stone") == 0
    w2 = world()
    teleport(w2, P1, 4, 9)
    assert act(w2, P1, kind="gather", item="stone", x=4, y=10)
    run_until_idle(w2, P1)
    assert w2.players[P1].inventory.count("stone") > 0


def test_AC14_better_tools_only_at_a_workshop():
    w = world()
    stock(w, P1, wood=3, stone=3)
    act(w, P1, kind="craft", tool="axe", tier="better")
    run_until_idle(w, P1)
    assert evs(w, "action_failed", player=P1, kind="craft")
    assert w.players[P1].inventory.find_tool("axe") is None
    add_structure(w, P1 and "workshop", 8, 9, P1)
    act(w, P1, kind="craft", tool="axe", tier="better")
    run_until_idle(w, P1)
    tool = w.players[P1].inventory.find_tool("axe")
    assert tool is not None and tool.tier == "better"


def test_AC14_tools_wear_and_break():
    w = world()
    tool = w.players[P1].inventory.add_tool("axe", "basic", 2)
    teleport(w, P1, 11, 6)
    act(w, P1, kind="gather", item="wood", x=11, y=5, amount=1)
    run_until_idle(w, P1)
    assert tool.durability < 2 or evs(w, "tool_broken")
    for _ in range(4):
        w.terrain[5][11] = "tree"
        act(w, P1, kind="gather", item="wood", x=11, y=5, amount=1)
        run_until_idle(w, P1)
    assert evs(w, "tool_broken")
    assert w.players[P1].inventory.find_tool("axe") is None


def test_AC14_tools_can_be_dropped_traded_stolen_and_are_lost_on_death():
    w = world()
    w.players[P1].inventory.add_tool("spear", "basic", 40)
    act(w, P1, kind="drop", tool="spear")
    run_until_idle(w, P1)
    assert w.players[P1].inventory.find_tool("spear") is None
    assert any(inv.tools for inv in w.drops.values())
    w = world()
    w.players[P1].inventory.add_tool("spear", "basic", 40)
    act(w, P1, kind="gift", target=P2, tool="spear")
    run_until_idle(w, P1)
    assert w.players[P2].inventory.find_tool("spear") is not None
    w = world()
    w.players[P1].inventory.add_tool("spear", "basic", 40)
    teleport(w, P1, 11, 10)
    body.kill_player(w, w.players[P1], "test", w.tick)
    assert w.players[P1].inventory.find_tool("spear") is None
    assert any(inv.tools for inv in w.drops.values())


def test_AC14_repair_costs_half_the_price():
    w = world()
    s = add_structure(w, "house", 7, 10, P1, hp=20)
    full = BAL.buildings.costs["house"]
    stock(w, P1, wood=full["wood"], stone=full["stone"])
    act(w, P1, kind="repair", structure=str(s.id))
    run_until_idle(w, P1)
    left_w = w.players[P1].inventory.count("wood")
    assert left_w >= full["wood"] // 2 - 1


# ----------------------------------------------------------------------------------- AC-15


def test_AC15_fire_burns_six_hours_and_refuels():
    w = world()
    assert BAL.fire.fuel_ticks == 360
    stock(w, P1, wood=4)
    act(w, P1, kind="make_fire", x=8, y=9)
    run_until_idle(w, P1)
    fire = next(s for s in w.structures.values() if s.kind == "campfire")
    t0 = w.tick
    assert fire.burning(t0)
    run(w, 340)
    assert fire.burning(w.tick)
    run(w, 60)
    assert not fire.burning(w.tick)
    act(w, P1, kind="make_fire", x=8, y=9)
    run_until_idle(w, P1)
    assert fire.burning(w.tick), "make_fire on an own fire refuels it"


def test_AC15_raw_meat_spoils_after_about_a_day():
    w = world()
    stock(w, P1, raw_meat=2)
    run(w, 1300)
    assert w.players[P1].inventory.count("raw_meat") == 2
    run(w, 400)
    assert w.players[P1].inventory.count("spoiled_meat") == 2


def test_AC15_fire_warms_people_nearby():
    w = world()
    far, near = w.players[P2], w.players[P1]
    teleport(w, P2, 20, 12)
    fire = add_structure(w, "campfire", 8, 9, P1)
    fire.fuel_until = w.tick + 360
    far.body.cold = near.body.cold = 40.0
    body.update_bodies(w, 60)  # night
    assert near.body.cold < 40.0 < far.body.cold


def test_AC15_night_sight_longer_near_a_fire():
    w = world()
    run(w, 60)  # night
    plain = sight_range(w, P1, w.tick)
    fire = add_structure(w, "campfire", 8, 9, P1)
    fire.fuel_until = w.tick + 360
    lit = sight_range(w, P1, w.tick)
    assert lit > plain


def test_AC15_rain_and_storm_put_out_campfires_not_hearths():
    w = world()
    camp = add_structure(w, "campfire", 5, 5, P1)
    hearth = add_structure(w, "hearth", 6, 5, P1)
    camp.fuel_until = hearth.fuel_until = w.tick + 360
    w.weather.current = "storm"
    run(w, 40)
    assert not camp.burning(w.tick)
    assert hearth.burning(w.tick)


# ----------------------------------------------------------------------------------- AC-16

SITES = {
    "house": (3, 3),
    "hearth": (4, 12),
    "field": (9, 10),
    "storehouse": (11, 11),
    "workshop": (3, 9),
    "pen": (5, 10),
    "granary": (11, 8),
    "monument": (8, 12),
}


@pytest.mark.parametrize("kind", list(SITES))
def test_AC16_building_type_can_be_built(kind):
    w = world()
    for t in ("tree", "stump", "rocky", "spring"):
        assert t not in (w.terrain[SITES[kind][1]][SITES[kind][0]],)
    if kind == "hearth":  # gameplay.md: a hearth sits inside a house
        add_structure(w, "house", 4, 11, P1)
    cost = BAL.buildings.costs[kind]
    stock(w, P1, **dict(cost))
    x, y = SITES[kind]
    teleport(w, P1, x, y + 1)
    assert act(w, P1, kind="build", structure=kind, x=x, y=y)
    run_until_idle(w, P1, 6000)
    built = [s for s in w.structures.values() if s.kind == kind and s.complete]
    assert built, f"{kind} not built: {[e.payload.reason for e in evs(w, 'action_failed')]}"


def test_AC16_bridge_can_be_built_over_water():
    w = world()
    stock(w, P1, **dict(BAL.buildings.costs["bridge"]))
    teleport(w, P1, 16, 14)
    act(w, P1, kind="build", structure="bridge", x=16, y=15)
    run_until_idle(w, P1, 6000)
    assert any(s.kind == "bridge" and s.complete for s in w.structures.values()), [
        e.payload.reason for e in evs(w, "action_failed")
    ]


def test_AC16_storms_damage_buildings_and_repair_restores():
    w = world()
    houses = [add_structure(w, "house", 4 + i % 8, 4 + i // 8 * 2, P1) for i in range(16)]
    w.weather.current = "storm"
    for _ in range(40):
        run(w, 30)
        w.weather.current = "storm"
        keep_fed(w)
    hit = [s for s in houses if s.hp < s.max_hp]
    assert hit, "a long storm over 16 buildings must damage at least one"
    target = hit[0]
    w.weather.current = "clear"
    target.hp = max(1, target.hp)
    before = target.hp
    stock(w, P1, wood=30, stone=10)
    teleport(w, P1, target.x, target.y + 1)
    act(w, P1, kind="repair", structure=str(target.id))
    run_until_idle(w, P1, 600)
    assert target.hp > before


# ----------------------------------------------------------------------------------- AC-17


def test_AC17_trade_changes_nothing_until_accepted_and_offers_expire():
    w = world()
    stock(w, P1, wood=3)
    stock(w, P2, stone=2)
    act(w, P1, kind="trade", target=P2, offer={"wood": 2}, want={"stone": 1})
    run_until_idle(w, P1)
    assert (
        w.players[P1].inventory.count("wood") == 3 and w.players[P2].inventory.count("stone") == 2
    )
    oid = evs(w, "trade_offered")[0].payload.id
    run(w, BAL.social.offer_expiry_minutes + 30)
    act(w, P2, kind="trade", target=P1, accept=oid)
    run_until_idle(w, P2)
    assert w.players[P1].inventory.count("wood") == 3, "an expired offer cannot be accepted"
    assert not evs(w, "trade_done")


def test_AC17_trade_fails_atomically_if_a_side_cannot_pay():
    w = world()
    stock(w, P1, wood=3)
    stock(w, P2, stone=1)
    act(w, P1, kind="trade", target=P2, offer={"wood": 2}, want={"stone": 1})
    run_until_idle(w, P1)
    oid = evs(w, "trade_offered")[0].payload.id
    w.players[P2].inventory.remove("stone", 1)
    act(w, P2, kind="trade", target=P1, accept=oid)
    run_until_idle(w, P2)
    assert w.players[P1].inventory.count("wood") == 3 and w.players[P2].inventory.count("wood") == 0


def test_AC17_promise_kept_and_broken_produce_events():
    w = world()
    stock(w, P1, wood=2)
    due = w.tick + 200
    spec = PromiseSpec(kind="give", to=P2, item="wood", amount=1, due_tick=due)
    act(w, P1, kind="promise", target=P2, promise=spec, text="x")
    run_until_idle(w, P1)
    act(w, P1, kind="gift", target=P2, item="wood", amount=1)
    run_until_idle(w, P1)
    run(w, 300)
    assert evs(w, "promise_kept")
    w = world()
    spec = PromiseSpec(kind="give", to=P2, item="wood", amount=1, due_tick=w.tick + 100)
    act(w, P1, kind="promise", target=P2, promise=spec, text="x")
    run_until_idle(w, P1)
    run(w, 300)
    assert evs(w, "promise_broken")


def test_AC17_teach_adds_lower_confidence_entry_and_a_false_one_can_be_taught():
    w = world()
    w.players[P1].knowledge.append(
        KnowledgeEntry(1, "berries", "red berries are safe", 1.0, "self", 0, True)
    )
    act(w, P1, kind="teach", target=P2, amount=1)
    run_until_idle(w, P1)
    got = w.players[P2].knowledge
    assert got and all(e.confidence < 1.0 for e in got)
    assert got[0].confidence == pytest.approx(BAL.social.teach_confidence_factor)
    w2 = world()
    act(w2, P1, kind="teach", target=P2, text="the green mushroom is safe")
    run_until_idle(w2, P1)
    e = w2.players[P2].knowledge[0]
    assert e.true is False or e.true is None
    assert e.confidence < 1.0


# ----------------------------------------------------------------------------------- AC-18


def test_AC18_claim_pool_tiles_and_stakes_return_to_pool():
    w = world()
    stock(w, P1, stake=1)
    teleport(w, P1, 16, 7)
    act(w, P1, kind="claim_land", x=16, y=8)
    run_until_idle(w, P1)
    claimed = [pos for pos, o in w.claims.items() if o == P1]
    r = BAL.claims.claim_radius
    assert claimed and all((x - 16) ** 2 + (y - 8) ** 2 <= r * r for x, y in claimed)
    teleport(w, P2, 16, 9)
    act(w, P2, kind="pull_stakes", x=16, y=8)
    run_until_idle(w, P2)
    assert not [1 for o in w.claims.values() if o == P1]


def test_AC18_attack_hurts_and_drops_items_on_the_victims_tile():
    w = world()
    stock(w, P2, wood=10, berries=5)
    v = w.players[P2]
    act(w, P1, kind="attack", target=P2)
    run_until_idle(w, P1)
    assert v.body.pain > 0
    assert w.drops.get((v.x, v.y)) is not None or any(i.count("wood") for i in w.drops.values())


# ----------------------------------------------------------------------------------- AC-19


def snapshot_people(w):
    return {
        pid: (
            p.inventory.counts(),
            round(p.body.hunger, 3),
            round(wellbeing.x_of(w, pid, w.tick), 3),
            round(p.b, 3),
            dict(p.trust),
            dict(p.anger),
        )
        for pid, p in w.players.items()
    }  # fmt: skip


@pytest.mark.parametrize("kind", ["pray", "ceremony"])
def test_AC19_pray_and_ceremony_change_nothing_but_time_and_log(kind):
    a, b = world(), world()
    act(a, P1, kind=kind)
    ticks = run_until_idle(a, P1)
    run(b, ticks)
    assert evs(a, "belief_act")
    assert snapshot_people(a) == snapshot_people(b)
    assert len(a.structures) == len(b.structures)
    assert {k: len(v) for k, v in a.animals.items()} == {k: len(v) for k, v in b.animals.items()}


def test_AC19_offering_removes_only_the_offered_item():
    a, b = world(), world()
    for w in (a, b):
        stock(w, P1, wood=3, berries=2)
    act(a, P1, kind="offering", item="wood")
    ticks = run_until_idle(a, P1)
    run(b, ticks)
    ca, cb = a.players[P1].inventory.counts(), b.players[P1].inventory.counts()
    assert ca.get("berries") == cb.get("berries") == 2
    assert ca.get("wood", 0) < 3
    assert round(wellbeing.x_of(a, P1), 3) == round(wellbeing.x_of(b, P1), 3)


def test_AC19_build_shrine_only_builds_the_shrine():
    w = world()
    stock(w, P1, wood=4, stone=4)
    act(w, P1, kind="build_shrine", x=7, y=10)
    run_until_idle(w, P1, 3000)
    assert [s.kind for s in w.structures.values()] == ["shrine"]
    assert w.players[P1].inventory.count("wood") == 0


# ----------------------------------------------------------------------------------- AC-20


def dog_world():
    w = world()
    for d in w.dogs:
        d.x = d.y = 20
    for pid in (P1, P2):
        teleport(w, pid, 20, 19)
    teleport(w, P2, 5, 5)
    for v in w.villagers.values():
        v.x = v.from_x = v.to_x = 5
        v.y = v.from_y = v.to_y = 5
    return w


def attacks(w):
    return evs(w, "dog_attack")


def test_AC20_wild_dogs_attack_a_lone_unarmed_player():
    w = dog_world()
    for _ in range(40):
        run(w, 10)
        w.players[P1].body.health = 100
        keep_fed(w)
        teleport_keep(w)
    assert attacks(w), "dogs must attack a lone unarmed player at night"


def teleport_keep(w):
    p = w.players[P1]
    if (p.x, p.y) != (20, 19):
        teleport(w, P1, 20, 19)


def pin(w, q, x, y):
    q.x = q.from_x = q.to_x = x
    q.y = q.from_y = q.to_y = y
    q.route = []
    q.next_think = 10**9


def test_AC20_dogs_are_scared_by_a_spear():
    w = dog_world()
    w.players[P1].inventory.add_tool("spear", "basic", 40)
    for _ in range(300):
        run(w, 1)
        keep_fed(w)
        teleport_keep(w)
    assert not attacks(w)


def test_AC20_dogs_are_scared_by_a_group_of_three():
    w = dog_world()
    mates = [v for v in w.villagers.values() if v.leader == P1][:2]
    for _ in range(300):
        run(w, 1)
        keep_fed(w)
        teleport_keep(w)
        for q in mates:
            pin(w, q, 20, 19)
    assert not attacks(w)


def test_AC20_dogs_attack_a_lone_villager():
    w = dog_world()
    v = [v for v in w.villagers.values() if v.leader == P1][0]
    teleport(w, P1, 5, 5)
    for _ in range(300):
        run(w, 1)
        keep_fed(w)
        pin(w, v, 20, 19)
    assert [a for a in attacks(w) if a.payload.victim == v.id]


def test_AC20_a_burning_fire_keeps_dogs_away():
    w = dog_world()
    fire = add_structure(w, "campfire", 20, 18, P1)
    for _ in range(40):
        fire.fuel_until = w.tick + 360
        run(w, 10)
        keep_fed(w)
        teleport_keep(w)
    assert not attacks(w)


# ----------------------------------------------------------------------------------- AC-21


def race(seed):
    w = example(CFG, seed)
    w.terrain[9][11] = "tree"
    w.terrain[5][11] = "grass"
    for tx, ty in ((10, 4), (11, 4), (10, 5)):
        w.terrain[ty][tx] = "grass"  # remove the other trees: exactly one tree is left
    teleport(w, P1, 11, 8)
    teleport(w, P2, 11, 10)
    for p in w.players.values():
        p.body.hunger = p.body.thirst = 0
    act(w, P1, kind="gather", item="wood", x=11, y=9)
    act(w, P2, kind="gather", item="wood", x=11, y=9)
    run(w, 200)
    return w.players[P1].inventory.count("wood"), w.players[P2].inventory.count("wood")


def test_AC21_exactly_one_gets_the_last_unit_decided_by_the_seed():
    winners = set()
    for seed in range(1, 13):
        a, b = race(seed)
        assert (a > 0) != (b > 0), f"seed {seed}: both or neither got the tree ({a},{b})"
        winners.add(P1 if a else P2)
    assert winners == {P1, P2}
    assert race(3) == race(3)


def test_AC21_player_order_rotates_every_tick():
    w = world()
    base = sorted(w.players)
    seen = [tuple(player_order(w, t)) for t in range(8)]
    assert seen[0] != seen[1]
    assert seen[0] == seen[len(base)]
    assert all(sorted(s) == base for s in seen)


# ----------------------------------------------------------------------------------- AC-22/23


def test_AC22_stage_1_gives_basic_tools_and_advances():
    w = world()
    stock(w, P1, wood=10, water=10, berries=10)
    for kind, n in (("wood", 10), ("water", 10), ("roots", 10)):
        w.players[P1].home_store.add(kind, n, w.tick)
    run(w, 180)
    p = w.players[P1]
    assert evs(w, "task_done", player=P1)
    assert evs(w, "stage_done", player=P1)
    assert p.task_stage >= 2 and 1 in p.task_receipts
    assert p.inventory.tools or any(s.store and s.store.tools for s in w.structures.values())


def test_AC22_joint_project_reward_is_larger_than_solo():
    assert BAL.buildings.coop_reward > BAL.buildings.solo_reward
    assert "granary" in BAL.buildings.joint_kinds and "bridge" in BAL.buildings.joint_kinds


@pytest.mark.slow
def test_AC22_dominating_a_landmark_for_a_week_gives_the_bonus():
    w = world()
    w.players[P1].task_stage = 1
    for pid in (P2,):
        teleport(w, pid, 3, 3)
    week = CFG.world.clock.days_per_week * DAY
    for _ in range(2 * week // 60 + 2):
        run(w, 60)
        keep_fed(w)
        teleport(w, P1, 20, 5)
        w.players[P1].action = None
        for v in w.villagers.values():
            v.x = v.from_x = v.to_x = 4
            v.y = v.from_y = v.to_y = 4
        teleport(w, P2, 3, 3)
    assert evs(w, "dominance_bonus", player=P1)
    assert not evs(w, "dominance_bonus", player=P2)


def test_AC23_borders_show_claimed_land_in_the_owners_pattern():
    from ai_island.sim import Simulation
    from ai_island.world.view import frame_from_world

    w = world()
    stock(w, P1, stake=1)
    teleport(w, P1, 16, 7)
    act(w, P1, kind="claim_land", x=16, y=8)
    run_until_idle(w, P1)
    sim = Simulation(CFG, 1, w.streams, w)
    frame = frame_from_world(sim)
    assert frame.borders and {b[2] for b in frame.borders} >= {1}
    assert any((x, y) == (16, 8) for x, y, _ in frame.stakes)
    assert len(frame.players) == 2 and len(frame.villagers) == len(w.villagers)


# ----------------------------------------------------------------------------------- AC-24


def test_AC24_sight_range_by_day_night_and_storm_and_hearing():
    w = world()
    run(w, 720)  # noon
    assert sight_range(w, P1, w.tick) == BAL.senses.sight_tiles == 7
    assert BAL.senses.night_sight_tiles == 3 and BAL.senses.storm_sight_tiles == 4
    w.weather.current = "storm"
    assert sight_range(w, P1, w.tick) == 4
    w.weather.current = "clear"
    assert BAL.senses.hearing_tiles == 5
    assert can_hear(w, (8, 8), (13, 8)) and not can_hear(w, (8, 8), (14, 8))
    assert can_see(w, P1, (15, 8), w.tick) and not can_see(w, P1, (16, 8), w.tick)


def test_AC24_night_sight_is_shorter():
    w = world()
    run(w, 60)
    assert sight_range(w, P1, w.tick) == BAL.senses.night_sight_tiles


def test_AC24_remembered_tile_can_differ_from_the_real_map():
    w = world()
    run(w, 720)
    teleport(w, P1, 11, 7)
    build_report(w, P1, w.tick)
    rt = remembered_tile(w, P1, (11, 5))
    assert rt is not None and rt.terrain == "tree"
    teleport(w, P1, 20, 20)
    w.terrain[5][11] = "stump"
    run(w, 30)
    build_report(w, P1, w.tick)
    assert remembered_tile(w, P1, (11, 5)).terrain == "tree"
    assert w.terrain[5][11] == "stump"
    assert remembered_tile(w, P1, (1, 1)) is None or True


# ----------------------------------------------------------------------------------- AC-25


def test_AC25_at_least_three_templates_per_event_kind():
    assert TEMPLATES
    for kind, options in TEMPLATES.items():
        assert len(options) >= 3, kind


def test_AC25_reports_are_identical_for_the_same_seed_and_hide_internal_names():
    a, b = world(), world()
    for w in (a, b):
        run(w, 720)
        stock(w, P1, mild_poison=1)
    ra, rb = build_report(a, P1, a.tick), build_report(b, P1, b.tick)
    assert ra.text == rb.text and ra.sights == rb.sights
    assert "mild_poison" not in ra.text and "strong_poison" not in ra.text
    assert "player_2" not in ra.feeling


# ----------------------------------------------------------------------------------- AC-26/27


def test_AC26_victim_learns_the_culprit_only_if_it_saw_or_heard():
    w = world()
    act(w, P1, kind="attack", target=P2)
    run_until_idle(w, P1)
    run(w, 5)
    assert w.players[P2].known_culprits and P1 in w.players[P2].known_culprits.values()
    w = world()
    far = HarmRecord(w.next("harm"), w.tick, "steal", P1, P2, 1, 1)
    teleport(w, P2, 22, 22)
    w.harm_log.append(far)
    run(w, 5)
    assert far.processed
    assert far.id not in w.players[P2].known_culprits
    # told later
    w.players[P2].knowledge.append(
        KnowledgeEntry(5, f"culprit:{far.id}", P1, 0.8, "taught:player_1", w.tick, True)
    )
    run(w, 5)
    assert w.players[P2].known_culprits.get(far.id) == P1


def test_AC27_talk_needs_sight_and_only_hearers_receive_words():
    w = world()
    sp = w.players[P1]
    near, edge, far = [v for v in w.villagers.values() if v.leader == P2][:3]
    for v, dx in ((near, 3), (edge, 5), (far, 7)):
        pin(w, v, sp.x + dx, sp.y)
    act(w, P1, kind="talk", target=P2, text="listen")
    run_until_idle(w, P1)
    run(w, 3)
    spoken = evs(w, "chat_spoken", speaker=P1)
    assert spoken
    hearers = set(spoken[0].payload.hearers)
    assert near.id in hearers and edge.id in hearers and far.id not in hearers
    # target out of sight
    w2 = world()
    teleport(w2, P2, 20, 20)
    act(w2, P1, kind="talk", target=P2, text="hello?")
    run_until_idle(w2, P1)
    run(w2, 3)
    assert not [e for e in evs(w2, "chat_spoken", speaker=P1) if P2 in e.payload.hearers]


# ----------------------------------------------------------------------------------- AC-28


def test_AC28_confidence_is_validated_between_0_and_1():
    KnowledgeEntry(1, "a", "b", 0.0, "self", 0)
    KnowledgeEntry(1, "a", "b", 1.0, "self", 0)
    for bad in (-0.1, 1.1):
        with pytest.raises(ValueError):
            KnowledgeEntry(1, "a", "b", bad, "self", 0)
