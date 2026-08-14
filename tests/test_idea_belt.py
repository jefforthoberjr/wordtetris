"""The idea belt's motion: two columns, one ring.

Only the geometry is tested. IdeaBelt's circles/labels need a GL context, so
these build a bare instance (__new__) with just the fields positions() reads --
the same trick test_sand_timer_render uses for RisingFill. What has to stay true
is the illusion the belt sells: the columns run in OPPOSITE directions, and they
are windows onto ONE loop, the down column trailing the up column by
idea_belt.window_offset items.
"""
from views.idea_belt import IdeaBelt


def _belt(scroll=0.0, visible=4, offset=15, y=0.0, height=400.0):
    belt = IdeaBelt.__new__(IdeaBelt)
    belt._scroll = scroll
    belt._visible = visible
    belt._offset = offset
    belt._y = y
    belt._height = height
    belt._band = height / visible
    belt._slot_count = visible + 2
    return belt


def test_up_column_rises_and_down_column_falls():
    # Track ONE ring item (index 2) across half a band of travel, in each column
    # at the time that column is showing it -- the up column early on, the down
    # column window_offset items later.
    up_before = [p[2] for p in _belt(scroll=2.0).positions() if p[1] == 2][0]
    up_after = [p[2] for p in _belt(scroll=2.5).positions() if p[1] == 2][0]
    down_before = [p[4] for p in _belt(scroll=17.0).positions() if p[3] == 2][0]
    down_after = [p[4] for p in _belt(scroll=17.5).positions() if p[3] == 2][0]
    assert up_after > up_before
    assert down_after < down_before


def test_down_column_trails_the_up_column_by_the_window_offset():
    belt = _belt(scroll=40.0, offset=15)
    ups = [p[1] for p in belt.positions()]
    downs = [p[3] for p in belt.positions()]
    for up, down in zip(ups, downs):
        assert up - down == 15


def test_an_item_leaving_the_top_of_the_up_column_returns_on_the_down_column():
    """The whole point of one shared ring: item N exits the up column at
    scroll = N + visible_items, and shows up at the TOP of the down column at
    scroll = N + window_offset -- the same picture, seen later."""
    visible, offset, height = 4, 15, 400.0
    exits_up = _belt(scroll=7.0 + visible, visible=visible,
                     offset=offset, height=height)
    top_of_up = [p[2] for p in exits_up.positions() if p[1] == 7][0]
    assert top_of_up == height

    enters_down = _belt(scroll=7.0 + offset, visible=visible,
                        offset=offset, height=height)
    top_of_down = [p[4] for p in enters_down.positions() if p[3] == 7][0]
    assert top_of_down == height


def test_one_slot_hangs_off_each_end_of_the_region():
    """The spare slots are what make the belt look continuous rather than
    popping: at any scroll, one item is part-way in and one part-way out."""
    belt = _belt(scroll=3.4, visible=4, height=400.0)
    ys = sorted(p[2] for p in belt.positions())
    assert ys[0] < 0
    assert ys[-1] > 400.0
