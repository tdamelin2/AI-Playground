"""Phase 2 AC-11: every action in ACTION_KINDS runs on the example map (one test each)."""

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

from ai_island.rules.actions import ACTION_KINDS
from ai_island.world.agents import PromiseSpec

CFG = make_cfg()
BAL = CFG.balance
MIN = BAL.actions.unit_minutes
P1, P2 = "player_1", "player_2"


def world():
    w = example(CFG)
    # keep the two players apart from other things and fed so that only the action matters
    for p in w.players.values():
        p.body.hunger = p.body.thirst = p.body.cold = p.body.fatigue = 0.0
    return w


def vill(w, pid, n=0):
    return [v for v in sorted(w.villagers.values(), key=lambda q: q.id) if v.leader == pid][n]


def go(w, pid, **kw):
    """Start an action, run it to the end; return (started, ticks)."""
    ok = act(w, pid, **kw)
    return ok, run_until_idle(w, pid)


def finished_ok(w, pid, kind):
    fin = evs(w, "action_finished", player=pid, kind=kind)
    bad = evs(w, "action_failed", player=pid, kind=kind)
    assert fin, f"{kind}: no action_finished event"
    assert not bad, f"{kind}: failed with {[b.payload.reason for b in bad]}"
    return fin[-1]


def retry(attempts, fn):
    """Run ``fn(i)`` until it returns True (random-outcome actions such as steal)."""
    for i in range(attempts):
        if fn(i):
            return True
    return False


def test_ACTION_KINDS_lists_all_39_contract_kinds():
    expected = (
        "eat drink rest move gather farm fish hunt build store craft make_fire cook tame use_herb "
        "assign_villager talk trade gift promise ally recruit teach guard steal sabotage attack "
        "chase_off claim_land pull_stakes capture poach pray ceremony build_shrine offering repair "
        "drop pick_up"
    ).split()
    assert list(ACTION_KINDS) == expected


# --------------------------------------------------------------- body, work and care actions


def test_AC11_eat():
    w = world()
    w.players[P1].body.hunger = 60
    stock(w, P1, roots=2)
    ok, ticks = go(w, P1, kind="eat", item="roots", amount=1)
    assert ok and ticks >= MIN["eat"]
    finished_ok(w, P1, "eat")
    assert w.players[P1].body.hunger < 60 - 10 and w.players[P1].inventory.count("roots") == 1


def test_AC11_drink():
    w = world()
    w.players[P1].body.thirst = 60
    stock(w, P1, water=2)
    ok, ticks = go(w, P1, kind="drink", amount=1)
    assert ok and ticks >= MIN["drink"]
    finished_ok(w, P1, "drink")
    assert w.players[P1].body.thirst < 60 and w.players[P1].inventory.count("water") == 1


def test_AC11_rest():
    w = world()
    w.players[P1].body.fatigue = 60
    ok, ticks = go(w, P1, kind="rest", minutes=60)
    assert ok and ticks >= 30
    finished_ok(w, P1, "rest")
    assert w.players[P1].body.fatigue < 60


def test_AC11_move():
    w = world()
    ok, ticks = go(w, P1, kind="move", x=10, y=10)
    assert ok and ticks >= 4
    finished_ok(w, P1, "move")
    p = w.players[P1]
    assert (p.x, p.y) == (10, 10)


def test_AC11_gather():
    w = world()
    ok, ticks = go(w, P1, kind="gather", item="wood", x=11, y=5)
    assert ok and ticks >= MIN["gather_wood"]
    finished_ok(w, P1, "gather")
    assert w.players[P1].inventory.count("wood") >= BAL.actions.gather_yield["wood"]


def test_AC11_farm():
    w = world()
    ok, ticks = go(w, P1, kind="farm", item="sow", x=6, y=8)
    assert ok and ticks >= MIN["farm"]
    finished_ok(w, P1, "farm")
    assert w.terrain[8][6] == "farmland_planted"
    ok, _ = go(w, P1, kind="farm", item="harvest", x=6, y=9)
    assert ok
    assert w.players[P1].inventory.count("crops") >= BAL.actions.crop_yield


def test_AC11_fish():
    w = world()
    stock(w, P1)
    teleport(w, P1, 14, 16)

    def attempt(i):
        go(w, P1, kind="fish", x=15, y=16, amount=3)
        return w.players[P1].inventory.count("fish") > 0

    assert retry(6, attempt)
    finished_ok(w, P1, "fish")


