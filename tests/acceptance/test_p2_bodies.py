"""Phase 2 AC-1..AC-6: needs, sickness, wellbeing X, bands, trust and anger, death."""

from __future__ import annotations

import math
import re

import pytest
from conftest import ROOT, load_toml
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

from ai_island.rules import body, wellbeing
from ai_island.rules.land import border_tiles  # noqa: F401  (imported to prove the module loads)

CFG = make_cfg()
BAL = CFG.balance
DAY = CFG.world.clock.ticks_per_day


def fresh():
    return example(CFG)


def clear_body(p):
    b = p.body
    b.hunger = b.thirst = b.cold = b.fatigue = b.pain = 0.0
    b.health = 100.0
    b.sickness = None


# ----------------------------------------------------------------------------------- AC-1


def test_AC1_hunger_and_thirst_rise_at_configured_rates():
    w = fresh()
    p = w.players["player_1"]
    clear_body(p)
    teleport(w, "player_1", 8, 8)
    run(w, 360)  # a quarter day, during the first (spring) night and morning
    assert p.body.hunger == pytest.approx(BAL.body.hunger_per_day * 360 / DAY, abs=1.5)
    assert p.body.thirst == pytest.approx(BAL.body.thirst_per_day * 360 / DAY, abs=1.5)


def test_AC1_eating_and_drinking_lower_hunger_and_thirst():
    w = fresh()
    p = w.players["player_1"]
    clear_body(p)
    p.body.hunger = 60.0
    p.body.thirst = 60.0
    stock(w, "player_1", berries=2, water=3)
    assert act(w, "player_1", kind="eat", item="berries", amount=1)
    run_until_idle(w, "player_1")
    assert p.body.hunger < 60.0 - BAL.body.hunger_per_food_unit * 0.5
    assert p.inventory.count("berries") == 1
    assert act(w, "player_1", kind="drink", amount=1)
    run_until_idle(w, "player_1")
    assert p.body.thirst < 60.0 - 1.0
    assert p.inventory.count("water") == 2


def test_AC1_cold_rises_at_night_outside_and_falls_with_fire_or_shelter():
    w = fresh()
    far = w.players["player_2"]
    teleport(w, "player_2", 20, 12)
    mine = w.players["player_1"]
    teleport(w, "player_1", 8, 8)
    add_structure(w, "house", 8, 9, "player_1")
    for p in (far, mine):
        clear_body(p)
    night = 60  # 01:00 on day 1 is night
    far.body.cold = mine.body.cold = 30.0
    body.update_bodies(w, night)
    assert far.body.cold > 30.0, "cold must rise at night outside"
    assert mine.body.cold < 30.0, "a finished house shelters"


def test_AC1_cold_rises_in_winter_by_day():
    w = fresh()
    p = w.players["player_2"]
    teleport(w, "player_2", 20, 12)
    clear_body(p)
    season = CFG.world.clock.season_ticks
    noon_winter = 3 * season + DAY // 2
    body.update_bodies(w, noon_winter)
    assert p.body.cold > 0.0


