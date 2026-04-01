import random


class SeededRNG:
    """Seeded random number generator for reproducible combat outcomes."""

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)
        self._seed = seed

    @property
    def seed(self) -> int:
        return self._seed

    def d(self, n: int) -> int:
        """Roll 1dN (1 to n inclusive)."""
        return self._rng.randint(1, n)

    def random_float(self) -> float:
        """Return a float in [0.0, 1.0)."""
        return self._rng.random()

    def uniform(self, lo: float, hi: float) -> float:
        return self._rng.uniform(lo, hi)

    def get_state(self) -> tuple:
        return self._rng.getstate()

    def set_state(self, state: tuple) -> None:
        self._rng.setstate(state)
