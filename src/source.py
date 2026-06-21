"""Random-source seam -- the single swap point for every nondeterministic draw
the game makes (gram picks, piece-pool order, formation placement, tie-breaks).

Why this exists: deterministic replay. A separate replay tool (a later chunk)
needs to reproduce -- or deliberately override -- the random choices a recorded
session made. Funnelling all randomness through one object means replay can swap
in a ReplaySource that returns recorded/mocked outcomes instead of rolling, with
no change at the call sites.

The default Source just delegates to the `random` module, so behavior is exactly
as before this seam existed (the "preserve the primitive version" rule: the
default IS the old behavior). The module RNG is seeded per session in
session_log.start_session, so even the plain Source replays identically from the
recorded seed; the seam is what lets replay go further and mock specific draws.

Call sites bind the `rand` accessor (not the instance) so a swap takes effect:

    from source import rand
    letter = rand().choice(letters)

Swap with set_active(ReplaySource(...)); reset() restores the default."""
import random


class Source:
    """Default (record) random source: every method delegates to the seeded
    `random` module. A replay source subclasses this and overrides the methods to
    hand back recorded outcomes. The method set is exactly what the game's call
    sites use -- add a method here when a new kind of draw needs routing."""

    def choice(self, seq):
        return random.choice(seq)

    def choices(self, population, weights=None, k=1):
        return random.choices(population, weights=weights, k=k)

    def randint(self, a, b):
        return random.randint(a, b)

    def randrange(self, n):
        return random.randrange(n)

    def random(self):
        return random.random()

    def sample(self, population, k):
        return random.sample(population, k)

    def shuffle(self, seq):
        random.shuffle(seq)


# The active source. One stable object the whole game draws through; replay
# swaps it via set_active() before a game is built. Accessed through rand() so
# call sites always see the current one rather than a stale import binding.
_active = Source()


def rand():
    """The active random source. Call this at each draw site so a replay swap is
    seen: `rand().choice(seq)`."""
    return _active


def set_active(source):
    """Install `source` as the active random source (replay uses this)."""
    global _active
    _active = source


def reset():
    """Restore the default record Source (real randomness)."""
    global _active
    _active = Source()