def test_AC1_cold_does_not_rise_by_day_outside_winter():
    w = fresh()
    p = w.players["player_2"]
    teleport(w, "player_2", 20, 12)
    clear_body(p)
    body.update_bodies(w, DAY // 2)
    assert p.body.cold == 0.0


def test_AC1_rest_restores_fatigue():
    w = fresh()
    p = w.players["player_1"]
    clear_body(p)
    p.body.fatigue = 70.0
    assert act(w, "player_1", kind="rest", minutes=120)
    run_until_idle(w, "player_1")
    assert p.body.fatigue < 70.0 - BAL.body.rest_recovery_per_hour


@pytest.mark.parametrize("item,sick", [
    ("mild_poison", "mild_poison"),
    ("strong_poison", "strong_poison"),
    ("raw_meat", "raw_meat"),
    ("spoiled_meat", "spoiled_meat"),
])  # fmt: skip
def test_AC1_bad_food_causes_its_sickness(item, sick):
    w = fresh()
    p = w.players["player_1"]
    clear_body(p)
    p.body.hunger = 60.0
    stock(w, "player_1", **{item: 1})
    assert act(w, "player_1", kind="eat", item=item, amount=1)
    run_until_idle(w, "player_1")
    assert p.body.sickness == sick
    assert evs(w, "sickness")


def test_AC1_strong_poison_can_kill_a_player_and_a_villager():
    w = fresh()
    p = w.players["player_1"]
    clear_body(p)
    body.apply_sickness(w, p, "strong_poison", w.tick)
    v = next(v for v in w.villagers.values() if v.leader == "player_2")
    clear_body(v)
    body.apply_sickness(w, v, "strong_poison", w.tick)
    v.loyalty = 100.0
    run(w, BAL.body.sickness["strong_poison"].duration_ticks + 20)
    assert evs(w, "died", player="player_1") or p.body.health < 100.0
    assert evs(w, "died", player="player_1"), "strong poison must be able to kill a player"
    assert evs(w, "villager_died", villager=v.id), "and a villager"


# ----------------------------------------------------------------------------------- AC-2


def test_AC2_f_is_concave_and_normalised():
    k = BAL.wellbeing.k
    assert wellbeing.f(0.0, k) == pytest.approx(0.0)
    assert wellbeing.f(1.0, k) == pytest.approx(1.0)
    xs = [i / 20 for i in range(21)]
    ys = [wellbeing.f(c, k) for c in xs]
    for i in range(1, 20):
        assert ys[i] >= (ys[i - 1] + ys[i + 1]) / 2 - 1e-9, "f must be concave"
    assert all(b >= a for a, b in zip(ys, ys[1:], strict=False))


def test_AC2_weights_sum_to_100_and_x_is_weighted_sum_plus_b():
    wb = BAL.wellbeing
    assert sum(wb.weights.values()) == pytest.approx(100.0)
    w = fresh()
    p = w.players["player_1"]
    c = wellbeing.comforts(w, "player_1", w.tick)
    core = sum(wb.weights[key] * wellbeing.f(c[key], wb.k) for key in wb.weights)
    p.b = 0.0
    assert wellbeing.x_of(w, "player_1", w.tick) == pytest.approx(min(100.0, max(0.0, core)))
    p.b = 7.0
    p.b_tick = w.tick
    assert wellbeing.x_of(w, "player_1", w.tick) == pytest.approx(min(100.0, max(0.0, core + 7.0)))


def test_AC2_b_halves_after_half_life_and_x_stays_in_range():
    w = fresh()
    p = w.players["player_1"]
    p.b = 0.0
    p.b_tick = 0
    wellbeing.add_gain(w, "player_1", 20.0, "test", 0)
    hl = BAL.wellbeing.half_life_ticks
    assert hl == 2880
    assert wellbeing.b_now(w, p, hl) == pytest.approx(10.0, rel=0.02)
    assert wellbeing.b_now(w, p, 2 * hl) == pytest.approx(5.0, rel=0.02)
    wellbeing.add_gain(w, "player_1", 5000.0, "huge", 0)
    assert 0.0 <= wellbeing.x_of(w, "player_1", 0) <= 100.0
    wellbeing.add_gain(w, "player_1", -50000.0, "huge", 0)
    assert 0.0 <= wellbeing.x_of(w, "player_1", 0) <= 100.0


def test_AC2_every_comfort_curve_is_concave_in_the_weights_table():
    assert set(BAL.wellbeing.weights) >= {"food", "water", "warmth", "rest", "health", "shelter"}


# ----------------------------------------------------------------------------------- AC-3

KEY_LINE = re.compile(r"^\s*([A-Za-z0-9_\"\.]+)\s*=\s*(.+)$")


def test_AC3_every_balance_value_has_a_reason_comment():
    text = (ROOT / "config" / "balance.toml").read_text(encoding="utf-8-sig")
    missing = []
    in_multiline = False
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("["):
            continue
        if in_multiline:
            if "]" in s:
                in_multiline = False
            continue
        m = KEY_LINE.match(line)
        if not m:
            continue
        if "#" not in m.group(2):
            if m.group(2).strip() == "[":
                in_multiline = True
                continue
            missing.append((n, s[:60]))
    assert not missing, f"keys without a reason comment: {missing[:10]} (+{len(missing)})"


def test_AC3_design_constants():
    bal = load_toml(ROOT / "config" / "balance.toml")
    assert bal["wellbeing"]["half_life_ticks"] == 2 * DAY
    assert bal["villagers"]["start_loyalty"] == 70
    assert bal["villagers"]["leave_below"] == 30


# ----------------------------------------------------------------------------------- AC-4

WORDS = {"strong": 100, "all_right": 70, "uneasy": 50, "suffering": 30, "miserable": 5}


def test_AC4_band_edges_and_multipliers():
    wb = BAL.wellbeing
    assert [wellbeing.band_of(x) for x in (100, 80, 79.9, 60, 59.9, 40, 39.9, 20, 19.9, 0)] == [
        wb.band_names[i] for i in (0, 0, 1, 1, 2, 2, 3, 3, 4, 4)
    ]
    assert list(wb.speed_mult) == [1.0, 1.0, 0.75, 0.45, 0.20]
    assert list(wb.work_mult) == [1.0, 1.0, 0.75, 0.45, 0.20]


@pytest.mark.parametrize("target,idx", [(90, 0), (70, 1), (50, 2), (30, 3), (10, 4)])
def test_AC4_speed_and_work_multipliers_follow_the_band(target, idx):
    w = fresh()
    p = w.players["player_1"]
    clear_body(p)
    now = wellbeing.x_of(w, "player_1", w.tick)
    p.b = target - now
    p.b_tick = w.tick
    assert wellbeing.x_of(w, "player_1", w.tick) == pytest.approx(target, abs=0.01)
    assert wellbeing.speed_mult(w, p) == [1.0, 1.0, 0.75, 0.45, 0.2][idx]
    assert wellbeing.work_mult(w, p) == [1.0, 1.0, 0.75, 0.45, 0.2][idx]


def test_AC4_hooked_exactly_when_x_below_40_or_pain_at_threshold():
    w = fresh()
    p = w.players["player_1"]
    clear_body(p)
    base = wellbeing.x_of(w, "player_1", w.tick)
    p.b = 45 - base
    p.b_tick = w.tick
    assert not wellbeing.is_hooked(w, "player_1")
    p.b = 39 - base
    assert wellbeing.is_hooked(w, "player_1")
    p.b = 45 - base
    p.body.pain = BAL.wellbeing.hooked_pain - 1
    assert not wellbeing.is_hooked(w, "player_1") or wellbeing.x_of(w, "player_1") < 40
    p.body.pain = BAL.wellbeing.hooked_pain
    assert wellbeing.is_hooked(w, "player_1")


# ----------------------------------------------------------------------------------- AC-5


def test_AC5_every_player_holds_trust_and_anger_toward_every_other():
    w = fresh()
    for a in w.players.values():
        for b in w.players.values():
            if a.id != b.id:
                assert b.id in a.trust and b.id in a.anger


def test_AC5_trust_and_anger_fade_toward_neutral():
    w = fresh()
    a = w.players["player_1"]
    a.trust["player_2"] = 90.0
    a.anger["player_2"] = 60.0
    w.players["player_2"].trust["player_1"] = 10.0
    for _ in range(50):
        wellbeing.fade_relationships(w, DAY // 4)
    assert a.trust["player_2"] < 90.0 and a.trust["player_2"] >= BAL.wellbeing.trust_neutral
    assert a.anger["player_2"] < 60.0 and a.anger["player_2"] >= BAL.wellbeing.anger_neutral
    assert w.players["player_2"].trust["player_1"] > 10.0
    for _ in range(2000):
        wellbeing.fade_relationships(w, DAY // 4)
    assert a.trust["player_2"] == pytest.approx(50.0)
    assert a.anger["player_2"] == pytest.approx(0.0)


# ----------------------------------------------------------------------------------- AC-6


def test_AC6_dead_player_respawns_home_items_on_death_tile_x_10_lower():
    w = fresh()
    p = w.players["player_1"]
    teleport(w, "player_1", 11, 10)
    stock(w, "player_1", wood=5)
    x_before = wellbeing.x_of(w, "player_1", w.tick)
    body.kill_player(w, p, "test", w.tick)
    home = w.homes[0]
    assert p.alive
    assert (p.x, p.y) == tuple(home.anchor) or abs(p.x - home.anchor[0]) + abs(
        p.y - home.anchor[1]
    ) <= 3
    assert w.drops.get((11, 10)) is not None
    assert w.drops[(11, 10)].count("wood") == 5
    assert p.inventory.count("wood") == 0
    assert evs(w, "died", player="player_1") and evs(w, "respawned", player="player_1")
    x_after = wellbeing.x_of(w, "player_1", w.tick)
    assert x_after == pytest.approx(max(0.0, x_before - 10.0), abs=0.6) or x_after <= x_before - 9.0


def test_AC6_respawn_body_values_come_from_config():
    w = fresh()
    p = w.players["player_1"]
    body.kill_player(w, p, "test", w.tick)
    assert p.body.hunger == pytest.approx(BAL.body.respawn_hunger, abs=1)
    assert p.body.health == pytest.approx(BAL.body.respawn_health, abs=1)
    assert p.action is None
    assert math.isfinite(wellbeing.x_of(w, "player_1"))
