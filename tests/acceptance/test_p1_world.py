"""P1 AC-12 .. AC-18: map, A*, weather, resources, plants, animals, dogs."""

from __future__ import annotations

import random

import pytest
from conftest import ROOT, centre_rect, find_tiles, home_rects, in_rect, load_toml

from ai_island.config import SEASONS
from ai_island.world import (
    astar,
    cut_tree,
    plant_crop,
    population,
    remove_animals,
    remove_plant,
    take_stone,
    water_output,
)
from ai_island.world.weather import draw_weather

SEASON_TICKS = 20160
YEAR = 80640


def block(world, rect):
    x0, y0, s = rect
    return [[world.terrain[y0 + j][x0 + i] for i in range(s)] for j in range(s)]


def rot_cw(grid):
    n = len(grid)
    return [[grid[n - 1 - j][i] for j in range(n)] for i in range(n)]


def count_in(world, rect, pred):
    x0, y0, s = rect
    return sum(1 for y in range(y0, y0 + s) for x in range(x0, x0 + s) if pred(world.terrain[y][x]))


# ---------------------------------------------------------------- AC-12


def test_AC12_map_size(sim, cfg):
    w = sim.world
    assert (w.width, w.height) == (80, 80)
    assert len(w.terrain) == 80 and all(len(r) == 80 for r in w.terrain)


def test_AC12_four_homes_identical_after_rotation(sim):
    w = sim.world
    assert len(w.homes) == 4
    base = block(w, home_rects(w)[0])
    rotations = [base]
    for _ in range(3):
        rotations.append(rot_cw(rotations[-1]))
    for rect in home_rects(w)[1:]:
        assert block(w, rect) in rotations
    # initial plants and animals per kind match across homes
    for i in range(1, 4):
        for kind in ("rabbit", "deer", "bird", "chicken", "nest_eggs", "goat", "boar", "fish"):
            assert population(w, kind, f"home_{i}") == population(w, kind, "home_0"), (kind, i)
    for kind in (
        "berries",
        "mushrooms",
        "roots",
        "herbs",
        "healing_herbs",
        "mild_poison",
        "strong_poison",
    ):
        counts = []
        for rect in home_rects(w):
            counts.append(sum(1 for p in w.plants if p.kind == kind and in_rect(p.x, p.y, rect)))
        assert len(set(counts)) == 1, (kind, counts)
    stones = [
        sorted(v for (x, y), v in w.stone.items() if in_rect(x, y, rect)) for rect in home_rects(w)
    ]
    assert all(s == stones[0] for s in stones)


def test_AC12_homes_have_forest_spring_farmland(sim):
    w = sim.world
    for rect in home_rects(w):
        assert count_in(w, rect, lambda t: t == "tree") > 0
        assert count_in(w, rect, lambda t: t == "spring") > 0
        assert count_in(w, rect, lambda t: t.startswith("farmland")) > 0


def test_AC12_centre_richer_than_homes(sim, cfg):
    w = sim.world
    c = centre_rect(cfg)
    c_trees = count_in(w, c, lambda t: t == "tree")
    c_farm = count_in(w, c, lambda t: t.startswith("farmland"))
    c_stone = sum(v for (x, y), v in w.stone.items() if in_rect(x, y, c))
    for rect in home_rects(w):
        assert c_trees > count_in(w, rect, lambda t: t == "tree")
        assert c_farm > count_in(w, rect, lambda t: t.startswith("farmland"))
        assert c_stone > sum(v for (x, y), v in w.stone.items() if in_rect(x, y, rect))


def test_AC12_landmarks_in_centre_and_everything_reachable(sim, cfg):
    w = sim.world
    c = centre_rect(cfg)
    kinds = {lm.kind: lm for lm in w.landmarks}
    assert {"quarry", "lake_dock", "great_tree"} <= set(kinds)
    for lm in kinds.values():
        assert in_rect(lm.x, lm.y, c), lm
    costs = w.cost_grid()
    anchors = [h.anchor for h in w.homes]
    targets = list(anchors) + [(lm.x, lm.y) for lm in w.landmarks]
    for a in anchors:
        for t in targets:
            if t == a:
                continue
            assert astar(costs, a, t) is not None, (a, t)


