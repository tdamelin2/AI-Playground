"""Phase 1.5 AC-2 .. AC-8 (world side): per-entity movement timers, steps, snapshots, speed."""

from __future__ import annotations

import json
import math
import shutil
import sqlite3
import time

import pytest
from conftest import LOGS, ROOT, RUNS, cli, db_events

from ai_island.config import ANIMAL_KINDS, load_config
from ai_island.sim import SNAPSHOT_VERSION, Simulation, SnapshotError
from ai_island.world.clock import Clock, daylight_at, is_night_at
from ai_island.world.movement import (
    begin_step,
    complete_step,
    moving_entities,
    step_minutes,
)

DAY = 1440
WEEK = 7 * DAY
YEAR = 80_640
MOVING = ["rabbit", "deer", "boar", "fish", "bird", "goat", "chicken"]


def _ident(entity):
    return ("wild_dog", entity.id) if hasattr(entity, "pack") else (entity.kind, entity.id)


def _kind(entity):
    return "wild_dog" if hasattr(entity, "pack") else entity.kind


def _movers(world):
    return list(moving_entities(world))


def _stepping(e):
    return (e.to_x, e.to_y) != (e.x, e.y)


def _cap(n):
    return n // 4 if n >= 4 else 1


# ---------------------------------------------------------------- shared controlled worlds


@pytest.fixture(scope="module")
def no_dog_cfg(tmp_path_factory):
    d = tmp_path_factory.mktemp("nodog") / "config"
    shutil.copytree(ROOT / "config", d)
    p = d / "world.toml"
    text = p.read_text(encoding="utf-8-sig")
    text = text.replace("initial_packs_centre = 2", "initial_packs_centre = 0")
    text = text.replace("initial_packs_buffer = 2", "initial_packs_buffer = 0")
    p.write_text(text, encoding="utf-8")
    return load_config(d)


def controlled_sim(cfg, terrain_key, seed=1):
    """Every tile one terrain kind (open habitat), no dogs; restored so the due-heap is rebuilt."""
    sim = Simulation.new(cfg, seed, players="none")
    w = sim.world
    assert not w.dogs
    for y in range(w.height):
        for x in range(w.width):
            w.terrain[y][x] = terrain_key
    return Simulation.from_snapshot(sim.snapshot(), config=cfg)


# ---------------------------------------------------------------- AC-2


@pytest.fixture(scope="module")
def day_starts(cfg):
    """Step starts per tick per kind over game day 1 on the default map."""
    sim = Simulation.new(cfg, 1, players="none")
    w = sim.world
    seen = set()
    starts = {}  # tick -> {kind: n}
    pops = {}  # kind -> max population during the day
    for _ in range(DAY):
        before = {k: len(w.animals[k]) for k in ANIMAL_KINDS}
        before["wild_dog"] = len(w.dogs)
        sim.step()
        counts = {}
        for e in _movers(w):
            key = (_ident(e), e.move_start_tick)
            if _stepping(e) and key not in seen:
                seen.add(key)
                counts[_kind(e)] = counts.get(_kind(e), 0) + 1
        now = {k: len(w.animals[k]) for k in ANIMAL_KINDS}
        now["wild_dog"] = len(w.dogs)
        for k in now:
            pops[k] = max(pops.get(k, 0), now[k], before[k])
        starts[w.tick] = (counts, {k: max(now[k], before[k]) for k in now})
    return starts, pops


def test_AC2_no_tick_starts_more_than_a_quarter_of_a_kind(day_starts):
    starts, pops = day_starts
    worst = {}
    for tick, (counts, n) in starts.items():
        for kind, c in counts.items():
            cap = _cap(n[kind])
            worst[kind] = max(worst.get(kind, 0), c)
            assert c <= cap, (
                f"tick {tick}: {c} {kind} steps started (population {n[kind]}, cap {cap})"
            )
    LOGS.mkdir(exist_ok=True)
    (LOGS / "p15_ac2_day.txt").write_text(
        "population and worst starts in one tick, day 1, seed 1\n"
        + "\n".join(f"{k}: pop {pops[k]} worst {worst.get(k, 0)}" for k in sorted(pops))
        + "\n",
        encoding="utf-8",
    )
    assert sum(worst.values()) > 0


