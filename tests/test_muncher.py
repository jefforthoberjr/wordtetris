"""Word-muncher mode (game_screen.mode: rule_mode_muncher): walking the board and
eating grams.

Two halves, matching where the code lives. MuncherMovingMode owns the character
and the word buffer, tested here against fakes (a bare __new__ instance, so no GL
window is needed for the sprite). MuncherMixin._muncher_eat owns what a bite does
to the BOARD, tested against a bare __new__ GameScreen the same way the selection
and cell-health tests do it.
"""

from views import moving_mode as mm
from views.game_screen import GameScreen


# --- fakes -----------------------------------------------------------------
class _Sprite:
    """Stand-in for MuncherSprite: records the calls the mode makes and lets a
    test pin whether a step is still animating, or whether a fade is running."""
    def __init__(self, stepping=False, fading=False, hidden=False):
        self.locked = stepping
        self.steps = []
        self.chews = 0
        self.placed = []
        self.fade_ins = 0
        self.fade_outs = 0
        self.belly = 0
        self._fading = fading
        self._hidden = hidden

    def stepping(self):
        return self.locked

    def fading(self):
        return self._fading

    def hidden(self):
        return self._hidden

    def place(self, x, y):
        self.placed.append((x, y))

    def fade_in(self):
        self.fade_ins += 1
        self._fading = False
        self._hidden = False

    def fade_out(self):
        self.fade_outs += 1
        self._hidden = True

    def set_belly(self, size):
        self.belly = size

    def belly_size(self):
        return self.belly

    def step_to(self, x, y):
        self.steps.append((x, y))

    def chew(self):
        self.chews += 1

    def tick(self, dt):
        pass