def _pool_checks(w, pool_zones):
    pool = list(w.unclaimed)
    assert pool
    assert all(isinstance(t, tuple) and len(t) == 2 for t in pool)
    assert pool == sorted(pool, key=lambda t: (t[1], t[0]))
    assert len(set(pool)) == len(pool)
    marks = {(m.x, m.y) for m in w.landmarks}
    for x, y in pool:
        assert w.zone_at(x, y) in pool_zones, (x, y)
        assert w.passable(x, y), (x, y)
        assert (x, y) not in marks, (x, y)
    return pool


def test_AC12_unclaimed_land_pool_nonempty(sim, cfg):
    from ai_island.world import unclaimed_pool

    w = sim.world
    zones = load_toml(ROOT / "config" / "world.toml")["land"]["pool_zones"]
    pool = _pool_checks(w, zones)
    assert unclaimed_pool(w) == pool


def test_AC12_unclaimed_pool_unchanged_after_ticks(sim):
    zones = load_toml(ROOT / "config" / "world.toml")["land"]["pool_zones"]
    before = list(sim.world.unclaimed)
    sim.run(500)
    assert _pool_checks(sim.world, zones) == before


def test_AC12_unclaimed_pool_survives_snapshot_round_trip(sim):
    from ai_island.sim import Simulation

    sim.run(100)
    before = list(sim.world.unclaimed)
    restored = Simulation.from_snapshot(sim.snapshot())
    assert list(restored.world.unclaimed) == before


# ---------------------------------------------------------------- AC-13


def path_cost(costs, path):
    return sum(costs[y][x] for x, y in path[1:])


def test_AC13_astar_lowest_cost():
    costs = [
        [1.0, 1.0, 1.0],
        [9.0, 9.0, 1.0],
        [1.0, 1.0, 1.0],
    ]
    path = astar(costs, (0, 0), (0, 2))
    assert path[0] == (0, 0) and path[-1] == (0, 2)
    assert path_cost(costs, path) == pytest.approx(6.0)
    for a, b in zip(path, path[1:], strict=False):
        assert abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1


def test_AC13_astar_prefers_cheap_detour_and_direct_when_cheaper():
    costs = [[1.0, 5.0, 1.0], [1.0, 1.0, 1.0]]
    path = astar(costs, (0, 0), (2, 0))
    assert path_cost(costs, path) == pytest.approx(4.0)
    costs = [[1.0, 2.0, 1.0], [1.0, 1.0, 1.0]]
    path = astar(costs, (0, 0), (2, 0))
    assert path_cost(costs, path) == pytest.approx(3.0)


def test_AC13_astar_unreachable_is_none():
    costs = [
        [1.0, None, 1.0],
        [1.0, None, 1.0],
        [1.0, None, 1.0],
    ]
    assert astar(costs, (0, 0), (2, 2)) is None
    assert astar([[1.0, 1.0], [1.0, None]], (0, 0), (1, 1)) is None


def test_AC13_astar_random_grids_match_dijkstra():
    import heapq

    rng = random.Random(4)
    for _ in range(30):
        n = 7
        costs = [
            [None if rng.random() < 0.2 else float(rng.choice([1, 1, 2, 3, 5])) for _ in range(n)]
            for _ in range(n)
        ]
        costs[0][0] = 1.0
        costs[n - 1][n - 1] = 1.0
        dist = {(0, 0): 0.0}
        pq = [(0.0, (0, 0))]
        while pq:
            d, (x, y) = heapq.heappop(pq)
            if d > dist[(x, y)]:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < n and 0 <= ny < n and costs[ny][nx] is not None:
                    nd = d + costs[ny][nx]
                    if nd < dist.get((nx, ny), 1e18):
                        dist[(nx, ny)] = nd
                        heapq.heappush(pq, (nd, (nx, ny)))
        path = astar(costs, (0, 0), (n - 1, n - 1))
        if (n - 1, n - 1) not in dist:
            assert path is None
        else:
            assert path_cost(costs, path) == pytest.approx(dist[(n - 1, n - 1)])


# ---------------------------------------------------------------- AC-14