def test_AC11_hunt():
    w = world()
    teleport(w, P1, 14, 10)

    def attempt(i):
        go(w, P1, kind="hunt", target="rabbit")
        return w.players[P1].inventory.count("raw_meat") > 0

    assert retry(8, attempt)
    finished_ok(w, P1, "hunt")


def test_AC11_build():
    w = world()
    stock(w, P1, wood=12, stone=2)
    ok, ticks = go(w, P1, kind="build", structure="house", x=7, y=10)
    assert ok and ticks >= BAL.buildings.work_minutes["house"] // 2
    finished_ok(w, P1, "build")
    houses = [s for s in w.structures.values() if s.kind == "house" and s.owner == P1]
    assert houses and houses[0].complete
    assert w.players[P1].inventory.count("wood") == 0


def test_AC11_store():
    w = world()
    stock(w, P1, berries=3)
    ok, ticks = go(w, P1, kind="store", item="berries", amount=3)
    assert ok and ticks >= MIN["store"]
    finished_ok(w, P1, "store")
    assert w.players[P1].home_store.count("berries") == 3
    assert w.players[P1].inventory.count("berries") == 0


def test_AC11_craft():
    w = world()
    stock(w, P1, wood=2, stone=1)
    ok, ticks = go(w, P1, kind="craft", tool="axe", tier="basic")
    assert ok and ticks >= MIN["craft"]
    finished_ok(w, P1, "craft")
    tool = w.players[P1].inventory.find_tool("axe")
    assert tool is not None and tool.tier == "basic"


def test_AC11_make_fire():
    w = world()
    stock(w, P1, wood=2)
    ok, ticks = go(w, P1, kind="make_fire", x=8, y=9)
    assert ok and ticks >= MIN["make_fire"]
    finished_ok(w, P1, "make_fire")
    fires = [s for s in w.structures.values() if s.kind == "campfire"]
    assert fires and fires[0].burning(w.tick)


def test_AC11_cook():
    w = world()
    fire = add_structure(w, "campfire", 8, 9, P1)
    fire.fuel_until = w.tick + BAL.fire.fuel_ticks
    stock(w, P1, raw_meat=2)
    ok, ticks = go(w, P1, kind="cook", amount=2)
    assert ok and ticks >= MIN["cook"]
    finished_ok(w, P1, "cook")
    assert w.players[P1].inventory.count("cooked_meat") == 2
    assert w.players[P1].inventory.count("raw_meat") == 0


def test_AC11_tame():
    w = world()
    pen = add_structure(w, "pen", 14, 11, P1)
    pen.owner = P1
    teleport(w, P1, 14, 10)
    stock(w, P1, berries=10)

    def attempt(i):
        go(w, P1, kind="tame", target="rabbit", item="berries")
        return any(getattr(a, "pen", 0) for a in w.animals["rabbit"])

    assert retry(6, attempt)
    finished_ok(w, P1, "tame")


def test_AC11_use_herb():
    w = world()
    stock(w, P1, herbs=2)
    w.players[P1].body.pain = 40
    ok, ticks = go(w, P1, kind="use_herb", item="herbs")
    assert ok and ticks >= MIN["use_herb"]
    finished_ok(w, P1, "use_herb")
    assert w.players[P1].body.pain < 40


def test_AC11_assign_villager():
    w = world()
    v = vill(w, P1)
    ok, ticks = go(w, P1, kind="assign_villager", target=v.id, job="farm", work_level="light")
    assert ok and ticks >= MIN["assign_villager"]
    finished_ok(w, P1, "assign_villager")
    assert v.job == "farm" and v.work_level == "light"


# --------------------------------------------------------------------------------- social


def test_AC11_talk():
    w = world()
    ok, ticks = go(w, P1, kind="talk", target=P2, text="hello there")
    assert ok and ticks >= MIN["talk"]
    finished_ok(w, P1, "talk")
    spoken = evs(w, "chat_spoken", speaker=P1)
    assert spoken and "hello there" in spoken[0].payload.text and P2 in spoken[0].payload.hearers


def test_AC11_trade():
    w = world()
    stock(w, P1, wood=3)
    stock(w, P2, stone=2)
    ok, ticks = go(w, P1, kind="trade", target=P2, offer={"wood": 2}, want={"stone": 1})
    assert ok and ticks >= MIN["trade"]
    finished_ok(w, P1, "trade")
    offers = evs(w, "trade_offered")
    assert offers
    oid = offers[0].payload.id
    ok, _ = go(w, P2, kind="trade", target=P1, accept=oid)
    assert ok
    assert (
        w.players[P2].inventory.count("wood") == 2 and w.players[P1].inventory.count("stone") == 1
    )
    assert evs(w, "trade_done")


