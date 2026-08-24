import math
import random
import time
from collections import Counter, defaultdict
import pyglet
from views.ingame_menu import IngameMenu
from views.moving_mode import (
    JigsawMovingMode, TypewriterMovingMode, OmniswapVsTimerMode, ConstellationMode,
    ShootingGalleryMode, LineBlastMovingMode, PlantVsTimerMode, BotanicalMode)
from views.found_word import FoundWord
from views.game_phase import Phase
from views.game_screen_wordfind import WordFindMixin
from views.game_screen_selection import SelectionMixin
from views.game_screen_setup import BoardSetupMixin
from views.game_screen_boardrules import BoardRulesMixin
from views.game_screen_constellation import ConstellationMixin
from views.game_screen_botanical import BotanicalMixin
from views.game_screen_shooting import ShootingMixin
from views.game_screen_input import InputMixin
from views.game_screen_piece import PieceControlMixin
from views.game_screen_health import CellHealthMixin
from views.game_screen_grammanip import (
    GramManipMixin, _GRAM_MANIP_RULES, rule_rightclick_none)
from views.moving_side_pane import MovingSidePane
from views.line_blast_side_pane import LineBlastMovingPane
from views.selecting_side_pane import SelectingSidePane
from views.moving_selecting_side_pane import MovingSelectingSidePane
from views.load_side_pane import LoadSidePane
from views.loading_animation import LoadingAnimation, AlphaFade, WhiteFade
from views.word_trail import WordTrail
from views.rising_fill import RisingFill
from views.border_dashes import BorderDashes
from views.disambiguation_lines import DisambiguationLines
from views.disambiguation_highlight import DisambiguationHighlight
from views.victory_overlay import VictoryOverlay
from views.end_video_overlay import EndVideoOverlay
from views.hunt_highlight import (
    get_hunt_highlight_batch, reset_hunt_highlight, get_hunt_match_rule,
)
from controllers.screen_manager import ScreenType
from models.piece_pool import PiecePool
# NOTE: the piece-set / gram-pick rules are resolved at board-build time in
# game_screen_setup._rule_use_*_grid via the square_piece / hex_piece accessors,
# so a game mode's *.piece_set / *.gram_pick override takes effect. They used to be
# imported here as import-time constants (frozen before apply_game_mode) -- removed.
from models.square_unimo import SquareUnimoType
from models.hex_unimo import HexUnimoType
from models.gram import Gram
from models.gram_picker import (
    reset_gram_dedup,
    begin_formation_gram_run,
    end_formation_gram_run,
    formation_length_sequence,
    set_forced_formation_length,
    set_forced_formation_cell,
    clear_forced_formation_cell,
    rule_grams_greater_than_47_lengthcontrolled,
    ideation_grade,
    set_unigram_vowel_guarantee,
)
# The hex / triangle direction constants and place_piece_cells moved out with the
# piece-control methods that used them -- see views/game_screen_piece.py.
from models.square_grid import SquareGrid
from models.hex_grid import HexGrid
from models.word_dictionary import (
    is_word, is_prefix, is_obscure, select_maximal_paths, all_words)
from models.spelling_suggester import SUGGEST_RULES
from models.scoring import Scorer
from starting_coverage import write_coverage_csv
from models.wild_vowel import wild_expansions
from models.player_dictionary import PlayerDictionary
from config import select_rule, get_color, get_string, active_mode, end_video_path, CONFIG
from controls import control_keys, control_button
import session_log
import log_codes as L
# All gameplay/setup randomness routes through the swappable Source seam (see
# source.py) so a replay reproduces or overrides formation, spawns and tie-breaks.
from source import rand


# Phase (the LOADING/MOVING/SELECTING/VICTORY state machine) now lives in
# views/game_phase.py and is imported at the top of this module, so gs.Phase
# still resolves and the extracted mixins can share it without importing back
# into game_screen.


# FoundWord (one dictionary word located on the board: cell `path`, the
# `segments` each cell contributed, the `word` they spell) now lives in
# views/found_word.py and is imported at the top of this module -- so gs.FoundWord
# still resolves and the word-finding mixin can share the type without importing
# back into game_screen.


# --- Stage-3 selection strategies (game_screen.word_select) ----------------
# Of the nucleated candidate words, decide which clear. Strategies share a tiny
# interface so GameScreen can treat them uniformly: `interactive` says whether
# selection spans frames (waits on the player) or resolves instantly. Auto
# strategies implement choose(); interactive ones own a UI via create_ui() and
# drive clearing through callbacks into GameScreen.
class AutoSelect:
    """Instant auto-select: keep every candidate that isn't a contiguous
    sub-path of a longer one. Overlapping words (FIN/INK sharing IN) and repeats
    of one word at different board locations both survive; only strict sub-words
    are dropped (CAT inside CATEGORY).

    Wild cells make a single path ambiguous (CAT vs COT vs COAT), and a wild
    cell can only resolve to one run when it clears. So among the candidates we
    keep only those spelling a longest word, then drop sub-paths among those --
    the longest-word-wins rule for wilds. (Ties beyond that aren't teased apart
    further here; the interactive selector is the primary mode.)"""
    interactive = False

    def choose(self, candidates):
        chosen = candidates
        if candidates:
            longest = max(len(c.word) for c in candidates)
            longest_words = [c for c in candidates if len(c.word) == longest]
            keep_paths = select_maximal_paths([c.path for c in longest_words])
            keep = {tuple(p) for p in keep_paths}
            chosen = []
            seen = set()
            for c in longest_words:
                key = tuple(c.path)
                if key in keep and key not in seen:
                    seen.add(key)
                    chosen.append(c)
        return chosen

    def create_ui(self, x, y, width, height, on_submit, on_next,
                  on_end=None, show_end=False, show_clear=True,
                  show_submit=True, show_next=True, error_display="text",
                  error_icon_keeps_suggestion=False, show_idea_belt=False):
        return None


class TextInputSelect:
    """Interactive: the player types a word and submits it (Enter or the Submit
    control) to clear that word, repeating until they hit Next piece. The UI is
    a SelectingSidePane in the right-pane region."""
    interactive = True

    def create_ui(self, x, y, width, height, on_submit, on_next,
                  on_end=None, show_end=False, show_clear=True,
                  show_submit=True, show_next=True, error_display="text",
                  error_icon_keeps_suggestion=False, show_idea_belt=False):
        return SelectingSidePane(
            x, y, width, height, on_submit, on_next,
            on_end=on_end, show_end=show_end,
            show_clear=show_clear, show_submit=show_submit,
            show_next=show_next, error_display=error_display,
            error_icon_keeps_suggestion=error_icon_keeps_suggestion,
            show_idea_belt=show_idea_belt)


# Control key bindings now live in assets/controls.yaml (loaded via controls.py).
# The old in-code CONTROL_KEYS dict moved there wholesale; self._keys / self._
# buttons below are built from it. Old version, for reference:
#   CONTROL_KEYS = {"move_left": "A", "move_right": "D", "move_up": "W",
#       "move_down": "S", "rotate_clockwise": "LEFT",
#       "rotate_counterclockwise": "RIGHT", "place": "SPACE", "pause": "ESCAPE"}
#   def _get_key(action): return getattr(pyglet.window.key, CONTROL_KEYS[action])


# Note: a cell can hold a multi-letter gram
#   - letters: how many letters the word spells (len of `text`)
#   - cells: how many cells/grams the word spans (len of `path`)
def rule_word_min2letters_min2cells(text, path):
    return len(text) >= 2 and len(path) >= 2

def rule_word_min3letters_min2cells(text, path):
    return len(text) >= 3 and len(path) >= 2

def rule_word_min3letters_min1cell(text, path):
    # Letters-only floor (3+), any cell count -- so a single multi-letter gram can
    # be a whole word. For the shooting gallery, where one shot is one cell and a
    # trigram cell shot once is a legitimate 3-letter word (the min2cells rules
    # would wrongly reject it), while single-letter shots (S / O / T) are still cut.
    return len(text) >= 3

# Minimum-word rule (letters + cells), chosen by the YAML key game_screen.word_length.
_WORD_LENGTH_RULES = {
    "rule_word_min2letters_min2cells": rule_word_min2letters_min2cells,
    "rule_word_min3letters_min2cells": rule_word_min3letters_min2cells,
    "rule_word_min3letters_min1cell": rule_word_min3letters_min1cell,
}


# Whether the right pane shows the player's lifetime dictionary size, chosen by
# the YAML key game_screen.dictionary_count. Every set_word_count call routes
# through the selected rule, so toggling the readout off is a single config edit.
def rule_show_dictionary_count(pane, count):
    pane.set_word_count(count)

def rule_hide_dictionary_count(pane, count):
    # Readout hidden -- skip the update so the pane's count label stays blank.
    pass

_DICTIONARY_COUNT_RULES = {
    "rule_show_dictionary_count": rule_show_dictionary_count,
    "rule_hide_dictionary_count": rule_hide_dictionary_count,
}


# Gram-manipulation rules + their dispatcher moved to
# views/game_screen_grammanip.py (GramManipMixin); _GRAM_MANIP_RULES and
# rule_rightclick_none are imported at the top of this module, so the
# right-click config wiring in __init__ still reads the same.


