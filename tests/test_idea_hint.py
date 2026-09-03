"""The double-click-a-cell-for-an-idea hint (game_screen.idea_hint_*).

Two back-to-back left clicks on one PLACED multigram cell paint a half-faded
emoji behind its letters: a picture of a word that cell could help spell, given
the rest of the board.

What has to stay true: the click is never CONSUMED (every mode's own click
handling must survive), the offered word is one the board can really build
THROUGH that cell (a hint you cannot follow is a lie), and the live piece is
never a target -- left-click is how a piece is moved.
"""
import config
from starting_coverage import sample_words_using_gram
from views import game_screen as gs


class _FakeGram:
    def __init__(self, text):
        self.text = text
        self.is_wild = False


class _Board:
    """Only what the hint asks: which cells are occupied, what gram each holds,
    which cell a pixel is in, and where a cell's middle is."""

    def __init__(self, grams, cell_size=40):
        self._grams = dict(grams)
        self._cell_size = cell_size

    def occupied_cells(self):
        return list(self._grams.keys())

    def gram_at(self, x, y):
        text = self._grams.get((x, y))
        return None if text is None else _FakeGram(text)

    def cell_at(self, px, py):
        return (int(px // self._cell_size), int(py // self._cell_size))

    def cell_visual_center(self, x, y):
        half = self._cell_size / 2
        return (x * self._cell_size + half, y * self._cell_size + half)


def _with_rules(**overrides):
    rules = config.CONFIG.setdefault("rules", {})
    for key, value in overrides.items():
        rules[key.replace("__", ".")] = value


def _restore():
    base = config.load_config()
    config.CONFIG.clear()
    config.CONFIG.update(base)


def _screen(grams, digram="rule_idea_hint_digram_on",
            trigram="rule_idea_hint_trigram_on"):
    _with_rules(game_screen__idea_hint_digram=digram,
                game_screen__idea_hint_trigram=trigram)
    screen = gs.GameScreen.__new__(gs.GameScreen)
    screen._board = _Board(grams)
    screen._cell_size = 40
    screen._buttons = {"move_primary": 1}
    screen._fossil_is_wall_rule = lambda cell: False
    screen._word_length_rule = lambda word, path: len(word) >= 3
    # A METHOD, matching GameScreen -- not an attribute. Modelling it as a plain
    # object here is what let a real bug (reading the method without calling it,
    # so the live piece never excluded anything) pass this suite once already.
    screen._current_piece = lambda: None
    screen._setup_idea_hint()
    # The glyph is the one part needing a GL context; the tests care about WHICH
    # word is offered and when, so record instead of drawing.
    screen._shown = []

    def _show(cell, word):
        # Mirrors the real _show_idea_hint's state EXACTLY apart from the Label --
        # the gram is part of it, since that is what _prune_idea_hints compares.
        screen._idea_hints[cell] = {"label": None, "word": word,
                                    "gram": screen._board.gram_at(*cell).text.upper()}
        screen._shown.append((cell, word))
    screen._show_idea_hint = _show

    def _hide(cell, action="hide"):
        state = screen._idea_hints.pop(cell, None)
        if state is not None:
            screen._shown.append((cell, None))
    screen._hide_idea_hint = _hide
    return screen


# --- the matcher (starting_coverage.sample_words_using_gram) ---------------
def test_the_word_must_use_the_clicked_gram_as_a_whole_segment():
    """SHARK counts for an ARK cell only because the board can cut it SH + ARK.
    A word that merely CONTAINS those letters, but whose board cut spells them
    out of single cells, is not an idea the player can act on."""
    grams = {"SH": 1, "ARK": 1, "A": 1, "R": 1, "K": 1, "P": 1}
    accept = lambda word, cells: len(word) >= 3
    found = sample_words_using_gram(["SHARK", "PARK"], grams, "ARK", accept, 10)
    assert "SHARK" in found and "PARK" in found
    # With no ARK cell the same words are unreachable through that gram.
    assert sample_words_using_gram(["SHARK"], {"SH": 1, "A": 1, "R": 1, "K": 1},
                                   "ARK", accept, 10) == []


def test_a_word_the_board_lacks_the_letters_for_is_never_offered():
    """The hint is a promise the board can keep: the OTHER cells have to be there
    too, not just the clicked one."""
    accept = lambda word, cells: len(word) >= 3
    assert sample_words_using_gram(["SHARK"], {"ARK": 1}, "ARK", accept, 10) == []


def test_the_supply_is_counted_not_just_matched():
    """Two ARK cells are needed for a word wanting the gram twice; one is not
    enough, even though the gram is 'on the board'."""
    accept = lambda word, cells: len(word) >= 3
    one = sample_words_using_gram(["ARKARK"], {"ARK": 1}, "ARK", accept, 10)
    two = sample_words_using_gram(["ARKARK"], {"ARK": 2}, "ARK", accept, 10)
    assert one == [] and two == ["ARKARK"]


# --- the double click ------------------------------------------------------
def test_two_clicks_on_one_cell_raise_a_hint_and_two_more_clear_it():
    try:
        screen = _screen({(0, 0): "SH", (1, 0): "ARK", (2, 0): "P"})
        screen._pick_idea_hint_word = lambda text: "SHARK"
        assert screen._note_idea_hint_click(50, 10, 1) is False   # first click
        assert screen._note_idea_hint_click(50, 10, 1) is True    # the pair
        assert (1, 0) in screen._idea_hints
        assert screen._note_idea_hint_click(50, 10, 1) is False
        assert screen._note_idea_hint_click(50, 10, 1) is True
        assert (1, 0) not in screen._idea_hints
    finally:
        _restore()


def test_clicks_on_two_different_cells_are_not_a_double():
    """The ordinary move/select click pattern must stay silent -- a player picking
    cell A then cell B has not asked for anything."""
    try:
        screen = _screen({(0, 0): "SH", (1, 0): "ARK"})
        screen._pick_idea_hint_word = lambda text: "SHARK"
        screen._note_idea_hint_click(10, 10, 1)
        assert screen._note_idea_hint_click(50, 10, 1) is False
        assert screen._idea_hints == {}
    finally:
        _restore()


def test_a_third_click_does_not_toggle_again():
    """Clicks pair up rather than every click after the first flipping the hint,
    which would make the picture flicker on a rapid series of clicks."""
    try:
        screen = _screen({(1, 0): "ARK"})
        screen._pick_idea_hint_word = lambda text: "SHARK"
        screen._note_idea_hint_click(50, 10, 1)
        screen._note_idea_hint_click(50, 10, 1)
        assert screen._note_idea_hint_click(50, 10, 1) is False
        assert (1, 0) in screen._idea_hints
    finally:
        _restore()


def test_the_right_button_never_raises_a_hint():
    """Right-click belongs to gram manipulation; the hint is a left-click verb."""
    try:
        screen = _screen({(1, 0): "ARK"})
        screen._pick_idea_hint_word = lambda text: "SHARK"
        screen._note_idea_hint_click(50, 10, 4)
        assert screen._note_idea_hint_click(50, 10, 4) is False
        assert screen._idea_hints == {}
    finally:
        _restore()


# --- which cells qualify ---------------------------------------------------
def test_a_unigram_cell_never_offers_a_hint():
    """One letter needs no idea, and every word contains one."""
    try:
        screen = _screen({(0, 0): "P"})
        screen._pick_idea_hint_word = lambda text: "SHARK"
        assert screen._toggle_idea_hint((0, 0)) is False
    finally:
        _restore()


def test_the_digram_and_trigram_slots_are_independent():
    """Separate rules per gram size: a mode may prompt on the digrams players miss
    most and leave the visually obvious trigrams alone."""
    try:
        screen = _screen({(0, 0): "SH", (1, 0): "ARK"},
                         trigram="rule_idea_hint_trigram_off")
        screen._pick_idea_hint_word = lambda text: "SHARK"
        assert screen._toggle_idea_hint((0, 0)) is True     # digram on
        assert screen._toggle_idea_hint((1, 0)) is False    # trigram off
    finally:
        _restore()


def test_a_cell_the_board_can_spell_nothing_through_shows_nothing():
    """No word, no picture -- and no crash. Logged as a 'none' so a player report
    of 'the hint does nothing' is greppable."""
    try:
        screen = _screen({(1, 0): "ARK"})
        screen._pick_idea_hint_word = lambda text: ""
        assert screen._toggle_idea_hint((1, 0)) is False
        assert screen._idea_hints == {}
    finally:
        _restore()


def test_the_live_piece_is_never_a_hint_target():
    """Left-click is how a piece is MOVED, so a double click on the live piece is
    ordinary movement -- the hint is a placed-cell verb only."""
    class _Piece:
        def get_cell_positions(self):
            return [(1, 0)]
    try:
        screen = _screen({(1, 0): "ARK"})
        screen._current_piece = lambda: _Piece()
        screen._pick_idea_hint_word = lambda text: "SHARK"
        assert screen._toggle_idea_hint((1, 0)) is False
    finally:
        _restore()


def test_a_new_game_takes_every_hint_off_the_board():
    try:
        screen = _screen({(1, 0): "ARK"})
        screen._pick_idea_hint_word = lambda text: "SHARK"
        screen._toggle_idea_hint((1, 0))
        assert screen._idea_hints
        # The stub hints carry no real Label, so hand reset_idea_hints something
        # with the one method it calls -- what is under test is that the dict and
        # the click pairing are both cleared, not pyglet teardown.
        class _Stub:
            def delete(self):
                pass
        for state in screen._idea_hints.values():
            state["label"] = _Stub()
        screen.reset_idea_hints()
        assert screen._idea_hints == {}
        assert screen._idea_hint_last_cell is None
    finally:
        _restore()


# --- a hint outlives neither its cell nor its gram -------------------------
def test_clearing_the_cell_takes_its_hint_off_the_board():
    """The bug this guards: spell the word the hint suggested, the cell leaves,
    and the picture stayed floating over an empty square."""
    try:
        screen = _screen({(1, 0): "ARK"})
        screen._pick_idea_hint_word = lambda text: "SHARK"
        screen._toggle_idea_hint((1, 0))
        assert (1, 0) in screen._idea_hints
        del screen._board._grams[(1, 0)]        # the word cleared that cell
        screen._prune_idea_hints()
        assert screen._idea_hints == {}
    finally:
        _restore()


def test_a_changed_gram_also_drops_the_hint():
    """A partial clear (or a right-click doubling) leaves the cell holding
    something else, so the old picture is now a word the player CANNOT build --
    the one thing this feature must never show."""
    try:
        screen = _screen({(1, 0): "ARK"})
        screen._pick_idea_hint_word = lambda text: "SHARK"
        screen._toggle_idea_hint((1, 0))
        screen._board._grams[(1, 0)] = "AR"     # ARK relabeled down to AR
        screen._prune_idea_hints()
        assert screen._idea_hints == {}
    finally:
        _restore()


def test_an_untouched_cell_keeps_its_hint_across_ticks():
    """The sweep runs every frame, so it must not churn the labels of hints whose
    cells are fine."""
    try:
        screen = _screen({(1, 0): "ARK"})
        screen._pick_idea_hint_word = lambda text: "SHARK"
        screen._toggle_idea_hint((1, 0))
        for _tick in range(5):
            screen._prune_idea_hints()
        assert (1, 0) in screen._idea_hints
        assert screen._idea_hints[(1, 0)]["word"] == "SHARK"
    finally:
        _restore()
