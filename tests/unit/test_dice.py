"""Tests for SeededRNG determinism and state persistence."""

from game.core.dice import SeededRNG


def test_same_seed_same_results():
    rng1 = SeededRNG(42)
    rng2 = SeededRNG(42)
    for _ in range(20):
        assert rng1.d(20) == rng2.d(20)


def test_different_seed_different_results():
    rng1 = SeededRNG(1)
    rng2 = SeededRNG(2)
    results1 = [rng1.d(20) for _ in range(10)]
    results2 = [rng2.d(20) for _ in range(10)]
    assert results1 != results2


def test_d_range():
    rng = SeededRNG(99)
    rolls = [rng.d(6) for _ in range(200)]
    assert all(1 <= r <= 6 for r in rolls)
    assert min(rolls) == 1
    assert max(rolls) == 6


def test_random_float_range():
    rng = SeededRNG(7)
    floats = [rng.random_float() for _ in range(100)]
    assert all(0.0 <= f < 1.0 for f in floats)


def test_uniform_range():
    rng = SeededRNG(7)
    vals = [rng.uniform(0.9, 1.1) for _ in range(100)]
    assert all(0.9 <= v <= 1.1 for v in vals)


def test_state_save_restore():
    rng = SeededRNG(42)
    rng.d(20)
    rng.d(20)
    saved = rng.get_state()

    next_three = [rng.d(20) for _ in range(3)]

    rng.set_state(saved)
    replayed = [rng.d(20) for _ in range(3)]

    assert next_three == replayed


def test_state_restore_across_instances():
    rng1 = SeededRNG(42)
    for _ in range(5):
        rng1.d(20)
    state = rng1.get_state()

    rng2 = SeededRNG(0)
    rng2.set_state(state)

    assert rng1.d(20) == rng2.d(20)
    assert rng1.d(6) == rng2.d(6)
