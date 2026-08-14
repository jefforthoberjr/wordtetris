"""SandTimerField's render bookkeeping, after its fill drawing moved onto the
shared views/rising_fill.RisingFill.

The field owns the TIMING; the overlay owns the shapes. What has to stay true is
the handover: every actively-timing cell gets its current fraction each frame, and
a cell that stops timing (expired / used in a word / swapped away) has its fill
dropped rather than left on the board. A fake overlay stands in for RisingFill,
whose real Polygons need a GL context.
"""
from views.moving_mode import SandTimerField


class _FakeFill:
    def __init__(self):
        self.fractions = {}

    def positions(self):
        return list(self.fractions)

    def set_fraction(self, cell, fraction):
        self.fractions[cell] = fraction

    def remove(self, cell):
        self.fractions.pop(cell, None)


def _field(seconds=10.0, delay=0.0):
    """A bare field with the overlay pre-injected, so _fill_overlay never reaches
    for the (absent) game screen's board and batch."""
    field = SandTimerField.__new__(SandTimerField)
    field._gs = None
    field._count = 1
    field._seconds = seconds
    field._delay = delay
    field._timers = {}
    field._shapes = {}
    field._fill = _FakeFill()
    return field


def test_each_timing_cell_gets_its_current_fraction():
    field = _field(seconds=10.0)
    field._timers = {(1, 1): 2.5, (2, 2): 5.0}
    field._render()
    assert field._fill.fractions == {(1, 1): 0.25, (2, 2): 0.5}


def test_a_cell_that_stops_timing_loses_its_fill():
    field = _field(seconds=10.0)
    field._timers = {(1, 1): 5.0, (2, 2): 5.0}
    field._render()
    # (2,2) fossilized / was used in a word / swapped away -- it stops timing.
    del field._timers[(2, 2)]
    field._render()
    assert (2, 2) not in field._fill.fractions
    assert field._fill.fractions == {(1, 1): 0.5}


def test_the_silent_delay_holds_the_fill_at_zero():
    # A timer in its lead-in reports 0, so the overlay draws nothing for it yet.
    field = _field(seconds=10.0, delay=4.0)
    field._timers = {(1, 1): 3.0}
    field._render()
    assert field._fill.fractions == {(1, 1): 0.0}


def test_the_fraction_never_exceeds_one():
    field = _field(seconds=10.0)
    field._timers = {(1, 1): 999.0}
    field._render()
    assert field._fill.fractions == {(1, 1): 1.0}