class _Board:
    """Rectangular board of grams: {(x, y): text}. Absent key = empty cell."""
    def __init__(self, width=4, height=3, grams=None):
        self.width = width
        self.height = height
        self.grams = dict(grams or {})

    def is_valid(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def cell_visual_center(self, x, y):
        return (x * 10.0, y * 10.0)

    def center_cell(self):
        """Mirrors SquareGrid.center_cell -- the spawn rules ask the board for its
        own center, so the fake has to answer the same way the real grids do."""
        return ((self.width - 1) // 2, (self.height - 1) // 2)

    def gram_at(self, x, y):
        text = self.grams.get((x, y))
        result = None
        if text is not None:
            result = _Gram(text)
        return result

    def clear_cell(self, x, y):
        self.grams.pop((x, y), None)


class _Gram:
    def __init__(self, text, is_wild=False):
        self.text = text
        self.is_wild = is_wild


class _Pane:
    def __init__(self):
        self.typed = []
        self.emptied = False       # pin True to fake a Clear-word button press

    def on_text(self, text):
        self.typed.append(text)

    def is_empty(self):
        return self.emptied


class _GS:
    """The GameScreen surface MuncherMovingMode reaches while walking + eating."""
    def __init__(self, board):
        self._board = board
        self._moving_side_pane = _Pane()
        self._cell_size = 10
        self.eaten = []
        self.submitted = []
        self.forced = []

    def _muncher_step_rule(self, symbol, modifiers, x, y):
        # Square-grid geometry, spelled out so the test does not depend on the
        # controls.yaml bindings: the symbol IS the (dx, dy) step.
        step = None
        if symbol is not None:
            step = (x + symbol[0], y + symbol[1])
        return step

    def _muncher_eat(self, pos):
        # Records the bite and returns whatever the fake board holds there.
        self.eaten.append(pos)
        text = self._board.grams.get(pos, "")
        self._board.clear_cell(*pos)
        return text

    def _muncher_submit(self, word, path, segments):
        self.submitted.append((word, list(path), list(segments)))

    def _muncher_forced_clear(self, word, path, segments):
        self.forced.append((word, list(path), list(segments)))


def _mode(board, pos=(1, 1), stepping=False, dead_end=False, grace=1):
    """A MuncherMovingMode wired to fakes, standing on `pos`. The dead-end cap is
    OFF by default so the walking / eating tests never trip it; the cap's own
    tests turn it on."""
    mode = mm.MuncherMovingMode.__new__(mm.MuncherMovingMode)
    mode._gs = _GS(board)
    mode._sprite = _Sprite(stepping)
    mode._pos = pos
    mode._buffer = []
    mode._grace_left = None
    mode._dead_end_rule = dead_end
    mode._dead_end_grace = grace
    mode._respawn_to = None
    mode._glyph_overlay = None
    mode._spawn_rule = mode._rule_muncher_spawn_center
    mode._belly_rule = mode._rule_muncher_belly_off
    mode._belly_letters = 3
    return mode


# --- walking ---------------------------------------------------------------
def test_step_moves_him_and_starts_the_glide():
    mode = _mode(_Board())
    mode._walk_to((2, 1))
    assert mode._pos == (2, 1)
    # The glide targets the VISUAL center of the cell he stepped onto.
    assert mode._sprite.steps == [(20.0, 10.0)]


def test_step_is_refused_while_the_previous_one_is_still_animating():
    # The step lockout: input is discrete, so a mashed arrow must not outrun the
    # animation and leave him drawn between two cells.
    mode = _mode(_Board(), stepping=True)
    mode._walk_to((2, 1))
    assert mode._pos == (1, 1)
    assert mode._sprite.steps == []


def test_step_off_the_board_is_refused():
    mode = _mode(_Board(width=4, height=3), pos=(3, 1))
    mode._walk_to((4, 1))
    assert mode._pos == (3, 1)
    assert mode._sprite.steps == []


def test_he_may_walk_onto_and_rest_in_an_empty_cell():
    # Eaten cells are holes, not walls -- he walks over and stands in them.
    board = _Board(grams={(1, 1): "CAT"})
    mode = _mode(board, pos=(1, 1))
    mode._walk_to((2, 1))          # (2, 1) holds no gram at all
    assert mode._pos == (2, 1)


# --- eating ----------------------------------------------------------------
def test_eating_banks_the_gram_and_shows_it_in_the_pane():
    board = _Board(grams={(1, 1): "CAT"})
    mode = _mode(board, pos=(1, 1))
    mode._eat()
    assert mode.word() == "CAT"
    assert mode._gs._moving_side_pane.typed == ["CAT"]
    assert mode._sprite.chews == 1


def test_eating_several_cells_concatenates_them_in_bite_order():
    board = _Board(grams={(1, 1): "C", (2, 1): "A", (3, 1): "T"})
    mode = _mode(board, pos=(1, 1))
    mode._eat()
    mode._walk_to((2, 1))
    mode._eat()
    mode._walk_to((3, 1))
    mode._eat()
    assert mode.word() == "CAT"


def test_biting_an_empty_cell_still_chews_but_adds_no_letters():
    # Chewing air is a legal move -- the animation plays, the word is untouched.
    board = _Board(grams={(1, 1): "CAT"})
    mode = _mode(board, pos=(1, 1))
    mode._eat()
    mode._eat()                    # the cell is a hole now
    assert mode.word() == "CAT"
    assert mode._sprite.chews == 2
    assert mode._gs._moving_side_pane.typed == ["CAT"]


def test_active_cells_reports_the_cell_he_stands_on():
    # The engine hides the hover preview under the character, as it does under a
    # live piece.
    mode = _mode(_Board(), pos=(2, 0))
    assert mode.active_cells() == [(2, 0)]


# --- the board side of a bite (MuncherMixin) --------------------------------
def _eat_game(board, fossilized=()):
    g = GameScreen.__new__(GameScreen)
    g._board = board
    g._fossilized_cells = set(fossilized)
    g._dbg_words_dirty = False
    g.replenished = []
    g._constellation_turnover_rule = lambda cells, lengths: g.replenished.append(
        (list(cells), dict(lengths)))
    return g


def test_bite_clears_the_cell_and_routes_it_through_the_replenish_rule():
    board = _Board(grams={(1, 1): "ING"})
    g = _eat_game(board)
    assert g._muncher_eat((1, 1)) == "ING"
    assert board.gram_at(1, 1) is None
    # The eaten gram's length category rides along, so the escalating
    # replenish_length rules (hydra growth) work off bites too.
    assert g.replenished == [([(1, 1)], {(1, 1): 3})]
    assert g._dbg_words_dirty is True


def test_bite_on_an_empty_cell_eats_nothing_and_replenishes_nothing():
    g = _eat_game(_Board())
    assert g._muncher_eat((0, 0)) == ""
    assert g.replenished == []


def test_a_fossilized_cell_is_inedible_and_stays_on_the_board():
    board = _Board(grams={(1, 1): "CAT"})
    g = _eat_game(board, fossilized=[(1, 1)])
    assert g._muncher_eat((1, 1)) == ""
    assert board.gram_at(1, 1) is not None
    assert g.replenished == []


def test_a_wild_cell_is_inedible():
    # A wild cell carries no fixed letters to spell with (the same reason the
    # shooting gallery counts a shot wild cell as a miss).
    board = _Board(grams={(1, 1): "A"})
    board.gram_at = lambda x, y: _Gram("A", is_wild=True)
    g = _eat_game(board)
    assert g._muncher_eat((1, 1)) == ""
    assert g.replenished == []


# --- submitting ------------------------------------------------------------
def test_submit_hands_the_eaten_word_and_its_cells_to_the_engine():
    board = _Board(grams={(1, 1): "C", (2, 1): "AT"})
    mode = _mode(board, pos=(1, 1))
    mode._eat()
    mode._walk_to((2, 1))
    mode._eat()
    mode.submit()
    assert mode._gs.submitted == [("CAT", [(1, 1), (2, 1)], ["C", "AT"])]


def test_submit_always_empties_the_buffer():
    # Accepted or rejected, the letters are gone -- they cannot go back on the
    # board, so the readout starts fresh either way.
    board = _Board(grams={(1, 1): "ZZ"})
    mode = _mode(board, pos=(1, 1))
    mode._eat()
    mode.submit()
    assert mode.word() == ""


def test_submitting_nothing_still_reaches_the_engine_to_be_ignored():
    # The engine (not the mode) decides an empty submit is a fumbled key press
    # rather than a life -- see MuncherMixin._muncher_submit.
    mode = _mode(_Board())
    mode.submit()
    assert mode._gs.submitted == [("", [], [])]


# --- the dead-end cap (game_screen.muncher_dead_end) ------------------------
def test_dead_end_grace_lets_one_more_gram_through_then_forces_the_clear():
    # The worked example from the design: F, then Z (dead here -- one gram of
    # grace), then ING forces it.
    board = _Board(grams={(1, 1): "F", (2, 1): "Z", (3, 1): "ING"})
    mode = _mode(board, pos=(1, 1), dead_end=True, grace=1)
    mode._eat()
    assert mode._gs.forced == []
    mode._walk_to((2, 1))
    mode._eat()                     # "FZ" -- no word starts with it
    assert mode._gs.forced == []    # the grace gram is still owed
    mode._walk_to((3, 1))
    mode._eat()
    assert mode._gs.forced == [("FZING", [(1, 1), (2, 1), (3, 1)], ["F", "Z", "ING"])]
    assert mode.word() == ""        # and the buffer went with it


def test_zero_grace_forces_the_clear_the_moment_the_word_dies():
    board = _Board(grams={(1, 1): "F", (2, 1): "Z"})
    mode = _mode(board, pos=(1, 1), dead_end=True, grace=0)
    mode._eat()
    mode._walk_to((2, 1))
    mode._eat()
    assert len(mode._gs.forced) == 1


def test_a_real_word_is_never_a_dead_end_even_when_it_could_grow_no_further():
    # is_prefix is true of a complete word, so eating up to a word is always safe.
    board = _Board(grams={(1, 1): "CA", (2, 1): "T"})
    mode = _mode(board, pos=(1, 1), dead_end=True, grace=1)
    mode._eat()
    mode._walk_to((2, 1))
    mode._eat()
    assert mode._gs.forced == []
    assert mode.word() == "CAT"


def test_the_cap_can_be_turned_off_entirely():
    board = _Board(grams={(1, 1): "Z", (2, 1): "Z", (3, 1): "Z"})
    mode = _mode(board, pos=(1, 1), dead_end=False)
    for cell in [(1, 1), (2, 1), (3, 1)]:
        mode._walk_to(cell)
        mode._eat()
    assert mode._gs.forced == []
    assert mode.word() == "ZZZ"


# --- word resolution + lives (MuncherMixin) ---------------------------------
class _RejectPane(_Pane):
    """Adds the reject surface a bad word lands on."""
    def __init__(self):
        super().__init__()
        self.cleared = 0
        self.errors = []
        self.status = None

    def clear_word(self):
        self.cleared += 1

    def show_errors(self, messages, reason=None):
        self.errors.append((list(messages), reason))

    def set_status_text(self, text):
        self.status = text


class _LifeLossMode:
    """Stand-in for MuncherMovingMode where the lives code reaches back into it:
    records each call so a test can check WHETHER the character was told to react,
    which is the whole contract (what the reaction looks like is the mode's own
    game_screen.muncher_life_loss rule)."""
    def __init__(self):
        self.reactions = 0

    def lose_life_effect(self):
        self.reactions += 1


def _submit_game(lives=3, repeat_ok=True, long_enough=True):
    """A bare GameScreen wired with just the surface _muncher_submit touches."""
    g = GameScreen.__new__(GameScreen)
    g._moving_side_pane = _RejectPane()
    g._moving_mode = _LifeLossMode()
    g._muncher_lives = lives
    g._word_length_rule = lambda word, path: long_enough
    g._repeat_rule = lambda word: repeat_ok
    g.banked = []
    g.ended = []
    g._shooting_submit = lambda word, path, segments: g.banked.append(word)
    g._enter_endgame = lambda: g.ended.append(True)
    return g


def test_a_good_word_is_banked_and_costs_no_life():
    g = _submit_game()
    assert g._muncher_submit("CAT", [(0, 0), (1, 0)], ["C", "AT"]) is True
    assert g.banked == ["CAT"]
    assert g._muncher_lives == 3
    assert g._moving_side_pane.errors == []


def test_a_non_word_costs_a_life_and_clears_the_readout():
    g = _submit_game()
    assert g._muncher_submit("ZQX", [(0, 0)], ["ZQX"]) is False
    assert g._muncher_lives == 2
    assert g._moving_side_pane.cleared == 1
    assert g._moving_side_pane.errors[0][1] == "not_in_dictionary"
    assert g.banked == []


def test_a_too_short_word_costs_a_life():
    # Every bad-word route costs a life in this mode -- there is no free retry.
    g = _submit_game(long_enough=False)
    assert g._muncher_submit("AT", [(0, 0)], ["AT"]) is False
    assert g._moving_side_pane.errors[0][1] == "too_short"
    assert g._muncher_lives == 2


def test_a_word_already_cleared_this_game_costs_a_life():
    g = _submit_game(repeat_ok=False)
    assert g._muncher_submit("CAT", [(0, 0)], ["CAT"]) is False
    assert g._moving_side_pane.errors[0][1] == "already_cleared"
    assert g._muncher_lives == 2


def test_an_empty_submit_is_ignored_rather_than_punished():
    g = _submit_game()
    assert g._muncher_submit("", [], []) is False
    assert g._muncher_lives == 3
    assert g._moving_side_pane.errors == []


def test_losing_the_last_life_ends_the_game():
    g = _submit_game(lives=1)
    g._muncher_submit("ZQX", [(0, 0)], ["ZQX"])
    assert g._muncher_lives == 0
    assert g.ended == [True]


def test_the_forced_clear_costs_a_life_with_its_own_reason():
    g = _submit_game()
    g._muncher_forced_clear("FZING", [(0, 0)], ["FZING"])
    assert g._moving_side_pane.errors[0][1] == "muncher_dead_end"
    assert g._muncher_lives == 2


def test_lives_are_dealt_fresh_and_shown_at_game_start():
    from config import CONFIG
    g = _submit_game(lives=0)
    g._muncher_start_lives()
    assert g._muncher_lives == CONFIG["rules"]["game_screen.muncher_lives"]
    assert str(g._muncher_lives) in g._moving_side_pane.status


def test_a_readout_emptied_from_under_the_mode_starts_a_fresh_word():
    # Defensive: the pane's Clear-word button empties the field directly. The
    # muncher preset hides that button (a word cannot be abandoned here), but a
    # mode file that shows it must not leave the buffer and the readout disagreeing.
    board = _Board(grams={(1, 1): "CAT", (2, 1): "S"})
    mode = _mode(board, pos=(1, 1))
    mode._eat()
    mode._gs._moving_side_pane.emptied = True
    mode._walk_to((2, 1))
    mode._eat()
    assert mode.word() == "S"


def test_lives_prefer_the_icon_row_when_the_pane_has_one():
    # The merged single-phase pane draws little characters; the text readout is
    # only the fallback for a pane without the icon row.
    class _IconPane(_RejectPane):
        def __init__(self):
            super().__init__()
            self.icon_count = None

        def set_lives(self, count):
            self.icon_count = count

    g = _submit_game()
    g._moving_side_pane = _IconPane()
    g._muncher_show_lives()
    assert g._moving_side_pane.icon_count == 3
    assert g._moving_side_pane.status is None


def test_a_lost_life_tells_the_character_to_react():
    # game_screen.muncher_life_loss: the mode is asked to dissolve/reform. What it
    # then does is the mode's rule; the mixin's job is only to ask.
    g = _submit_game(lives=3)
    assert g._muncher_submit("ZZZ", [(0, 0), (1, 0)], ["Z", "ZZ"]) is False
    assert g._moving_mode.reactions == 1


def test_the_last_life_ends_the_game_without_a_character_reaction():
    # The endgame has just taken the screen off the board, and a fade would freeze
    # input as the final act of a finished game -- so the reaction is skipped.
    g = _submit_game(lives=1)
    assert g._muncher_submit("ZZZ", [(0, 0), (1, 0)], ["Z", "ZZ"]) is False
    assert g.ended == [True]
    assert g._moving_mode.reactions == 0


# --- spawn cell (game_screen.muncher_spawn) ---------------------------------
def test_top_center_spawn_is_the_top_row_of_the_center_column():
    # 12 o'clock: the center rule's column, the top row. The x formula matches
    # center_cell, so an even width breaks the tie the same way in both.
    mode = _mode(_Board(width=6, height=6))
    assert mode._rule_muncher_spawn_top_center() == (2, 5)
    assert mode._rule_muncher_spawn_center() == (2, 2)


def test_top_center_spawn_tracks_the_board_size():
    mode = _mode(_Board(width=9, height=4))
    assert mode._rule_muncher_spawn_top_center() == (4, 3)


# --- the life-loss fade (game_screen.muncher_life_loss) ---------------------
def test_life_loss_respawn_dissolves_him_and_queues_the_spawn_cell():
    mode = _mode(_Board(width=6, height=6), pos=(0, 0))
    mode._life_loss_rule = mode._rule_muncher_life_loss_respawn
    mode._spawn_rule = mode._rule_muncher_spawn_top_center
    mode.lose_life_effect()
    assert mode._sprite.fade_outs == 1
    assert mode._respawn_to == (2, 5)


def test_life_loss_in_place_queues_the_cell_he_is_already_on():
    mode = _mode(_Board(width=6, height=6), pos=(4, 1))
    mode._life_loss_rule = mode._rule_muncher_life_loss_fade_in_place
    mode.lose_life_effect()
    assert mode._sprite.fade_outs == 1
    assert mode._respawn_to == (4, 1)


def test_life_loss_none_leaves_him_alone():
    mode = _mode(_Board(width=6, height=6), pos=(4, 1))
    mode._life_loss_rule = mode._rule_muncher_life_loss_none
    mode.lose_life_effect()
    assert mode._sprite.fade_outs == 0
    assert mode._respawn_to is None


def test_a_finished_dissolve_moves_him_and_fades_him_back_in():
    mode = _mode(_Board(width=6, height=6), pos=(0, 0))
    mode._life_loss_rule = mode._rule_muncher_life_loss_respawn
    mode._spawn_rule = mode._rule_muncher_spawn_top_center
    mode.lose_life_effect()
    # The dissolve is still running: he has not moved yet.
    mode._sprite._fading = True
    mode.update(0.1)
    assert mode._pos == (0, 0)
    # It finishes (hidden, no longer fading) -- now he reforms on the spawn cell.
    mode._sprite._fading = False
    mode.update(0.1)
    assert mode._pos == (2, 5)
    assert mode._respawn_to is None
    assert mode._sprite.fade_ins == 1


# --- the freeze gate --------------------------------------------------------
def test_keys_are_swallowed_while_a_fade_runs():
    # Swallowed, not passed through: a mashed arrow during the dissolve must not
    # queue a step that fires the instant he reforms.
    mode = _mode(_Board(width=6, height=6), pos=(1, 1))
    mode._sprite._fading = True
    assert mode.on_key_press(0, 0) is True
    assert mode._sprite.steps == []
    assert mode._buffer == []


def test_keys_are_swallowed_while_he_is_dissolved_away():
    mode = _mode(_Board(width=6, height=6), pos=(1, 1))
    mode._sprite._hidden = True
    assert mode.on_key_press(0, 0) is True
    assert mode._sprite.steps == []


# --- the dissolve animation (views/muncher_sprite) --------------------------
def test_the_fade_plays_forward_in_and_backward_out():
    """One animation, both directions: fade_in materializes him and fade_out is the
    same frames reversed, ending with him off the board entirely."""
    from views.muncher_sprite import MuncherSprite, FADE_FRAMES

    sprite = MuncherSprite(60)
    step = sprite._fade_seconds / len(FADE_FRAMES)

    sprite.fade_in()
    seen = []
    for _ in range(len(FADE_FRAMES)):
        seen.append(sprite._frame())
        sprite.tick(step)
    assert seen == list(FADE_FRAMES)
    # A finished fade-IN hands off to the ordinary frames and leaves him visible.
    assert sprite.fading() is False
    assert sprite.hidden() is False
    assert sprite._frame() == "closed_standing"

    sprite.fade_out()
    seen = []
    for _ in range(len(FADE_FRAMES)):
        seen.append(sprite._frame())
        sprite.tick(step)
    assert seen == list(reversed(FADE_FRAMES))
    # A finished fade-OUT leaves him HIDDEN -- draw() puts nothing on the board.
    assert sprite.fading() is False
    assert sprite.hidden() is True


# --- belly size (game_screen.muncher_belly) ---------------------------------
def test_belly_size_steps_once_per_band_and_caps():
    from views.muncher_sprite import BELLY_IMAGES

    mode = _mode(_Board())
    belly = mode._rule_muncher_belly_on
    # An empty buffer wears no belly at all -- size 0 is "no overlay", not an image.
    assert belly(0) == 0
    # 3 letters per size: 1-3 -> 1, 4-6 -> 2, 7-9 -> 3, 10-12 -> 4.
    assert [belly(n) for n in (1, 2, 3)] == [1, 1, 1]
    assert [belly(n) for n in (4, 5, 6)] == [2, 2, 2]
    assert [belly(n) for n in (7, 8, 9)] == [3, 3, 3]
    assert [belly(n) for n in (10, 11, 12)] == [4, 4, 4]
    # The cap is the image count, so a long word keeps him at his fattest rather
    # than indexing off the end of the art.
    assert belly(40) == len(BELLY_IMAGES)


def test_belly_band_width_is_configurable():
    mode = _mode(_Board())
    mode._belly_letters = 1
    assert [mode._rule_muncher_belly_on(n) for n in (0, 1, 2, 3)] == [0, 1, 2, 3]


def test_belly_off_stays_empty_however_much_he_eats():
    mode = _mode(_Board())
    assert [mode._rule_muncher_belly_off(n) for n in (0, 1, 9, 99)] == [0, 0, 0, 0]


def test_the_belly_tracks_the_buffer_through_eating_and_submitting():
    # Recomputed from the letters every frame, so the buffer is the single source
    # of truth -- no per-bite bookkeeping to fall out of step.
    board = _Board(grams={(1, 1): "STR", (1, 2): "ING"})
    mode = _mode(board, pos=(1, 1))
    mode._belly_rule = mode._rule_muncher_belly_on
    mode.update(0.1)
    assert mode._sprite.belly == 0

    mode._eat()
    mode.update(0.1)
    assert mode._sprite.belly == 1          # STR -> 3 letters

    mode._pos = (1, 2)
    mode._eat()
    mode.update(0.1)
    assert mode._sprite.belly == 2          # STRING -> 6 letters

    # Emptying the buffer deflates him, whatever emptied it.
    mode._clear_buffer()
    mode.update(0.1)
    assert mode._sprite.belly == 0


def test_the_belly_sprite_really_has_geometry_to_draw():
    """Regression: the belly was first switched off with pyglet's
    `sprite.visible = False`, which collapses all four vertices onto the origin --
    and _get_vertices keeps returning zeros while the flag is False, so the sprite
    never drew again no matter what image or position was set afterwards. The rule
    was asking for the right size every frame and nothing appeared.

    Size 0 is expressed by NOT DRAWING (the guard in draw()), never by switching
    the sprite off, so the quad must stay non-degenerate at every size."""
    from views.muncher_sprite import MuncherSprite, BELLY_IMAGES

    sprite = MuncherSprite(60)
    sprite.place(100, 100)
    for size in range(len(BELLY_IMAGES) + 1):
        sprite.set_belly(size)
        sprite.tick(0.016)
        corners = list(sprite._belly._vertex_list.position[:])
        assert any(c != 0 for c in corners), f"belly collapsed at size {size}"
