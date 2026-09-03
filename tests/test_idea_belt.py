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


def _resettable(scroll, indices, unused_ring):
    """A belt stripped down to what reset() touches, with _layout stubbed out (it
    drives pyglet objects). Slots are plain dicts, as the real ones are."""
    belt = IdeaBelt.__new__(IdeaBelt)
    belt._scroll = scroll
    belt._slots = [{"index": i} for i in indices]
    belt._unused_ring = unused_ring
    belt._layout = lambda: None
    return belt


def test_reset_forgets_what_each_slot_was_showing():
    """The snowflake/BOOK bug: a new ring reuses the same index numbers, so unless
    reset() clears them, a slot keeps the OLD picture while the pool serves the NEW
    word for that index -- a click types a word the player never saw."""
    belt = _resettable(scroll=12.0, indices=[3, 7, 45], unused_ring=False)
    old_pool = belt._pool = object()
    belt.reset()
    assert [slot["index"] for slot in belt._slots] == [None, None, None]
    assert belt._scroll == 0.0
    assert belt._pool is not old_pool


def test_first_reset_keeps_the_ring_the_belt_was_built_with():
    """GameScreen builds the pane, then starts the first game -- that reset must
    not deal (and log) a second ring before the first one is ever played."""
    belt = _resettable(scroll=0.0, indices=[0, 1], unused_ring=True)
    pool = belt._pool = object()
    belt.reset()
    assert belt._pool is pool
    # The next game does deal a fresh one.
    belt.reset()
    assert belt._pool is not pool


def test_one_slot_hangs_off_each_end_of_the_region():
    """The spare slots are what make the belt look continuous rather than
    popping: at any scroll, one item is part-way in and one part-way out."""
    belt = _belt(scroll=3.4, visible=4, height=400.0)
    ys = sorted(p[2] for p in belt.positions())
    assert ys[0] < 0
    assert ys[-1] > 400.0


def _match_belt(pool):
    """A bare belt wrapping `pool`, with no slots -- enough to exercise the
    surface the board's match rule calls (see GameScreen's idea_belt.match rule),
    which is where a missing passthrough shows up."""
    belt = _belt()
    belt._pool = pool
    belt._slots = []
    belt._slot_count = 0
    return belt


def test_the_board_match_surface_reaches_the_pool():
    """The match rule calls clear_word() and active_count() on the BELT, but the
    ring is the pool's -- both have to pass through. A missing passthrough threw
    mid-clear, which pyglet swallows, so the word never listed and the score never
    refreshed even though the picture had already gone."""
    from models.idea_pool import IdeaPool
    deck = [{"image": "", "emoji": "A", "word1": "apple", "word2": ""},
            {"image": "", "emoji": "B", "word1": "bear", "word2": ""}]
    belt = _match_belt(IdeaPool(size=2, deck=deck))
    assert belt.active_count() == 2
    assert belt.clear_word("APPLE") == ["A"]
    assert belt.active_count() == 1
    assert belt.clear_word("APPLE") == []


# --- the hint-debug read-out (idea_belt.source) ------------------------------
def _debug_belt():
    """A bare hint-debug belt: no GL, no slots, just the ring surface the cell
    hint feeds (see views/game_screen_ideahint._feed_idea_hint_belt)."""
    from models.idea_pool import IdeaPool
    belt = _belt()
    belt._slots = []
    belt._slot_count = 0
    belt._hint_debug = True
    belt._targeted = False
    belt._unused_ring = True
    belt._pool = IdeaPool(size=50, deck=[], word_art=[], reason="awaiting click")
    return belt


def test_a_hint_event_replaces_the_whole_debug_ring():
    """The belt answers ONE cell -- the one most recently asked about -- so the
    second double click must not leave the first cell's ideas on the conveyor."""
    belt = _debug_belt()
    assert belt.hint_debug is True
    assert belt._pool.size() == 0
    belt.show_hint_ideas([("SHARK", "A"), ("SHARE", "B")], "hint debug: SH")
    # Set, not list: the default order rule shuffles the ring.
    assert set(belt._pool.words()) == {"SHARK", "SHARE"}
    belt.show_hint_ideas([("ARK", "C")], "hint debug: AR")
    assert belt._pool.words() == ["ARK"]
    assert belt._scroll == 0.0
    # A hint toggled off, or a cell with nothing to say: empty, no message.
    belt.show_hint_ideas([], "hint debug: AR")
    assert belt._pool.size() == 0


def test_a_hint_debug_belt_refuses_board_stocking():
    """Its ring belongs to the last double click, so a formation-time restock
    would only be thrown away by the first one."""
    belt = _debug_belt()
    belt.show_hint_ideas([("ARK", "C")], "hint debug: AR")
    assert belt.restock({"spellable_multigram": ["APPLE"]}) == {}
    assert belt._pool.words() == ["ARK"]


def test_the_click_rule_decides_whether_a_picture_types_its_word():
    """idea_belt.click off leaves the belt a pure read-out: nothing is typed, and
    the click is NOT consumed, so it falls through to whatever is behind it."""
    from models.idea_pool import IdeaItem
    picked = []
    belt = _belt()
    belt._on_pick = picked.append
    item = IdeaItem("SHARK", "A", "", "A")
    assert belt._rule_idea_click_types_word(item) is True
    assert picked == ["SHARK"]
    assert belt._rule_idea_click_off(item) is False
    assert picked == ["SHARK"]