def test_AC2_every_moving_kind_actually_moves_in_a_day(day_starts):
    starts, pops = day_starts
    total = {}
    for counts, _n in starts.values():
        for kind, c in counts.items():
            total[kind] = total.get(kind, 0) + c
    # kinds with individuals present must show movement over a day (rest <= 120 min)
    for kind in MOVING + ["wild_dog"]:
        if pops.get(kind, 0) > 0:
            assert total.get(kind, 0) > 0, kind


def test_AC2_small_kind_cap_is_one_start_per_tick(no_dog_cfg):
    # three goats only: at most one start per tick
    sim = Simulation.new(no_dog_cfg, 3, players="none")
    w = sim.world
    for extra in list(w.animals["goat"])[3:]:
        w.animals["goat"].remove(extra)
    assert len(w.animals["goat"]) >= 1
    sim = Simulation.from_snapshot(sim.snapshot(), config=no_dog_cfg)
    w = sim.world
    n = len(w.animals["goat"])
    seen, per_tick = set(), []
    for _ in range(DAY):
        sim.step()
        c = 0
        for e in w.animals["goat"]:
            if _stepping(e) and (e.id, e.move_start_tick) not in seen:
                seen.add((e.id, e.move_start_tick))
                c += 1
        per_tick.append(c)
    assert n < 4
    assert max(per_tick) <= 1
    assert sum(per_tick) > 0


# ---------------------------------------------------------------- AC-3


def _expected_rate(e):
    eb = (e["bout_min_tiles"] + e["bout_max_tiles"]) / 2
    er = (e["rest_min_minutes"] + e["rest_max_minutes"]) / 2
    return 60 * eb / (e["minutes_per_tile"] * eb + er)


def _tiles_per_hour(sim, kinds, ticks):
    w = sim.world
    tracked = {k: list(w.animals[k]) for k in kinds}
    assert all(tracked[k] for k in kinds), tracked
    last = {(k, a.id): (a.x, a.y) for k in kinds for a in tracked[k]}
    moved = dict.fromkeys(kinds, 0)
    for _ in range(ticks):
        sim.step()
        for k in kinds:
            for a in tracked[k]:
                pos = (a.x, a.y)
                if pos != last[(k, a.id)]:
                    moved[k] += 1
                    last[(k, a.id)] = pos
    hours = ticks / 60
    return {k: moved[k] / (len(tracked[k]) * hours) for k in kinds}


@pytest.fixture(scope="module")
def week_rates(no_dog_cfg):
    land = controlled_sim(no_dog_cfg, "grass")
    water = controlled_sim(no_dog_cfg, "lake")
    rates = _tiles_per_hour(land, ["rabbit", "deer", "boar", "bird", "goat", "chicken"], WEEK)
    rates.update(_tiles_per_hour(water, ["fish"], WEEK))
    return rates


@pytest.mark.parametrize("kind", MOVING)
@pytest.mark.slow
def test_AC3_open_habitat_rate_matches_formula(week_rates, cfg, kind):
    bal = load_config_balance(kind)
    expected = _expected_rate(bal)
    got = week_rates[kind]
    LOGS.mkdir(exist_ok=True)
    with (LOGS / "p15_ac3_rates.txt").open("a", encoding="utf-8") as fh:
        fh.write(f"controlled {kind}: tiles/hour {got:.3f} expected {expected:.3f}\n")
    assert abs(got - expected) <= 0.15 * expected, (kind, got, expected)


def load_config_balance(kind):
    import tomllib

    raw = tomllib.loads((ROOT / "config" / "balance.toml").read_text(encoding="utf-8-sig"))
    return raw["animals"][kind]


def test_AC3_default_map_rates_reported(cfg):
    sim = Simulation.new(cfg, 1, players="none")
    rates = _tiles_per_hour(sim, ["rabbit", "deer", "goat", "chicken", "bird", "fish"], 2 * DAY)
    LOGS.mkdir(exist_ok=True)
    with (LOGS / "p15_ac3_rates.txt").open("a", encoding="utf-8") as fh:
        for k, v in rates.items():
            fh.write(f"default map {k}: tiles/hour {v:.3f}\n")
    assert all(v > 0 for v in rates.values())