def test_AC11_gift():
    w = world()
    stock(w, P1, wood=4)
    ok, ticks = go(w, P1, kind="gift", target=P2, item="wood", amount=3)
    assert ok and ticks >= MIN["gift"]
    finished_ok(w, P1, "gift")
    assert w.players[P2].inventory.count("wood") == 3 and w.players[P1].inventory.count("wood") == 1


def test_AC11_promise():
    w = world()
    spec = PromiseSpec(kind="give", to=P2, item="wood", amount=1, due_tick=w.tick + 100)
    ok, ticks = go(w, P1, kind="promise", target=P2, promise=spec, text="I will give wood")
    assert ok and ticks >= MIN["promise"]
    finished_ok(w, P1, "promise")
    assert evs(w, "promise_made")


def test_AC11_ally():
    w = world()
    ok, ticks = go(w, P1, kind="ally", target=P2)
    assert ok and ticks >= MIN["ally"]
    finished_ok(w, P1, "ally")
    oid = evs(w, "trade_offered", kind="ally")[0].payload.id
    ok, _ = go(w, P2, kind="ally", target=P1, accept=oid)
    assert ok
    assert P1 in w.players[P2].allies and P2 in w.players[P1].allies


def test_AC11_recruit():
    w = world()
    wanderer = next(v for v in w.villagers.values() if v.leader is None)
    teleport(w, P1, wanderer.x - 1, wanderer.y)

    def attempt(i):
        go(w, P1, kind="recruit", target=wanderer.id)
        return wanderer.leader == P1

    assert retry(4, attempt)
    assert evs(w, "villager_joined")


def test_AC11_teach():
    w = world()
    ok, ticks = go(w, P1, kind="teach", target=P2, text="red berries are safe")
    assert ok and ticks >= MIN["teach"]
    finished_ok(w, P1, "teach")
    entries = w.players[P2].knowledge
    assert entries and all(0.0 <= e.confidence < 1.0 for e in entries)


def test_AC11_guard():
    w = world()
    ok, ticks = go(w, P1, kind="guard", minutes=30, x=8, y=8)
    assert ok
    finished_ok(w, P1, "guard")


# ---------------------------------------------------------------------------------- harm


def harm_kinds(w):
    return [e.payload.kind for e in evs(w, "harm")]


def test_AC11_steal():
    w = world()
    stock(w, P2, wood=30)

    def attempt(i):
        go(w, P1, kind="steal", target=P2, item="wood")
        return w.players[P1].inventory.count("wood") > 0

    assert retry(10, attempt)
    assert "steal" in harm_kinds(w)
    assert w.players[P2].inventory.count("wood") < 30


def test_AC11_sabotage():
    w = world()
    s = add_structure(w, "house", 10, 9, P2)
    ok, ticks = go(w, P1, kind="sabotage", structure=str(s.id))
    assert ok and ticks >= MIN["sabotage"]
    finished_ok(w, P1, "sabotage")
    assert s.hp == s.max_hp - BAL.harm.sabotage_hp
    assert "sabotage" in harm_kinds(w)


def test_AC11_attack():
    w = world()
    stock(w, P2, wood=10)
    p2 = w.players[P2]
    h0 = p2.body.health
    ok, ticks = go(w, P1, kind="attack", target=P2)
    assert ok
    assert p2.body.pain > 0 and p2.body.health < h0
    assert "attack" in harm_kinds(w)
    dropped = sum(inv.count("wood") for inv in w.drops.values())
    assert dropped > 0 and p2.inventory.count("wood") < 10


def test_AC11_chase_off():
    w = world()
    p2 = w.players[P2]
    before = (p2.x, p2.y)
    ok, ticks = go(w, P1, kind="chase_off", target=P2)
    assert ok
    assert "chase_off" in harm_kinds(w)
    run(w, 40)
    after = (p2.x, p2.y)
    assert abs(after[0] - before[0]) + abs(after[1] - before[1]) >= 2, "target must be moved away"


