"""P1 AC-7 .. AC-11: snapshot round trip, determinism, streams, speed, clock."""

from __future__ import annotations

import time

import pytest
from conftest import LOGS, cli, db_events

from ai_island.rng import Streams
from ai_island.world.clock import Clock

YEAR = 80_640


@pytest.mark.parametrize(
    "t_ticks,m_ticks", [pytest.param(20161, 1000, marks=pytest.mark.slow), (1439, 2000)]
)
def test_AC7_resume_equals_uninterrupted(t_ticks, m_ticks):
    import shutil

    from conftest import RUNS

    a, b = "acc_ac7_split", "acc_ac7_whole"
    for n in (a, b):
        shutil.rmtree(RUNS / n, ignore_errors=True)
    try:
        assert (
            cli(
                "headless",
                "--run",
                a,
                "--ticks",
                str(t_ticks),
                "--seed",
                "5",
                env_extra={"PYTHONHASHSEED": "1"},
            ).returncode
            == 0
        )
        r = cli("resume", a, "--ticks", str(m_ticks), env_extra={"PYTHONHASHSEED": "777"})
        assert r.returncode == 0, r.stderr
        r = cli(
            "headless",
            "--run",
            b,
            "--ticks",
            str(t_ticks + m_ticks),
            "--seed",
            "5",
            env_extra={"PYTHONHASHSEED": "42"},
        )
        assert r.returncode == 0, r.stderr
        ea, eb = db_events(a), db_events(b)
        assert len(ea) > 0
        assert ea == eb
    finally:
        for n in (a, b):
            shutil.rmtree(RUNS / n, ignore_errors=True)


def _year_run(name, seed, hashseed="0"):
    r = cli(
        "headless",
        "--run",
        name,
        "--ticks",
        str(YEAR),
        "--seed",
        str(seed),
        env_extra={"PYTHONHASHSEED": hashseed},
    )
    assert r.returncode == 0, r.stderr
    return r


@pytest.mark.slow
def test_AC8_full_year_deterministic_and_seed_sensitive():
    import shutil

    from conftest import RUNS

    names = ["acc_ac8_a", "acc_ac8_b", "acc_ac8_c"]
    for n in names:
        shutil.rmtree(RUNS / n, ignore_errors=True)
    try:
        _year_run(names[0], 11, "1")
        _year_run(names[1], 11, "99")
        _year_run(names[2], 12)
        ea, eb, ec = (db_events(n) for n in names)
        assert len(ea) > 0
        assert ea == eb
        assert ea != ec
    finally:
        for n in names:
            shutil.rmtree(RUNS / n, ignore_errors=True)


def test_AC9_streams_are_independent():
    s1 = Streams(7)
    s2 = Streams(7)
    for _ in range(500):
        s1.get("alpha").random()
    base = [s2.get("beta").random() for _ in range(20)]
    after = [s1.get("beta").random() for _ in range(20)]
    assert base == after
    # drawing from beta must not change alpha either
    s3, s4 = Streams(7), Streams(7)
    for _ in range(50):
        s3.get("beta").random()
    assert [s3.get("alpha").random() for _ in range(10)] == [
        s4.get("alpha").random() for _ in range(10)
    ]
    # different seeds and different names differ
    assert Streams(7).get("alpha").random() != Streams(8).get("alpha").random()
    assert Streams(7).get("alpha").random() != Streams(7).get("beta").random()


def test_AC9_stream_state_round_trip():
    s = Streams(3)
    for _ in range(10):
        s.get("x").random()
    state = s.state()
    s2 = Streams.from_state(state)
    assert [s.get("x").random() for _ in range(5)] == [s2.get("x").random() for _ in range(5)]


@pytest.mark.slow
def test_AC10_full_year_under_five_minutes(run_name):
    t0 = time.perf_counter()
    _year_run(run_name, 3)
    elapsed = time.perf_counter() - t0
    LOGS.mkdir(exist_ok=True)
    (LOGS / "ac10_year_seconds.txt").write_text(f"{elapsed:.2f}\n")
    print(f"AC-10 persisted full year: {elapsed:.2f} s")
    assert elapsed < 300


def test_AC11_tick_zero(cfg):
    c = Clock.at(0, cfg.world.clock)
    assert (c.year, c.season, c.week, c.day, c.hour, c.minute) == (1, "spring", 1, 1, 0, 0)


def test_AC11_day_length_and_seasons(cfg):
    ck = cfg.world.clock
    assert ck.ticks_per_day == 1440
    assert Clock.at(1439, ck).day == 1
    assert Clock.at(1440, ck).day == 2
    # (tick, season, week)
    cases = [
        (14 * 1440 - 1, "spring", 2),
        (7 * 1440, "spring", 2),
        (14 * 1440, "summer", 3),
        (28 * 1440 - 1, "summer", 4),
        (28 * 1440, "autumn", 5),
        (42 * 1440 - 1, "autumn", 6),
        (42 * 1440, "winter", 7),
        (56 * 1440 - 1, "winter", 8),
    ]
    for tick, season, week in cases:
        c = Clock.at(tick, ck)
        assert (c.season, c.week, c.year) == (season, week, 1), tick
    assert YEAR == 56 * 1440
    c = Clock.at(YEAR, ck)
    assert (c.year, c.season, c.week, c.day) == (2, "spring", 1, 1)
    c = Clock.at(YEAR - 1, ck)
    assert (c.year, c.season) == (1, "winter")


def test_AC11_night_follows_config(cfg):
    ck = cfg.world.clock
    start, end = ck.night_start_hour, ck.night_end_hour
    for hour in range(24):
        for minute in (0, 59):
            c = Clock.at(hour * 60 + minute, ck)
            assert c.hour == hour
            expected = (hour >= start or hour < end) if start > end else (start <= hour < end)
            assert c.is_night == expected, (hour, minute)
    assert Clock.at(12 * 60, ck).is_night is False
    assert Clock.at(2 * 60, ck).is_night is True
    # a changed config changes the answer
    changed = ck.model_copy(update={"night_start_hour": 10, "night_end_hour": 12})
    assert Clock.at(11 * 60, changed).is_night is True
    assert Clock.at(2 * 60, changed).is_night is False


def test_AC11_simulation_clock_advances(sim):
    sim.run(1440)
    c = sim.clock
    assert (c.tick, c.day, c.season) == (1440, 2, "spring")