@pytest.mark.slow
def test_AC3_slower_kinds_move_fewer_tiles_per_hour(week_rates):
    assert week_rates["bird"] > week_rates["rabbit"] > week_rates["goat"]
    assert week_rates["rabbit"] > week_rates["boar"] > week_rates["fish"]


def test_AC3_fleeing_step_is_faster_than_wandering_step(no_dog_cfg):
    sim = controlled_sim(no_dog_cfg, "grass")
    w = sim.world
    from ai_island.world.state import Dog

    dog = Dog(w.new_id(), 0, 40, 40)
    w.dogs.append(dog)
    sim = Simulation.from_snapshot(sim.snapshot(), config=no_dog_cfg)
    w = sim.world
    assert len(w.dogs) == 1
    bal = no_dog_cfg.balance.animals["rabbit"]
    flee, wander, radius = bal.flee_minutes_per_tile, bal.minutes_per_tile, bal.flee_radius
    assert flee < wander
    seen = set()
    fast, slow, odd = [], [], []
    for _ in range(4 * DAY):
        sim.step()
        d = w.dogs[0]
        for a in w.animals["rabbit"]:
            key = (a.id, a.move_start_tick)
            if not _stepping(a) or key in seen:
                continue
            seen.add(key)
            dur = a.move_end_tick - a.move_start_tick
            cheb = max(abs(a.from_x - d.x), abs(a.from_y - d.y))
            manh = abs(a.from_x - d.x) + abs(a.from_y - d.y)
            if dur == flee:
                fast.append(cheb)
            elif dur == wander:
                slow.append(manh)
            else:
                odd.append(dur)
    assert not odd, f"unexpected step durations {sorted(set(odd))}"
    assert fast, "no fleeing step ever seen with a dog loose in the zone"
    assert slow
    assert max(fast) <= radius + 1, max(fast)
    assert min(slow) >= 1
    far_but_fast = [c for c in fast if c > radius + 1]
    assert not far_but_fast


# ---------------------------------------------------------------- AC-4


@pytest.fixture(scope="module")
def dog_year(cfg):
    sim = Simulation.new(cfg, 1, players="none")
    w = sim.world
    clock = cfg.world.clock
    mine_moves, mine_minutes = {}, {}
    last = {d.id: (d.x, d.y) for d in w.dogs}
    for _ in range(YEAR):
        sim.step()
        c = Clock.at(w.tick - 1, clock)
        bucket = f"{c.season}_{'night' if is_night_at(w.tick - 1, clock) else 'day'}"
        mine_minutes[bucket] = mine_minutes.get(bucket, 0) + len(w.dogs)
        for d in w.dogs:
            pos = (d.x, d.y)
            if d.id in last and pos != last[d.id]:
                mine_moves[bucket] = mine_moves.get(bucket, 0) + 1
            last[d.id] = pos
    return w.counters, mine_moves, mine_minutes