def test_AC11_claim_land():
    w = world()
    stock(w, P1, stake=1)
    teleport(w, P1, 16, 7)
    ok, ticks = go(w, P1, kind="claim_land", x=16, y=8)
    assert ok and ticks >= MIN["claim_land"]
    finished_ok(w, P1, "claim_land")
    assert w.stakes.get((16, 8)) == P1
    assert (16, 8) in w.claims and w.claims[(16, 8)] == P1


def test_AC11_pull_stakes():
    w = world()
    stock(w, P2, stake=1)
    teleport(w, P2, 16, 7)
    go(w, P2, kind="claim_land", x=16, y=8)
    assert w.stakes.get((16, 8)) == P2
    teleport(w, P1, 16, 9)
    ok, ticks = go(w, P1, kind="pull_stakes", x=16, y=8)
    assert ok and ticks >= MIN["pull_stakes"]
    finished_ok(w, P1, "pull_stakes")
    assert (16, 8) not in w.stakes
    assert not any(o == P2 for o in w.claims.values())
    assert "pull_stakes" in harm_kinds(w)


def test_AC11_capture():
    w = world()
    v = vill(w, P2)
    teleport(w, P1, v.x - 1, v.y)

    def attempt(i):
        go(w, P1, kind="capture", target=v.id)
        return v.captive

    assert retry(8, attempt)
    assert "capture" in harm_kinds(w)


def test_AC11_poach():
    w = world()
    v = vill(w, P2)
    v.loyalty = (BAL.villagers.leave_below + BAL.villagers.poach_loyalty) / 2
    teleport(w, P1, v.x - 1, v.y)

    def attempt(i):
        go(w, P1, kind="poach", target=v.id)
        return v.leader == P1

    assert retry(8, attempt)
    assert "poach" in harm_kinds(w)
    assert [e for e in evs(w, "harm") if e.payload.kind == "poach"][0].payload.victim == P2


# --------------------------------------------------------------------------------- belief


def test_AC11_pray():
    w = world()
    ok, ticks = go(w, P1, kind="pray")
    assert ok and ticks >= MIN["pray"]
    finished_ok(w, P1, "pray")
    assert evs(w, "belief_act")


def test_AC11_ceremony():
    w = world()
    ok, ticks = go(w, P1, kind="ceremony")
    assert ok and ticks >= MIN["ceremony"]
    finished_ok(w, P1, "ceremony")
    assert evs(w, "belief_act")


def test_AC11_build_shrine():
    w = world()
    stock(w, P1, wood=4, stone=4)
    ok, ticks = go(w, P1, kind="build_shrine", x=7, y=10)
    assert ok
    finished_ok(w, P1, "build_shrine")
    shrines = [s for s in w.structures.values() if s.kind == "shrine"]
    assert shrines and shrines[0].complete
    assert evs(w, "belief_act")


def test_AC11_offering():
    w = world()
    stock(w, P1, wood=2)
    ok, ticks = go(w, P1, kind="offering", item="wood")
    assert ok and ticks >= MIN["offering"]
    finished_ok(w, P1, "offering")
    assert w.players[P1].inventory.count("wood") < 2


# ---------------------------------------------------------------------------- tools & items


def test_AC11_repair():
    w = world()
    s = add_structure(w, "house", 7, 10, P1, hp=20)
    stock(w, P1, wood=12, stone=2)
    ok, ticks = go(w, P1, kind="repair", structure=str(s.id))
    assert ok and ticks >= MIN["repair"]
    finished_ok(w, P1, "repair")
    assert s.hp > 20


def test_AC11_drop_and_pick_up():
    w = world()
    stock(w, P1, wood=3)
    ok, ticks = go(w, P1, kind="drop", item="wood", amount=2)
    assert ok and ticks >= MIN["drop"]
    finished_ok(w, P1, "drop")
    assert w.players[P1].inventory.count("wood") == 1
    assert w.drops[(8, 8)].count("wood") == 2
    ok, ticks = go(w, P1, kind="pick_up", x=8, y=8)
    assert ok and ticks >= MIN["pick_up"]
    finished_ok(w, P1, "pick_up")
    assert w.players[P1].inventory.count("wood") == 3


@pytest.mark.parametrize("kind", ACTION_KINDS)
def test_AC11_every_kind_has_a_test(kind):
    here = globals()
    name = {"pick_up": "drop_and_pick_up", "drop": "drop_and_pick_up"}.get(kind, kind)
    assert f"test_AC11_{name}" in here, f"no one-test-per-action test for {kind}"