class GameScreen(WordFindMixin, BoardRulesMixin, BoardSetupMixin, SelectionMixin,
                 ConstellationMixin, BotanicalMixin, ShootingMixin, InputMixin,
                 PieceControlMixin, CellHealthMixin, GramManipMixin):
    # Error-display defaults so the submission pipeline reads sane values on a bare
    # __new__ test instance (build() overrides both from config). Text mode always
    # shows the "did you mean?" hint, matching the pre-icon behavior. See
    # _submission_messages and game_screen.error_display / error_icon_keeps_suggestion.
    _error_display = "text"
    _error_icon_keeps_suggestion = False
    # Line-blast flag + highlight default, so a bare __new__ test instance (and the
    # nucleation rule) resolve before build() sets the real values.
    _line_blast = False
    _line_blast_highlight = set()

    GRID_WIDTH = CONFIG["rules"]["game_screen.grid_width"]
    PIECE_POOL_SIZE = CONFIG["rules"]["game_screen.piece_pool_size"]
    # Obstacle pieces the scattered formation drops before play begins; also gates
    # the obstacle victory rule (0 == board never had obstacles). Config-surfaced
    # near game_screen.setup_formation; the ring formation derives its own count.
    # NOTE: read at IMPORT, so this (and the three other numeric knobs here) is the
    # BASE config value -- __init__ re-reads all four from the live CONFIG so a game
    # mode's override actually applies. Add numeric knobs to that block too, not
    # just here. See the comment at the top of __init__.
    OBSTACLE_COUNT = CONFIG["rules"]["game_screen.obstacle_count"]
    # Obstacle cells render with their own fill (see colors.yaml) so they read
    # as pre-placed hazards distinct from the playable pieces.
    OBSTACLE_CELL_COLOR = get_color("board.obstacle_fill")
    # Mission pieces the scattered formation drops before play begins -- the
    # light-red goal pieces the mission victory rules want cleared. A parallel
    # track to the obstacles above (own count, own tint, own tracking set / config
    # keys); same config-surfaced count, same victory gate.
    MISSION_COUNT = CONFIG["rules"]["game_screen.mission_count"]
    MISSION_CELL_COLOR = get_color("board.mission_fill")
    # The live/movable piece is tinted a darker blue so it stands out from both
    # the settled cells and the lighter-blue pieces already placed this moving
    # phase. On placement a piece's cells recolor to PLACED_PIECE_CELL_COLOR and
    # stay lit through the next selection turn; they revert to the settled fill
    # only once selection (auto or interactive) leaves them behind.
    ACTIVE_PIECE_CELL_COLOR = get_color("board.active_piece_fill")
    PLACED_PIECE_CELL_COLOR = get_color("board.placed_piece_fill")
    # Batch (clear-at-phase-end) mode tints a selected word's cells light green
    # until the phase commits the whole batch; see the clear-timing rules.
    PENDING_WORD_CELL_COLOR = get_color("board.pending_word_fill")
    SETTLED_CELL_COLOR = get_color("board.settled_cell_fill")
    # The MOVING_TYPEWRITER cursor cell's tint (dark grey); see TypewriterMovingMode.
    CURSOR_CELL_COLOR = get_color("board.cursor_fill")
    # A fossilized cell's tint (stone grey): a formed word frozen on the board,
    # dead to word-finding and swapping. See the clear-action / fossilize rules.
    FOSSILIZED_CELL_COLOR = get_color("board.fossilized_fill")

    def _read_config_knobs(self):
        """Re-read the numeric board knobs from the LIVE config, shadowing the
        class-level constants of the same name with per-instance values. Called
        first thing in __init__, before the board and pools are built from them.

        Why this exists: the class body runs at IMPORT, which is before
        apply_game_mode merges the selected mode's overrides into CONFIG -- so a
        class-level CONFIG read freezes the BASE config.yaml value and every mode
        override of that key is SILENTLY ignored. That is the same freeze-at-import
        trap as resolving a select_rule into a module global, and the sibling of
        the class-level COLOR constants documented in config.apply_game_mode --
        but unlike colors, these are functional knobs modes really do set (four
        game modes override obstacle_count / mission_count, and before this the
        board ignored all of them). GameScreen is rebuilt after each mode swap, so
        reading here always tracks the active mode.

        Add any future numeric knob HERE as well as to the class body -- the class
        attribute is only the default a bare __new__ instance reads. Every use site
        goes through self., so these shadow cleanly."""
        self.GRID_WIDTH = CONFIG["rules"]["game_screen.grid_width"]
        self.PIECE_POOL_SIZE = CONFIG["rules"]["game_screen.piece_pool_size"]
        self.OBSTACLE_COUNT = CONFIG["rules"]["game_screen.obstacle_count"]
        self.MISSION_COUNT = CONFIG["rules"]["game_screen.mission_count"]
        # Seconds a word trail takes to fade off the board, read by the trail-fade
        # rules below (game_screen.word_trail_fade). Inert when the fade is off.
        self._word_trail_fade_seconds = CONFIG["rules"][
            "game_screen.word_trail_fade_seconds"]
        # Seconds the END GAME card holds before an endgame mode takes the screen
        # over (game_screen.endgame_intro_seconds). Unused when endgame is off.
        self._endgame_intro_seconds = CONFIG["rules"][
            "game_screen.endgame_intro_seconds"]

    def __init__(self, window, screen_manager):
        self._window = window
        self._screen_manager = screen_manager

        self._read_config_knobs()

        # Each value is a TUPLE of accepted key symbols (controls.yaml may bind one
        # key or several to an action), so every check below is `symbol in ...`.
        self._keys = {
            "move_left": control_keys("game.move_left"),
            "move_right": control_keys("game.move_right"),
            "move_up": control_keys("game.move_up"),
            "move_down": control_keys("game.move_down"),
            "rotate_clockwise": control_keys("game.rotate_clockwise"),
            "rotate_counterclockwise": control_keys("game.rotate_counterclockwise"),
            "place": control_keys("game.place"),
            "pause": control_keys("game.pause"),
            "select_open": control_keys("game.select_open"),
            "word_clear": control_keys("game.word_clear"),
            "selection_end": control_keys("game.selection_end"),
            "word_submit": control_keys("game.word_submit"),
            "word_backspace": control_keys("game.word_backspace"),
            "word_cycle_prev": control_keys("game.word_cycle_prev"),
            "word_cycle_next": control_keys("game.word_cycle_next"),
        }
        # Mouse buttons (single constants; see controls.yaml "mouse" + "ONLY WHEN"
        # rule-combo notes for what each does per game_screen.mode). place_piece
        # is None when unassigned (so right-click is free for gram_manipulate).
        self._buttons = {
            "move_primary": control_button("mouse.move_primary"),
            "place_piece": control_button("mouse.place_piece"),
            "gram_manipulate": control_button("mouse.gram_manipulate"),
            "select_primary": control_button("mouse.select_primary"),
        }
        # Cell gram-manipulation rules (right-click a cell during MOVING), one per
        # gram length plus wild; see the rule functions and game_screen.rightclick_*.
        # Right-click gram rules, keyed by the gram's vowel/consonant SHAPE (not
        # just its length) -- one config slot per shape, all routed via
        # _gram_manip_family / _apply_shape_rule. cc/cv/vc/vv/ck cover the
        # digrams (and their doubled 3-letter reverse forms); vcv/cvk cover the
        # trigrams; every other 3+ shape (CKV, VCK, CKS) is an unconfigured no-op.
        self._rightclick_rules = {
            "unigram": select_rule("game_screen.rightclick_unigram", _GRAM_MANIP_RULES),
            "cc": select_rule("game_screen.rightclick_cc", _GRAM_MANIP_RULES),
            "cv": select_rule("game_screen.rightclick_cv", _GRAM_MANIP_RULES),
            "vc": select_rule("game_screen.rightclick_vc", _GRAM_MANIP_RULES),
            "vv": select_rule("game_screen.rightclick_vv", _GRAM_MANIP_RULES),
            "ck": select_rule("game_screen.rightclick_ck", _GRAM_MANIP_RULES),
            "vcv": select_rule("game_screen.rightclick_vcv", _GRAM_MANIP_RULES),
            "cvk": select_rule("game_screen.rightclick_cvk", _GRAM_MANIP_RULES),
            "vowelwild": select_rule("game_screen.rightclick_vowelwild", _GRAM_MANIP_RULES),
        }
        # CVK doubling is stateful (it alternates front/back), so the pure-function
        # slot can't carry the on/off; derive an explicit flag from its rule.
        self._cvk_enabled = self._rightclick_rules["cvk"] is not rule_rightclick_none
        # Per-cell alternation for CVK doubling: (x, y) -> the side last doubled
        # ('front' / 'back'), so successive doubles on a cell flip sides
        # (MER -> MMER -> MER -> MERR -> MER). Keyed by board coords; a gram that
        # MOVES to another cell starts fresh (rare, self-heals). Collapses
        # (4 letters -> 3) do NOT advance it, so the round-trip alternates cleanly.
        self._cvk_double_side = {}
        # The live piece whose CVK slots are currently in _cvk_double_side; when a
        # different piece becomes live those slots are dropped (see _piece_cvk_key).
        self._cvk_piece = None
        self._menu_open = False
        self._ingame_menu = IngameMenu(window, screen_manager, ScreenType.MAIN_MENU)

        # Tracks currently-held keys, so a movement can use non-standard keys as
        # held modifiers (e.g. up-arrow). 
        self._key_state = pyglet.window.key.KeyStateHandler()
        window.push_handlers(self._key_state)

        # The grid occupies a square region on the left (its side is limited by
        # the window height); the side pane fills the remaining width to its
        # right. Both grid builders size themselves to this square region rather
        # than the full window.
        self._grid_area_size = window.height
        # A single-line title along the top of the board naming the current game
        # mode. Small text, centered across the board width, drawn over the top of
        # the grid. Its text is set by the game_screen.mode_title rule below (on =
        # the active mode's label; off = blank, so the label draws nothing).
        self._mode_title_label = pyglet.text.Label(
            "",
            font_size=max(11, math.floor(window.height / 45)),
            x=math.floor(self._grid_area_size / 2),
            y=window.height - 4,
            anchor_x="center", anchor_y="top",
            color=get_color("board.mode_title"),
        )
        mode_title_rules = {
            "rule_mode_title_on": self._rule_mode_title_on,
            "rule_mode_title_off": self._rule_mode_title_off,
        }
        select_rule("game_screen.mode_title", mode_title_rules)()
        side_pane_x = self._grid_area_size
        side_pane_width = window.width - self._grid_area_size
        # Whether the MOVING pane shows its word-hunt field at all. Off drops the
        # prompt/input and swallows typed letters (SELECTING is still reachable via
        # ENTER / the Select button); only meaningful in two-phase, since the
        # single-phase merged pane below owns its own text entry.
        hunt_field_rules = {
            "rule_hunt_field_on": lambda: True,
            "rule_hunt_field_off": lambda: False,
        }
        show_hunt_field = select_rule("game_screen.moving_hunt_field", hunt_field_rules)()
        self._moving_side_pane = MovingSidePane(
            side_pane_x, 0, side_pane_width, window.height,
            on_change=self._on_hunt_change, show_hunt_field=show_hunt_field,
        )
        # Which letters of a board gram light up for the typed hunt word (full-gram
        # vs single-letter); see hunt_highlight and game_screen.hunt_highlight.
        self._hunt_match_rule = get_hunt_match_rule()
        # Shown only during the LOADING phase (the opening reveal); its own class
        # so its UI can diverge later (progress bar, spinner) without touching the
        # play panes.
        self._load_side_pane = LoadSidePane(
            side_pane_x, 0, side_pane_width, window.height
        )
        # The active opening-reveal animation, or None once play has begun (set
        # in _begin_loading, cleared in _finish_loading).
        self._loading_anim = None

        # Victory overlay: a solid panel + big centered label drawn over the grid
        # region only in the VICTORY phase. See views/victory_overlay.py.
        self._victory_overlay = VictoryOverlay(self._grid_area_size, window.height)
        # The end-state overlay is dismissable: a click in the VICTORY phase hides
        # it, leaving the player looking at the final board. Reset each time the
        # game ends (see _enter_endstate).
        self._end_overlay_dismissed = False

        # Endgame mode (game_screen.endgame): what happens once play is over. The
        # rule returns the endgame view to run, or None to keep VICTORY as the
        # final state (the original behavior). Built here so its labels exist
        # before any game ends; it stays inert until started. See _start_endgame.
        endgame_rules = {
            "rule_endgame_none": self._rule_endgame_none,
            "rule_endgame_typing_bonus": self._rule_endgame_typing_bonus,
        }
        self._endgame = select_rule("game_screen.endgame", endgame_rules)(
            side_pane_x, side_pane_width)
        # Counts down the END GAME card before the endgame view takes over; None
        # whenever no hand-off is pending (see _enter_endstate / update).
        self._endgame_intro_remaining = None

        # End-of-game video (game_screen.end_video): a one-shot fullscreen clip
        # played over the frozen end state, removing itself when it finishes. Path
        # is None (feature off) unless a mode names a file under assets/video/.
        self._end_video = EndVideoOverlay(window, end_video_path())

        # Cleared-word path trails, overlaid on top of the board. Accumulate all
        # game; cleared on each new game. The game_screen.word_trail rule gates
        # whether _clear_paths records into it. See views/word_trail.py.
        self._word_trail = WordTrail()

        # Transient candidate polylines for the "select which one" chooser
        # (a game_screen.clear_disambiguation cycle rule). Empty except while a
        # submitted word with several clearable paths is being resolved.
        # See views/disambiguation_lines.py and _begin_disambiguation.
        self._disambig_lines = DisambiguationLines()
        # Alternate chooser visual: cell text-highlight + lime fill instead of the
        # blue lines. Which one an open chooser uses is game_screen.disambig_display
        # (_rule_disambig_display_lines / _highlight); the unused view stays inert.
        self._disambig_highlight = DisambiguationHighlight()
        self._disambig_display_rule = select_rule(
            "game_screen.disambig_display",
            {
                "rule_disambig_display_lines": self._rule_disambig_display_lines,
                "rule_disambig_display_highlight": self._rule_disambig_display_highlight,
            },
        )

        # The player's lifetime word collection, persisted across every game.
        # Words cleared for the first time ever are shown green and autosaved.
        self._player_dict = PlayerDictionary()

        # Running point total for the current game (the config-driven scoring:
        # block). Reset each new game in _start_new_game; per-word points
        # accumulate through _clear_paths. See models/scoring.py.
        self._scorer = Scorer()

        # Minimum word to clear (letters + cells); see _WORD_LENGTH_RULES.
        self._word_length_rule = select_rule("game_screen.word_length", _WORD_LENGTH_RULES)

        # Whether to enumerate every word the opening board could spell at game
        # start (debug/analysis). Bound methods so the rule can read the live board
        # and rules; see _rule_starting_coverage_* near the loading section.
        self._starting_coverage_rule = select_rule(
            "game_screen.starting_coverage_dictionary", {
                "rule_starting_coverage_on": self._rule_starting_coverage_on,
                "rule_starting_coverage_off": self._rule_starting_coverage_off,
            })
        # Replay seam: when replaying a session that did a coverage pass, the
        # harness sets this to the recorded compute time (already scaled by
        # playback speed). The "on" rule then SIMULATES that pause -- shows
        # CALCULATING for the duration -- instead of recomputing or rewriting the
        # file. None during live play (the real compute runs). See replay.py.
        self._coverage_sim_seconds = None

        # Whether the right pane shows the dictionary-size readout; routed
        # through this rule so every set_word_count call honors the toggle.
        self._dictionary_count_rule = select_rule(
            "game_screen.dictionary_count", _DICTIONARY_COUNT_RULES)

        # Victory condition, chosen by the YAML key game_screen.victory. Bound
        # methods so the rule can read live board / obstacle-cell state; see the
        # _rule_victory_* methods near the other rule definitions.
        victory_rules = {
            "rule_victory_missions_cleared": self._rule_victory_missions_cleared,
            "rule_victory_missions_and_obstacles_cleared": self._rule_victory_missions_and_obstacles_cleared,
            "rule_victory_obstacles_cleared": self._rule_victory_obstacles_cleared,
            "rule_victory_grid_empty": self._rule_victory_grid_empty,
            "rule_victory_grid_fossilized": self._rule_victory_grid_fossilized,
            "rule_victory_none": self._rule_victory_none,
        }
        self._victory_rule = select_rule("game_screen.victory", victory_rules)
        # Whole-board fill bonus (game_screen.fill_board): a mode-dependent test
        # for "the board is entirely filled" (all fossilized vs all occupied).
        # Bound methods so the rule reads live board / fossil state; see the
        # _rule_fill_board_* methods and _check_board_fill.
        self._fill_board_rule = select_rule("game_screen.fill_board", {
            "rule_fill_board_all_fossilized": self._rule_fill_board_all_fossilized,
            "rule_fill_board_all_occupied": self._rule_fill_board_all_occupied,
            "rule_fill_board_off": self._rule_fill_board_off,
        })
        # Coordinates of the starting obstacle cells not yet cleared; emptied as
        # they clear, so rule_victory_obstacles_cleared wins when it hits empty.
        self._obstacle_cells = set()
        # The mission-piece twin of _obstacle_cells: the starting mission cells
        # not yet cleared, tracked for the mission victory rules and <> encoding.
        self._mission_cells = set()
        # Cells fossilized by a formed word (game_screen.clear_action: fossilize):
        # dead to word-finding, un-swappable, and skipped by the typewriter cursor.
        # Stays empty under the default remove clear-action. See _is_fossilized.
        self._fossilized_cells = set()

        # Cell health (game_screen.cell_health): the per-game maps, the rule
        # selections and the damage-display knobs all live with the feature.
        # See CellHealthMixin in views/game_screen_health.py.
        self._init_cell_health()
        # MOVING_PLANT: the green stem cells (center column) that each carry the
        # game's root gram, and the root text itself. Empty / None outside plant
        # mode. The stem is fossilized-but-walkable (rule_fossil_allow); a word whose
        # path touches a stem cell is a 'plant word' (see _rule_formation_plant).
        self._stem_cells = set()
        self._plant_root = None
        # MOVING_BOTANICAL: stem cells that have already sprouted their one leaf word
        # (a used stem cell hosts no more words). Empty outside botanical.
        self._sprouted_stem_cells = set()

        # Cell-overlap rules: one independent slot per piece track, each deciding
        # whether a piece may be moved onto / placed over a cell of that track.
        # _overlap_allowed ANDs all three, so a position holds only when none of
        # them blocks it. game_screen.cell_overlap_action (separate) decides what
        # becomes of the covered cells. See the _rule_*over_*_cell methods near
        # the victory rules.
        cell_overlap_player_rules = {
            "rule_moveandplace_over_player_cell": self._rule_moveandplace_over_player_cell,
            "rule_block_moveandplace_over_player_cell": self._rule_block_moveandplace_over_player_cell,
        }
        self._cell_overlap_player_rule = select_rule(
            "game_screen.cell_overlap_player", cell_overlap_player_rules
        )
        cell_overlap_obstacle_rules = {
            "rule_moveandplace_over_obstacle_cell": self._rule_moveandplace_over_obstacle_cell,
            "rule_block_moveandplace_over_obstacle_cell": self._rule_block_moveandplace_over_obstacle_cell,
        }
        self._cell_overlap_obstacle_rule = select_rule(
            "game_screen.cell_overlap_obstacle", cell_overlap_obstacle_rules
        )
        cell_overlap_mission_rules = {
            "rule_moveandplace_over_mission_cell": self._rule_moveandplace_over_mission_cell,
            "rule_block_moveandplace_over_mission_cell": self._rule_block_moveandplace_over_mission_cell,
        }
        self._cell_overlap_mission_rule = select_rule(
            "game_screen.cell_overlap_mission", cell_overlap_mission_rules
        )
        cell_overlap_fossilized_rules = {
            "rule_moveandplace_over_fossilized_cell": self._rule_moveandplace_over_fossilized_cell,
            "rule_block_moveandplace_over_fossilized_cell": self._rule_block_moveandplace_over_fossilized_cell,
        }
        self._cell_overlap_fossilized_rule = select_rule(
            "game_screen.cell_overlap_fossilized", cell_overlap_fossilized_rules
        )
        cell_overlap_action_rules = {
            "rule_old_cells_get_delete": self._rule_old_cells_get_delete,
        }
        self._cell_overlap_action_rule = select_rule(
            "game_screen.cell_overlap_action", cell_overlap_action_rules
        )

        # Clear-action rule (game_screen.clear_action): the fate of the cells a
        # formed word covers -- remove them (the original) or fossilize them in
        # place (frozen + dead). See _clear_paths / the _rule_clear_* methods.
        clear_action_rules = {
            "rule_remove_cells": self._rule_remove_cells,
            "rule_fossilize_cells": self._rule_fossilize_cells,
            "rule_clear_plant": self._rule_clear_plant,
            "rule_clear_none": self._rule_clear_none,
        }
        self._clear_action_rule = select_rule(
            "game_screen.clear_action", clear_action_rules
        )

        # Player-piece spawn positioning (one live piece at a time), chosen by the
        # YAML key game_screen.spawn.
        spawn_rules = {
            "rule_spawn_center": self._rule_spawn_center,
            "rule_spawn_random_spot": self._rule_spawn_random_spot,
        }
        self._spawn_rule = select_rule("game_screen.spawn", spawn_rules)

        # Starting-formation rule, chosen by the YAML key game_screen.setup_formation.
        # Lays out the whole opening set of obstacle + mission pieces: builds the
        # pools at the counts it needs and places every piece. Distinct from the
        # per-piece player spawn above (several pieces, fixed layout vs one live
        # piece). See the _rule_formation_* methods.
        # Every full-board layout is one setup_formation rule -- the diagonal vs
        # random length arrangement of the uniform fill are now sibling formations
        # here (rule_formation_fill_player_diagonal/_random), alongside the ideation side-pane
        # layouts, rather than a separate formation_arrangement key. One place to pick
        # the opening layout.
        setup_formation_rules = {
            "rule_formation_empty": self._rule_formation_empty,
            "rule_formation_scattered": self._rule_formation_scattered,
            "rule_formation_mission_center_obstacle_ring": self._rule_formation_mission_center_obstacle_ring,
            "rule_formation_jumbo_mission_center_obstacle_ring":
                self._rule_formation_jumbo_mission_center_obstacle_ring,
            "rule_formation_fill_player_diagonal": self._rule_formation_fill_player_diagonal,
            "rule_formation_fill_player_wood_grain": self._rule_formation_fill_player_wood_grain,
            "rule_formation_fill_player_random": self._rule_formation_fill_player_random,
            "rule_formation_fill_ideation_trigram_sidepanes_digram_centercircle":
                self._rule_formation_fill_ideation_trigram_sidepanes_digram_centercircle,
            "rule_formation_fill_ideation_trigram_sidepanes_digram_bottompyramid":
                self._rule_formation_fill_ideation_trigram_sidepanes_digram_bottompyramid,
            "rule_formation_fill_ideation_trigram_sidepanes":
                self._rule_formation_fill_ideation_trigram_sidepanes,
            "rule_formation_fill_ideation_trigram_sidepanes_zigzag":
                self._rule_formation_fill_ideation_trigram_sidepanes_zigzag,
            "rule_formation_plant": self._rule_formation_plant,
            "rule_formation_botanical": self._rule_formation_botanical,
        }
        self._setup_formation_rule = select_rule(
            "game_screen.setup_formation", setup_formation_rules
        )

        # Optional guarantee on the formation's UNIGRAM cells (game_screen.
        # formation_vowel_coverage): returns the set of letters every fill must place
        # at least once among its single-letter cells. The picker draws unigrams
        # normally and only forces a still-missing one into the final slots, so it
        # barely perturbs the weighted/quota picking. Needs the length-controlled
        # picker (same as the length arrangements). See _rule_vowel_coverage_*.
        vowel_coverage_rules = {
            "rule_vowel_coverage_off": self._rule_vowel_coverage_off,
            "rule_vowel_coverage_each_unigram": self._rule_vowel_coverage_each_unigram,
        }
        self._formation_vowel_coverage_rule = select_rule(
            "game_screen.formation_vowel_coverage", vowel_coverage_rules
        )

        # How the opening reveal (LOADING) buckets each cell's GLYPH (letter) into
        # fade categories (game_screen.loading_fade_glyphs_category). This is the
        # GLYPH axis: it governs every cell's letter, ordinary or special. A cell's
        # kind (mission / obstacle / fossilized) instead drives its BACKGROUND fill
        # (see _begin_loading) -- the two are independent axes, so a fossilized
        # single letter fades on the glyph scheme's 'uni' bucket while its gray fill
        # reveals on 'fossilized_background'. The 'by_category' scheme is the one
        # that groups GLYPHS by kind. Each scheme's category names must have a slot
        # in loading_animation.yaml. See _rule_loading_fade_*_glyph.
        loading_fade_glyphs_category_rules = {
            "rule_loading_fade_by_length_glyph": self._rule_loading_fade_by_length_glyph,
            "rule_loading_fade_by_ideation_strength_glyph": self._rule_loading_fade_by_ideation_strength_glyph,
            "rule_loading_fade_by_ideation_fix_glyph": self._rule_loading_fade_by_ideation_fix_glyph,
            "rule_loading_fade_by_ideation_length_strength_fix_glyph":
                self._rule_loading_fade_by_ideation_length_strength_fix_glyph,
            "rule_loading_fade_by_category_glyph": self._rule_loading_fade_by_category_glyph,
        }
        self._loading_fade_glyphs_category_rule = select_rule(
            "game_screen.loading_fade_glyphs_category", loading_fade_glyphs_category_rules
        )

        # Spawn orientation rule (independent of position), chosen by the YAML
        # key game_screen.spawn_orientation.
        orient_rules = {
            "rule_orient_default": self._rule_orient_default,
            "rule_orient_random": self._rule_orient_random,
        }
        self._orient_rule = select_rule("game_screen.spawn_orientation", orient_rules)

        repeat_rules = {
            "rule_repeat_allow": self._rule_repeat_allow,
            "rule_repeat_block": self._rule_repeat_block,
        }
        self._repeat_rule = select_rule("game_screen.word_repeat", repeat_rules)

        word_trail_rules = {
            "rule_word_trail_on": self._rule_word_trail_on,
            "rule_word_trail_off": self._rule_word_trail_off,
        }
        self._word_trail_rule = select_rule("game_screen.word_trail", word_trail_rules)
        # The cleanup half of the same knob: cells leaving the board drop the word
        # lines drawn through them, so an attacking word's line never outlives the
        # target it was attacking. Keyed off the SAME config value, so recording
        # and dropping can't fall out of step. See CellHealthMixin.
        self._drop_trails_rule = select_rule("game_screen.word_trail", {
            "rule_word_trail_on": self._rule_drop_trails_on_release,
            "rule_word_trail_off": self._rule_drop_trails_never,
        })
        # How long each recorded trail lives before fading itself away
        # (game_screen.word_trail_fade). Independent of the two rules above: they
        # decide whether a line is drawn at all and whether cells leaving take it
        # with them; this decides whether a line that nothing removed times out.
        self._trail_fade_rule = select_rule("game_screen.word_trail_fade", {
            "rule_word_trail_fade_off": self._rule_word_trail_fade_off,
            "rule_word_trail_fade_all": self._rule_word_trail_fade_all,
            "rule_word_trail_fade_nonattacker": self._rule_word_trail_fade_nonattacker,
        })

        # Stage-3 selection strategy, chosen by the YAML key
        # game_screen.word_select. The auto strategy clears instantly; the text-
        # input strategy enters the SELECTING phase and lets the player type the
        # words to clear (see Phase / the selector classes above).
        select_rules = {
            "rule_select_mostwords_withoverlaps_withrepeats": AutoSelect,
            "rule_select_by_text_input": TextInputSelect,
        }
        self._selector = select_rule("game_screen.word_select", select_rules)()

        # Phase-transition rules: when a placement triggers the selection stage.
        # The trigger rule (game_screen.select_trigger) counts placements and
        # says whether this one is a selection turn; the skip rule
        # (game_screen.skip_select_isolated) drops the turn when the placed piece
        # is isolated. Both feed _begin_selection. _placements_until_select is the
        # live countdown the trigger rule advances and the moving pane displays;
        # reset per game in _start_new_game.
        select_trigger_rules = {
            "rule_select_every_placement": self._rule_select_every_placement,
            "rule_select_after_n_placements": self._rule_select_after_n_placements,
        }
        self._select_trigger_rule = select_rule(
            "game_screen.select_trigger", select_trigger_rules
        )
        self._select_trigger_count = CONFIG["rules"]["game_screen.select_trigger_count"]
        # Initial countdown shown before the first placement, picked by the same
        # trigger rule (single edit point in YAML). "Every placement" always shows
        # 1 ("this piece"); "after N" starts a full cycle at N. Without this the
        # label flashed the after-N count on the first turn under every-placement.
        select_trigger_initial = {
            "rule_select_every_placement": 1,
            "rule_select_after_n_placements": self._select_trigger_count,
        }
        self._initial_placements_until_select = select_rule(
            "game_screen.select_trigger", select_trigger_initial
        )
        self._placements_until_select = self._initial_placements_until_select
        skip_select_rules = {
            "rule_skip_select_if_isolated": self._rule_skip_select_if_isolated,
            "rule_never_skip_select": self._rule_never_skip_select,
        }
        self._skip_select_rule = select_rule(
            "game_screen.skip_select_isolated", skip_select_rules
        )

        # Select-phase board-click rule (game_screen.select_click): what a click
        # on a board cell does while SELECTING. The move-piece rule routes the
        # click to the active MOVING mode's board handler, so cells can be
        # rearranged (omniswap swap, etc.) without leaving word entry -- blurring
        # the SELECTING/MOVING line for the free-choice modes. The none rule
        # disables board clicks (the hard phase separation of the timed modes).
        select_click_rules = {
            "rule_select_click_move_piece": self._rule_select_click_move_piece,
            "rule_select_click_none": self._rule_select_click_none,
        }
        self._select_click_rule = select_rule(
            "game_screen.select_click", select_click_rules
        )

        # Player word-piece rule (game_screen.player_word_piece): whether clicking
        # a cleared word in the right pane during MOVING swaps the live piece for a
        # single-cell piece carrying that whole word. The handler returns whether a
        # swap happened, so on_mouse_press knows to consume the click.
        player_word_piece_rules = {
            "rule_player_word_piece_enabled": self._rule_player_word_piece_enabled,
            "rule_player_word_piece_disabled": self._rule_player_word_piece_disabled,
        }
        self._player_word_piece_rule = select_rule(
            "game_screen.player_word_piece", player_word_piece_rules
        )

        # Whether the gram-manipulate button (right-click) also works during the
        # SELECTING phase, not just MOVING (game_screen.gram_manip_in_selecting).
        # The omniswap modes spend most of their play in SELECT, so leaving it
        # MOVING-only makes right-click feel dead there. Evaluated once (static
        # config); see _try_gram_manipulate and the SELECTING branch of
        # on_mouse_press.
        gram_manip_in_selecting_rules = {
            "rule_gram_manip_in_selecting_enabled": self._rule_gram_manip_in_selecting_enabled,
            "rule_gram_manip_in_selecting_disabled": self._rule_gram_manip_in_selecting_disabled,
        }
        self._gram_manip_in_selecting = select_rule(
            "game_screen.gram_manip_in_selecting", gram_manip_in_selecting_rules
        )()

        # WHICH thing a right-click may reshape -- two independent slots, since
        # editing a settled cell and shaping the piece you are about to drop are
        # different verbs (game_screen.rightclicks_on_placed_piece /
        # ..._on_active_piece). Both evaluated once (static config); see
        # _handle_gram_manipulate, which prefers the live piece when both match.
        rightclick_placed_rules = {
            "rule_rightclicks_actionable_on_placed_piece": self._rule_rightclicks_actionable_on_placed_piece,
            "rule_rightclicks_inert_on_placed_piece": self._rule_rightclicks_inert_on_placed_piece,
        }
        self._rightclick_on_placed_piece = select_rule(
            "game_screen.rightclicks_on_placed_piece", rightclick_placed_rules
        )()
        rightclick_active_rules = {
            "rule_rightclicks_actionable_on_active_piece": self._rule_rightclicks_actionable_on_active_piece,
            "rule_rightclicks_inert_on_active_piece": self._rule_rightclicks_inert_on_active_piece,
        }
        self._rightclick_on_active_piece = select_rule(
            "game_screen.rightclicks_on_active_piece", rightclick_active_rules
        )()

        # MOVING-phase mode bundle (game_screen.mode): which moving-phase strategy
        # runs. The mode owns how the moving phase presents its active element and
        # turns one input into one committed action; the shared SELECT pipeline,
        # word-finding, board and dictionary stay on this engine. See MovingMode.
        moving_modes = {
            "rule_mode_jigsaw": JigsawMovingMode,
            "rule_mode_typewriter": TypewriterMovingMode,
            "rule_mode_omniswap_vs_timer": OmniswapVsTimerMode,
            "rule_mode_constellation": ConstellationMode,
            "rule_mode_shooting_gallery": ShootingGalleryMode,
            "rule_mode_line_blast": LineBlastMovingMode,
            "rule_mode_plant_vs_timer": PlantVsTimerMode,
            "rule_mode_botanical": BotanicalMode,
        }
        self._moving_mode = select_rule("game_screen.mode", moving_modes)(self)
        # Constellation mode swaps stage-1 word-finding from the adjacency
        # pathfinder to an on-submit matcher that assembles a typed word from grams
        # ANYWHERE on the board (see ConstellationMixin). The mode advertises this
        # so the shared SELECT pipeline routes candidate lookup + error wording
        # through the constellation seam instead of the pre-enumerated candidate
        # map. False for every other mode.
        self._constellation = self._moving_mode.finds_words_by_constellation
        # Omniswap mode: a fixed pool of freely-swappable grams that fossilizes as
        # words form. The engine reads it to gate the omniswap auto-end + F3 word
        # sample (see _rule_omniswap_auto_end_on / _omniswap_word_samples). False
        # for every other mode.
        self._omniswap = self._moving_mode.is_omniswap
        # Shooting-gallery mode: a fairground shooter where cells are SHOT (not
        # typed) to build a word, greedily submitted the instant it is a dictionary
        # word (see ShootingMixin / ShootingGalleryMode). The engine reads it to draw
        # the crosshair overlay + hide the system cursor. False for every other mode.
        self._shooting = self._moving_mode.is_shooting
        # Shooting-gallery knobs (game_screen.shooting_*), read by ShootingField +
        # ShootingGalleryMode; ignored by every other mode. The crosshair color comes
        # from the colors asset (board.crosshair), overridable per mode via assets.colors.
        self._shooting_batch_size = CONFIG["rules"]["game_screen.shooting_batch_size"]
        self._shooting_batch_count = CONFIG["rules"]["game_screen.shooting_batch_count"]
        self._shooting_batch_delay_seconds = CONFIG["rules"]["game_screen.shooting_batch_delay_seconds"]
        self._shooting_fade_in_seconds = CONFIG["rules"]["game_screen.shooting_fade_in_seconds"]
        self._shooting_hold_seconds = CONFIG["rules"]["game_screen.shooting_hold_seconds"]
        self._shooting_fade_out_seconds = CONFIG["rules"]["game_screen.shooting_fade_out_seconds"]
        self._shooting_shot_fade_seconds = CONFIG["rules"]["game_screen.shooting_shot_fade_seconds"]
        self._shooting_word_timeout_seconds = CONFIG["rules"]["game_screen.shooting_word_timeout_seconds"]
        self._shooting_crosshair_scale = CONFIG["rules"]["game_screen.shooting_crosshair_scale"]
        self._shooting_crosshair_gap = CONFIG["rules"]["game_screen.shooting_crosshair_gap"]
        # Misspell instadeath: when on, a shot buffer that no dictionary word begins
        # with (a dead end -- see ShootingGalleryMode._instadeath) ends the game at
        # once, overriding any running game_timer. Off leaves the buffer to time out
        # as a plain miss. Only read by the shooting mode.
        self._misspell_instadeath = select_rule(
            "game_screen.misspell_instadeath",
            {"rule_misspell_instadeath_off": False,
             "rule_misspell_instadeath_on": True})
        self._crosshair_color = get_color("board.crosshair")
        # Per-mode fossil tint: re-read here (in __init__, AFTER the mode's
        # assets.colors swap) so it tracks the active colors file, unlike the
        # class-level FOSSILIZED_CELL_COLOR fixed at import (see config.apply_game_mode).
        # MOVING_PLANT points assets.colors at plant_colors.yaml, whose fossil tint is
        # green -- so the stem trunk AND the branches grown by cleared plant words read
        # green; every other mode re-reads its own default (grey) unchanged. The
        # instance attribute shadows the class constant for all self.FOSSILIZED_CELL_COLOR
        # readers.
        self.FOSSILIZED_CELL_COLOR = get_color("board.fossilized_fill")
        # Gram-text color for the NON-root stem cells (board.stem_text). Separate from
        # the ordinary cell text so a mode can restyle -- or, set to the stem's own fill,
        # HIDE -- the repeated root glyphs up the trunk while the bottom (root) cell keeps
        # its normal text. Only MOVING_PLANT places stem cells; every other mode ignores it.
        self.STEM_TEXT_COLOR = get_color("board.stem_text")
        # MOVING_BOTANICAL cell tints (per-mode, read after the assets.colors swap):
        # the vertical stem column's spine cells, and the leaf cells words grow into.
        # Both ignored outside botanical. See _rule_formation_botanical / _place_leaf_cell.
        self.STEM_CELL_COLOR = get_color("board.stem_fill")
        self.LEAF_CELL_COLOR = get_color("board.leaf_fill")
        # Line-blast mode: pieces picked from a side-pane pool and dropped on an empty
        # board; a filled row/column opens SELECT over exactly those cells (see
        # LineBlastMovingMode). The engine reads the flag to route mouse motion to the
        # mode and to swap in the line-blast moving pane. False for every other mode.
        self._line_blast = self._moving_mode.is_line_blast
        # Botanical mode: an empty board but for a vertical stem column, where a typed
        # word crosses one stem cell and grows out both sides as leaf cells (see
        # BotanicalMixin). The engine reads it to route word submission through the
        # botanical placement matcher (_on_submit_word) instead of the clear pipeline.
        # False for every other mode.
        self._botanical = self._moving_mode.is_botanical
        # Line-blast knobs (game_screen.line_blast_*), read by LineBlastMovingMode +
        # LineBlastMovingPane; ignored by every other mode.
        self._line_blast_pool_size = CONFIG["rules"]["game_screen.line_blast_pool_size"]
        self._line_blast_slots = CONFIG["rules"]["game_screen.line_blast_slots"]
        self._line_blast_preview_scale = CONFIG["rules"]["game_screen.line_blast_preview_scale"]
        self._line_blast_highlight_color = get_color("board.line_blast_highlight")
        self._line_blast_valid_color = get_color("board.line_blast_floating_valid")
        self._line_blast_invalid_color = get_color("board.line_blast_floating_invalid")
        # The completed row/column cells currently highlighted for line-blast SELECT
        # (the nucleation domain; the whole set clears on Next piece). Empty except
        # while a line-blast SELECT is open. Reset per game in _start_new_game.
        self._line_blast_highlight = set()
        # Phase model (game_screen.phase_model): two distinct phases (MOVING then
        # SELECTING) or one merged MOVING_AND_SELECTING pane where the player
        # rearranges the board and submits words inline, never leaving MOVING.
        # Single-phase is meaningful only for an interactive selector on a pre-
        # filled-board mode; the auto selector never opens SELECT to begin with.
        self._single_phase = select_rule(
            "game_screen.phase_model",
            {"rule_two_phase": False, "rule_single_phase": True},
        )
        # Right-pane control-button visibility (game_screen.show_*_button): each
        # button label on the SELECT / merged pane is built only when its flag is
        # set. Hiding a button drops just the clickable label -- the keyboard route
        # (ENTER submits, the selection_end / word_clear keys) is untouched.
        self._show_clear_btn = select_rule(
            "game_screen.show_clear_button",
            {"rule_show_clear_button": True, "rule_hide_clear_button": False},
        )
        self._show_submit_btn = select_rule(
            "game_screen.show_submit_button",
            {"rule_show_submit_button": True, "rule_hide_submit_button": False},
        )
        self._show_next_btn = select_rule(
            "game_screen.show_next_button",
            {"rule_show_next_button": True, "rule_hide_next_button": False},
        )
        # End game: "auto" keeps its historical behavior -- shown only for
        # constellation, which has no piece to shrink the board and (endless preset)
        # no victory rule to close on -- or force it always on / off.
        _end_btn_mode = select_rule(
            "game_screen.show_end_button",
            {"rule_end_button_auto": "auto",
             "rule_show_end_button": True,
             "rule_hide_end_button": False},
        )
        self._show_end_btn = (
            self._constellation if _end_btn_mode == "auto" else _end_btn_mode
        )
        # Idea belt (game_screen.idea_belt): the young-player picture conveyor
        # takes over the lower right pane, dropping the score / cleared-word list /
        # dictionary count that would otherwise fill it. The pane that owns the
        # typed field builds it (merged pane in single-phase, SELECT pane in
        # two-phase); the widget itself is cached in self._idea_belt below so the
        # per-frame tick and the new-game reshuffle can reach it.
        self._show_idea_belt = select_rule(
            "game_screen.idea_belt",
            {"rule_idea_belt_on": True, "rule_idea_belt_off": False},
        )
        self._idea_belt = None
        # How the belt's ring is STOCKED (idea_belt.stock_category_weight.*):
        # a weighted mix of stocking categories rather than one selected rule, so
        # one ring can carry both multigram-using pictures and plainly spellable
        # ones. Each category here is scanned only when its weight is above zero;
        # weight on `blind` alone leaves the belt dealing itself a random ring.
        # Wired before the panes are built -- a stocked belt opens with an empty
        # ring and is filled by _stock_idea_belt once each game's formation is
        # down. See WordFindMixin and models.idea_pool.STOCK_CATEGORIES.
        self._idea_stock_category_rules = {
            "spellable_multigram": self._rule_idea_stock_category_spellable_multigram,
            "spellable_by_path": self._rule_idea_stock_category_spellable_by_path,
            "spellable_any_gram": self._rule_idea_stock_category_spellable_any_gram,
        }
        # What a cleared word does to the belt (idea_belt.match): strike the
        # matching picture off and pay the match bonus, or leave the conveyor
        # alone. Resolved even when the belt is off -- the rule reads
        # self._idea_belt, which stays None there, so it is a no-op.
        idea_match_rules = {
            "rule_idea_match_clear_and_bonus": self._rule_idea_match_clear_and_bonus,
            "rule_idea_match_off": self._rule_idea_match_ignore,
        }
        self._idea_match_rule = select_rule("idea_belt.match", idea_match_rules)
        # Cap on how many distinct cell-assemblies the constellation matcher
        # returns per submitted word (the disambiguation chooser cycles them;
        # auto-pick keeps the fewest-cell one). Ignored by the other modes.
        self._constellation_max_paths = CONFIG["rules"]["game_screen.constellation_max_paths"]
        # Constellation turnover (game_screen.constellation_turnover): after a word
        # clears, whether the vacated cells stay empty (board shrinks toward the
        # grid-empty win) or refill with fresh grams (endless board). Only consulted
        # in constellation mode; see _commit_clear_now.
        constellation_turnover_rules = {
            "rule_constellation_no_replenish": self._rule_constellation_no_replenish,
            "rule_constellation_replenish": self._rule_constellation_replenish,
        }
        self._constellation_turnover_rule = select_rule(
            "game_screen.constellation_turnover", constellation_turnover_rules)
        # Seconds a replenished (vacated-then-refilled) cell fades in; 0 = instant
        # pop. Generic across modes -- constellation's replenish turnover and plant's
        # refresh clear-action both use it. Live fades tracked in _replenish_fades,
        # ticked in update and built by _begin_replenish_fade. See replenish_fade_seconds.
        self._replenish_fade_seconds = CONFIG["rules"][
            "game_screen.replenish_fade_seconds"]
        self._replenish_fades = []
        # Seconds a vacated cell stays empty before its replenishment gram is placed;
        # 0 = fill instantly. Generic across modes (see above). Pending waits tracked
        # in _pending_replenishes, counted down in update and queued by
        # _schedule_replenish. See replenish_delay_seconds.
        self._replenish_delay_seconds = CONFIG["rules"][
            "game_screen.replenish_delay_seconds"]
        self._pending_replenishes = []
        # Constellation auto-end (game_screen.constellation_auto_end): after a word
        # clears, optionally finish the game once the remaining grams can spell no
        # dictionary word. Off by default (an auto-finish reveals board exhaustion,
        # against the no-hints rule). Only consulted in constellation mode; see
        # _commit_clear_now.
        constellation_auto_end_rules = {
            "rule_constellation_auto_end_off": self._rule_constellation_auto_end_off,
            "rule_constellation_auto_end_on": self._rule_constellation_auto_end_on,
        }
        self._constellation_auto_end_rule = select_rule(
            "game_screen.constellation_auto_end", constellation_auto_end_rules)
        # Omniswap auto-end (game_screen.omniswap_auto_end): after a word fossilizes,
        # optionally finish the game once the remaining SWAPPABLE grams can spell no
        # submittable word -- so the player isn't left running down the clock hunting
        # for a word that cannot exist (e.g. the board is all but fully fossilized).
        # Off by default (an auto-finish reveals board exhaustion, against the
        # no-hints rule). Only consulted in omniswap mode; see _commit_clear_now.
        omniswap_auto_end_rules = {
            "rule_omniswap_auto_end_off": self._rule_omniswap_auto_end_off,
            "rule_omniswap_auto_end_on": self._rule_omniswap_auto_end_on,
        }
        self._omniswap_auto_end_rule = select_rule(
            "game_screen.omniswap_auto_end", omniswap_auto_end_rules)
        # Debug panel (F3): example words the board can currently spell. Recomputed
        # only while the panel is visible and the board changed (_dbg_words_dirty),
        # so hidden play pays nothing; a rising edge of visibility re-dirties so the
        # samples appear as soon as the panel opens. See _refresh_debug_word_samples.
        self._dbg_words_dirty = True
        self._dbg_panel_was_visible = False
        # How many example words to sample (a short list, never a count -- see the
        # no-word-availability-hints rule; a count is a stronger hint).
        self._dbg_word_sample_count = 5
        # Seconds the MOVING_OMNISWAP countdown starts at (game_screen.mode:
        # rule_mode_omniswap_vs_timer); ignored by the other modes.
        self._omniswap_timer_seconds = CONFIG["rules"]["game_screen.omniswap_timer_seconds"]
        # Omniswap timer + endgame variant (game_screen.omniswap_timer), read by
        # OmniswapVsTimerMode. Both variants share the timer length above:
        #   rule_omniswap_timer_per_phase (False) -- the clock runs only in MOVING
        #     and resets to full each time a word returns play to MOVING; timer-
        #     zero forces a last-chance SELECT and leaving SELECT with no word ends
        #     the game (surrender). The original omniswap behavior.
        #   rule_omniswap_timer_race (True) -- one continuous clock counts down
        #     across BOTH phases; the player toggles MOVING/SELECT freely and the
        #     game ends the instant the clock hits zero (FINISHED, no win check).
        #   rule_omniswap_timer_sand ("sand") -- no global clock; up to
        #     sand_timer_count cells fill over sand_timer_seconds each, fossilizing
        #     on fill; the game ends when the whole board is fossilized. See
        #     SandTimerField. The timer follows its gram on a swap.
        omniswap_timer_variants = {
            "rule_omniswap_timer_per_phase": "per_phase",
            "rule_omniswap_timer_race": "race",
            "rule_omniswap_timer_sand": "sand",
        }
        variant = select_rule("game_screen.omniswap_timer", omniswap_timer_variants)
        self._omniswap_timer_race = variant == "race"
        self._omniswap_timer_sand = variant == "sand"
        # Whole-game countdown (game_screen.game_timer on/off + game_timer_seconds
        # for its length): a single wall clock owned by GameScreen -- not by any
        # one mode -- that runs across MOVING and SELECTING alike and ends the game
        # (FINISHED, no win check) at zero. Mode-agnostic sibling of the omniswap timer above:
        # that clock lives inside OmniswapVsTimerMode, this one lets ANY mode be
        # time-boxed (e.g. a constellation speed-type). Started in _finish_loading,
        # ticked in update(), painted + expired in _tick_game_timer (boardrules).
        # Do not pair with an omniswap timer variant -- they share the pane label
        # and both end at zero. See CONFIG_REFERENCE.md.
        self._game_timer_on = select_rule(
            "game_screen.game_timer",
            {"rule_game_timer_off": False, "rule_game_timer_on": True})
        self._game_timer_seconds = CONFIG["rules"]["game_screen.game_timer_seconds"]
        self._game_timer_remaining = float(self._game_timer_seconds)
        self._game_timer_last_shown = None
        # Sand-timer settings (rule_omniswap_timer_sand only); see SandTimerField.
        # A cell's life is a silent delay then the filling animation.
        self._sand_timer_delay_seconds = CONFIG["rules"]["game_screen.sand_timer_delay_seconds"]
        self._sand_timer_seconds = CONFIG["rules"]["game_screen.sand_timer_seconds"]
        self._sand_timer_count = CONFIG["rules"]["game_screen.sand_timer_count"]
        # Whether the word-piece feature is on, as a plain flag a mode can read
        # before doing its own mode-specific replacement (jigsaw swaps the live
        # piece via _player_word_piece_rule; typewriter replaces the cursor gram).
        self._word_piece_enabled = (
            CONFIG["rules"]["game_screen.player_word_piece"]
            == "rule_player_word_piece_enabled"
        )

        # Typewriter swap rule (game_screen.typewriter_swap): on a cursor<->cell
        # swap, which of the two cells count as placed (nucleation sites) this
        # turn. The TypewriterMovingMode hands the swapped pair here and feeds the
        # result to _begin_selection; see the _rule_swap_places_* methods.
        typewriter_swap_rules = {
            "rule_swap_places_cursor_only": self._rule_swap_places_cursor_only,
            "rule_swap_places_both": self._rule_swap_places_both,
        }
        self._typewriter_swap_rule = select_rule(
            "game_screen.typewriter_swap", typewriter_swap_rules
        )

        # Clear-timing rule (game_screen.clear_timing): when a typed word clears.
        #   rule_clear_on_submit -- each submit clears immediately, recomputing
        #     against the shrinking board (original interactive behavior)
        #   rule_clear_at_phase_end -- submits are held (cells tinted green) and
        #     all clear together at phase end, so cells reuse across words
        #     (overlaps + repeats), the interactive twin of
        #     rule_select_mostwords_withoverlaps_withrepeats
        # One config key drives two seams -- what a submit does and what phase end
        # does -- so two registries resolve the same key to a paired method.
        submit_clear_rules = {
            "rule_clear_on_submit": self._rule_submit_clears_now,
            "rule_clear_at_phase_end": self._rule_submit_defers,
        }
        self._submit_clear_rule = select_rule(
            "game_screen.clear_timing", submit_clear_rules
        )
        endphase_clear_rules = {
            "rule_clear_on_submit": self._rule_endphase_clear_none,
            "rule_clear_at_phase_end": self._rule_endphase_clear_pending,
        }
        self._endphase_clear_rule = select_rule(
            "game_screen.clear_timing", endphase_clear_rules
        )
        # Single-phase overrides the clear-timing pair to clear-on-submit; see the
        # method for why (no phase boundary to flush a batch into). No-op otherwise.
        self._force_single_phase_clear_timing()

        # Disambiguation rule (game_screen.clear_disambiguation): how the one
        # spelling to clear is chosen when a submitted word has several clearable
        # paths -- and whether a lone path still asks to confirm. Both clear-timing
        # seams route their candidate list through it (see _rule_submit_clears_now
        # / _rule_submit_defers); auto-pick returns a FoundWord immediately, the
        # cycle rules open the board chooser and return None (the choice commits
        # later via the on_confirm callback). The two cycle rules differ only in
        # the candidate count at which the chooser opens: 2+ (a lone path clears
        # instantly) vs 1+ (every valid submit previews + confirms).
        disambig_rules = {
            "rule_disambig_auto_pick": self._rule_disambig_auto_pick,
            "rule_disambig_cycle_two_or_more_choices":
                self._rule_disambig_cycle_two_or_more_choices,
            "rule_disambig_cycle_one_or_more_choices":
                self._rule_disambig_cycle_one_or_more_choices,
        }
        self._disambiguation_rule = select_rule(
            "game_screen.clear_disambiguation", disambig_rules
        )
        # Whether word_clear backs out of the open chooser or is ignored (commit).
        disambig_cancel_rules = {
            "rule_disambig_cancel_on": self._rule_disambig_cancel_on,
            "rule_disambig_cancel_off": self._rule_disambig_cancel_off,
        }
        self._disambig_cancel_rule = select_rule(
            "game_screen.disambig_cancel", disambig_cancel_rules
        )
        # Whether a back-out gesture actually closes the chooser (mirrors the
        # cancel rule above); lets the typing/edit/escape back-outs know if the
        # gesture may then edit the field (see _backout_disambiguation).
        self._disambig_cancel_enabled = select_rule(
            "game_screen.disambig_cancel",
            {"rule_disambig_cancel_on": True, "rule_disambig_cancel_off": False},
        )
        # Botanical grow-site disambiguation (game_screen.botanical_disambiguation):
        # how WHERE a submitted word grows is chosen when several stem crossings /
        # leaf layouts fit. Botanical bypasses the SELECT clear pipeline, so its
        # _botanical_submit consults this seam directly -- auto-pick grows the most
        # compact layout, the cycle rules reuse the shared chooser (blue lines).
        botanical_disambig_rules = {
            "rule_botanical_disambig_auto_pick":
                self._rule_botanical_disambig_auto_pick,
            "rule_botanical_disambig_cycle_two_or_more_choices":
                self._rule_botanical_disambig_cycle_two_or_more_choices,
            "rule_botanical_disambig_cycle_one_or_more_choices":
                self._rule_botanical_disambig_cycle_one_or_more_choices,
        }
        self._botanical_disambiguation_rule = select_rule(
            "game_screen.botanical_disambiguation", botanical_disambig_rules
        )
        # Whether a rejected submit echoes the typed word as a ghost above a
        # cleared field (game_screen.reject_ghost); see _reject_submission.
        self._reject_ghost = select_rule(
            "game_screen.reject_ghost",
            {"rule_reject_ghost_on": True, "rule_reject_ghost_off": False},
        )
        # How a rejected submit surfaces its reason in the right pane
        # (game_screen.error_display): the text message (default), or a reason
        # icon in place of the text. Passed to the SELECT / merged pane, which maps
        # the reason key (_last_reject_reason) to an icon; reasons with no icon
        # fall back to text. See _reject_submission and the panes' show_errors.
        self._error_display = select_rule(
            "game_screen.error_display",
            {"rule_error_text": "text", "rule_error_icon": "icon"},
        )
        # When error_display is the icon, whether a "did you mean?" spelling
        # suggestion still rides under the icon as text, or is dropped so only the
        # icon shows (game_screen.error_icon_keeps_suggestion). Inert under
        # rule_error_text (text mode always shows the suggestion). Passed to the
        # SELECT / merged pane; see the panes' show_errors.
        self._error_icon_keeps_suggestion = select_rule(
            "game_screen.error_icon_keeps_suggestion",
            {"rule_error_icon_keeps_suggestion_on": True,
             "rule_error_icon_keeps_suggestion_off": False},
        )
        # Stable reason key of the most recent rejection (set by the _*_error
        # functions right before they log it); read by _reject_submission.
        self._last_reject_reason = None
        # On a NOT-ON-BOARD reject, whether to redden the "You typed:" ghost letters
        # that don't exist anywhere on the board (game_screen.missing_letter_highlight);
        # a pure letter-existence hint, no tiling. See _missing_letters.
        self._missing_letter_highlight = select_rule(
            "game_screen.missing_letter_highlight",
            {"rule_missing_letter_highlight_on": True,
             "rule_missing_letter_highlight_off": False},
        )
        # Whether ENTER-into-SELECT auto-submits the carried word-hunt word
        # (game_screen.select_autosubmit_hunt), skipping the dead middle ENTER;
        # see the interactive branch of _begin_selection.
        self._select_autosubmit_hunt = select_rule(
            "game_screen.select_autosubmit_hunt",
            {
                "rule_select_autosubmit_on": True,
                "rule_select_autosubmit_off": False,
            },
        )

        # Select word-limit rule (game_screen.select_word_limit): whether the
        # interactive SELECT phase ends after the first accepted word or stays
        # open for more. Consulted after each accepted submit; composes with the
        # clear-timing rules above. See the _rule_*_per_select methods.
        select_word_limit_rules = {
            "rule_unlimited_words": self._rule_unlimited_words,
            "rule_one_word_per_select": self._rule_one_word_per_select,
        }
        self._select_word_limit_rule = select_rule(
            "game_screen.select_word_limit", select_word_limit_rules
        )

        # Spelling-suggestion rule (game_screen.spell_suggest): the "did you mean?"
        # engine consulted when a submitted word isn't in the dictionary. Takes a
        # typed word, returns up to a couple of close in-dictionary spellings.
        self._spell_suggest_rule = select_rule(
            "game_screen.spell_suggest", SUGGEST_RULES
        )

        # Interactive selectors build their UI in the right-pane region (same
        # spot as the side pane; shown only while SELECTING).
        # Constellation has no piece to shrink the board and (endless preset) no
        # victory rule, so surface a manual End game button in its SELECT pane;
        # every other mode closes on its own and hides it.
        if self._single_phase:
            # MOVING_AND_SELECTING (game_screen.phase_model = rule_single_phase):
            # the game never leaves MOVING, so one merged pane serves both roles.
            # Point BOTH slots at it -- the submit pipeline talks to the selecting
            # slot, the hunt highlight + status labels to the moving slot -- and it
            # replaces the plain MovingSidePane built earlier in __init__.
            # Shooting gallery drives the merged field by SHOOTING, not typing, and
            # its buffer letters need not be on the board -- so the live word-HUNT
            # highlight (on_change) has nothing meaningful to light and is dropped.
            on_change = None if self._shooting else self._on_hunt_change
            merged = MovingSelectingSidePane(
                self._moving_side_pane.x, 0, self._moving_side_pane.width, window.height,
                on_submit=self._on_submit_word, on_change=on_change,
                on_end=self._enter_endgame, show_end=self._show_end_btn,
                show_clear=self._show_clear_btn, show_submit=self._show_submit_btn,
                error_display=self._error_display,
                error_icon_keeps_suggestion=self._error_icon_keeps_suggestion,
                show_idea_belt=self._show_idea_belt,
            )
            self._moving_side_pane = merged
            self._selecting_side_pane = merged
            self._idea_belt = merged.idea_belt()
        else:
            # Interactive selectors build their UI in the right-pane region (same
            # spot as the side pane; shown only while SELECTING).
            self._selecting_side_pane = self._selector.create_ui(
                self._moving_side_pane.x, 0, self._moving_side_pane.width, window.height,
                on_submit=self._on_submit_word, on_next=self._end_selection,
                on_end=self._enter_endgame, show_end=self._show_end_btn,
                show_clear=self._show_clear_btn, show_submit=self._show_submit_btn,
                show_next=self._show_next_btn, error_display=self._error_display,
                error_icon_keeps_suggestion=self._error_icon_keeps_suggestion,
                show_idea_belt=self._show_idea_belt,
            )
            # Auto (non-interactive) selectors build no UI, so there is no pane to
            # hang the belt on -- getattr keeps that case a plain None.
            if self._selecting_side_pane is not None:
                self._idea_belt = self._selecting_side_pane.idea_belt()
            # Line blast swaps the plain MovingSidePane (hunt field + cleared list)
            # for the piece-preview pane: up to `slots` half-size previews of the
            # pool pieces the player can drop next, a running score, and a manual
            # End-game button (line blast has no victory rule). SELECTING still uses
            # the SelectingSidePane built above. Preview cell = half the board cell,
            # sized from the same square-region math the grid builder uses (the board
            # isn't built until _start_new_game, so _cell_size isn't set yet).
            if self._line_blast:
                preview_cell = math.floor(
                    self._grid_area_size / self.GRID_WIDTH * self._line_blast_preview_scale)
                self._moving_side_pane = LineBlastMovingPane(
                    side_pane_x, 0, side_pane_width, window.height,
                    on_end=self._enter_endgame, preview_cell=preview_cell,
                    slots=self._line_blast_slots)
        self._set_phase(Phase.MOVING)
        # Candidate word-paths for the move being selected (interactive only):
        # the full path list plus a word -> path map (first path wins a tie).
        self._candidates = []
        self._candidate_words = {}
        # Every clearable spelling, mapped word -> list of FoundWords (all paths
        # / wild expansions, not just the fewest-cell one). Batch mode reads it to
        # hand out a distinct path each time a word is re-submitted.
        self._candidate_word_options = {}
        # Batch (clear-at-phase-end) mode: FoundWords selected this phase but not
        # yet cleared. Their cells are tinted green; the whole list clears when
        # the phase ends. Empty in clear-on-submit mode.
        self._pending = []
        # Open "select which one" chooser (the cycle rules only): the ordered
        # candidate FoundWords, the highlighted index, the submitted word, and the
        # callback that commits the chosen one (clear-now or defer, per timing).
        # _disambig_options is empty except while a chooser is open.
        self._disambig_options = []
        self._disambig_index = 0
        self._disambig_word = None
        self._disambig_commit = None
        # Words accepted during the current interactive SELECT phase. Reset on
        # entering SELECT, bumped on each accepted submit; MOVING_OMNISWAP reads
        # it to decide whether leaving SELECT continues the game or ends it.
        self._words_submitted_this_select = 0
        # Wider word sets the submission-error diagnosis reads (see
        # _recompute_candidates): every board word ignoring length, and those
        # that meet the length minimum.
        self._board_words_any = set()
        self._length_ok_words = set()
        # Words passing every stage-2 filter except the fossil requirement (see
        # _recompute_candidates), read by _submission_error to word a fossil-only
        # rejection.
        self._pre_fossil_words = set()
        # Cells of EVERY piece placed since the last selection turn -- the
        # accumulated nucleation set for the moving phase. With the multi-
        # placement select trigger several pieces land before selection opens, so
        # this grows as each is placed (see _begin_selection) and empties once
        # the pieces settle (see _settle_placed_cells). Nucleation and the
        # candidate recompute run against the ones still on the board as words
        # clear.
        self._move_placed = set()

        # Nucleation rule, chosen by the YAML key game_screen.word_nucleation.
        # Of every word found on the board, this decides which count for the move
        # just made -- the gate between pathfinding and selection. Grid-agnostic.
        #   rule_adjacent_to_placed_pieces -- bridge a placed cell and an old one
        #   rule_nucleate_anywhere -- any board word counts (no placement tie)
        #   rule_nucleate_none -- nothing qualifies (clearing off)
        nucleation_rules = {
            "rule_adjacent_to_placed_pieces": self._rule_adjacent_to_placed_pieces,
            "rule_nucleate_anywhere": self._rule_nucleate_anywhere,
            "rule_nucleate_none": self._rule_nucleate_none,
            "rule_nucleate_within_highlight": self._rule_nucleate_within_highlight,
        }
        self._nucleation_rule = select_rule(
            "game_screen.word_nucleation", nucleation_rules
        )

        # Placed-cell requirement, chosen by game_screen.placed_cell_requirement.
        # An independent second stage-2 filter applied after nucleation: whether a
        # word must include at least one cell from a piece placed this moving
        # phase. Orthogonal to word_nucleation, so it composes -- e.g.
        # rule_nucleate_anywhere + rule_require_placed_cell keeps any board word
        # that also touches a placed cell. Default optional, so the existing
        # nucleation rule's own placed-cell requirement is unchanged.
        placed_cell_rules = {
            "rule_require_placed_cell": self._rule_require_placed_cell,
            "rule_placed_cell_optional": self._rule_placed_cell_optional,
        }
        self._placed_cell_rule = select_rule(
            "game_screen.placed_cell_requirement", placed_cell_rules
        )

        # Fossil requirement, chosen by game_screen.fossil_requirement. A third
        # independent stage-2 filter (2c), applied after the placed-cell filter:
        # whether a word must include at least one fossilized cell. Fossils only
        # appear once a word has cleared under a fossilize clear-action (see
        # _is_fossilized), so on its own this makes the very first word of a game
        # unclearable -- pair with the first-word-skip rule below to bootstrap.
        # Default optional, so existing configs are unchanged.
        fossil_req_rules = {
            "rule_require_fossil_cell": self._rule_require_fossil_cell,
            "rule_fossil_cell_optional": self._rule_fossil_cell_optional,
        }
        self._fossil_requirement_rule = select_rule(
            "game_screen.fossil_requirement", fossil_req_rules
        )
        # First-word skip (game_screen.fossil_requirement_first_word): an
        # enable/disable knob read by rule_require_fossil_cell. When enabled, the
        # fossil requirement is waived while no word has cleared this game yet, so
        # the opening word can bootstrap the first fossils; disabled keeps the
        # requirement in force from the very first word (unplayable unless fossils
        # already exist). A third variant, rule_fossil_seed_center, instead SEEDS a
        # fossil near the board center at game start (see the seed registry below),
        # so the requirement can hold from word one without waiving -- hence it maps
        # to _rule_fossil_no_skip here (never waive; a fossil already exists).
        fossil_first_word_rules = {
            "rule_fossil_skip_first_word": self._rule_fossil_skip_first_word,
            "rule_fossil_no_skip": self._rule_fossil_no_skip,
            "rule_fossil_seed_center": self._rule_fossil_no_skip,
        }
        self._fossil_first_word_rule = select_rule(
            "game_screen.fossil_requirement_first_word", fossil_first_word_rules
        )
        # Start-of-game fossil seeding, driven by the SAME knob so swapping the rule
        # is a one-line edit. Only rule_fossil_seed_center seeds anything; the skip
        # / no-skip variants seed nothing. Invoked once per game in _start_new_game
        # (after the board is filled, before the opening reveal).
        fossil_first_word_seed_rules = {
            "rule_fossil_skip_first_word": self._rule_fossil_seed_none,
            "rule_fossil_no_skip": self._rule_fossil_seed_none,
            "rule_fossil_seed_center": self._rule_fossil_seed_center,
        }
        self._fossil_first_word_seed_rule = select_rule(
            "game_screen.fossil_requirement_first_word", fossil_first_word_seed_rules
        )

        # Gram-usage rule (game_screen.gram_usage): may a word use only part of a
        # cell's gram. rule_gram_use_whole demands the entire gram (original
        # behavior); rule_gram_use_partial lets a word start inside a gram (a
        # suffix of its first cell) and end inside one (a prefix of its last
        # cell), leaving the unused letters on the board. Drives _collect_words
        # (pathfinding) and _clear_paths (leftover re-lettering).
        gram_usage_rules = {
            "rule_gram_use_whole": self._rule_gram_use_whole,
            "rule_gram_use_partial": self._rule_gram_use_partial,
        }
        self._gram_usage_rule = select_rule(
            "game_screen.gram_usage", gram_usage_rules
        )

        # Fossil-word-use rule (game_screen.fossil_word_use): may a NEW word use fossilized
        # cells. One config key drives two seams of _collect_words -- whether the
        # walk treats a fossil as a wall, and whether a finished word's fossil mix
        # is allowed -- so the two registries below share the same key.
        #   rule_fossil_block -- fossils are walls (original behavior)
        #   rule_fossil_allow -- fossils are walkable, but a word must include at
        #     least one non-fossilized cell.
        fossil_wall_rules = {
            "rule_fossil_block": self._rule_fossil_block_is_wall,
            "rule_fossil_allow": self._rule_fossil_allow_is_wall,
        }
        self._fossil_is_wall_rule = select_rule(
            "game_screen.fossil_word_use", fossil_wall_rules
        )
        fossil_word_rules = {
            "rule_fossil_block": self._rule_fossil_block_word_ok,
            "rule_fossil_allow": self._rule_fossil_allow_word_ok,
        }
        self._fossil_word_ok_rule = select_rule(
            "game_screen.fossil_word_use", fossil_word_rules
        )

        self._start_new_game()

    def _start_new_game(self):
        """Begin a fresh game: rebuild the board and piece pools and drop a new
        random set of obstacles. Called once at construction and again every
        time the player (re)enters from the menu via "Start Game".

        Each game gets brand-new batches so every shape from the previous game
        (grid lines, placed pieces, obstacles) is released together for GC,
        rather than piling up invisible behind the new board."""
        # Every game opens in LOADING: the formation + grid lines fade in on a
        # timeline (see _begin_loading) before play starts. _finish_loading flips
        # to MOVING and starts the active mode (spawn / timer).
        self._set_phase(Phase.LOADING)
        if self._selecting_side_pane is not None:
            self._selecting_side_pane.begin()
            self._dictionary_count_rule(self._selecting_side_pane, len(self._player_dict))
        self._board_batch = pyglet.graphics.Batch()
        self._piece_batch = pyglet.graphics.Batch()
        # Drop last game's hunt-highlight overlays before the new board's pieces
        # build fresh ones (they share one batch across games; see hunt_highlight).
        reset_hunt_highlight()
        # Sand-timer fills (rule_omniswap_timer_sand): the rising bottom-up cell
        # fills, drawn on top of the piece cells/labels. Its own batch so draw()
        # can layer it above the board without touching the piece rendering.
        self._sand_batch = pyglet.graphics.Batch()
        # Drop last game's path trails (they accumulate within a game only).
        self._word_trail.clear()
        # Deal a fresh idea-belt ring and rewind the conveyor, so a replayed
        # session's belt is the one its log_06009 line records. A no-op when the
        # belt is off. Done here (not in the pane) because the belt may live on
        # either pane and only one of them gets a per-game reset call.
        if self._idea_belt is not None:
            self._idea_belt.reset()
        # Separate batch for the starting obstacle pieces. Their cells live on
        # the board once dropped, but render through this batch so they stay
        # visually grouped and independently styleable.
        self._obstacle_batch = pyglet.graphics.Batch()
        # Mission pieces get their own batch too, the twin of the obstacle batch.
        self._mission_batch = pyglet.graphics.Batch()

        # Grid bundle, chosen by the YAML key game_screen.grid. The chosen
        # builder also wires up its own movement + clear rules and sizes the
        # pieces, so it must run before the pools are built.
        grid_rules = {
            "rule_use_square_grid": self._rule_use_square_grid,
            "rule_use_hex_grid": self._rule_use_hex_grid,
            "rule_use_triangle_grid": self._rule_use_triangle_grid,
        }
        self._board = select_rule("game_screen.grid", grid_rules)(self._window)

        # Every word cleared this game, so the repeat rule can prevent a word
        # from being cleared twice. Fresh per game, alongside the cleared-word
        # list shown in the side pane.
        self._cleared_word_history = set()
        # Fresh per game: an ORDERED, de-duplicated record of the words cleared
        # this game -- each with the gram grouping it was cleared with THIS game
        # (not the player dictionary's other known groupings) and the points it
        # earned. Feeds the endgame typing bonus, which re-displays and re-scores
        # these words after play ends; see _record_cleared_word.
        self._cleared_word_records = []
        # Fresh per game: no endgame is running or pending (a new game may start
        # from a finished one, mid-card or mid-typing-bonus).
        self._endgame_intro_remaining = None
        if self._endgame is not None:
            self._endgame.stop()
        # Fresh per game: the starting obstacle cells the victory rule tracks.
        self._obstacle_cells = set()
        # Fresh per game: the starting mission cells (obstacles' twin).
        self._mission_cells = set()
        # Fresh per game: cells fossilized by formed words (empty until a fossilize
        # clear-action runs; see _is_fossilized).
        self._fossilized_cells = set()
        # Fresh per game: the plant/botanical stem cells + plant root, repopulated by
        # rule_formation_plant / rule_formation_botanical below (empty / None in every
        # other mode). _sprouted_stem_cells tracks which botanical stems have grown.
        self._stem_cells = set()
        self._plant_root = None
        self._sprouted_stem_cells = set()
        # Fresh per game: the line-blast highlighted line(s) (empty until a placement
        # completes a row/column; see LineBlastMovingMode).
        self._line_blast_highlight = set()
        # Fresh per game: how many words have cleared so far. Drives the
        # first-word skip for the fossil requirement (rule_fossil_skip_first_word);
        # 0 means the opening word hasn't landed yet.
        self._words_cleared_this_game = 0
        # Fresh per game: the whole-board fill bonus fires at most once (see
        # _check_board_fill / game_screen.fill_board).
        self._fill_board_awarded = False
        # Fresh per game: zero the point total, then show it on the panes.
        self._scorer.reset()
        self._moving_side_pane.reset()
        self._dictionary_count_rule(self._moving_side_pane, len(self._player_dict))
        self._refresh_score()
        # Fresh per game: restart the selection-trigger countdown and show it.
        # Uses the rule-specific initial value so the label is right before the
        # first placement (every-placement shows 1, not the after-N count).
        self._placements_until_select = self._initial_placements_until_select
        self._moving_side_pane.set_phase_label(self._placements_until_select)

        # Lay out the opening obstacle + mission pieces per the active starting-
        # formation rule (game_screen.setup_formation): it builds the obstacle and
        # mission pools at the counts the formation calls for and places every
        # piece (recording cells in _obstacle_cells / _mission_cells). These use
        # their own piece set + gram-pick rules (square_obstacle.* / hex_obstacle.*
        # and the mission twins) and their own batches. Separate from the
        # per-piece player spawn rule. Rebuilt every game, so each game gets a
        # fresh opening.
        # Fresh per game: forget multi-letter grams used by the previous game so
        # the gram.dedup rule starts clean. Must run before any piece is built
        # (formation below + the player pool), since both pick through pick_grams.
        reset_gram_dedup()
        # Per-cell *fix the formation BINNED a gram for (e.g. a region trigram drawn
        # from the prefix vs midsuf pool), so the fade categorizers use that as the
        # gram's primary *fix instead of re-deriving by priority. Filled by the
        # ideation formations; empty for the others (-> priority fallback). Reset here.
        self._formation_fix_tags = {}
        # The unigram cap (gram.unigram_dedup) applies to the opening formation
        # only -- bracket the formation build so the piece pool below draws
        # uncapped (100+ pieces can't fit under a few copies of each letter).
        begin_formation_gram_run()
        self._setup_formation_rule()
        end_formation_gram_run()

        # Hand the freshly-placed obstacle / mission cells their health, now that
        # the formation has recorded them in _obstacle_cells / _mission_cells. A
        # no-op under rule_cell_health_off. See views/game_screen_health.py.
        # The damage overlay is rebuilt first, per game: it draws into the
        # (per-game) sand batch and reads the (per-game) board's cell outlines.
        # Fresh cells are undamaged, so it starts with nothing drawn.
        self._damage_fill = RisingFill(
            self._board, self._sand_batch,
            get_color("board.damage_fill"), self._damage_fill_opacity)
        # The border indicators' twin. The "dash" overlay paints part of each slot
        # in board.damage_dash -- the board background color blanks the outline so
        # it reads as dashed, while any other color (red, say) paints visible
        # dashes ON it instead. The "mark" overlay paints the damage color over the
        # whole slot, so the outline reddens. See views/border_dashes.py.
        self._damage_border_gap = BorderDashes(
            self._board, self._sand_batch, get_color("board.damage_dash"),
            self._damage_border_thickness, span=0.55)
        self._damage_border_mark = BorderDashes(
            self._board, self._sand_batch, get_color("board.damage_fill"),
            self._damage_border_thickness, span=1.0)
        self._assign_cell_health()

        # Seed any start-of-game fossils (game_screen.fossil_requirement_first_word:
        # rule_fossil_seed_center). Runs after the formation has filled the board
        # (so there are grams to fossilize) and before _begin_loading (so the seeded
        # cell reveals in the fossilized fade category). A no-op for the other
        # first-word variants.
        self._fossil_first_word_seed_rule()

        # Stock the idea belt's ring against the board the formation just laid
        # (idea_belt.stock_category_weight.*). Here because this is the first
        # moment there IS a board to scan -- the belt's own reset() above runs
        # before the grid is even rebuilt. A no-op with the belt off, or when no
        # stocking category carries weight.
        self._stock_idea_belt()

        self._piece_pool = PiecePool(
            self.PIECE_POOL_SIZE, self._cell_size, self._piece_batch,
            self._piece_class, self._player_piece_types,
            cell_color=self.ACTIVE_PIECE_CELL_COLOR
        )
        # No word-piece swap active at the start of a game (the player word-piece
        # feature; see _swap_to_word_piece). Cleared here so a swap left dangling
        # by a previous game's restart is dropped with its old batch.
        self._override_piece = None
        # Begin the opening reveal FIRST: constructing the LoadingAnimation blanks
        # every just-placed cell (opacity 0 / white-faded), so the board starts
        # empty and nothing flashes before the fade. This must precede the coverage
        # pass below, which may force a frame (its CALCULATING label) mid-load --
        # otherwise that frame would show the whole board for an instant.
        self._begin_loading()
        # Optional debug/analysis pass (game_screen.starting_coverage_dictionary):
        # enumerate every word this opening board could spell. It reads the grams
        # from the board data, which the blanking above (opacity only) doesn't
        # touch, so it still measures the untouched starting formation. Blocking,
        # so nothing animates until it returns; a no-op under the default 'off' rule.
        self._starting_coverage_rule()

    # Extracted to BoardSetupMixin (views/game_screen_setup.py); see there.

    
    # Extracted to PieceControlMixin (views/game_screen_piece.py); see there.

    # Extracted to GramManipMixin (views/game_screen_grammanip.py); see there.


    def _rule_repeat_allow(self, word):
        """Allow a word to clear even if it cleared before (original behavior)."""
        return True

    def _rule_repeat_block(self, word):
        """Block a word that has already been cleared earlier this game."""
        return word not in self._cleared_word_history

    # Mode-title rule (game_screen.mode_title): whether the current game mode's
    # name is shown as a single line along the top of the board (see draw /
    # self._mode_title_label). Resolved once at construction.
    def _rule_mode_title_on(self):
        """Show the active mode's label (blank if on the bare base config)."""
        active = active_mode()
        self._mode_title_label.text = active[1] if active else ""

    def _rule_mode_title_off(self):
        """No title (leave the label blank so it draws nothing)."""
        self._mode_title_label.text = ""

    # Word-trail rule (game_screen.word_trail): whether a cleared word leaves a
    # path trail overlaid on the board (see _clear_paths / views.word_trail).
    def _rule_word_trail_on(self, accepted):
        """Record a path trail for each cleared word, center to center. Tagged
        with the word's cells, so a trail can later be dropped when those cells
        leave the board -- which is how an attacking word's line disappears with
        the target it was attacking (see CellHealthMixin._release_dead_cells).
        Uses the grid's VISUAL center, so a line into a jumbo hexagon meets it in
        the middle rather than at its anchor triangle."""
        for fw in accepted:
            points = [self._board.cell_visual_center(x, y) for (x, y) in fw.path]
            self._word_trail.add_path(points, cells=fw.path,
                                      fade_seconds=self._trail_fade_rule(fw))

    def _rule_word_trail_off(self, accepted):
        """No path trails (the original behavior)."""
        pass

    # Trail-fade rule (game_screen.word_trail_fade): how long a freshly drawn
    # trail stays before fading itself off the board. Each returns the fade time
    # for ONE word's trail in seconds, or None for "never fades" (it then leaves
    # only with its cells, per _drop_trails_rule). Ticked in views.word_trail's
    # update(); the duration is game_screen.word_trail_fade_seconds, deliberately
    # a game_screen knob rather than an animation.yaml one, since it is a gameplay
    # readability choice per mode and not a piece of the shared animation kit.
    def _rule_word_trail_fade_off(self, fw):
        """Trails never fade: they accumulate for the whole game (the original
        behavior)."""
        return None

    def _rule_word_trail_fade_all(self, fw):
        """Every trail fades out over word_trail_fade_seconds, attacker lines
        included. The board self-cleans; a health target's trail may vanish before
        the target falls."""
        return self._word_trail_fade_seconds

    def _rule_word_trail_fade_nonattacker(self, fw):
        """Fade only the trails that clear plain board cells, and leave a trail
        that runs through a health-carrying cell (obstacle / mission) up. Those
        attacker lines are information -- they show which words are committed to a
        target -- and they already disappear when the target falls, so this fades
        exactly the leftover lines from words spelled away from the targets.
        Identical to rule_word_trail_fade_all when cell health is off (no cell
        carries health, so no word is an attacker)."""
        attacking = False
        for cell in fw.path:
            if cell in self._cell_health:
                attacking = True
        if attacking:
            fade = None
        else:
            fade = self._word_trail_fade_seconds
        return fade

    # Bare-instance defaults for the fade, in the same spirit as CellHealthMixin's
    # block: a __new__ test instance (no __init__, so no select_rule pass) reads the
    # feature as OFF instead of raising. Named methods, not lambdas, so instance
    # access still binds self. __init__ overwrites both.
    _trail_fade_rule = _rule_word_trail_fade_off
    _word_trail_fade_seconds = 0.0

    # The word-clearing pipeline runs in four stages, each its own seam:
    #   1. pathfind  -- find every dictionary word on the board (_find_words)
    #   2. nucleate  -- keep the words that count for this move
    #                   (self._nucleation_rule, game_screen.word_nucleation)
    #   3. select    -- pick which to clear (self._selector, game_screen.word_
    #                   select): the auto strategy chooses instantly, the text-
    #                   input strategy waits on the player across frames
    #   4. clear     -- read each word, gate on the repeat rule, remove cells
    #                   (_clear_paths)
    # Stage 1's geometry is configured per board (hex_grid.word_pathfinding) and
    # stage 4 is mechanical; stages 2-3 are the swappable seams.
    def _piece_touches_existing(self, piece_cells):
        """True if any still-present cell of `piece_cells` is physically adjacent
        to an occupied cell outside that set. Gates the SELECT phase: cells that
        touch nothing can never bridge into a word, and their isolation is
        plainly visible, so we skip SELECT for them. `piece_cells` may be one
        piece (the mid-select exit check) or the whole accumulated placed set
        (the entry skip rule) -- two placed pieces adjacent only to each other
        still read as isolated, since each other's cells are inside the set. Cells
        that DO touch the board always open SELECT, however -- regardless of
        whether a word can actually be formed -- since opening only when one
        exists would tip the player off that it does."""
        piece = set(piece_cells)
        for (x, y) in piece:
            if self._board.gram_at(x, y) is None:
                continue  # this piece cell has since been cleared
            for (nx, ny) in self._board.neighbors(x, y):
                if (nx, ny) not in piece and self._board.gram_at(nx, ny) is not None:
                    return True
        return False

    def _mark_placed_cells(self, positions):
        """Tint a just-placed piece's cells the placed (light-blue) color and add
        them to the accumulated nucleation set. They stay lit -- through every
        further placement this moving phase -- until selection leaves them behind
        (see _settle_placed_cells). Distinct from the live piece's darker active
        tint, so the player can tell the movable piece from the placed ones."""
        self._move_placed |= set(positions)
        for (x, y) in positions:
            cell = self._board.get_cell(x, y)
            if cell is not None and cell.square is not None:
                cell.square.color = self.PLACED_PIECE_CELL_COLOR

    def _settle_placed_cells(self):
        """Revert every placed piece's still-present cells from the placed
        (light-blue) tint to the settled board color, and empty the accumulated
        nucleation set. Called when the pieces are left behind: on leaving
        SELECT, when SELECT is skipped, or on victory. Cells already cleared
        (square is None) are skipped."""
        for (x, y) in self._move_placed:
            cell = self._board.get_cell(x, y)
            if cell is not None and cell.square is not None:
                # Resting color, not a hardcoded settled fill: a cell fossilized
                # this turn keeps its stone tint instead of reverting to white.
                cell.square.color = self._cell_resting_color((x, y))
        self._move_placed = set()
        # A placement that just settled may have filled the board (jigsaw fills
        # empty cells until none remain); award the fill bonus if so.
        self._check_board_fill()

    # Extracted to BoardRulesMixin (views/game_screen_boardrules.py); see there.


    # Extracted to SelectionMixin (views/game_screen_selection.py); see there.


    # Word-finding + word-gating rules (stage 1 pathfinding, gram-usage,
    # fossil-walk, nucleation, placed-cell/fossil requirements, fossil
    # seeding) live in WordFindMixin -- see views/game_screen_wordfind.py.

    # Extracted to PieceControlMixin (views/game_screen_piece.py); see there.

    def _on_hunt_change(self, text):
        """The MOVING-phase hunt field changed (typed / backspaced / cleared):
        re-light every board + active-piece gram involved in the typed word."""
        self._refresh_hunt_highlight(text)

    def _apply_hunt_to_overlay(self, overlay, gram, text):
        """Light `overlay`'s letters per the active match rule, or clear it. Wilds
        (no letters) and empty grams never light."""
        if overlay is None:
            return
        if not text or gram is None or gram.is_wild or not gram.text:
            overlay.clear()
            return
        overlay.set_matched(self._hunt_match_rule(gram.text, text))

    def _refresh_hunt_highlight(self, text=None):
        """Re-apply the word-hunt highlight for `text` (default: the current hunt
        field) across every settled board cell and the visible active piece. Wilds
        are skipped (they render as a sprite, not a label). Empty text clears all.
        Called on each keystroke, on a fresh piece spawn, and after a gram is
        relabeled -- each a cheap per-glyph color pass, no allocation."""
        if text is None:
            text = self._moving_side_pane.hunt_text()
        for (x, y) in self._board.occupied_cells():
            cell = self._board.get_cell(x, y)
            if cell is not None:
                self._apply_hunt_to_overlay(cell.overlay, cell.gram, text)
        # The live piece too (only when it's actually floating on the board -- e.g.
        # omniswap never deals a visible piece, so its current piece is skipped).
        piece = self._current_piece()
        if piece is not None and not piece.placed and piece.visible:
            for _gx, _gy, _c, _l, gram, overlay in piece.get_cell_data():
                self._apply_hunt_to_overlay(overlay, gram, text)
    
    # Extracted to PieceControlMixin (views/game_screen_piece.py); see there.

    def on_enter(self):
        self._menu_open = False
        self._ingame_menu.reset()
        # Open a fresh session log before the game is built so the formation /
        # gram draws (logged in a later chunk) land in the file. The construction
        # call to _start_new_game runs before any on_enter, so its throwaway board
        # is never recorded. log_00001 marks the first body line.
        session_log.start_session(self._window)
        L.log_00001()
        # Entering from the menu ("Start Game") begins a fresh game, which lays
        # down a new random obstacle set.
        self._start_new_game()

    def on_exit(self):
        # Leaving the game screen without reaching an end state (surrender to
        # menu, quit) still closes the session so no file is left dangling open.
        # A game that ended via _enter_endstate already closed it -- no-op here.
        if session_log.is_open():
            L.log_00002("left_screen")
            session_log.close(reason="left_screen")
        # Stop any end-of-game clip so its audio does not keep playing off-screen.
        self._end_video.stop()
        # Never leave the game screen with the system cursor hidden (shooting mode
        # hides it for the crosshair); restore it for the menu / other screens.
        self._window.set_mouse_visible(True)

    def dispose(self):
        """Detach this screen's window handlers so it can be dropped for GC. Called
        when switching game modes rebuilds a fresh GameScreen (see main.start_game_mode):
        __init__ pushes _key_state onto the window, so without this the old screen's
        handler would keep firing (and leak) alongside the new one's. Closes any
        session still open, the same as on_exit."""
        self.on_exit()
        self._window.remove_handlers(self._key_state)
    
    def draw(self):
        # glClearColor wants 0-1 floats, but colors.yaml stores 0-255 channels,
        # so normalize. Clear to the board background, then restore the default
        # window background for the menu/title screens that just call clear().
        bg = get_color("board.background")
        win_bg = get_color("window.background")
        pyglet.gl.glClearColor(bg[0] / 255, bg[1] / 255, bg[2] / 255, 1)
        self._window.clear()
        pyglet.gl.glClearColor(win_bg[0] / 255, win_bg[1] / 255, win_bg[2] / 255, 1)

        # ENDGAME: the endgame mode owns the whole screen -- the board is no longer
        # relevant once play is over, so its region is reused for the endgame's own
        # display (the words to type) and the right pane for its typing UI. The
        # board / pane / overlay drawing below is skipped entirely.
        if self._phase == Phase.ENDGAME:
            self._endgame.draw()
            if self._menu_open:
                self._ingame_menu.draw()
            # The end-of-game clip still plays over everything, as it does over the
            # frozen board -- it started at the end transition and may outlast the
            # END GAME card. Inactive in every mode with no clip configured.
            if self._end_video.active:
                self._end_video.draw()
            return

        self._board_batch.draw()
        self._obstacle_batch.draw()
        self._mission_batch.draw()
        self._piece_batch.draw()
        # Current game-mode title, along the top of the board (blank on base config).
        self._mode_title_label.draw()
        # Word-hunt highlight overlays: a transparent per-letter paint layer drawn
        # directly on top of the gram glyphs (board + active piece). Empty (draws
        # nothing) unless the player is hunting a word in the MOVING side pane.
        get_hunt_highlight_batch().draw()
        # Sand-timer fills sit above the cells/glyphs (translucent, so the gram
        # stays readable underneath); empty in every non-sand mode.
        self._sand_batch.draw()
        # Cleared-word path trails, on top of the board cells and glyphs.
        self._word_trail.draw()
        # Candidate polylines for the open "select which one" chooser, above the
        # trails; empty (draws nothing) when no chooser is open.
        self._disambig_lines.draw()
        # Shooting-gallery aiming reticle, over the board while the player is aiming
        # (MOVING, menu closed). Drawn only in shooting mode; the system cursor is
        # hidden to match (see _sync_shooting_cursor).
        if (self._shooting and self._phase == Phase.MOVING and not self._menu_open):
            self._moving_mode.draw_crosshair()
        # The right pane swaps between the opening "LOADING..." pane, the
        # game-long cleared-word list (MOVING) and the word-entry UI (SELECTING).
        if self._phase == Phase.LOADING:
            self._load_side_pane.draw()
        elif self._phase == Phase.SELECTING:
            self._selecting_side_pane.draw()
        else:
            self._moving_side_pane.draw()

        # On a win, the VICTORY panel sits over the grid; the pane above already
        # reverted to the cleared-word list (phase is no longer SELECTING). A click
        # dismisses it (see on_mouse_press), leaving just the final board on view.
        if self._phase == Phase.VICTORY and not self._end_overlay_dismissed:
            self._victory_overlay.draw()

        if self._menu_open:
            self._ingame_menu.draw()

        # The end-of-game clip plays fullscreen over everything else while the game
        # is frozen; it removes itself when the clip finishes (see EndVideoOverlay).
        # Inactive (draws nothing) in every mode that leaves game_screen.end_video off.
        if self._end_video.active:
            self._end_video.draw()

    def _sync_shooting_cursor(self):
        """Hide the system cursor exactly while the shooting-gallery crosshair is
        live -- MOVING with the menu closed -- and show it again whenever the menu
        is open or the game has ended (so the player can point at the pause menu / a
        dismiss click). A no-op outside shooting mode. Called on every menu toggle
        and end transition; the mode also hides it once on start()."""
        if self._shooting:
            live = self._phase == Phase.MOVING and not self._menu_open
            self._window.set_mouse_visible(not live)

    def update(self, dt):
        # End-of-game clip: tear it down once it has played through. Runs ahead of
        # every phase/menu guard below so the video always self-dismisses, even if
        # the pause menu is opened over the frozen end state. A no-op when idle.
        self._end_video.update()
        # END GAME card countdown: with an endgame mode configured, the end panel
        # holds for a moment and then the endgame view takes the screen over. Runs
        # while the game is frozen (that freeze is the point) but pauses with the
        # pause menu, like every other timed thing here. A no-op when no hand-off
        # is pending -- including every mode that leaves game_screen.endgame off.
        if not self._menu_open:
            self._tick_endgame_intro(dt)
        # Debug panel (F3) formable-word samples: recompute only while the panel is
        # visible and something changed, so normal (hidden) play does no dictionary
        # work. Opening the panel counts as a change, so the samples show at once.
        self._update_debug_word_samples()
        # During the opening reveal, drive the fade-in (paused while the menu is
        # open, like the moving timer below); when it finishes, hand off to the
        # active mode. No piece spawns and no timer runs until then.
        if self._phase == Phase.LOADING:
            if not self._menu_open:
                self._loading_anim.update(dt)
                if self._loading_anim.done:
                    self._finish_loading()
            return
        # ENDGAME: play is over, so nothing below (the board fades, trails, the
        # whole-game clock, the active mode) applies -- only the endgame view ticks,
        # and it pauses with the menu like everything else.
        if self._phase == Phase.ENDGAME:
            if not self._menu_open:
                self._endgame.update(dt)
            return
        # Drive the active mode's per-tick hook only during MOVING (and never
        # while the pause menu is open), so a timed mode counts down only when the
        # player can actually act. Event-driven modes ignore this. SELECTING gets
        # its own hook, used only by a mode whose clock spans both phases (the
        # omniswap race variant); every other mode leaves it a no-op.
        if self._menu_open:
            return
        # Idea belt: the right pane's picture conveyor keeps turning through both
        # play phases, and pauses with the menu like every other timed thing (it
        # sits under the guard above). None unless game_screen.idea_belt is on.
        if self._idea_belt is not None:
            self._idea_belt.update(dt)
        # Fill in any cells whose empty-cell replenish delay has elapsed
        # (constellation), then bloom in any cells replenished this game. Both run
        # in every play phase (a two-phase clear replenishes in SELECTING, then
        # hands back to MOVING mid-wait/fade), paused with the menu like the timer.
        self._update_pending_replenishes(dt)
        self._update_replenish_fades(dt)
        # Age out the cleared-word path trails (game_screen.word_trail_fade). Runs
        # in every play phase and pauses with the menu, like the fades above; a
        # no-op when no trail carries a fade time.
        self._word_trail.update(dt)
        # Whole-game countdown (game_screen.game_timer_seconds): one clock spanning
        # both play phases, owned here so it is mode-agnostic. A no-op when off.
        # Ticked before the mode so an expiry ends the game this frame.
        self._tick_game_timer(dt)
        if self._phase == Phase.MOVING:
            self._moving_mode.update(dt)
        elif self._phase == Phase.SELECTING:
            self._moving_mode.update_during_select(dt)