@pytest.mark.slow
def test_AC4_dogs_move_more_tiles_per_dog_hour_at_night_and_in_winter(dog_year):
    _c, moves, minutes = dog_year
    rate = {b: 60 * moves.get(b, 0) / minutes[b] for b in minutes if minutes[b] > 0}
    assert rate["summer_night"] > rate["summer_day"]
    assert rate["winter_day"] > rate["summer_day"]
    assert rate["winter_night"] > rate["summer_night"]
    LOGS.mkdir(exist_ok=True)
    (LOGS / "p15_ac4_dog_rates.txt").write_text(
        "tiles per dog-hour by bucket\n"
        + "\n".join(f"{b}: {v:.3f}" for b, v in sorted(rate.items()))
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.slow
def test_AC4_counters_count_dog_minutes_and_completed_steps(dog_year):
    counters, moves, minutes = dog_year
    for bucket, mine in minutes.items():
        got = counters["dog_checks"].get(bucket, 0)
        assert abs(got - mine) <= max(40, 0.02 * mine), (bucket, got, mine)
    for bucket, mine in moves.items():
        got = counters["dog_moves"].get(bucket, 0)
        assert abs(got - mine) <= max(10, 0.02 * mine), (bucket, got, mine)
    # dog_moves is completed steps, so it is far below dog_checks (dog-minutes) in summer days
    assert counters["dog_moves"]["summer_day"] < counters["dog_checks"]["summer_day"]


@pytest.mark.slow
def test_AC4_phase1_property_via_counters(dog_year):
    c, _m, _n = dog_year

    def rate(key):
        return c["dog_moves"].get(key, 0) / c["dog_checks"][key]

    assert rate("summer_night") > rate("summer_day")
    assert rate("winter_day") > rate("summer_day")


# ---------------------------------------------------------------- AC-5


def test_AC5_step_ends_exactly_minutes_per_tile_later_and_tile_changes_at_the_end(no_dog_cfg):
    sim = controlled_sim(no_dog_cfg, "grass")
    w = sim.world
    mpt = {k: no_dog_cfg.balance.animals[k].minutes_per_tile for k in MOVING}
    open_steps = {}  # (kind, id, start) -> (end, from, to)
    seen = set()
    checked = 0
    for _ in range(3 * DAY):
        sim.step()
        t = w.tick
        for e in _movers(w):
            kind, key = _kind(e), (_ident(e), e.move_start_tick)
            if kind not in mpt:
                continue
            if _stepping(e) and key not in seen:
                seen.add(key)
                T = e.move_start_tick
                assert e.move_end_tick - T == mpt[kind], (kind, T, e.move_end_tick)
                assert (e.x, e.y) == (e.from_x, e.from_y), "tile moved at the start of a step"
                assert abs(e.to_x - e.from_x) + abs(e.to_y - e.from_y) == 1
                open_steps[key] = (e, e.move_end_tick, (e.from_x, e.from_y), (e.to_x, e.to_y))
        for key, (e, end, src, dst) in list(open_steps.items()):
            if t == end - 1:
                assert (e.x, e.y) == src, f"{key}: tile changed before T+M (at T+M-1)"
            if t == end:
                assert (e.x, e.y) == dst, f"{key}: tile not committed at T+M"
                del open_steps[key]
                checked += 1
            if t < end - 1:
                assert (e.x, e.y) == src, f"{key}: tile changed mid-step"
    assert checked > 500


def test_AC5_dog_step_durations_follow_day_night_winter(cfg):
    clock = cfg.world.clock
    bal = cfg.balance.dogs

    def expect(tick):
        div = 1.0
        if is_night_at(tick, clock):
            div *= bal.night_multiplier
        if Clock.at(tick, clock).season == "winter":
            div *= bal.winter_multiplier
        return max(1, math.ceil(bal.minutes_per_tile / div - 1e-9))

    for offset in (0, 3 * 14 * DAY):
        sim = Simulation.new(cfg, 1, players="none")
        if offset:
            sim.run(offset)
        w = sim.world
        seen, durations = set(), {}
        for _ in range(DAY):
            sim.step()
            for d in w.dogs:
                key = (d.id, d.move_start_tick)
                if _stepping(d) and key not in seen:
                    seen.add(key)
                    dur = d.move_end_tick - d.move_start_tick
                    durations.setdefault(expect(d.move_start_tick), set()).add(dur)
        assert durations
        for exp, got in durations.items():
            assert got == {exp}, (offset, exp, got)


def test_AC5_animals_stay_in_habitat_and_zone_dogs_out_of_homes(cfg):
    sim = Simulation.new(cfg, 2, players="none")
    w = sim.world
    homes = [(h.x, h.y, h.size) for h in w.homes]
    prev = {}
    for _ in range(2 * DAY):
        sim.step()
        for kind in ANIMAL_KINDS:
            habitat = cfg.world.animals[kind].habitat
            for a in w.animals[kind]:
                assert w.terrain[a.y][a.x] in habitat, (kind, a.x, a.y)
                assert w.zone_at(a.x, a.y) == a.zone, (kind, a.id)
                old = prev.get(("a", a.id))
                if old is not None:
                    assert abs(old[0] - a.x) + abs(old[1] - a.y) <= 1
                prev[("a", a.id)] = (a.x, a.y)
        for d in w.dogs:
            assert w.passable(d.x, d.y)
            assert not any(rx <= d.x < rx + s and ry <= d.y < ry + s for rx, ry, s in homes), (
                d.x,
                d.y,
            )
            old = prev.get(("d", d.id))
            if old is not None:
                assert abs(old[0] - d.x) + abs(old[1] - d.y) <= 1
            prev[("d", d.id)] = (d.x, d.y)


def test_AC5_primitives_begin_and_complete_step(cfg):
    sim = Simulation.new(cfg, 1, players="none")
    a = sim.world.animals["rabbit"][0]
    x, y = a.x, a.y
    begin_step(a, (x + 1, y), 100, 3)
    assert (a.x, a.y) == (x, y)
    assert (a.from_x, a.from_y, a.to_x, a.to_y) == (x, y, x + 1, y)
    assert (a.move_start_tick, a.move_end_tick) == (100, 103)
    assert a.facing == 1
    assert complete_step(a, 102) is False and (a.x, a.y) == (x, y)
    assert complete_step(a, 103) is True and (a.x, a.y) == (x + 1, y)
    assert complete_step(a, 103) is False  # exactly once
    begin_step(a, (x, y), 110, 1)
    assert a.facing == -1


def test_AC5_step_minutes_formula():
    assert step_minutes(3) == 3
    assert step_minutes(3, 1.5) == 5
    assert step_minutes(0.2) == 1
    assert step_minutes(4, 1.2) == 5
    assert step_minutes(2.5) == 3


def test_AC5_moving_entities_by_id_excludes_nests(cfg):
    sim = Simulation.new(cfg, 1, players="none")
    ents = moving_entities(sim.world)
    ids = [e.id for e in ents]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    assert not any(getattr(e, "kind", "") == "nest_eggs" for e in ents)
    assert len(sim.world.dogs) > 0
    assert {id(d) for d in sim.world.dogs} <= {id(e) for e in ents}
    assert sum(1 for e in ents if hasattr(e, "kind")) == sum(
        len(sim.world.animals[k]) for k in ANIMAL_KINDS if k != "nest_eggs"
    )


# ---------------------------------------------------------------- AC-6

MID_TICK = 3000


def _mid_step(world):
    return [e for e in _movers(world) if e.move_start_tick < world.tick < e.move_end_tick]


def _event_dump(events):
    """Events as key-order-independent JSON (the same text the database stores)."""
    return [json.dumps(e.model_dump(mode="json"), sort_keys=True) for e in events]


@pytest.fixture(scope="module")
def mid_step_tick(cfg):
    sim = Simulation.new(cfg, 5, players="none")
    sim.run(1000)
    for _ in range(200):
        if len(_mid_step(sim.world)) >= 3:
            return sim.world.tick
        sim.step()
    pytest.fail("no tick with movers in the middle of a step found")


def test_AC6_mid_step_snapshot_round_trip_matches_uninterrupted_run(cfg, mid_step_tick):
    extra = 4000
    whole = Simulation.new(cfg, 5, players="none")
    whole.run(mid_step_tick)
    assert _mid_step(whole.world), "snapshot is not taken in the middle of a step"
    snap = whole.snapshot()
    n_before = len(whole.events)
    mid_state = {
        _ident(e): (
            e.x,
            e.y,
            e.from_x,
            e.from_y,
            e.to_x,
            e.to_y,
            e.move_start_tick,
            e.move_end_tick,
        )
        for e in _movers(whole.world)
    }
    restored = Simulation.from_snapshot(snap)
    assert {
        _ident(e): (
            e.x,
            e.y,
            e.from_x,
            e.from_y,
            e.to_x,
            e.to_y,
            e.move_start_tick,
            e.move_end_tick,
        )
        for e in _movers(restored.world)
    } == mid_state
    whole.run(extra)
    restored.run(extra)
    assert _event_dump(restored.events) == _event_dump(whole.events[n_before:])
    a, b = whole.snapshot(), restored.snapshot()
    assert a.state_json == b.state_json
    assert a.rng_json == b.rng_json
    assert a.tick == b.tick


def test_AC6_snapshot_carries_version_3_after_phase_2_and_mover_fields(cfg):
    assert SNAPSHOT_VERSION == 3
    sim = Simulation.new(cfg, 1, players="none")
    sim.run(500)
    snap = sim.snapshot()
    assert snap.schema_version == 3
    state = json.loads(snap.state_json)
    assert state.get("schema") == 3
    # a restored snapshot has the same movers in the same states
    again = Simulation.from_snapshot(snap)
    assert again.snapshot().state_json == snap.state_json


def test_AC6_older_version_is_refused_naming_both_versions(cfg):
    sim = Simulation.new(cfg, 1, players="none")
    snap = sim.snapshot()
    old = snap.model_copy(update={"schema_version": 1})
    with pytest.raises(SnapshotError) as ei:
        Simulation.from_snapshot(old)
    msg = str(ei.value)
    assert "1" in msg and "3" in msg and "version" in msg, msg
    # the version is checked before the config or state is parsed
    broken = snap.model_copy(
        update={"schema_version": 1, "config_json": "{not json", "state_json": "garbage"}
    )
    with pytest.raises(SnapshotError) as ei2:
        Simulation.from_snapshot(broken)
    assert "version 1" in str(ei2.value) and "3" in str(ei2.value)
    newer = snap.model_copy(update={"schema_version": 4})
    with pytest.raises(SnapshotError):
        Simulation.from_snapshot(newer)


def test_AC6_cli_resume_refuses_old_snapshot_and_db_version_stays_1(run_name):
    assert cli("new", run_name, "--seed", "1").returncode == 0
    db = RUNS / run_name / "run.db"
    con = sqlite3.connect(db)
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 1
        assert con.execute("SELECT MAX(schema_version) FROM snapshots").fetchone()[0] == 3
        con.execute("UPDATE snapshots SET schema_version = 1")
        con.commit()
    finally:
        con.close()
    r = cli("resume", run_name)
    assert r.returncode != 0
    msg = r.stderr + r.stdout
    assert "version" in msg and "1" in msg and "3" in msg, msg
    assert "Traceback" not in msg, msg


def test_AC6_cli_split_run_equals_whole_run_event_log(mid_step_tick):
    a, b = "acc_p15_split", "acc_p15_whole"
    for n in (a, b):
        shutil.rmtree(RUNS / n, ignore_errors=True)
    extra = 3000
    try:
        r = cli(
            "headless",
            "--run",
            a,
            "--ticks",
            str(mid_step_tick),
            "--seed",
            "5",
            env_extra={"PYTHONHASHSEED": "3"},
        )
        assert r.returncode == 0, r.stderr
        r = cli("resume", a, "--ticks", str(extra), env_extra={"PYTHONHASHSEED": "900"})
        assert r.returncode == 0, r.stderr
        r = cli(
            "headless",
            "--run",
            b,
            "--ticks",
            str(mid_step_tick + extra),
            "--seed",
            "5",
            env_extra={"PYTHONHASHSEED": "17"},
        )
        assert r.returncode == 0, r.stderr
        ea, eb = db_events(a), db_events(b)
        assert ea and ea == eb
    finally:
        for n in (a, b):
            shutil.rmtree(RUNS / n, ignore_errors=True)


# ---------------------------------------------------------------- AC-7


@pytest.mark.slow
def test_AC7_full_year_headless_under_five_minutes(run_name):
    LOGS.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    r = cli("headless", "--run", run_name, "--ticks", str(YEAR), "--seed", "1")
    elapsed = time.perf_counter() - t0
    assert r.returncode == 0, r.stderr
    (LOGS / "p15_ac7_year_seconds.txt").write_text(f"{elapsed:.2f}\n", encoding="utf-8")
    print(f"AC-7 persisted full year: {elapsed:.2f} s")
    assert elapsed < 300


def test_AC7_in_process_logs_equal_for_same_seed_and_differ_for_other(cfg):
    def log(seed):
        s = Simulation.new(cfg, seed, players="none")
        s.run(3 * WEEK)
        return _event_dump(s.events), s.snapshot().state_json

    a1, s1 = log(21)
    a2, s2 = log(21)
    b, sb = log(22)
    assert a1 == a2 and s1 == s2
    assert a1 != b and s1 != sb
    assert len(a1) > 0


def test_AC7_daylight_helpers_do_not_touch_streams(cfg):
    sim = Simulation.new(cfg, 1, players="none")
    before = sim.snapshot().rng_json
    for t in range(0, DAY, 7):
        daylight_at(float(t), cfg.world.clock)
    assert sim.snapshot().rng_json == before