@pytest.mark.slow
def test_AC14_weather_frequencies_over_100_years(cfg):
    rng = random.Random(2024)
    draws_per_season = 100 * (SEASON_TICKS // cfg.world.weather.interval_ticks)
    assert draws_per_season >= 2000
    for season in SEASONS:
        odds = cfg.world.weather.odds[season]
        counts = {"clear": 0, "rain": 0, "storm": 0, "drought": 0}
        for _ in range(draws_per_season):
            counts[draw_weather(rng, odds)] += 1
        for kind, n in counts.items():
            expected = getattr(odds, kind)
            if expected == 0:
                assert n == 0, (season, kind)
            else:
                assert abs(n / draws_per_season - expected) <= 0.05, (season, kind, n)


def test_AC14_simulated_weather_obeys_odds_support(sim, cfg):
    """Drought only ever happens in summer when run through the real tick loop."""
    seen = {}
    for _ in range(YEAR // 720):
        sim.run(720)
        seen.setdefault(sim.clock.season, set()).add(sim.world.weather.current)
    for season in SEASONS:
        allowed = {
            k
            for k in ("clear", "rain", "storm", "drought")
            if getattr(cfg.world.weather.odds[season], k) > 0
        }
        assert seen[season] <= allowed, (season, seen[season])


def test_AC14_flags_and_drought_water(sim):
    w = sim.world
    w.weather.current = "storm"
    f = w.weather.flags
    assert f.stops_outdoor_work and f.puts_out_campfires
    w.weather.current = "clear"
    f = w.weather.flags
    assert not f.stops_outdoor_work and not f.puts_out_campfires
    spring = find_tiles(w, "spring")[0]
    lake = find_tiles(w, "lake")[0]
    w.weather.current = "clear"
    clear_spring, clear_lake = water_output(w, spring), water_output(w, lake)
    assert clear_spring > 0 and clear_lake > 0
    w.weather.current = "drought"
    assert w.weather.flags.water_multiplier < 1.0
    assert water_output(w, spring) < clear_spring
    assert water_output(w, lake) < clear_lake


# ---------------------------------------------------------------- AC-15


def balance():
    return load_toml(ROOT / "config" / "balance.toml")


def test_AC15_cut_tree_regrows(sim):
    w = sim.world
    home = home_rects(w)[0]
    x, y = next((x, y) for (x, y) in find_tiles(w, "tree") if in_rect(x, y, home))
    assert cut_tree(w, (x, y), w.tick)
    assert w.terrain[y][x] != "tree"
    regrow = balance()["trees"]["regrow_ticks"]
    sim.run(regrow + 2880)
    assert w.terrain[y][x] == "tree"


def test_AC15_overcut_area_does_not_regrow(sim):
    w = sim.world
    home = home_rects(w)[0]
    trees = [(x, y) for (x, y) in find_tiles(w, "tree") if in_rect(x, y, home)]
    cut = [p for p in trees if cut_tree(w, p, w.tick)]
    assert len(cut) == len(trees) > 0
    sim.run(balance()["trees"]["regrow_ticks"] * 2)
    back = [p for p in trees if w.terrain[p[1]][p[0]] == "tree"]
    assert back == []


def test_AC15_stone_never_increases(sim):
    w = sim.world
    q = next(lm for lm in w.landmarks if lm.kind == "quarry")
    total = lambda: sum(w.stone.values())  # noqa: E731
    start = total()
    assert start > 0
    pos = next(iter(w.stone))
    got = take_stone(w, pos, 5)
    assert 0 < got <= 5
    after_take = total()
    assert after_take < start
    prev = after_take
    for _ in range(8):
        sim.run(SEASON_TICKS // 4)
        now = total()
        assert now <= prev
        prev = now
    assert q is not None


def test_AC15_crop_ready_within_one_season(sim):
    w = sim.world
    home = home_rects(w)[0]
    x, y = next(p for p in find_tiles(w, "farmland_empty") if in_rect(*p, home))
    plant_crop(w, (x, y), w.tick)
    sim.run(SEASON_TICKS - 100)
    assert sim.clock.season == "spring"
    assert w.terrain[y][x] == "farmland_ready"


def test_AC15_no_crop_growth_in_winter(sim):
    w = sim.world
    sim.run(3 * SEASON_TICKS + 1)
    assert sim.clock.season == "winter"
    home = home_rects(w)[0]
    x, y = next(p for p in find_tiles(w, "farmland_empty") if in_rect(*p, home))
    plant_crop(w, (x, y), w.tick)
    sim.run(SEASON_TICKS - 5000)
    assert sim.clock.season == "winter"
    assert w.terrain[y][x] not in ("farmland_growing", "farmland_ready")


# ---------------------------------------------------------------- AC-16

PLANT_KINDS = [
    "berries",
    "mushrooms",
    "roots",
    "herbs",
    "healing_herbs",
    "mild_poison",
    "strong_poison",
]


def plant_seasons():
    return {k: v["seasons"] for k, v in load_toml(ROOT / "config" / "world.toml")["plants"].items()}


def test_AC16_plants_only_in_their_seasons(sim):
    w = sim.world
    seasons = plant_seasons()
    for si, season in enumerate(SEASONS):
        target = si * SEASON_TICKS + SEASON_TICKS // 2
        sim.run(target - w.tick)
        assert sim.clock.season == season
        for kind in PLANT_KINDS:
            n = sum(1 for p in w.plants if p.kind == kind and p.present)
            if season in seasons[kind]:
                assert n > 0, (kind, season)
            else:
                assert n == 0, (kind, season, n)


@pytest.mark.parametrize("kind", PLANT_KINDS)
def test_AC16_plant_regrows_after_removal(sim, kind):
    w = sim.world
    season = plant_seasons()[kind][0]
    si = SEASONS.index(season)
    sim.run(si * SEASON_TICKS + 1000 - w.tick)
    site = next(p for p in w.plants if p.kind == kind and p.present)
    assert remove_plant(w, (site.x, site.y), w.tick)
    assert not any(p.present for p in w.plants if (p.x, p.y) == (site.x, site.y) and p.kind == kind)
    regrow = balance()["plants"][kind]["regrow_ticks"]
    sim.run(regrow + 1440)
    assert sim.clock.season == season
    assert any(p.present for p in w.plants if (p.x, p.y) == (site.x, site.y) and p.kind == kind)


# ---------------------------------------------------------------- AC-17


@pytest.mark.parametrize("kind", ["rabbit", "chicken"])
def test_AC17_population_grows_in_breeding_season(sim, kind):
    w = sim.world
    start = population(w, kind)
    assert start > 0
    sim.run(SEASON_TICKS - 100)
    assert population(w, kind) > start


def test_AC17_extinct_kind_stays_absent(sim):
    w = sim.world
    delay = balance()["extinction_delay_ticks"]
    sim.run(500)
    assert population(w, "rabbit", "centre") > 0
    remove_animals(w, "rabbit", "centre", w.tick)
    assert population(w, "rabbit", "centre") == 0
    removed_at = w.tick
    while w.tick < removed_at + delay - 1440:
        sim.run(1440)
        assert population(w, "rabbit", "centre") == 0, w.tick - removed_at


def test_AC17_nests_only_in_spring(sim):
    w = sim.world
    assert population(w, "nest_eggs") > 0
    for si, season in enumerate(SEASONS):
        sim.run(si * SEASON_TICKS + SEASON_TICKS // 2 - w.tick)
        assert sim.clock.season == season
        n = population(w, "nest_eggs")
        if season == "spring":
            assert n > 0
        else:
            assert n == 0, season


# ---------------------------------------------------------------- AC-18


def test_AC18_initial_dog_packs(sim, cfg):
    w = sim.world
    assert w.dogs
    packs = {}
    for d in w.dogs:
        packs.setdefault(d.pack, []).append(d)
    for members in packs.values():
        assert 2 <= len(members) <= 4
    homes = home_rects(w)
    for d in w.dogs:
        assert not any(in_rect(d.x, d.y, r) for r in homes), (d.x, d.y)
        assert w.terrain[d.y][d.x] == "tree", (d.x, d.y, w.terrain[d.y][d.x])


def rate(counters, key):
    checks = counters["dog_checks"].get(key, 0)
    moves = counters["dog_moves"].get(key, 0)
    assert checks > 0, key
    return moves / checks


@pytest.mark.slow
def test_AC18_dogs_move_more_at_night_and_in_winter(sim):
    sim.run(YEAR)
    c = sim.world.counters
    summer_day = rate(c, "summer_day")
    assert rate(c, "summer_night") > summer_day
    assert rate(c, "winter_day") > summer_day


def test_AC18_dog_population_grows_slower_than_rabbits(sim):
    w = sim.world
    dogs0, rabbits0 = len(w.dogs), population(w, "rabbit")
    assert dogs0 > 0 and rabbits0 > 0
    sim.run(2 * SEASON_TICKS)
    dogs1, rabbits1 = len(w.dogs), population(w, "rabbit")
    assert rabbits1 / rabbits0 > dogs1 / dogs0
    assert dogs1 >= 1
