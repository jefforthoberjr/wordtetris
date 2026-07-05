import math
import time
from collections import namedtuple, Counter, defaultdict
from enum import Enum
import pyglet
from views.ingame_menu import IngameMenu
from views.moving_mode import JigsawMovingMode, TypewriterMovingMode, OmniswapVsTimerMode
from views.moving_side_pane import MovingSidePane
from views.selecting_side_pane import SelectingSidePane
from views.load_side_pane import LoadSidePane
from views.loading_animation import LoadingAnimation, AlphaFade, WhiteFade
from views.word_trail import WordTrail
from views.disambiguation_lines import DisambiguationLines
from views.victory_overlay import VictoryOverlay
from views.hunt_highlight import (
    get_hunt_highlight_batch, reset_hunt_highlight, get_hunt_match_rule,
)
from controllers.screen_manager import ScreenType
from models.piece_pool import PiecePool
from models.square_piece import SquarePiece, PLAYER_PIECE_TYPES as SQUARE_PLAYER_PIECE_TYPES
from models.square_piece import OBSTACLE_PIECE_TYPES as SQUARE_OBSTACLE_PIECE_TYPES
from models.square_piece import OBSTACLE_GRAM_PICK_RULE as SQUARE_OBSTACLE_GRAM_PICK_RULE
from models.square_piece import MISSION_PIECE_TYPES as SQUARE_MISSION_PIECE_TYPES
from models.square_piece import MISSION_GRAM_PICK_RULE as SQUARE_MISSION_GRAM_PICK_RULE
from models.hex_piece import HexPiece, PLAYER_PIECE_TYPES as HEX_PLAYER_PIECE_TYPES
from models.hex_piece import OBSTACLE_PIECE_TYPES as HEX_OBSTACLE_PIECE_TYPES
from models.hex_piece import OBSTACLE_GRAM_PICK_RULE as HEX_OBSTACLE_GRAM_PICK_RULE
from models.hex_piece import MISSION_PIECE_TYPES as HEX_MISSION_PIECE_TYPES
from models.hex_piece import MISSION_GRAM_PICK_RULE as HEX_MISSION_GRAM_PICK_RULE
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
from models.hex_domino import hex_neighbor
from models.hex_domino import HEX_UP, HEX_DOWN
from models.hex_domino import HEX_UP_LEFT, HEX_DOWN_LEFT
from models.hex_domino import HEX_UP_RIGHT, HEX_DOWN_RIGHT
from models.square_grid import SquareGrid
from models.hex_grid import HexGrid
from models.word_dictionary import (
    is_word, is_prefix, is_obscure, select_maximal_paths, all_words)
from models.spelling_suggester import SUGGEST_RULES
from starting_coverage import write_coverage_csv
from models.wild_vowel import wild_expansions
from models.player_dictionary import PlayerDictionary
from config import select_rule, get_color, get_string, CONFIG
from controls import control_keys, control_button, control_modifier
import session_log
import log_codes as L
# All gameplay/setup randomness routes through the swappable Source seam (see
# source.py) so a replay reproduces or overrides formation, spawns and tie-breaks.
from source import rand


class Phase(Enum):
    """Game-screen phases. LOADING: the opening reveal -- formation cells and
    grid lines fade in on a timeline and all input is blocked; no live piece,
    no timer (see loading_animation). MOVING: a piece is live and the player
    moves/places it. SELECTING: a piece has been placed and the player is
    choosing which words to clear before the next piece spawns (interactive
    selection rules only; the auto selector never leaves MOVING). VICTORY: the
    active victory rule was met -- no live piece, no word entry; the player can
    only open the menu (Escape)."""
    LOADING = 0
    MOVING = 1
    SELECTING = 2
    VICTORY = 3


# One dictionary word found on the board: the cell `path`, the `segments` each
# cell contributed in order (a wild cell's resolved 1-3 vowel run, else the
# gram's letters), and the `word` they spell. A plain (no-wild) path yields one
# FoundWord; a path through a wild cell can yield several (CAT, COT, CUT ...),
# one per expansion that completes a word.
FoundWord = namedtuple("FoundWord", ["path", "segments", "word"])


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

    def create_ui(self, x, y, width, height, on_submit, on_next):
        return None


class TextInputSelect:
    """Interactive: the player types a word and submits it (Enter or the Submit
    control) to clear that word, repeating until they hit Next piece. The UI is
    a SelectingSidePane in the right-pane region."""
    interactive = True

    def create_ui(self, x, y, width, height, on_submit, on_next):
        return SelectingSidePane(x, y, width, height, on_submit, on_next)


# Control key bindings now live in assets/controls.yaml (loaded via controls.py).
# The old in-code CONTROL_KEYS dict moved there wholesale; self._keys / self._
# buttons below are built from it. Old version, for reference:
#   CONTROL_KEYS = {"move_left": "A", "move_right": "D", "move_up": "W",
#       "move_down": "S", "rotate_clockwise": "LEFT",
#       "rotate_counterclockwise": "RIGHT", "place": "SPACE", "pause": "ESCAPE"}
#   def _get_key(action): return getattr(pyglet.window.key, CONTROL_KEYS[action])


# Modifier bits worth recording on a logged key press; the OS lock keys
# (NUMLOCK / CAPSLOCK / SCROLLLOCK) are dropped as noise. See log_20001.
_LOG_MODIFIERS = (
    (pyglet.window.key.MOD_SHIFT, "SHIFT"),
    (pyglet.window.key.MOD_CTRL, "CTRL"),
    (pyglet.window.key.MOD_ALT, "ALT"),
    (pyglet.window.key.MOD_COMMAND, "CMD"),
)


def _mods_str(modifiers):
    """The meaningful held modifiers as a '+'-joined string ('' if none)."""
    return "+".join(name for bit, name in _LOG_MODIFIERS if modifiers & bit)

# Note: a cell can hold a multi-letter gram
#   - letters: how many letters the word spells (len of `text`)
#   - cells: how many cells/grams the word spans (len of `path`)
def rule_word_min2letters_min2cells(text, path):
    return len(text) >= 2 and len(path) >= 2

def rule_word_min3letters_min2cells(text, path):
    return len(text) >= 3 and len(path) >= 2

# Minimum-word rule (letters + cells), chosen by the YAML key game_screen.word_length.
_WORD_LENGTH_RULES = {
    "rule_word_min2letters_min2cells": rule_word_min2letters_min2cells,
    "rule_word_min3letters_min2cells": rule_word_min3letters_min2cells,
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


# --- gram-manipulation rules (game_screen.rightclick_*) --------------------
# A RIGHT-click on a board cell during the MOVING phase manipulates that one
# cell's gram, dispatched by the gram's length (a separate rule for unigrams,
# digrams, and trigrams-or-larger) plus a fourth for wild-vowel cells. Each rule
# takes the cell's current gram TEXT and returns the NEW text, or None to leave
# the cell untouched -- so rule_rightclick_none restores the original behavior
# (right-click did nothing). The dispatcher (_handle_gram_manipulate) relabels
# the cell with whatever non-None text comes back.

def rule_unigram_double(text):
    """Unigram: double the single letter (O -> OO, B -> BB)."""
    return text + text

def rule_cc_collapse(text):
    """CC digram (a doubled consonant, LL): collapse to the single letter,
    CC -> C (LL -> L). The forward C -> CC lives in the unigram slot
    (rule_unigram_double), so the two together make the L <-> LL toggle. Returns
    None if the pair isn't a real double."""
    if len(text) == 2 and text[0] == text[1]:
        return text[0]                 # LL -> L
    return None

def rule_cv_double(text):
    """CV digram (consonant+vowel, BA): double the consonant, C -> CC
    (BA -> BBA); the 3-letter CCV form collapses back, CC -> C (BBA -> BA).
    Returns None otherwise. The dispatcher routes only CV / CCV grams here
    (see _gram_manip_family), so the shape is trusted."""
    if len(text) == 2:
        return text[0] + text          # BA -> BBA
    if len(text) == 3:
        return text[1:]                # BBA -> BA
    return None

def rule_vc_double(text):
    """VC digram (vowel+consonant, AN): double the consonant, C -> CC
    (AN -> ANN); the 3-letter VCC form collapses back, CC -> C (ANN -> AN).
    Returns None otherwise. The dispatcher routes only VC / VCC grams here."""
    if len(text) == 2:
        return text + text[1]          # AN -> ANN
    if len(text) == 3:
        return text[:2]                # ANN -> AN
    return None

def rule_ck_double(text):
    """CK digram (two DISTINCT consonants, ST): double the FRONT consonant,
    C -> CC (ST -> SST); the 3-letter CCK form collapses back, CC -> C
    (SST -> ST). Front-only by design -- the back double (STT) never lands in
    real words (0/59 CK digrams in the corpus vs. 32% for the front), so it's
    dropped, and no alternation state is needed. Returns None otherwise. The
    dispatcher routes only CK / CCK grams here."""
    if len(text) == 2:
        return text[0] + text          # ST -> SST
    if len(text) == 3:
        return text[1:]                # SST -> ST
    return None

def rule_vcv_double(text):
    """VCV trigram (ARE): double the single middle consonant, C -> CC
    (ARE -> ARRE); a 4-letter VCCV whose middle is a real double collapses back,
    CC -> C (ARRE -> ARE). Returns None otherwise. The dispatcher only routes
    genuine VCV / VCCV grams here (see _gram_manip_family), so the shape is
    trusted. Corpus-backed: doubling the middle consonant lands inside real words
    for ~73% of the VCV trigrams (ate->atte, ile->ille, ome->omme)."""
    if len(text) == 3:
        return text[0] + text[1] + text[1] + text[2]     # ARE -> ARRE
    if len(text) == 4 and text[1] == text[2]:
        return text[0] + text[1] + text[3]               # ARRE -> ARE
    return None

def rule_cvk_double(text, side="back"):
    """CVK trigram (MER): double a consonant, C -> CC. `side` picks which one --
    'front' -> CCVK (MER -> MMER), 'back' -> CVKK (MER -> MERR); the dispatcher
    alternates side across successive doubles on a cell (see _advance_cvk_side)
    so BOTH forms are reachable. A 4-letter doubled form collapses back, CC -> C
    (MMER -> MER, MERR -> MER); `side` is irrelevant there. Returns None
    otherwise. The dispatcher routes only genuine CVK-family grams here."""
    if len(text) == 4:
        if text[0] == text[1]:
            return text[1:]                              # MMER -> MER
        if text[2] == text[3]:
            return text[:3]                              # MERR -> MER
        return None
    if len(text) == 3:
        return text[0] + text if side == "front" else text + text[2]
    return None

def rule_rightclick_none(text):
    """Right-click leaves this gram untouched -- the original behavior, before
    cell gram-manipulation existed. Returns None so the dispatcher relabels
    nothing."""
    return None

_GRAM_MANIP_RULES = {
    "rule_unigram_double": rule_unigram_double,
    "rule_cc_collapse": rule_cc_collapse,
    "rule_cv_double": rule_cv_double,
    "rule_vc_double": rule_vc_double,
    "rule_ck_double": rule_ck_double,
    "rule_vcv_double": rule_vcv_double,
    "rule_cvk_double": rule_cvk_double,
    "rule_rightclick_none": rule_rightclick_none,
}

# Y is a CONSONANT here (strict AEIOU), so ITY / ARY / PHY are NOT read as
# VCV/CVK -- a deliberate choice: doubling a consonant in those Y-shapes never
# lands in real words (see the corpus note in config.yaml).
_STRICT_VOWELS = set("AEIOU")

def _is_manip_vowel(ch):
    return ch in _STRICT_VOWELS

def _gram_manip_family(text):
    """Classify a 2+ letter gram for right-click routing by its vowel/consonant
    shape (Y is a consonant). Returns the config-slot key that owns this gram's
    doubling cycle, or None for an unmatched shape -- a plain no-op, only
    reachable at 3+ letters (CKV, VCK, CKS were analyzed and found not worth a
    doubling rule; see the config note):
      2-letter:  'cc' (LL), 'ck' (ST), 'cv' (BA), 'vc' (AN), 'vv' (EE / EA)
      3-letter forward:  'vcv' (ARE), 'cvk' (MER)
      3-letter reverse (the doubled results the digram rules produce, recognized
        so a second right-click collapses them):  'cv' (CCV=BBA), 'vc' (VCC=ANN),
        'ck' (CCK=SST) -- only when the doubled pair is a REAL double, so genuine
        clusters (STR, CKV, VCK) stay unmatched
      4-letter reverse:  'vcv' (ARRE), 'cvk' (MMER / MERR)"""
    v = [_is_manip_vowel(c) for c in text]
    n = len(text)
    if n == 2:
        if not v[0] and not v[1]:
            return "cc" if text[0] == text[1] else "ck"
        if not v[0]:
            return "cv"
        if not v[1]:
            return "vc"
        return "vv"
    if n == 3:
        if v == [True, False, True]:
            return "vcv"
        if v == [False, True, False]:
            return "cvk"
        if v == [False, False, True] and text[0] == text[1]:
            return "cv"                                   # CCV (BBA) -> collapse
        if v == [True, False, False] and text[1] == text[2]:
            return "vc"                                   # VCC (ANN) -> collapse
        if v == [False, False, False] and text[0] == text[1]:
            return "ck"                                   # CCK (SST) -> collapse
    elif n == 4:
        if v == [True, False, False, True] and text[1] == text[2]:
            return "vcv"                                  # ARRE
        if v == [False, False, True, False] and text[0] == text[1]:
            return "cvk"                                  # MMER
        if v == [False, True, False, False] and text[2] == text[3]:
            return "cvk"                                  # MERR
    return None


class GameScreen:
    GRID_WIDTH = CONFIG["rules"]["game_screen.grid_width"]
    PIECE_POOL_SIZE = CONFIG["rules"]["game_screen.piece_pool_size"]
    # Obstacle pieces the scattered formation drops before play begins; also gates
    # the obstacle victory rule (0 == board never had obstacles). Config-surfaced
    # near game_screen.setup_formation; the ring formation derives its own count.
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

    def __init__(self, window, screen_manager):
        self._window = window
        self._screen_manager = screen_manager

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
        side_pane_x = self._grid_area_size
        side_pane_width = window.width - self._grid_area_size
        self._moving_side_pane = MovingSidePane(
            side_pane_x, 0, side_pane_width, window.height,
            on_change=self._on_hunt_change,
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

        # Cleared-word path trails, overlaid on top of the board. Accumulate all
        # game; cleared on each new game. The game_screen.word_trail rule gates
        # whether _clear_paths records into it. See views/word_trail.py.
        self._word_trail = WordTrail()

        # Transient candidate polylines for the "select which one" chooser
        # (a game_screen.clear_disambiguation cycle rule). Empty except while a
        # submitted word with several clearable paths is being resolved.
        # See views/disambiguation_lines.py and _begin_disambiguation.
        self._disambig_lines = DisambiguationLines()

        # The player's lifetime word collection, persisted across every game.
        # Words cleared for the first time ever are shown green and autosaved.
        self._player_dict = PlayerDictionary()

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
            "rule_victory_none": self._rule_victory_none,
        }
        self._victory_rule = select_rule("game_screen.victory", victory_rules)
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
            "rule_clear_remove": self._rule_clear_remove,
            "rule_clear_fossilize": self._rule_clear_fossilize,
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
            "rule_formation_scattered": self._rule_formation_scattered,
            "rule_formation_mission_center_obstacle_ring": self._rule_formation_mission_center_obstacle_ring,
            "rule_formation_fill_player_diagonal": self._rule_formation_fill_player_diagonal,
            "rule_formation_fill_player_wood_grain": self._rule_formation_fill_player_wood_grain,
            "rule_formation_fill_player_random": self._rule_formation_fill_player_random,
            "rule_formation_fill_ideation_trigram_sidepanes_digram_centercircle":
                self._rule_formation_fill_ideation_trigram_sidepanes_digram_centercircle,
            "rule_formation_fill_ideation_trigram_sidepanes_digram_bottompyramid":
                self._rule_formation_fill_ideation_trigram_sidepanes_digram_bottompyramid,
            "rule_formation_fill_ideation_trigram_sidepanes":
                self._rule_formation_fill_ideation_trigram_sidepanes,
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

        # How the opening reveal (LOADING) buckets SETTLED formation cells into fade
        # categories (game_screen.loading_fade_category). Special cells (mission /
        # obstacle / fossilized) are always categorized by their kind first; this
        # rule only governs the ordinary settled cells. Each scheme's category names
        # must have a slot in loading_animation.yaml. See _rule_loading_fade_by_*.
        loading_fade_category_rules = {
            "rule_loading_fade_by_length": self._rule_loading_fade_by_length,
            "rule_loading_fade_by_ideation_strength": self._rule_loading_fade_by_ideation_strength,
            "rule_loading_fade_by_ideation_fix": self._rule_loading_fade_by_ideation_fix,
            "rule_loading_fade_by_ideation_length_strength_fix":
                self._rule_loading_fade_by_ideation_length_strength_fix,
        }
        self._loading_fade_category_rule = select_rule(
            "game_screen.loading_fade_category", loading_fade_category_rules
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

        # MOVING-phase mode bundle (game_screen.mode): which moving-phase strategy
        # runs. The mode owns how the moving phase presents its active element and
        # turns one input into one committed action; the shared SELECT pipeline,
        # word-finding, board and dictionary stay on this engine. See MovingMode.
        moving_modes = {
            "rule_mode_jigsaw": JigsawMovingMode,
            "rule_mode_typewriter": TypewriterMovingMode,
            "rule_mode_omniswap_vs_timer": OmniswapVsTimerMode,
        }
        self._moving_mode = select_rule("game_screen.mode", moving_modes)(self)
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
        # Whether a rejected submit echoes the typed word as a ghost above a
        # cleared field (game_screen.reject_ghost); see _reject_submission.
        self._reject_ghost = select_rule(
            "game_screen.reject_ghost",
            {"rule_reject_ghost_on": True, "rule_reject_ghost_off": False},
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
        self._selecting_side_pane = self._selector.create_ui(
            self._moving_side_pane.x, 0, self._moving_side_pane.width, window.height,
            on_submit=self._on_submit_word, on_next=self._end_selection,
        )
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
        }
        self._board = select_rule("game_screen.grid", grid_rules)(self._window)

        # Every word cleared this game, so the repeat rule can prevent a word
        # from being cleared twice. Fresh per game, alongside the cleared-word
        # list shown in the side pane.
        self._cleared_word_history = set()
        # Fresh per game: the starting obstacle cells the victory rule tracks.
        self._obstacle_cells = set()
        # Fresh per game: the starting mission cells (obstacles' twin).
        self._mission_cells = set()
        # Fresh per game: cells fossilized by formed words (empty until a fossilize
        # clear-action runs; see _is_fossilized).
        self._fossilized_cells = set()
        self._moving_side_pane.reset()
        self._dictionary_count_rule(self._moving_side_pane, len(self._player_dict))
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

    # --- LOADING phase (opening reveal) ------------------------------------
    def _begin_loading(self):
        """Enter LOADING: bucket every just-placed cell (and the grid lines) into
        fade categories and build the LoadingAnimation that reveals them on the
        loading_animation.yaml timeline (its constructor blanks them). The active
        mode is NOT started yet -- _finish_loading does that when the reveal ends,
        so no piece spawns and no timer runs during it."""
        # defaultdict so the active fade scheme's category names appear on demand;
        # categories that get no cells never enter the map, so they add no dead air
        # (only the categories actually used this game count toward the timeline).
        handles = defaultdict(list)
        # Grid lines alpha-fade (background-agnostic), filling the gaps last.
        handles["grid_lines"] = [AlphaFade(line) for line in self._board.line_shapes()]
        for (x, y) in self._board.occupied_cells():
            cell = self._board.get_cell(x, y)
            if cell is None:
                continue
            category = self._loading_category_for_cell((x, y), cell)
            self._add_cell_fade_handles(handles[category], cell)
        self._loading_anim = LoadingAnimation(dict(handles))

    def _add_cell_fade_handles(self, into, cell):
        """Append the fade handles for one placed cell to its category list. The
        hex inner fill white-fades (held opaque, so it masks the black outer and
        no gray bleeds through mid-fade); everything else alpha-fades."""
        square = cell.square
        if hasattr(square, "inner"):
            # Hex cell: two polygons. White-fade the opaque inner, alpha-fade the
            # outer rim. (Old uniform-alpha version -- caused the gray interior --
            # was: into.append(AlphaFade(square)).)
            into.append(WhiteFade(square.inner))
            into.append(AlphaFade(square.outer))
        else:
            # Square cell: one BorderedRectangle. Its fill region stays white over
            # the white board at any opacity, so plain alpha-fade is gray-free.
            into.append(AlphaFade(square))
        if cell.label is not None:
            into.append(AlphaFade(cell.label))

    def _loading_category_for_cell(self, pos, cell):
        """Which fade category a placed cell belongs to. Special cells go by their
        kind (mission / obstacle / fossilized) first; every other settled cell is
        bucketed by the active game_screen.loading_fade_category scheme."""
        if pos in self._mission_cells:
            return "mission"
        if pos in self._obstacle_cells:
            return "obstacle"
        if pos in self._fossilized_cells:
            return "fossilized"
        return self._loading_fade_category_rule(pos, cell)

    def _cell_primary_fix(self, pos, cell):
        """The gram's PRIMARY *fix for fade purposes: the *fix bin the formation
        SELECTED it for (recorded in _formation_fix_tags), if any -- so a midsuf-pool
        gram that also happens to be prefix=y still fades as suffix/midfix. Otherwise
        derived by priority prefix>suffix>midfix from the cleaned3 grade, or None when
        the gram has no *fix / no grade."""
        tag = self._formation_fix_tags.get(pos)
        if tag is not None:
            return tag
        grade = ideation_grade(cell.gram.text) if cell.gram is not None else None
        if not grade:
            return None
        if grade["prefix"]:
            return "prefix"
        if grade["suffix"]:
            return "suffix"
        if grade["midfix"]:
            return "midfix"
        return None

    # --- loading-fade category schemes (game_screen.loading_fade_category) ---
    # Each maps one SETTLED formation cell (pos, cell) to a fade-category name (which
    # must have a slot in loading_animation.yaml). Swap which axis the reveal groups by.
    def _rule_loading_fade_by_length(self, pos, cell):
        """Bucket by gram length: settled_3plus / settled_2 / settled_1 (wild vowels
        -- empty text -- fade with the singles). The original reveal grouping."""
        length = len(cell.gram) if cell.gram is not None else 1
        if length >= 3:
            return "settled_3plus"
        if length == 2:
            return "settled_2"
        return "settled_1"

    def _rule_loading_fade_by_ideation_strength(self, pos, cell):
        """Bucket by ideation strength from the cleaned3 grades: 'strong' (graded
        y-strong) vs 'not_strong' (m / n, or no grade, e.g. a scrabble letter)."""
        grade = ideation_grade(cell.gram.text) if cell.gram is not None else None
        return "strong" if grade and grade["strong"] else "not_strong"

    def _rule_loading_fade_by_ideation_fix(self, pos, cell):
        """Bucket by *fix: 'prefix' / 'suffix' / 'midfix', else 'no_fix'. Uses the
        gram's PRIMARY *fix (the bin the formation selected it for, else priority
        prefix>suffix>midfix) -- see _cell_primary_fix."""
        return self._cell_primary_fix(pos, cell) or "no_fix"

    def _rule_loading_fade_by_ideation_length_strength_fix(self, pos, cell):
        """Composite reveal order: bucket each SETTLED cell by gram LENGTH x ideation
        STRENGTH x *fix, e.g. 'tri_strong_pre'. Lets the opening reveal sweep through
        tri_strong_pre, tri_strong_mid, ... di_weak_suf, uni in whatever order their
        slots in loading_animation.yaml give them.
          length   -- tri (3+) / di (2); single letters are one 'uni' bucket (they
                      grade uniformly strong + all-fix, so splitting them is moot)
          strength -- strong (graded y) / weak (m / n / ungraded)
          *fix     -- pre / mid / suf from the gram's PRIMARY *fix (the bin it was
                      selected for, else priority), else nofix (no *fix / ungraded)"""
        gram = cell.gram
        length = len(gram) if gram is not None else 1
        if length == 1:
            return "uni"
        size = "tri" if length >= 3 else "di"
        grade = ideation_grade(gram.text) if gram is not None else None
        strength = "strong" if (grade and grade["strong"]) else "weak"
        fix = self._cell_primary_fix(pos, cell)
        fix_part = {"prefix": "pre", "suffix": "suf", "midfix": "mid"}.get(fix, "nofix")
        return "%s_%s_%s" % (size, strength, fix_part)

    def _finish_loading(self):
        """End LOADING: drop the animation, flip to MOVING, and start the active
        mode's first turn (spawn / timer). Called from update() once the reveal
        completes."""
        self._loading_anim = None
        self._set_phase(Phase.MOVING)
        self._moving_mode.start()

    # --- starting-coverage rules (game_screen.starting_coverage_dictionary) -
    # Optionally enumerate EVERY word the opening board could spell, once, before
    # the reveal -- a debug/analysis snapshot of how rich/limited a formation is.
    # See starting_coverage.py for the (decoupled, unit-tested) algorithm.
    def _rule_starting_coverage_off(self):
        """Starting-coverage disabled (the default): no enumeration, no file."""
        pass

    def _rule_starting_coverage_on(self):
        """Enumerate every dictionary word the initial board could spell and write
        it beside the session log as <id>.coverage.csv, logging how long it took.
        Blocking and synchronous: called after the formation is fully placed and
        before the opening reveal, so it sees the untouched starting board and the
        player can't act until it finishes. Needs an open session (logging.enabled)
        to have somewhere to write; a silent no-op otherwise."""
        if self._coverage_sim_seconds is not None:
            # Replay: reproduce the recorded CALCULATING pause (already scaled to
            # playback speed) without recomputing or writing the file.
            self._simulate_starting_coverage(self._coverage_sim_seconds)
            return
        path = session_log.coverage_path()
        if path is None:
            return
        # Phase is LOADING here, so the LoadSidePane is what's on screen: swap its
        # top label to "CALCULATING..." and force one frame so it's actually
        # visible during the blocking compute (the event loop is paused until we
        # return), then restore "LOADING..." for the reveal that follows.
        self._load_side_pane.set_calculating()
        self._force_paint()
        grams = self._starting_gram_multiset()
        # Grouping separator mirrors player_dictionary's grid-aware scheme.
        sep = "/" if CONFIG["rules"]["game_screen.grid"] == "rule_use_hex_grid" else "|"
        # The word-length rule reads only len(text) and len(path), so feed it a
        # placeholder path of the grouping's cell count: coverage honors the same
        # min-letters/min-cells gate as live play while ignoring all nucleation.
        accept = lambda word, n_cells: self._word_length_rule(word, [None] * n_cells)
        t0 = time.perf_counter()
        stats = write_coverage_csv(str(path), all_words(), grams, accept, sep)
        L.log_06004(time.perf_counter() - t0, stats)
        self._load_side_pane.set_loading()

    def _simulate_starting_coverage(self, seconds):
        """Replay-only: show CALCULATING for `seconds` (the recorded compute time,
        already scaled by playback speed) and block, but do NOT run the
        enumeration or write any file -- the recorded log already holds the
        result. Keeps a replay's opening visually faithful to the original run."""
        self._load_side_pane.set_calculating()
        self._force_paint()
        if seconds > 0:
            time.sleep(seconds)
        self._load_side_pane.set_loading()

    def _force_paint(self):
        """Draw one frame and present it immediately, outside the normal event
        loop -- used to show a status label before a synchronous, blocking pass
        (the starting-coverage compute) that would otherwise leave the screen
        frozen on the prior frame until it returns."""
        self.draw()
        self._window.flip()

    def _starting_gram_multiset(self):
        """The multiset {gram text -> cell count} of the INITIAL board: every
        occupied cell -- player, obstacle and mission alike -- pooled by letters,
        skipping wild-vowel cells. The raw material the starting-coverage pass
        counts assignments against."""
        counts = Counter()
        for (x, y) in self._board.occupied_cells():
            cell = self._board.get_cell(x, y)
            if cell is None or cell.gram is None or cell.gram.is_wild:
                continue
            if cell.gram.text:
                counts[cell.gram.text] += 1
        return counts

    # --- starting-formation rules (game_screen.setup_formation) ------------
    # Each lays out the full opening set of obstacle + mission pieces: builds the
    # pools at the counts the formation calls for, places every piece, and records
    # its cells in _obstacle_cells / _mission_cells. Clearing is intentionally
    # skipped (we never call _begin_selection), so the player doesn't start the
    # game with words already cleared for free.
    def _rule_formation_scattered(self):
        """The original opening: OBSTACLE_COUNT obstacles and MISSION_COUNT
        missions, each scattered to a random on-board, non-overlapping spot.
        Obstacles and missions share one `occupied` set so the two never stack."""
        self._build_obstacle_pool(self.OBSTACLE_COUNT)
        self._build_mission_pool(self.MISSION_COUNT)
        occupied = set()
        self._scatter_pool(self._obstacle_pool, occupied, self._obstacle_cells, "obstacle")
        self._scatter_pool(self._mission_pool, occupied, self._mission_cells, "mission")

    def _rule_formation_mission_center_obstacle_ring(self):
        """One mission piece on the board's center cell, ringed by obstacle pieces
        on that cell's neighbors -- 6 on a hex grid, 4 on a square grid. Builds a
        one-piece mission pool and one obstacle per on-board neighbor. Intended
        for single-cell (unimo) pieces; a multi-cell piece would extend past its
        anchor cell and could overlap a neighbor or hang off the board."""
        center = self._board.center_cell()
        ring = self._board.neighbors(*center)
        self._build_mission_pool(1)
        self._build_obstacle_pool(len(ring))
        occupied = set()
        self._place_one_setup_piece(
            self._mission_pool, center, self._mission_cells, occupied, "mission"
        )
        for cell in ring:
            self._place_one_setup_piece(
                self._obstacle_pool, cell, self._obstacle_cells, occupied, "obstacle"
            )

    def _rule_formation_fill_player_diagonal(self):
        """Fill every board cell with a single-cell player piece; the gram lengths
        form DIAGONAL LINES (the round-robin length cadence mapped row-major aliases
        into diagonals), unless the length-controlled picker is inactive -- then it
        just fills row-major. The default full fill. See _fill_player_with for the
        shared body and the no-obstacle/mission caveats (pair with
        game_screen.victory: rule_victory_none)."""
        self._fill_player_with(self._rule_formation_arrange_diagonal)

    def _rule_formation_fill_player_wood_grain(self):
        """Like rule_formation_fill_player_diagonal, but the multi-letter (digram /
        trigram+) cells are laid into HARD-CODED top-left -> bottom-right grain
        lines instead of the old accidental aliasing stripes: a few parallel
        down-right diagonals spaced >=1 unigram apart, each kinked by 2-3
        straight-down jags for a wood-grain feel. Unigrams fill the gaps. Line
        count FLOATS with the digram/trigram+ percentages. Same uni/digram/3+
        counts as the diagonal fill -- only WHERE each length lands changes.
        Hex grid only (the grain stepping uses hex directions). See
        _rule_formation_arrange_wood_grain."""
        self._fill_player_with(self._rule_formation_arrange_wood_grain)

    def _rule_formation_fill_player_random(self):
        """Like rule_formation_fill_player_diagonal but the gram lengths are
        SCATTERED to random cells (same unigram/digram/3+ counts, no diagonal),
        unless the length-controlled picker is inactive -- then row-major."""
        self._fill_player_with(self._rule_formation_arrange_random)

    def _fill_player_with(self, arrange_rule):
        """Shared body of the uniform fill formations: pack every board cell with a
        settled single-cell player piece (no obstacles/missions, so pair with
        game_screen.victory: rule_victory_none; filled cells are ordinary player
        cells a live piece may overlap). When the length-controlled picker is active,
        `arrange_rule` maps the gram lengths onto cells (diagonal vs random); any
        other picker just fills row-major (its lengths aren't ours to arrange)."""
        cells = [(x, y)
                 for y in range(self._board.height)
                 for x in range(self._board.width)
                 if self._board.is_valid(x, y)]
        if self._formation_length_arrangement_active():
            self._fill_player_arranged(cells, arrange_rule)
        else:
            for x, y in cells:
                self._fill_one_player_cell(x, y)

    def _formation_length_arrangement_active(self):
        """True when the active player gram-pick is the length-controlled corpus
        picker -- the only picker whose draws carry the unigram/digram/3+ lengths
        the arrangement steers. Other pickers fill plain row-major."""
        key = ("hex_player.gram_pick"
               if CONFIG["rules"]["game_screen.grid"] == "rule_use_hex_grid"
               else "square_player.gram_pick")
        return CONFIG["rules"][key] == "rule_grams_greater_than_47_lengthcontrolled"

    def _fill_player_arranged(self, cells, arrange_rule):
        """Lay out each cell's gram LENGTH up front (formation_length_sequence), let
        `arrange_rule` map those lengths onto cells (diagonal or scattered), then
        draw + place a gram of each cell's pinned length. The length placement is
        thus fixed independently of the order grams are drawn, so the diagonal reveal
        survives future draw-order refactors."""
        lengths = formation_length_sequence(len(cells))
        placement = arrange_rule(cells, lengths)
        self._arm_vowel_guarantee(sum(1 for _x, _y, length in placement if length == 1))
        for x, y, length in placement:
            set_forced_formation_length(length)
            try:
                self._fill_one_player_cell(x, y)
            finally:
                set_forced_formation_length(None)

    def _fill_one_player_cell(self, x, y, gram_pick_rule=None):
        """Build one settled single-cell player piece at (x, y), place its gram on
        the board, and log it. Shared by the arranged and plain fills. gram_pick_rule
        defaults to None (the configured player gram-pick); the region formation
        passes the length-controlled picker explicitly so its forced-cell draws
        engage regardless of the configured *_player.gram_pick."""
        # gram_pick_rule=None falls back to the configured player gram-pick
        # (square_player.gram_pick / hex_player.gram_pick); the unimo shape makes
        # each piece exactly one cell so the fill tiles the board. Tinted SETTLED
        # (white board color), not the live piece's blue active fill: these open
        # already settled, like long-placed cells (see _settle_placed_cells).
        piece = self._piece_class(
            self._unimo_type, self._cell_size, self._piece_batch,
            visible=False, gram_pick_rule=gram_pick_rule,
            cell_color=self.SETTLED_CELL_COLOR,
        )
        piece.set_position(x, y)
        piece.place()
        logged_cells = []
        for gx, gy, cell, label, gram, overlay in piece.get_cell_data():
            self._board.place(gx, gy, cell, label, gram, overlay)
            logged_cells.append((gx, gy, gram))
        L.log_06002("fill", logged_cells)
        piece.set_visible(True)

    # --- length arrangements for the uniform fill formations -----------------
    # Helpers for rule_formation_fill_player_diagonal/_random. Each takes the row-major
    # `cells` list and the round-robin `lengths` sequence and returns a list of
    # (x, y, length) telling _fill_player_arranged which length to pin at each cell.
    def _rule_formation_arrange_diagonal(self, cells, lengths):
        """Map the round-robin length sequence onto cells in ROW-MAJOR order, so
        the periodic length cadence aliases against the grid's row width into
        diagonal lines (preserving the emergent opening reveal). `cells` arrives
        row-major; zip pairs cell i with length i."""
        return [(x, y, length) for (x, y), length in zip(cells, lengths)]

    def _rule_formation_arrange_random(self, cells, lengths):
        """Same length multiset, scattered: shuffle which cell gets which length,
        so the unigram/digram/3+ counts stay exactly as configured but their
        positions are random (no diagonal). rand() keeps it replay-reproducible."""
        shuffled = list(cells)
        rand().shuffle(shuffled)
        return [(x, y, length) for (x, y), length in zip(shuffled, lengths)]

    # --- wood_grain: the recovered round-robin diagonal as a reusable MOLD ----------
    # The grain the user wanted was an accidental but pleasing artifact of the legacy
    # round-robin length cadence (formation_length_sequence) mapped row-major into
    # diagonals -- the SAME thing _arrange_diagonal does. It only ever "broke" because
    # changing gram_length.*_percent changed the cadence. So we freeze the SHAPE here and
    # let the configured percentages control only the DENSITY. WOOD_GRAIN_LENGTH_WEIGHTS
    # was recovered from the session that produced the reference (sessions/
    # 2026-06-25T13-34-45_29a6, embedded gram_length 50/30/20); run row-major it
    # reproduces that board's grain cell-for-cell (verified). The mold's multigram cells
    # are the "grain slots"; gram_length.*_percent (the configured `lengths`) then decides
    # how many multigrams actually fill them and the digram/trigram split. The configured
    # percentages still drive every other draw (piece pool, the other formations) too.
    WOOD_GRAIN_LENGTH_WEIGHTS = [50, 30, 20]   # unigram / digram / trigram+ (relative)

    def _rule_formation_arrange_wood_grain(self, cells, lengths):
        """Lay multigrams along the fixed wood-grain mold, at the configured density.
        The mold (WOOD_GRAIN_LENGTH_WEIGHTS run row-major) marks the diagonal 'grain
        slots'; the configured `lengths` decide how many multigrams to place and the
        digram-vs-trigram split. Multigrams fill grain slots first -- if the config asks
        for FEWER than the mold has, the leftover slots fall back to unigrams (gaps in
        the grain); if it asks for MORE, the surplus scatter randomly into the gap cells.
        Exact uni/digram/3+ counts from `lengths` are preserved, so the vowel guarantee
        and quotas stay honest. rand() (replay-reproducible) picks which slots gap out and
        where overflow lands. `cells` arrives row-major."""
        mold = formation_length_sequence(len(cells), self.WOOD_GRAIN_LENGTH_WEIGHTS)
        grain_slots = [c for c, m in zip(cells, mold) if m >= 2]   # ideal multigram cells
        gap_cells = [c for c, m in zip(cells, mold) if m < 2]
        multi_lengths = [n for n in lengths if n >= 2]   # configured 2s + 3s: count + split
        n_multi = len(multi_lengths)
        if n_multi <= len(grain_slots):      # underflow: nibble the ends, keep grain contiguous
            chosen = self._wood_grain_underfill(grain_slots, n_multi)
        else:                                # overflow: surplus multigrams go in the gaps
            rand().shuffle(gap_cells)
            chosen = grain_slots + gap_cells[:n_multi - len(grain_slots)]
        chosen = set(chosen)
        rand().shuffle(multi_lengths)        # which chosen cell is a digram vs trigram+
        take = iter(multi_lengths)
        return [(x, y, next(take) if (x, y) in chosen else 1) for (x, y) in cells]

    def _wood_grain_underfill(self, grain_slots, n_multi):
        """Fill `n_multi` of the ordered grain slots, taking the deficit off the ENDS of
        the grain (a random split between the front and back ends) so the filled grain
        stays ONE contiguous run -- the gaps are at the ends, never stranding a single
        grain cell between two gaps. The slots are row-major, so the trimmed ends read
        as blank bands at the top/bottom of the grain. Returns the cells to fill."""
        deficit = len(grain_slots) - n_multi
        if deficit <= 0:
            return list(grain_slots)
        front = rand().randint(0, deficit)   # nibble this many off the front, the rest off the back
        return grain_slots[front:len(grain_slots) - (deficit - front)]

    # --- unigram vowel coverage (game_screen.formation_vowel_coverage) -------
    # Each returns the set of letters the fill must place on at least one unigram cell;
    # the picker forces only the ones that don't appear naturally (see gram_picker).
    def _rule_vowel_coverage_off(self):
        """No guarantee (default): unigrams are drawn purely by the picker."""
        return []

    def _rule_vowel_coverage_each_unigram(self):
        """Guarantee at least one of each vowel -- A E I O U Y -- among the formation's
        unigram cells."""
        return ["A", "E", "I", "O", "U", "Y"]

    def _arm_vowel_guarantee(self, unigram_count):
        """Arm the picker's unigram vowel-coverage guarantee for `unigram_count` cells
        per the active rule (a no-op disarm when off). Call right before a fill places
        its unigram cells."""
        set_unigram_vowel_guarantee(self._formation_vowel_coverage_rule(), unigram_count)

    # --- ideation-regions formation (rule_formation_fill_ideation_regions) ---
    def _rule_formation_fill_ideation_trigram_sidepanes_digram_centercircle(self):
        """Trigram+ side panes (prefix far-left / midsuf far-right); DIGRAMS in a
        rough CIRCLE at board center (random *fix mix); UNIGRAMS fill the rest."""
        self._fill_ideation_sidepanes(self._digram_region_centercircle)

    def _rule_formation_fill_ideation_trigram_sidepanes_digram_bottompyramid(self):
        """Trigram+ side panes (prefix far-left / midsuf far-right); DIGRAMS in a
        TRIANGLE at the screen BOTTOM pointing up; UNIGRAMS fill the rest."""
        self._fill_ideation_sidepanes(self._digram_region_bottompyramid)

    def _rule_formation_fill_ideation_trigram_sidepanes(self):
        """Trigram+ side panes (prefix far-left / midsuf far-right), but with NO
        dedicated digram region: DIGRAMS and UNIGRAMS are mixed RANDOMLY together
        across every non-pane cell. Same trigram panes, counts, forced picker and
        no obstacle/mission pieces as the *_digram_centercircle/bottompyramid
        siblings -- see _fill_ideation_sidepanes."""
        cells = [(x, y)
                 for y in range(self._board.height)
                 for x in range(self._board.width)
                 if self._board.is_valid(x, y)]
        n_uni, n_di, n_tri = self._region_length_counts(len(cells))

        # No digram region: the trigram panes carve off the edges, then the inner
        # (non-pane) cells are shuffled and split into a random digram/unigram mix.
        tri_left, tri_right, inner = self._split_sidepane_trigrams(cells, n_tri)
        rand().shuffle(inner)
        n_di = min(n_di, len(inner))
        digrams, unigrams = inner[:n_di], inner[n_di:]

        self._place_region_cells(tri_left, 3, "prefix")  # trigram+ prefix -> left
        self._place_region_cells(tri_right, 3, "midsuf") # trigram+ mid/suffix -> right
        self._place_region_cells(digrams, 2, None)       # digrams, any *fix
        self._arm_vowel_guarantee(len(unigrams))
        self._place_region_cells(unigrams, 1, None)      # unigrams fill the gaps

    def _fill_ideation_sidepanes(self, digram_region_rule):
        """Shared body for the ideation side-pane formations. Lays the opening board
        by gram TYPE in space: trigram+ PREFIX grams packed into the far-LEFT edge,
        trigram+ MIDFIX/SUFFIX into the far-RIGHT edge, DIGRAMS in whatever region
        `digram_region_rule(cells, n_di)` returns, and UNIGRAMS filling every gap.
        Counts of each length come from gram_length.*; the left/right trigram split
        from gram_ideation.trigramplus.* (prefix : midfix+suffix). Lays settled
        single-cell player pieces and no obstacle/mission pieces (pair with
        game_screen.victory: rule_victory_none). Draws are forced through the
        length-controlled picker regardless of the configured *_player.gram_pick,
        and deduped like any other formation."""
        cells = [(x, y)
                 for y in range(self._board.height)
                 for x in range(self._board.width)
                 if self._board.is_valid(x, y)]
        n_uni, n_di, n_tri = self._region_length_counts(len(cells))

        # Digrams claim their region first; the trigram panes + unigrams use the rest.
        digrams = digram_region_rule(cells, n_di)
        digram_set = set(digrams)
        outer = [c for c in cells if c not in digram_set]

        tri_left, tri_right, unigrams = self._split_sidepane_trigrams(outer, n_tri)

        self._place_region_cells(digrams, 2, None)       # digrams, any *fix
        self._place_region_cells(tri_left, 3, "prefix")  # trigram+ prefix -> left
        self._place_region_cells(tri_right, 3, "midsuf") # trigram+ mid/suffix -> right
        self._arm_vowel_guarantee(len(unigrams))
        self._place_region_cells(unigrams, 1, None)      # unigrams fill the gaps

    def _split_sidepane_trigrams(self, cells, n_tri):
        """Split `cells` into (tri_left, tri_right, inner): trigram+ PREFIX grams
        packed into the far-LEFT edge, trigram+ MIDFIX/SUFFIX into the far-RIGHT
        edge, and `inner` = every leftover cell (running inward from the panes).

        The trigram+ budget is split by the gram_ideation.trigramplus.* shares (NOT
        by region size): prefix grams go left, midfix+suffix go right, so the
        left/right counts honor prefix_percent : (midfix_percent + suffix_percent).
        midfix vs suffix are NOT separated -- this 2-pane layout only splits prefix
        from non-prefix; both share the right side, drawn from the combined midsuf
        pool by corpus frequency. Each side is capped by how many edge cells it has."""
        cx = self._board.cell_center(*self._board.center_cell())[0]
        left = [c for c in cells if self._board.cell_center(c[0], c[1])[0] < cx]
        right = [c for c in cells if self._board.cell_center(c[0], c[1])[0] >= cx]

        pre = CONFIG["rules"]["gram_ideation.trigramplus.prefix_percent"]
        mid = CONFIG["rules"]["gram_ideation.trigramplus.midfix_percent"]
        suf = CONFIG["rules"]["gram_ideation.trigramplus.suffix_percent"]
        denom = pre + mid + suf
        left_share = (pre / denom) if denom else 0.5
        n_tri_left = min(round(n_tri * left_share), len(left))
        n_tri_right = min(n_tri - n_tri_left, len(right))

        # Push the trigram+ grams to the OUTER edges: order each side by horizontal
        # extremity (leftmost / rightmost cell first) and take the most extreme ones,
        # so the multigrams pack into the edge columns and the inner cells fill inward
        # (rather than trigrams scattering through the half).
        left.sort(key=lambda c: self._board.cell_center(c[0], c[1]))            # px asc, py asc
        right.sort(key=lambda c: (-self._board.cell_center(c[0], c[1])[0],
                                  self._board.cell_center(c[0], c[1])[1]))      # px desc, py asc
        tri_left = left[:n_tri_left]
        tri_right = right[:n_tri_right]
        inner = left[n_tri_left:] + right[n_tri_right:]
        return tri_left, tri_right, inner

    def _digram_region_centercircle(self, cells, n_di):
        """The n_di cells nearest board center (a rough disc)."""
        cx, cy = self._board.cell_center(*self._board.center_cell())

        def dist2(c):
            px, py = self._board.cell_center(c[0], c[1])
            return (px - cx) ** 2 + (py - cy) ** 2

        return sorted(cells, key=dist2)[:n_di]

    def _digram_region_bottompyramid(self, cells, n_di):
        """The n_di cells forming an upward-pointing TRIANGLE anchored at the screen
        BOTTOM (min pixel-y, pyglet y-up): widest along the bottom row, narrowing
        toward the top. Cells are ranked by height-above-bottom plus horizontal
        distance from center, so taking the n_di lowest grows the pyramid up-and-out
        from the bottom-center."""
        centers = {c: self._board.cell_center(c[0], c[1]) for c in cells}
        cx = self._board.cell_center(*self._board.center_cell())[0]
        bottom_py = min(py for _px, py in centers.values())

        def score(c):
            px, py = centers[c]
            return (py - bottom_py) + abs(px - cx)

        return sorted(cells, key=score)[:n_di]

    def _region_length_counts(self, n):
        """Split `n` cells into (unigram, digram, trigram+) counts from the
        gram_length.*_percent shares (the same knobs the length quota uses)."""
        pcts = [CONFIG["rules"]["gram_length.unigram_percent"],
                CONFIG["rules"]["gram_length.digram_percent"],
                CONFIG["rules"]["gram_length.trigramplus_percent"]]
        total = sum(pcts) or 1
        n_uni = round(n * pcts[0] / total)
        n_di = round(n * pcts[1] / total)
        if n_uni + n_di > n:
            n_di = max(0, n - n_uni)
        return n_uni, n_di, n - n_uni - n_di

    def _place_region_cells(self, cells, length, attr):
        """Fill each of `cells` with a settled player piece whose gram is the given
        `length` (and ideation pool `attr`, if any), forced per cell through the
        length-controlled picker. Deduped like every other formation draw. Records the
        *fix the gram was BINNED for (prefix pool -> prefix; midsuf pool -> suffix or
        midfix per the placed gram) so the fade categorizers honor that as its primary
        *fix; digram/unigram pools (attr None) leave no tag (-> priority fallback)."""
        for x, y in cells:
            set_forced_formation_cell(length, attr)
            try:
                self._fill_one_player_cell(
                    x, y, gram_pick_rule=rule_grams_greater_than_47_lengthcontrolled)
            finally:
                clear_forced_formation_cell()
            if attr == "prefix":
                self._formation_fix_tags[(x, y)] = "prefix"
            elif attr == "midsuf":
                self._formation_fix_tags[(x, y)] = self._resolve_midsuf_fix((x, y))

    def _resolve_midsuf_fix(self, pos):
        """Primary *fix for a gram drawn from the combined midfix/suffix (right-pane)
        pool: 'suffix' if graded so, else 'midfix' (priority suffix>midfix); the pool
        guarantees one of them, so default 'suffix'."""
        gram = self._board.gram_at(*pos)
        grade = ideation_grade(gram.text) if gram is not None else None
        if grade and grade["suffix"]:
            return "suffix"
        if grade and grade["midfix"]:
            return "midfix"
        return "suffix"

    def _build_obstacle_pool(self, count):
        """(Re)build the obstacle pool with `count` pieces, using the obstacle
        piece set / gram-pick / batch / tint set up by the grid builder."""
        self._obstacle_pool = PiecePool(
            count, self._cell_size, self._obstacle_batch,
            self._piece_class, self._obstacle_piece_types,
            gram_pick_rule=self._obstacle_gram_pick_rule,
            cell_color=self.OBSTACLE_CELL_COLOR, kind="obstacle"
        )

    def _build_mission_pool(self, count):
        """(Re)build the mission pool with `count` pieces (the obstacles' twin,
        using the mission piece set / gram-pick / batch / tint)."""
        self._mission_pool = PiecePool(
            count, self._cell_size, self._mission_batch,
            self._piece_class, self._mission_piece_types,
            gram_pick_rule=self._mission_gram_pick_rule,
            cell_color=self.MISSION_CELL_COLOR, kind="mission"
        )

    def _scatter_pool(self, pool, occupied, track_cells, kind):
        """Place every piece in `pool` at a random on-board spot clear of
        `occupied`, recording each cell in `occupied` (so later pieces avoid it)
        and `track_cells` (its victory/encoding set). The scattered formation's
        per-pool worker. `kind` labels the pieces in the session log."""
        while True:
            piece = pool.current_piece()
            self._orient_rule(piece)
            self._position_scattered(piece, occupied)
            self._settle_setup_piece(piece, track_cells, occupied, kind)
            if pool.advance() is None:
                break

    def _place_one_setup_piece(self, pool, cell, track_cells, occupied, kind):
        """Place the pool's current piece at a specific `cell` -- for formation
        rules that lay pieces at fixed coordinates -- record it, and advance the
        pool. `kind` labels the piece in the session log."""
        piece = pool.current_piece()
        self._orient_rule(piece)
        piece.set_position(*cell)
        self._settle_setup_piece(piece, track_cells, occupied, kind)
        pool.advance()

    def _settle_setup_piece(self, piece, track_cells, occupied, kind):
        """Drop an already-positioned setup piece onto the board: place it, record
        each of its cells in `occupied` (so later setup pieces avoid it) and
        `track_cells` (its victory/encoding set), and reveal it."""
        piece.place()
        logged_cells = []
        for gx, gy, cell, label, gram, overlay in piece.get_cell_data():
            self._board.place(gx, gy, cell, label, gram, overlay)
            occupied.add((gx, gy))
            track_cells.add((gx, gy))
            logged_cells.append((gx, gy, gram))
        # Record the opening cells + grams so a replay can rebuild this piece.
        L.log_06002(kind, logged_cells)
        piece.set_visible(True)

    def _position_scattered(self, piece, occupied):
        """Pick a random on-board anchor whose cells are all on the grid and clear
        of `occupied`. Retries a bounded number of times, then keeps the last spot
        rather than looping forever on a crowded board. Independent of the player
        spawn rule -- starting pieces lay themselves out, they don't spawn live."""
        for _ in range(100):
            x = rand().randint(0, self.GRID_WIDTH - 1)
            y = rand().randint(0, self._board_height - 1)
            piece.set_position(x, y)
            cells = piece.get_cell_positions()
            on_board = all(self._board.get_cell(cx, cy) is not None for (cx, cy) in cells)
            free = all((cx, cy) not in occupied for (cx, cy) in cells)
            if on_board and free:
                return

    def _rule_use_square_grid(self, window):
        """Build a square board and set piece sizing/type to match. Sized to the
        square grid region so columns and rows come out equal."""
        self._cell_size = math.floor(self._grid_area_size / self.GRID_WIDTH)
        self._board_height = math.floor(self._grid_area_size / self._cell_size)
        self._piece_class = SquarePiece
        self._player_piece_types = SQUARE_PLAYER_PIECE_TYPES
        # Single-cell shape a clicked-word piece uses on this grid (see
        # _swap_to_word_piece / game_screen.player_word_piece).
        self._unimo_type = SquareUnimoType.SINGLE
        # Obstacles get their own piece set + gram-pick (square_obstacle.* keys),
        # so they can differ from the playable pieces.
        self._obstacle_piece_types = SQUARE_OBSTACLE_PIECE_TYPES
        self._obstacle_gram_pick_rule = SQUARE_OBSTACLE_GRAM_PICK_RULE
        # Missions: the obstacles' twin, own piece set + gram-pick (square_mission.*).
        self._mission_piece_types = SQUARE_MISSION_PIECE_TYPES
        self._mission_gram_pick_rule = SQUARE_MISSION_GRAM_PICK_RULE
        self._movement_rule = self._rule_square_movement
        # Gram separator a cleared word is recorded with in the player dictionary
        # (see _encode_variation): "|" marks a word formed on the square grid.
        self._gram_separator = "|"
        grid_px_width = self.GRID_WIDTH * self._cell_size
        grid_px_height = self._board_height * self._cell_size
        board = SquareGrid(
            self.GRID_WIDTH, self._board_height, self._cell_size,
            grid_px_width, grid_px_height, self._board_batch
        )
        return board

    def _rule_use_hex_grid(self, window):
        """Build a flat-top hex board and set piece sizing to match.
        """
        cell_size = math.floor(self._grid_area_size / self.GRID_WIDTH)
        hex_size = cell_size / math.sqrt(3)
        board = HexGrid(
            hex_size, self._grid_area_size, self._grid_area_size,
            self._board_batch
        )
        # Keep the float hex_size: the piece must use the exact same value as
        # the grid, or it drifts off the cells across the board.
        self._cell_size = hex_size
        self._board_height = board.height
        self._piece_class = HexPiece
        self._player_piece_types = HEX_PLAYER_PIECE_TYPES
        # Single-cell shape a clicked-word piece uses on this grid (see
        # _swap_to_word_piece / game_screen.player_word_piece).
        self._unimo_type = HexUnimoType.SINGLE
        # Obstacles get their own gram-pick (hex_obstacle.gram_pick); the hex set
        # has a single piece type, so obstacle types match the main set.
        self._obstacle_piece_types = HEX_OBSTACLE_PIECE_TYPES
        self._obstacle_gram_pick_rule = HEX_OBSTACLE_GRAM_PICK_RULE
        # Missions: the obstacles' twin, own piece set + gram-pick (hex_mission.*).
        self._mission_piece_types = HEX_MISSION_PIECE_TYPES
        self._mission_gram_pick_rule = HEX_MISSION_GRAM_PICK_RULE

        self._movement_rule = self._rule_hex_movement_holdshift
        # self._movement_rule = self._rule_hex_movement_arrows
        # Gram separator a cleared word is recorded with in the player dictionary
        # (see _encode_variation): "/" marks a word formed on the hex grid.
        self._gram_separator = "/"
        return board

    def _init_first_piece(self):
        piece = self._piece_pool.current_piece()
        self._spawn_piece(piece)
        piece.set_visible(True)
        # Hide the board cells beneath the live piece so it sits cleanly on top,
        # the same as every later spawn (_advance_piece). Without this the first
        # piece overlaps any settled cells already under it -- invisible on an
        # empty opening, but visible glyph overlap on a pre-filled board (see
        # rule_formation_fill_player_diagonal).
        self._update_hover_visibility()
    
    def _spawn_piece(self, piece):
        """Apply the current spawn orientation, then positioning rule."""
        self._orient_rule(piece)
        self._spawn_rule(piece)
        # Record the deal: this live piece's type, grams, and resting cells.
        L.log_06003(piece)
        # A fresh piece under an active hunt lights up immediately (else it would
        # stay dark until the next keystroke). Only work when a hunt is typed.
        if self._moving_side_pane.hunt_text():
            self._refresh_hunt_highlight()

    def _rule_orient_default(self, piece):
        """Spawn in the piece's default orientation (rotation state 0)."""
        pass

    def _rule_orient_random(self, piece):
        """Spawn in a random rotation: turn clockwise a random number of times."""
        turns = rand().randrange(piece.rotation_count)
        for _ in range(turns):
            piece.rotate_cw()

    def _rule_spawn_center(self, piece):
        """Position a piece at the grid's center cell. The grid computes it from
        its own dimensions, so this adapts to any grid size."""
        center_x, center_y = self._board.center_cell()
        piece.set_position(center_x, center_y)
    
    def _rule_spawn_random_spot(self, piece):
        """Position a piece at a random legal resting spot: every cell on the
        grid AND the active cell-overlap rule satisfied. The anchor alone being a
        valid cell isn't enough -- a piece anchored at an edge can still hang
        cells off it -- and a blocking overlap rule must hold at spawn too, or
        the piece would respect the rule for every move yet sit on a forbidden
        cell the instant it appeared. So retry until a legal spot is found, then
        keep the last spot rather than looping forever if none does.

        NOTE (busy board): with a blocking overlap rule, a crowded board may have
        no legal spot within 100 tries; the piece then spawns on the last
        (overlapping) spot and could be stuck. Fine while boards are sparse;
        revisit with a board-full / game-over condition once they fill up."""
        for _ in range(100):
            x = rand().randint(0, self.GRID_WIDTH - 1)
            y = rand().randint(0, self._board_height - 1)
            piece.set_position(x, y)
            if self._move_allowed(piece):
                return
    
    def _rule_square_movement(self, symbol, modifiers):
        """Square grid: A/D/W/S nudge the piece by one cell. Returns handled."""
        handled = True
        if symbol in self._keys["move_left"]:
            self._move_piece(-1, 0)
        elif symbol in self._keys["move_right"]:
            self._move_piece(1, 0)
        elif symbol in self._keys["move_up"]:
            self._move_piece(0, 1)
        elif symbol in self._keys["move_down"]:
            self._move_piece(0, -1)
        else:
            handled = False
        return handled

    def _rule_hex_movement_holdshift(self, symbol, modifiers):
        """Flat-top hex: A=up-left, Shift+A=down-left, D=up-right,
        Shift+D=down-right, W=up, S=down. Returns handled. (The hold modifier is
        controls.yaml game.hex_down_modifier; A/D/W/S are game.move_*.)"""
        shift = (modifiers & control_modifier("game.hex_down_modifier")) != 0
        handled = True
        if symbol in self._keys["move_left"]:
            self._move_piece_hexdir(HEX_DOWN_LEFT if shift else HEX_UP_LEFT)
        elif symbol in self._keys["move_right"]:
            self._move_piece_hexdir(HEX_DOWN_RIGHT if shift else HEX_UP_RIGHT)
        elif symbol in self._keys["move_up"]:
            self._move_piece_hexdir(HEX_UP)
        elif symbol in self._keys["move_down"]:
            self._move_piece_hexdir(HEX_DOWN)
        else:
            handled = False
        return handled

    def _rule_hex_movement_arrows(self, symbol, modifiers):
        """Flat-top hex, arrow-key chords: up+A=up-left, down+A=down-left,
        up+D=up-right, down+D=down-right, W=up, S=down. A/D alone do nothing.
        Returns handled."""
        # Held-key chord: only the first key bound to each arrow is consulted.
        up = self._key_state[control_keys("game.hex_arrow_up")[0]]
        down = self._key_state[control_keys("game.hex_arrow_down")[0]]
        handled = True
        if symbol in self._keys["move_left"]:
            if up:
                self._move_piece_hexdir(HEX_UP_LEFT)
            elif down:
                self._move_piece_hexdir(HEX_DOWN_LEFT)
            else:
                handled = False
        elif symbol in self._keys["move_right"]:
            if up:
                self._move_piece_hexdir(HEX_UP_RIGHT)
            elif down:
                self._move_piece_hexdir(HEX_DOWN_RIGHT)
            else:
                handled = False
        elif symbol in self._keys["move_up"]:
            self._move_piece_hexdir(HEX_UP)
        elif symbol in self._keys["move_down"]:
            self._move_piece_hexdir(HEX_DOWN)
        else:
            handled = False
        return handled

    def _move_piece_hexdir(self, direction):
        """Move the piece to its hex neighbor in the given direction index."""
        piece = self._current_piece()
        nx, ny = hex_neighbor(piece.grid_x, piece.grid_y, direction)
        self._move_piece(nx - piece.grid_x, ny - piece.grid_y)

    # Gram-manip-in-SELECTING rule (game_screen.gram_manip_in_selecting): whether
    # right-click transforms a board gram during SELECTING as well as MOVING.
    def _rule_gram_manip_in_selecting_enabled(self):
        """Right-click manipulates board grams during SELECTING too (needed for
        the omniswap modes, which live in SELECT)."""
        return True

    def _rule_gram_manip_in_selecting_disabled(self):
        """Right-click is inert during SELECTING -- gram-manip is MOVING-only (the
        original behavior, and the hard phase separation the timed modes want)."""
        return False

    def _try_gram_manipulate(self, x, y, button):
        """If `button` is the gram-manipulate button (right-click), transform the
        clicked cell's gram and report True (the click is consumed). Shared by the
        MOVING and SELECTING phases so board gram-doubling works in BOTH -- the
        omniswap modes spend most of their play in SELECT, so a MOVING-only gate
        left right-click dead there. An UNASSIGNED (None) button never matches, so
        it can't swallow a click when gram_manipulate isn't bound."""
        manip_button = self._buttons["gram_manipulate"]
        if manip_button is not None and button == manip_button:
            self._handle_gram_manipulate(x, y)
            return True
        return False

    def _handle_gram_manipulate(self, x, y):
        """Right-click a board cell during MOVING (controls.yaml
        mouse.gram_manipulate): transform that cell's gram via the
        game_screen.rightclick_* rule for its vowel/consonant SHAPE (see
        _apply_shape_rule) or wild-ness. Empty and fossilized cells are left
        alone, the same as the swap rules. Mode-agnostic -- the MOVING modes never
        see this button. A rule returning None (e.g. rule_rightclick_none, or a
        shape with no rule) is a no-op."""
        cell = self._board.cell_at(x, y)
        if cell is None:
            L.log_20004(None, None, None, "off_board")
            return
        if self._is_fossilized(cell):
            L.log_20004(cell, None, None, "fossilized")
            return
        gram = self._board.gram_at(*cell)
        if gram is None:
            L.log_20004(cell, None, None, "empty")
            return
        if gram.is_wild:
            new_text = self._rightclick_rules["vowelwild"](gram.text)
        elif len(gram) == 1:
            new_text = self._rightclick_rules["unigram"](gram.text)
        else:
            new_text = self._apply_shape_rule(cell, gram.text)
        if new_text is None:
            # A rule that declines (e.g. rule_rightclick_none, or a shape whose
            # slot is off) -- relabel nothing, but record that the click was seen.
            L.log_20004(cell, gram.text, None, "rule_noop")
            return
        self._board.relabel_cell(cell[0], cell[1], new_text)
        L.log_20004(cell, gram.text, new_text, "applied")
        # The gram changed under an active hunt: re-light so the new letters
        # reflect the typed word (relabel_cell already re-synced the overlay).
        if self._moving_side_pane.hunt_text():
            self._refresh_hunt_highlight()

    def _apply_shape_rule(self, cell, text):
        """Route a right-click on a 2+ letter gram to its shape's config slot
        (see _gram_manip_family). cc/cv/vc/vv/ck own the digrams (and the doubled
        3-letter forms they produce); vcv/cvk own the trigrams; any 3+ shape with
        no family (CKV, VCK, CKS, ...) is a plain no-op. A matched family whose own
        slot is off also returns None -- each shape's behavior is governed solely
        by its own config key. CVK is the lone stateful rule (it alternates
        front/back doubling); every other shape is a pure toggle. Returns new text
        or None."""
        family = _gram_manip_family(text)
        if family is None:
            return None
        if family == "cvk":
            if not self._cvk_enabled:
                return None
            rule = self._rightclick_rules["cvk"]
            if len(text) == 3:
                return rule(text, self._advance_cvk_side(cell))
            return rule(text)          # 4-letter collapse; side is irrelevant
        return self._rightclick_rules[family](text)

    def _advance_cvk_side(self, cell):
        """Pick which consonant the next CVK double touches, flipping from the
        side this cell doubled last so repeated doubles alternate MMER/MERR. A
        fresh cell defaults to 'back' (MER -> MERR), the corpus-favored double."""
        side = "front" if self._cvk_double_side.get(cell) == "back" else "back"
        self._cvk_double_side[cell] = side
        return side

    def _rule_repeat_allow(self, word):
        """Allow a word to clear even if it cleared before (original behavior)."""
        return True

    def _rule_repeat_block(self, word):
        """Block a word that has already been cleared earlier this game."""
        return word not in self._cleared_word_history

    # Word-trail rule (game_screen.word_trail): whether a cleared word leaves a
    # path trail overlaid on the board (see _clear_paths / views.word_trail).
    def _rule_word_trail_on(self, accepted):
        """Record a path trail for each cleared word, center to center."""
        for fw in accepted:
            points = [self._board.cell_center(x, y) for (x, y) in fw.path]
            self._word_trail.add_path(points)

    def _rule_word_trail_off(self, accepted):
        """No path trails (the original behavior)."""
        pass

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

    # --- victory rules (game_screen.victory) -----------------------------
    # Each returns True when its win condition is met against the current board.
    # Selected in __init__; consulted by _check_victory after every clear and
    # before each spawn.
    def _rule_victory_missions_cleared(self):
        # Win once every starting mission cell has been cleared, regardless of any
        # obstacle or player cells left on the board. _mission_cells shrinks as
        # cells clear (see _clear_paths) / get covered (see the overlap-action
        # rule), so empty == all gone. Guard against a mission-less board never
        # having had missions to clear.
        return len(self._mission_cells) == 0 and self.MISSION_COUNT > 0

    def _rule_victory_missions_and_obstacles_cleared(self):
        # Win once every starting mission AND obstacle cell has been cleared,
        # regardless of player cells left on the board. Both tracking sets must be
        # empty; guard against a board that started with neither.
        started_with_targets = self.MISSION_COUNT > 0 or self.OBSTACLE_COUNT > 0
        all_gone = len(self._mission_cells) == 0 and len(self._obstacle_cells) == 0
        return all_gone and started_with_targets

    def _rule_victory_obstacles_cleared(self):
        # Win once every starting obstacle cell has been cleared. _obstacle_cells
        # shrinks as cells clear (see _clear_paths), so empty == all gone. Guard
        # against an obstacle-less board never having had obstacles to clear.
        return len(self._obstacle_cells) == 0 and self.OBSTACLE_COUNT > 0

    def _rule_victory_grid_empty(self):
        # Win once the board holds no cells at all.
        return len(self._board.occupied_cells()) == 0

    def _rule_victory_none(self):
        # No victory condition: the game runs until the player quits (the
        # original endless behavior, preserved as a selectable option).
        return False

    # --- cell-overlap rules (game_screen.cell_overlap_player / _obstacle / _mission)
    # One independent allow/block pair per piece track. Each receives the full set
    # of occupied cells the piece would cover (`overlapped`) and filters to its own
    # track; _overlap_allowed ANDs all three. A covered obstacle/mission cell is
    # dropped from its tracking set by the overlap-action rule, so a player cell
    # never lingers at an obstacle/mission coordinate and the block rules stay in
    # sync with the victory rules. Player cells are the covered cells in neither
    # tracking set.
    def _players_covered(self, overlapped):
        # The covered cells belonging to neither the obstacle nor mission track.
        return overlapped - self._obstacle_cells - self._mission_cells

    def _rule_moveandplace_over_player_cell(self, overlapped):
        # Player-overlap rule: moving or placing over a player cell is always
        # permitted. `overlapped` is ignored.
        return True

    def _rule_block_moveandplace_over_player_cell(self, overlapped):
        # Player-overlap rule: a piece may not move onto or place over a player
        # cell. Permitted unless it would cover one.
        return len(self._players_covered(overlapped)) == 0

    def _rule_moveandplace_over_obstacle_cell(self, overlapped):
        # Obstacle-overlap rule: moving or placing over an obstacle cell is always
        # permitted. `overlapped` is ignored.
        return True

    def _rule_block_moveandplace_over_obstacle_cell(self, overlapped):
        # Obstacle-overlap rule: a piece may not move onto or place over an
        # obstacle cell. Permitted unless it would cover one.
        obstacles_covered = overlapped & self._obstacle_cells
        return len(obstacles_covered) == 0

    def _rule_moveandplace_over_mission_cell(self, overlapped):
        # Mission-overlap rule: moving or placing over a mission cell is always
        # permitted. `overlapped` is ignored.
        return True

    def _rule_block_moveandplace_over_mission_cell(self, overlapped):
        # Mission-overlap rule: a piece may not move onto or place over a mission
        # cell. Permitted unless it would cover one.
        missions_covered = overlapped & self._mission_cells
        return len(missions_covered) == 0

    def _rule_moveandplace_over_fossilized_cell(self, overlapped):
        # Fossilized-overlap rule: moving or placing over a fossilized cell is
        # always permitted. `overlapped` is ignored.
        return True

    def _rule_block_moveandplace_over_fossilized_cell(self, overlapped):
        # Fossilized-overlap rule: a fossilized cell is frozen -- a piece may not
        # move onto or place over one. Permitted unless it would cover one. (The
        # typewriter swap gates on _is_fossilized directly; this is the move/place
        # gate, so a fossilize+jigsaw combo is blocked too.)
        return len(overlapped & self._fossilized_cells) == 0

    def _rule_old_cells_get_delete(self, overlapped):
        # Cell-overlap action rule: the cells a placement covers are treated as
        # gone. The board already overwrote their contents in place(); this drops
        # any covered starting-obstacle / mission coordinates from their tracking
        # sets so a covered obstacle (or mission) counts as cleared for its
        # victory rule.
        self._obstacle_cells.difference_update(overlapped)
        self._mission_cells.difference_update(overlapped)

    def _set_phase(self, new_phase):
        """Single point for phase changes: log the transition (log_10001) then
        switch. Every `self._phase` assignment routes through here so the session
        log's phase track is complete and the format lives in one place. A no-op
        repeat (same phase) is not logged; the construction-time default is logged
        only as a no-session no-op."""
        old = getattr(self, "_phase", None)
        self._phase = new_phase
        if old is not new_phase:
            L.log_10001(old, new_phase)
            # Leaving SELECT with the "select which one" chooser still open (e.g.
            # a timer forced the phase out from under it): drop its overlay +
            # prompt so no candidate lines linger into MOVING.
            if old == Phase.SELECTING and self._disambiguating():
                self._end_disambiguation()
            # Leaving MOVING clears the word-hunt field (and its highlight), so no
            # hunt lingers into SELECTING or the next MOVING phase.
            if old == Phase.MOVING and getattr(self, "_moving_side_pane", None):
                self._moving_side_pane.clear_hunt()

    def _check_victory(self):
        """If the active victory rule is satisfied, enter VICTORY and return
        True; otherwise return False. Already being in VICTORY counts as True so
        callers never spawn a piece past the win."""
        won = self._phase == Phase.VICTORY
        if not won and self._victory_rule():
            self._enter_victory()
            won = True
        return won

    def _enter_victory(self):
        """End the game on a win: show the end panel reading VICTORY."""
        self._enter_endstate(get_string("victory"))

    def _enter_endgame(self):
        """End the game with no win/lose verdict -- the MOVING_TYPEWRITER cursor
        ran off the board, or the omniswap race clock hit zero: show the end panel
        reading FINISHED, and swap the moving pane's top label to match (so the
        last countdown value isn't left frozen behind the overlay)."""
        self._moving_side_pane.set_finished_label()
        self._enter_endstate(get_string("finished"))

    def _enter_endstate(self, label_text):
        """Shared end transition: label the end panel `label_text`, settle the
        last placed piece (so no cell is left tinted) and stop play. Phase.VICTORY
        is the single frozen end-state -- the overlay is drawn by draw() and the
        right pane reverts to the cleared-word list (phase no longer SELECTING);
        the label is what distinguishes a win from a plain finish."""
        self._victory_overlay.set_text(label_text)
        self._end_overlay_dismissed = False
        self._set_phase(Phase.VICTORY)
        self._settle_placed_cells()
        # Close out the session: the final tally, then the session-end line, then
        # flush + close. on_exit finds nothing open afterward.
        L.log_50001(label_text, len(self._cleared_word_history),
                    len(self._obstacle_cells), len(self._mission_cells))
        L.log_00002(label_text)
        session_log.close(reason=label_text)

    def _is_fossilized(self, cell):
        """Whether (x, y) `cell` has been fossilized by a formed word -- dead to
        word-finding and swapping, skipped by the typewriter cursor. Always False
        until a fossilize clear-action populates _fossilized_cells."""
        return cell in self._fossilized_cells

    # --- selection-trigger rules (game_screen.select_trigger) --------------
    # Decide whether the placement just made is a "selection turn". The counter
    # they share (_placements_until_select) is the number the moving pane shows.
    def _rule_select_every_placement(self):
        """Original behavior: every placed piece is a selection turn. The
        countdown is meaningless here, so pin it to 1 (always 'this piece')."""
        self._placements_until_select = 1
        return True

    def _rule_select_after_n_placements(self):
        """Selection turns come once every select_trigger_count placements. Tick
        the countdown down each placement; when it hits zero this placement is
        the selection turn and the counter resets for the next cycle."""
        self._placements_until_select -= 1
        if self._placements_until_select <= 0:
            self._placements_until_select = self._select_trigger_count
            return True
        return False

    # --- typewriter swap-placed rules (game_screen.typewriter_swap) ---------
    # On a MOVING_TYPEWRITER cursor<->cell swap, decide which of the two cells
    # count as placed (nucleation sites) this turn. Whatever isn't returned here
    # is left as a settled board cell.
    def _rule_swap_places_cursor_only(self, cursor, other):
        """Only the cursor cell is placed; the swapped-in cell settles, so a
        cleared word must nucleate around the cursor."""
        return [cursor]

    def _rule_swap_places_both(self, cursor, other):
        """Both swapped cells are placed (original behavior): a word may nucleate
        around either end of the swap."""
        return [cursor, other]

    # --- isolated-piece skip rules (game_screen.skip_select_isolated) -------
    # On a selection turn, decide whether to skip it because the placed pieces
    # are isolated (none touches the board, so no word can bridge them). Receives
    # the accumulated placed set, so a turn is skipped only when EVERY piece
    # placed this phase is stranded -- one adjacent piece keeps it.
    def _rule_skip_select_if_isolated(self, placed_positions):
        """Skip the selection stage when no placed piece touches anything on the
        board (original behavior, generalized to the accumulated set)."""
        return not self._piece_touches_existing(placed_positions)

    def _rule_never_skip_select(self, placed_positions):
        """Always run the selection stage, isolated pieces or not."""
        return False

    # --- select-phase board-click rules (game_screen.select_click) ----------
    # While SELECTING, decide what a left-click on a board cell does.
    def _rule_select_click_move_piece(self, x, y):
        """Route a SELECTING-phase board click to the active MOVING mode's board
        handler, so the player can rearrange cells (the omniswap swap, a jigsaw
        move, ...) without first leaving word entry -- the SELECTING/MOVING blur.
        The mode may change the board (a completed swap), so re-find the
        clearable words afterward; otherwise a word the player just made by
        swapping would still read as 'not on the board'. The pane's own button
        clicks are handled before this rule runs."""
        self._moving_mode.on_mouse_press(x, y, self._buttons["move_primary"])
        self._recompute_candidates()

    def _rule_select_click_none(self, x, y):
        """Board clicks do nothing while selecting (piece-moving disabled)."""
        pass

    def _begin_selection(self, placed_positions):
        """Called after each placement. Add the new piece to the accumulated
        placed set (kept lit in the placed tint), recompute the move's
        candidates, then let the phase-transition rules decide what happens.

        Two rules gate the selection stage. The trigger rule
        (game_screen.select_trigger) decides whether this placement ends the
        moving phase -- and advances the moving-pane countdown either way, so it
        runs every placement. On a non-selection turn the piece simply stays lit
        and play moves to the next piece, the placed cells accumulating until the
        trigger fires. On a selection turn the skip rule
        (game_screen.skip_select_isolated) drops it when no placed piece touches
        the board (no word can bridge one); otherwise the auto selector clears
        instantly or the interactive selector enters the SELECTING phase (next
        piece withheld). Every placed piece since the last selection settles
        together once the turn resolves."""
        self._mark_placed_cells(placed_positions)
        self._recompute_candidates()
        is_select_turn = self._select_trigger_rule()
        # Reflect the (possibly reset) countdown in the moving pane now, so the
        # right label is correct the moment that pane is next shown.
        self._moving_side_pane.set_phase_label(self._placements_until_select)
        if not is_select_turn:
            # Still mid-phase: leave the placed pieces lit and advance the turn.
            self._moving_mode.advance()
            return
        # Selection turn: skip it if none of the placed pieces touch the board.
        # The accumulated set (not just the last piece) is the adjacency test, so
        # a word bridging any placed piece keeps the turn.
        if self._skip_select_rule(self._move_placed):
            self._settle_placed_cells()
            self._moving_mode.advance()
            return
        if not self._selector.interactive:
            self._clear_paths(self._selector.choose(self._candidates))
            self._settle_placed_cells()
            # The clear may have met the victory condition; only spawn the next
            # piece if it didn't.
            if not self._check_victory():
                self._moving_mode.advance()
        else:
            # UX shortcut: carry any word already typed in the MOVING word-hunt
            # field into the SELECT typed-word field, so opening SELECT (ENTER)
            # with a hunted word pre-loads it. Grab it before _set_phase clears the
            # hunt field (see clear_hunt in _set_phase).
            hunted = self._moving_side_pane.hunt_text()
            self._set_phase(Phase.SELECTING)
            # Fresh batch for this selection phase (no-op in clear-on-submit mode).
            self._pending = []
            self._words_submitted_this_select = 0
            self._selecting_side_pane.begin()
            if hunted:
                self._selecting_side_pane.prefill(hunted)
            self._dictionary_count_rule(self._selecting_side_pane, len(self._player_dict))
            # Auto-submit the carried word (game_screen.select_autosubmit_hunt) so
            # the SAME ENTER that opened SELECT lands on the blue-path confirm --
            # no dead middle ENTER to submit a word already in the field. A junk /
            # too-short hunt just rejects (ghost + reason, field cleared). Off:
            # leave it pre-loaded for a manual confirm/edit (original behavior).
            if hunted and self._select_autosubmit_hunt:
                self._on_submit_word(hunted)

    def _recompute_candidates(self):
        """Re-run stages 1-2 against the current board and refresh the word sets
        a typed submission is checked against. Also builds the wider sets the
        error diagnosis needs to tell apart 'too short' from 'didn't involve the
        placed piece' from 'isn't on the board':

          _board_words_any  -- every dictionary word on the board, ignoring the
                               length minimum (so a too-short word still shows up)
          _length_ok_words  -- those that also meet the length rule
          _candidate_words  -- length-OK words that nucleate around the move's
                               still-present placed cells (the clearable set),
                               mapped word -> path (first path wins a tie)
        """
        live_placed = {
            p for p in self._move_placed if self._board.gram_at(*p) is not None
        }
        found_any = self._find_words(apply_length=False)
        self._board_words_any = {fw.word for fw in found_any}
        found = [fw for fw in found_any if self._word_length_rule(fw.word, fw.path)]
        self._length_ok_words = {fw.word for fw in found}
        # Stage 2: nucleate, then apply the independent placed-cell requirement.
        nucleated = self._nucleation_rule(found, live_placed)
        self._candidates = self._placed_cell_rule(nucleated, live_placed)
        # Of several ways to spell the same word (different paths, or different
        # wild-vowel expansions), keep the one covering the fewest cells, so a
        # typed word makes the most compact clear -- e.g. a single wild as "OA"
        # over two wilds as "O"+"A" -- leaving more cells in play.
        by_word = {}
        for fw in self._candidates:
            by_word.setdefault(fw.word, []).append(fw)
        # All spellings per word (batch mode hands out a distinct path per
        # re-submit) plus the single fewest-cell pick (instant mode clears it).
        self._candidate_word_options = by_word
        self._candidate_words = {}
        for word, options in by_word.items():
            self._candidate_words[word] = self._fewest_cell_word(options)

    def _fewest_cell_word(self, found_words):
        """Pick the FoundWord covering the fewest cells; break ties at random.
        Used when a typed word can be cleared several ways (common with wild
        vowels)."""
        fewest = min(len(fw.path) for fw in found_words)
        smallest = []
        for fw in found_words:
            if len(fw.path) == fewest:
                smallest.append(fw)
        return rand().choice(smallest)

    def _encode_variation(self, found):
        """Encode the gram grouping a cleared word was made of, for the player
        dictionary: each cell's contributed letters in order, joined by the
        active grid's separator (_gram_separator -- "|" square, "/" hex). A wild
        cell wraps the run it resolved to in "?...?"; a starting-obstacle cell
        wraps in "[ ]" and a starting-mission cell in "<>" (each outside the wild
        marker, e.g. "[?ea?]" / "<?ea?>"). A cell is at most one of obstacle /
        mission (distinct pieces never share a cell), so the wraps don't combine.
        Must run before _clear_paths prunes the tracking sets, so a just-cleared
        obstacle or mission still reads as one."""
        parts = []
        for (x, y), segment in zip(found.path, found.segments):
            gram = self._board.gram_at(x, y)
            text = segment.lower()
            if gram is not None and gram.is_wild:
                text = "?" + text + "?"
            if (x, y) in self._obstacle_cells:
                text = "[" + text + "]"
            elif (x, y) in self._mission_cells:
                text = "<" + text + ">"
            parts.append(text)
        return self._gram_separator.join(parts)

    def _clear_paths(self, found_words):
        """Stage 4: apply the chosen FoundWords to the board. Gates each word
        through the repeat rule, captures its gram grouping (before any cell
        changes), then hands the accepted words to the active clear-action rule
        (game_screen.clear_action) -- which removes or fossilizes their cells and
        reports which (if any) fully left the board. Records history + the player
        dictionary and lists the words; returns the words actually applied."""
        accepted = [fw for fw in found_words if self._repeat_rule(fw.word)]
        cleared_words = [fw.word for fw in accepted]
        # Leave a path trail per accepted word (gated by game_screen.word_trail).
        # Captured here, before any cell change, so the centers are still valid
        # even when the clear-action removes the cells.
        self._word_trail_rule(accepted)
        # The gram grouping each word was made of, captured BEFORE any cell change
        # so an obstacle / mission / partial gram still reads true.
        cleared_variations = [self._encode_variation(fw) for fw in accepted]
        fully_cleared = self._clear_action_rule(accepted)
        # A starting obstacle or mission cell counts as gone only once FULLY
        # cleared; a partially-used (or fossilized) one stays tracked.
        self._obstacle_cells.difference_update(fully_cleared)
        self._mission_cells.difference_update(fully_cleared)
        for word in cleared_words:
            self._cleared_word_history.add(word)
        if cleared_words:
            # Record each word + its gram grouping in the player's lifetime
            # dictionary (instant autosave). add() returns True only for words
            # never collected before, so they list green; a word re-collected
            # with a new grouping saves the grouping but stays black (the count
            # didn't grow).
            new_flags = []
            obscure_flags = []
            for fw, variation in zip(accepted, cleared_variations):
                is_new = self._player_dict.add(fw.word, variation)
                word_obscure = is_obscure(fw.word)
                new_flags.append(is_new)
                obscure_flags.append(word_obscure)
                # Single sink for every clear (interactive / batch / auto).
                L.log_30002(fw.word, fw.path, variation, is_new, word_obscure)
            self._moving_side_pane.add_cleared_words(
                cleared_words, new_flags, obscure_flags)
            self._dictionary_count_rule(self._moving_side_pane, len(self._player_dict))
        return cleared_words

    # --- clear-action rules (game_screen.clear_action) ---------------------
    # Stage 4's cell fate for the accepted words. Both record the words the same
    # way (see _clear_paths); they differ only in what becomes of the cells. Each
    # returns the cells that FULLY left the board (for obstacle/mission tracking).
    def _rule_clear_remove(self, accepted):
        """Original: the consumed cells leave the board, partial-gram aware. Per
        cell, count letters eaten from the head (largest prefix any word took) and
        tail (largest suffix): a word's first cell gives up a suffix, its last a
        prefix, every middle cell the whole gram; wild / single-cell paths go
        whole. The leftover is the contiguous middle gram[head : n - tail] -- empty
        when the runs meet, so the cell clears. Batches naturally: WIN + GO over
        W ING O clears ING, while HI + GO leaves its middle N (see
        _apply_partial_clears)."""
        force_clear = set()           # cells consumed whole (middle / wild / 1-cell)
        eaten = {}                    # endpoint cell -> [head_eaten, tail_eaten]

        def eat_head(cell, j):
            slot = eaten.setdefault(cell, [0, 0])
            slot[0] = max(slot[0], j)

        def eat_tail(cell, k):
            slot = eaten.setdefault(cell, [0, 0])
            slot[1] = max(slot[1], k)

        for fw in accepted:
            last = len(fw.path) - 1
            for idx, (cell, seg) in enumerate(zip(fw.path, fw.segments)):
                gram = self._board.gram_at(*cell)
                if gram is None:
                    continue
                if gram.is_wild or last == 0 or (idx != 0 and idx != last):
                    force_clear.add(cell)        # whole gram consumed
                elif idx == 0:
                    eat_tail(cell, len(seg))     # word starts here: a suffix goes
                else:                            # idx == last
                    eat_head(cell, len(seg))     # word ends here: a prefix goes
        return self._apply_partial_clears(force_clear, eaten)

    def _rule_clear_fossilize(self, accepted):
        """Typewriter: every cell on each accepted word's path FOSSILIZES -- it
        stays on the board with its whole gram intact (no partial split, even
        under rule_gram_use_partial) but goes permanently dead: tracked in
        _fossilized_cells, tinted the fossil color, un-swappable, and skipped by
        the pathfinder (_collect_words) and the cursor. Nothing leaves the board,
        so no cell is reported cleared (obstacle/mission tracking is untouched)."""
        for fw in accepted:
            for cell in fw.path:
                if self._board.gram_at(*cell) is not None:
                    self._fossilize_cell(cell)
        return set()

    def _fossilize_cell(self, cell):
        """Freeze one cell: record it dead and tint it the fossil color in place."""
        self._fossilized_cells.add(cell)
        c = self._board.get_cell(*cell)
        if c is not None and c.square is not None:
            c.square.color = self.FOSSILIZED_CELL_COLOR

    def _apply_partial_clears(self, force_clear, eaten):
        """Clear the whole-gram cells outright, then resolve each partially-eaten
        endpoint cell: clear it if head + tail eat the whole gram, else re-letter
        it to the leftover middle run. Returns the set of cells fully cleared."""
        fully_cleared = set()
        for cell in force_clear:
            self._board.clear_cell(*cell)
            fully_cleared.add(cell)
        for cell, (head, tail) in eaten.items():
            if cell in force_clear:
                continue
            gram = self._board.gram_at(*cell)
            if gram is None:
                continue
            n = len(gram.text)
            if head + tail >= n:
                self._board.clear_cell(*cell)
                fully_cleared.add(cell)
            else:
                self._reletter_cell(*cell, gram.text[head:n - tail])
        return fully_cleared

    def _reletter_cell(self, x, y, text):
        """Re-render an occupied cell to its leftover letters after a partial-gram
        clear, then restore its resting color (it may have been tinted blue while
        placed or green while pending)."""
        self._board.relabel_cell(x, y, text)
        cell = self._board.get_cell(x, y)
        if cell is not None and cell.square is not None:
            cell.square.color = self._cell_resting_color((x, y))

    def _cell_resting_color(self, cell):
        """The fill a cell shows when no piece tint applies: its fossilized tint
        if it is dead, else its obstacle / mission tint if it is still one, else
        the plain settled color. Fossilized wins -- a fossilized cell is its
        permanent end state regardless of what it started as."""
        if cell in self._fossilized_cells:
            return self.FOSSILIZED_CELL_COLOR
        if cell in self._obstacle_cells:
            return self.OBSTACLE_CELL_COLOR
        if cell in self._mission_cells:
            return self.MISSION_CELL_COLOR
        return self.SETTLED_CELL_COLOR

    def _on_submit_word(self, typed):
        """Interactive submit (Enter or the Submit control). Dispatches to the
        active clear-timing rule, which either clears the word now or holds it for
        the phase-end batch; both show the most specific error on rejection."""
        word = typed.strip().upper()
        if not word:
            return
        L.log_30001(word)
        self._submit_clear_rule(word)

    def _reject_submission(self, word, messages):
        """Show why a submitted word was rejected. Under game_screen.reject_ghost
        = rule_reject_ghost_on, echo the word as a dim ghost above a CLEARED field
        (so corrective typing starts fresh, not appended to the failed attempt);
        under _off, leave the failed word in the field and just show the reason
        (original behavior)."""
        if self._reject_ghost:
            self._selecting_side_pane.reject(word, messages)
        else:
            self._selecting_side_pane.show_errors(messages)

    # --- clear-timing rules (game_screen.clear_timing) ---------------------
    # Paired per timing: a submit rule (what one submit does) and a phase-end
    # rule (what ending the phase does). See the registries in __init__.
    def _rule_submit_clears_now(self, word):
        """Clear-on-submit: if the word is a clearable candidate, resolve WHICH
        spelling (disambiguation rule) then clear it from the board and recompute
        against the smaller board; else show why not. (Original interactive
        behavior, now with the chooser seam.)"""
        options = self._candidate_word_options.get(word)
        if not options or not self._repeat_rule(word):
            self._reject_submission(word, self._submission_messages(word))
            return
        # Auto-pick returns the FoundWord to clear now; cycle opens the board
        # chooser and returns None, committing later via _commit_clear_now.
        chosen = self._disambiguation_rule(word, options, self._commit_clear_now)
        if chosen is not None:
            self._commit_clear_now(word, chosen)

    def _commit_clear_now(self, word, found):
        """Apply one resolved spelling in clear-on-submit mode: clear it, list it,
        recompute, and run the phase-end checks. Shared by the instant path (auto-
        pick / single spelling) and the chooser's confirm."""
        # Capture newness before _clear_paths adds the word to the player's
        # dictionary, so the entry pane can list it green.
        is_new = not self._player_dict.contains(word)
        self._clear_paths([found])
        self._words_submitted_this_select += 1
        self._selecting_side_pane.accept_word(word, is_new, is_obscure(word))
        self._dictionary_count_rule(self._selecting_side_pane, len(self._player_dict))
        self._recompute_candidates()
        # This clear may have won the game immediately (e.g. it removed the last
        # obstacle/mission cell); if so, stop here rather than ending selection.
        if self._check_victory():
            return
        # One-word-per-select ends the phase right after this first clear,
        # regardless of adjacency (game_screen.select_word_limit).
        if self._select_word_limit_rule():
            self._end_selection()
            return
        # Leave SELECT once the placed piece is no longer adjacent to the board --
        # its remaining cells were consumed or stranded -- mirroring the adjacency
        # gate in _begin_selection. Keyed on adjacency, not the candidate count,
        # so the transition never reveals whether a word is still formable.
        if not self._piece_touches_existing(self._move_placed):
            self._end_selection()

    def _rule_submit_defers(self, word):
        """Clear-at-phase-end: hold the word for the phase-end batch instead of
        clearing now, tinting its cells green. The board never shrinks mid-phase,
        so cells reuse across words (overlaps); a word can be held several times
        as long as each takes a distinct path (repeats). Nothing clears until the
        phase ends (see _rule_endphase_clear_pending)."""
        options = self._candidate_word_options.get(word)
        if not options or not self._repeat_rule(word):
            self._reject_submission(word, self._submission_messages(word))
            return
        # Only spellings not already held this phase are offerable -- the chooser
        # (and auto-pick) resolve among these, so a re-submit takes a fresh path.
        fresh = self._unused_pending_paths(word, options)
        if not fresh:
            # A candidate, but every distinct way to spell it here is already
            # held -- a batch-mode-specific rejection.
            self._reject_submission(word, [self._no_more_paths_error(word)])
            return
        chosen = self._disambiguation_rule(word, fresh, self._commit_defer)
        if chosen is not None:
            self._commit_defer(word, chosen)

    def _commit_defer(self, word, found):
        """Hold one resolved spelling for the phase-end batch: append it, tint its
        cells, list it. Shared by the instant path and the chooser's confirm."""
        is_new = not self._player_dict.contains(word)
        self._pending.append(found)
        self._words_submitted_this_select += 1
        self._highlight_pending_cells(found.path)
        self._selecting_side_pane.accept_word(word, is_new, is_obscure(word))
        # One-word-per-select ends the phase now; _end_selection clears the single
        # held word on the way out (game_screen.select_word_limit).
        if self._select_word_limit_rule():
            self._end_selection()

    # --- disambiguation rules (game_screen.clear_disambiguation) -----------
    # Resolve WHICH spelling a submitted word clears when several paths exist.
    # Signature (word, options, on_confirm) -> FoundWord | None: return a chosen
    # FoundWord to commit now, or None having deferred to the chooser, which will
    # call on_confirm(word, found) once the player confirms.
    def _rule_disambig_auto_pick(self, word, options, on_confirm):
        """Original: silently keep the fewest-cell spelling (ties at random), no
        player choice. on_confirm is unused -- the pick commits immediately."""
        return self._fewest_cell_word(options)

    def _rule_disambig_cycle_two_or_more_choices(self, word, options, on_confirm):
        """Open the board chooser only when 2+ spellings exist; a lone spelling
        clears instantly (no needless prompt) -- the original ambiguity chooser.
        Returns None when the chooser opens (commit later via on_confirm), else
        the FoundWord to clear now."""
        return self._open_cycle_chooser(word, options, on_confirm, min_choices=2)

    def _rule_disambig_cycle_one_or_more_choices(self, word, options, on_confirm):
        """Open the board chooser for EVERY clearable word, a lone spelling
        included -- so every valid submit gets the blue-path preview + an explicit
        confirm (a second word_submit). Returns None (the choice commits later via
        on_confirm)."""
        return self._open_cycle_chooser(word, options, on_confirm, min_choices=1)

    def _open_cycle_chooser(self, word, options, on_confirm, min_choices):
        """Shared entry for the rule_disambig_cycle_* rules: open the board
        chooser once the candidate count reaches min_choices, else clear the lone
        spelling instantly. min_choices=1 always opens (options is never empty
        here); min_choices=2 opens only for genuine ambiguity."""
        if len(options) < min_choices:
            return options[0]
        self._begin_disambiguation(word, options, on_confirm)
        return None

    # --- disambiguation-cancel rules (game_screen.disambig_cancel) ---------
    def _rule_disambig_cancel_on(self):
        """word_clear backs out of the chooser, restoring the typed word."""
        self._cancel_disambiguation()

    def _rule_disambig_cancel_off(self):
        """word_clear is inert while the chooser is open -- the player must commit
        to one candidate once a valid word is submitted."""
        pass

    # --- disambiguation chooser (the cycle rules) --------------------------
    def _disambiguating(self):
        """Whether the 'select which one' chooser is currently open."""
        return bool(self._disambig_options)

    def _begin_disambiguation(self, word, options, on_confirm):
        """Open the chooser: order the candidates deterministically (fewest-cell
        first, then by path -- never shuffle, so the same cycle keys re-select the
        same path on replay), draw them, and show the prompt. The typed word is
        left in the field so a cancel returns to it."""
        ordered = sorted(options, key=lambda fw: (len(fw.path), fw.path))
        self._disambig_word = word
        self._disambig_options = ordered
        self._disambig_index = 0
        self._disambig_commit = on_confirm
        self._selecting_side_pane.clear_errors()
        # The submit was valid, so any prior rejection ghost has served its
        # purpose -- drop it before the chooser prompt takes the slot.
        self._selecting_side_pane.clear_ghost()
        # A lone path is a confirm, not a choice -- word it accordingly.
        prompt = (
            "disambig_confirm_prompt" if len(ordered) == 1 else "disambig_prompt"
        )
        self._selecting_side_pane.show_prompt(get_string(prompt))
        self._render_disambiguation()

    def _render_disambiguation(self):
        """Redraw the candidate polylines with the current highlight."""
        paths = [
            [self._board.cell_center(x, y) for (x, y) in fw.path]
            for fw in self._disambig_options
        ]
        self._disambig_lines.show(paths, self._disambig_index)

    def _cycle_disambiguation(self, delta):
        """Move the highlight to the next/previous candidate, wrapping around."""
        n = len(self._disambig_options)
        self._disambig_index = (self._disambig_index + delta) % n
        self._render_disambiguation()

    def _confirm_disambiguation(self):
        """Commit the highlighted candidate: log the choice, close the chooser,
        then run the timing-specific commit (clear-now or defer)."""
        word = self._disambig_word
        found = self._disambig_options[self._disambig_index]
        index, total = self._disambig_index, len(self._disambig_options)
        commit = self._disambig_commit
        L.log_30004(word, found.path, index, total)
        self._end_disambiguation()
        commit(word, found)

    def _cancel_disambiguation(self):
        """Back out without clearing: close the chooser, leaving the typed word in
        place for a re-submit or edit."""
        self._end_disambiguation()

    def _backout_disambiguation(self):
        """A typing / edit / Escape gesture while the chooser is open backs out of
        it, per game_screen.disambig_cancel. Returns True if the chooser actually
        closed (cancel enabled), so the caller may then let that same gesture edit
        the field (a letter appends, Backspace deletes) -- the player flows
        straight from 'confirm this word?' into hunting a different one."""
        if not self._disambig_cancel_enabled:
            return False
        self._cancel_disambiguation()
        return True

    def _end_disambiguation(self):
        """Tear down chooser state and its overlay + prompt."""
        self._disambig_options = []
        self._disambig_index = 0
        self._disambig_word = None
        self._disambig_commit = None
        self._disambig_lines.clear()
        self._selecting_side_pane.hide_prompt()

    def _rule_endphase_clear_none(self):
        """Clear-on-submit: phase end clears nothing extra (each word already
        cleared as it was submitted)."""
        pass

    def _rule_endphase_clear_pending(self):
        """Clear-at-phase-end: clear the whole held batch together when the phase
        ends. Overlapping cells (shared across held words) clear once; each held
        word still records its own gram grouping (see _encode_variation)."""
        if self._pending:
            self._clear_paths(self._pending)
        self._pending = []

    # --- select word-limit rules (game_screen.select_word_limit) -----------
    # Consulted after each accepted word in the interactive SELECT phase: return
    # True to end the phase now (back to MOVING), False to stay open for more.
    def _rule_unlimited_words(self):
        """Stay in SELECT after an accepted word; the phase ends only on Next
        piece or (clear-on-submit) when the placed piece is stranded. Original."""
        return False

    def _rule_one_word_per_select(self):
        """End the SELECT phase as soon as one word is accepted."""
        return True

    def _unused_pending_paths(self, word, options):
        """Every clearable FoundWord for `word` NOT already held this phase.
        Spellings are distinguished by path AND segments, so two different partial
        bites of the same cells (e.g. the same word taking a different prefix /
        suffix) each count as their own selection. The disambiguation rule then
        picks among these (auto-pick keeps the fewest-cell one; cycle offers them
        all)."""
        def key(fw):
            return (tuple(fw.path), tuple(fw.segments))
        used = {key(fw) for fw in self._pending if fw.word == word}
        return [fw for fw in options if key(fw) not in used]

    def _unused_pending_path(self, word, options):
        """The single fewest-cell spelling of `word` not already held, or None
        when every distinct spelling is taken. Retained for callers that want the
        old auto-pick directly; the submit path now goes through
        _unused_pending_paths + the disambiguation rule."""
        fresh = self._unused_pending_paths(word, options)
        if not fresh:
            return None
        return self._fewest_cell_word(fresh)

    def _no_more_paths_error(self, word):
        """The batch-mode rejection when a word is on the board but every way to
        spell it here is already held: distinct wording by how many ways exist."""
        total = len(self._candidate_word_options.get(word, []))
        reason = "already_selected_one_way" if total <= 1 else "every_way_selected"
        L.log_30003(word, reason)
        return get_string(f"err_{reason}")

    def _highlight_pending_cells(self, path):
        """Tint a held word's cells light green so the player sees what the
        phase-end batch will clear. All cells go green -- including starting
        obstacle / mission cells on the path -- since the batch clears them too."""
        for (x, y) in path:
            cell = self._board.get_cell(x, y)
            if cell is not None and cell.square is not None:
                cell.square.color = self.PENDING_WORD_CELL_COLOR

    def _submission_error(self, word):
        """The single most specific reason `word` can't be cleared right now,
        walking the pipeline from the typed word inward: a non-word, a word not
        on the board at all, a board word too short to clear, a board word that
        doesn't touch the placed piece, or one already cleared this game. Logs the
        stable reason key, then returns the localized message string."""
        if not is_word(word):
            reason = "not_in_dictionary"
        elif word not in self._board_words_any:
            reason = "not_on_board"
        elif word not in self._length_ok_words:
            reason = "too_short"
        elif word not in self._candidate_words:
            reason = "not_involved"
        else:
            reason = "already_cleared"
        L.log_30003(word, reason)
        return get_string(f"err_{reason}")

    def _submission_messages(self, word):
        """The error line for a rejected `word`, plus -- only when it's simply not
        a dictionary word -- a 'did you mean?' line of close spellings underneath.
        Shown together in the selecting pane's multiline error area."""
        messages = [self._submission_error(word)]
        if not is_word(word):
            suggestions = self._spell_suggest_rule(word)
            if suggestions:
                joined = ", ".join(suggestions)
                messages.append(get_string("did_you_mean", words=joined))
        return messages

    # --- Player word-piece rules (game_screen.player_word_piece) -----------
    # Clicking a cleared word in the right pane (MOVING) swaps the live piece for
    # a single-cell unimo whose one gram is that whole word, a normal player
    # piece in every other respect (overlap rules, placement, word formation).
    # The displaced pool piece is set aside, not consumed, and returns as the
    # next piece once the word-piece is placed (see _advance_piece). Only one
    # swap per piece: a word-piece can't be re-swapped until it's placed and a
    # fresh pool piece appears.

    def _rule_player_word_piece_enabled(self, x, y):
        """Feature on: try to swap the live piece for the clicked word. Returns
        True if a swap happened so the click is consumed."""
        return self._swap_to_word_piece(x, y)

    def _rule_player_word_piece_disabled(self, x, y):
        """Feature off: right-pane clicks do nothing during MOVING."""
        return False

    def _swap_to_word_piece(self, x, y):
        """Replace the live pool piece with a single-cell word-piece for the word
        clicked in the right pane. No-op (returns False) unless a normal pool
        piece is live, unplaced, and the click landed on a non-blank word row."""
        # Already holding a word-piece (override set) -> one swap per piece only.
        if self._override_piece is not None:
            return False
        pool_piece = self._piece_pool.current_piece()
        if pool_piece.placed:
            return False
        word = self._moving_side_pane.word_at(x, y)
        if not word:
            return False
        # Set the pool piece aside: clear the cells it hover-hides and hide it.
        # It stays at its pool index, so _advance_piece restores it next.
        self._clear_hover_visibility()
        pool_piece.set_visible(False)
        # Build the word-piece: the active grid's unimo, its single gram forced to
        # the clicked word. Same cell size / batch / tint as a normal pool piece.
        # dedup_grams=False: a player-chosen word bypasses the no-duplicate-multigram
        # rule (it's a deliberate fixed word, never re-rolled).
        word_piece = self._piece_class(
            self._unimo_type, self._cell_size, self._piece_batch, visible=False,
            gram_pick_rule=lambda count: [Gram(word)],
            cell_color=self.ACTIVE_PIECE_CELL_COLOR,
            dedup_grams=False,
        )
        self._override_piece = word_piece
        self._spawn_piece(word_piece)
        word_piece.set_visible(True)
        self._update_hover_visibility()
        return True

    def _advance_piece(self):
        """Spawn the next piece and resume play (or do nothing if the pool is
        exhausted). Checks victory first, so a win is caught before the next
        piece spawns (rule_victory_grid_empty's 'before spawning' point)."""
        if self._check_victory():
            return
        # A just-placed word-piece restores the pool piece set aside for it,
        # rather than consuming the next pooled piece (the swap left the pool
        # index untouched, so current_piece() is still that set-aside piece).
        if self._override_piece is not None:
            self._override_piece = None
            piece = self._piece_pool.current_piece()
            self._spawn_piece(piece)
            piece.set_visible(True)
            self._update_hover_visibility()
            return
        next_piece = self._piece_pool.advance()
        if next_piece:
            self._spawn_piece(next_piece)
            next_piece.set_visible(True)
            self._update_hover_visibility()

    def _end_selection(self):
        """Leave the SELECTING phase (the Next piece control, or once the piece
        is no longer adjacent to the board) and spawn the next piece. First runs
        the phase-end clear rule -- in batch mode this clears the whole held
        selection together (it may win the game, caught by _advance_piece) -- then
        settles the placed piece's remaining cells from light blue back to the
        board color."""
        self._endphase_clear_rule()
        self._settle_placed_cells()
        self._set_phase(Phase.MOVING)
        self._moving_mode.advance()

    def _find_words(self, apply_length=True):
        """Stage 1 (pathfind): every dictionary word spellable on the board, as
        a list of FoundWord (path + resolved segments + word). Walks from each
        occupied cell via _collect_words; the step geometry comes from the
        board's forward_neighbors (square: four cardinals, hardcoded; hex: shaped
        by hex_grid.word_pathfinding), so this is grid-agnostic. A wild cell
        branches into its possible vowel runs, so one path can yield several
        FoundWord. With apply_length=False the word-length minimum is skipped, so
        the caller sees too-short words too (used to diagnose a rejected
        submission)."""
        found = []  # each entry: a FoundWord spelling a dictionary word
        for start in self._board.occupied_cells():
            self._collect_words(start, None, [], "", [], found, apply_length)
        return found

    # --- Gram-usage rules (game_screen.gram_usage) -------------------------
    # For a non-wild gram, split its letters into the contributions a word may
    # take here, returning (continue_options, end_only_options):
    #   continue_options -- substrings a word may take and then walk on through
    #                       (whole gram, or any suffix when this is the word's
    #                       first cell so it can start partway in)
    #   end_only_options -- substrings that can only TERMINATE a word here (proper
    #                       prefixes, so it can stop partway through the last cell)
    # is_start says whether this is the word's first cell (path empty so far).
    def _rule_gram_use_whole(self, gram, is_start):
        """Whole-gram only: a word always consumes every letter of a cell's gram
        (original behavior)."""
        return [gram.text], []

    def _rule_gram_use_partial(self, gram, is_start):
        """Partial grams: the first cell may contribute any suffix of its gram
        (the word starts partway in) and the last cell any prefix (the word ends
        partway through); middle cells stay whole. Leftover letters remain on the
        board (see _clear_paths)."""
        text = gram.text
        if is_start:
            # Start partway in: every suffix (k == 0 is the whole gram).
            continue_options = [text[k:] for k in range(len(text))]
            end_only_options = []
        else:
            # Walk straight through with the whole gram, or end partway via a
            # proper prefix (a full-gram ending is already a continue_option).
            continue_options = [text]
            end_only_options = [text[:j] for j in range(1, len(text))]
        return continue_options, end_only_options

    # --- Fossil-word-use rules (game_screen.fossil_word_use) -------------------------
    # Whether a fossilized cell (a frozen formed word) can take part in a NEW
    # word. Two seams of _collect_words, both keyed off game_screen.fossil_word_use:
    # the *_is_wall pair gates the pathfinding walk (block walls fossils off for
    # speed + correctness); the *_word_ok pair gates a finished word (allow still
    # demands at least one non-fossilized cell, so a word isn't built purely from
    # frozen ones).
    def _rule_fossil_block_is_wall(self, cell):
        """Walk: a fossilized cell walls off word-finding (original behavior)."""
        return cell in self._fossilized_cells

    def _rule_fossil_allow_is_wall(self, cell):
        """Walk: fossilized cells are walkable; the word gate enforces freshness."""
        return False

    def _rule_fossil_block_word_ok(self, path):
        """Word: block never admits a fossil into a path, so always accept."""
        return True

    def _rule_fossil_allow_word_ok(self, path):
        """Word: require at least one non-fossilized cell in the path."""
        return any(cell not in self._fossilized_cells for cell in path)

    def _collect_words(self, cell, prev_direction, path, text, segments, found, apply_length=True):
        """Pathfinding walk: step forward from `cell` (snaking via the board's
        forward_neighbors), collecting every dictionary word reachable. Grid-
        agnostic -- each board supplies its own snake geometry. `prev_direction`
        is the step taken to reach `cell` (None at the start), which a board's
        pathfinding rule may use to veto sharp twists (the square grid ignores
        it). Prunes as soon as the letters so far begin no word.

        A wild-vowel cell contributes any of its vowel runs rather than one fixed
        gram, so the walk branches over each run (`segments` records the run
        actually taken, so a matched word knows its exact spelling). Plain grams
        go through the gram-usage rule, which may let a word take only a prefix /
        suffix of a cell (see _rule_gram_use_partial)."""
        # Fossilized cells and word-finding: the fossil-use rule decides whether a
        # fossil walls off the walk (block) or is walkable (allow). The companion
        # _fossil_word_ok_rule gates finished words below.
        if self._fossil_is_wall_rule(cell):
            return
        gram = self._board.gram_at(*cell)
        if gram is None:
            return
        is_start = len(path) == 0
        if gram.is_wild:
            # Wild cells keep their whole-run behavior (no partial usage).
            continue_options = wild_expansions()
            end_only_options = []
        else:
            continue_options, end_only_options = self._gram_usage_rule(gram, is_start)
        path = path + [cell]
        for option in continue_options:
            text2 = text + option
            if not is_prefix(text2):
                continue
            segments2 = segments + [option]
            if is_word(text2) and (not apply_length or self._word_length_rule(text2, path)) and self._fossil_word_ok_rule(path):
                found.append(FoundWord(path, segments2, text2))
            for nxt, direction in self._board.forward_neighbors(*cell, prev_direction):
                # Never step backwards onto a cell already in this word's path.
                # The right/down rules can't revisit (their directions are
                # monotonic), so this guard only bites for rules that allow
                # turning back, like rule_snake_anydirection; it also keeps that
                # walk from looping.
                if nxt not in path:
                    self._collect_words(nxt, direction, path, text2, segments2, found, apply_length)
        # End-only options terminate the word here without walking on (a partial
        # prefix leaves the rest of the gram behind, so the path can't continue).
        for option in end_only_options:
            text2 = text + option
            segments2 = segments + [option]
            if is_word(text2) and (not apply_length or self._word_length_rule(text2, path)) and self._fossil_word_ok_rule(path):
                found.append(FoundWord(path, segments2, text2))

    # --- Nucleation rules (game_screen.word_nucleation) --------------------
    # Stage 2a: of every word _find_words turned up, decide which count for the
    # move just made. The gate between pathfinding and selection; its output is
    # then narrowed by the placed-cell rule (stage 2b) below.
    def _rule_adjacent_to_placed_pieces(self, found, placed_positions):
        """Keep words that bridge a piece placed this moving phase and the
        existing board: a word must cover at least one placed cell and at least
        one pre-existing cell. With the multi-placement select trigger, EVERY
        piece placed since the last selection is a nucleation site (placed_
        positions is the accumulated set), so a word nucleating around any of
        them qualifies -- not just the last piece down. Words made purely of old
        letters, or purely of placed cells, are dropped."""
        new_cells = set(placed_positions)
        candidates = []
        for fw in found:
            has_placed = any(cell in new_cells for cell in fw.path)
            has_old = any(cell not in new_cells for cell in fw.path)
            if has_placed and has_old:
                candidates.append(fw)
        return candidates

    def _rule_nucleate_anywhere(self, found, placed_positions):
        """Every word found on the board counts, wherever it sits -- no tie to a
        placed piece. A word made entirely of old cells qualifies, so the player
        can build words anywhere on the board. (Pair with rule_require_placed_cell
        to still demand a placed cell without the bridge-to-old requirement.)"""
        return list(found)

    def _rule_nucleate_none(self, found, placed_positions):
        """No word ever qualifies, which disables clearing entirely."""
        return []

    # --- Placed-cell requirement rules (game_screen.placed_cell_requirement) -
    # Stage 2b: an independent filter on the nucleated words -- whether a word
    # must include a cell from a piece placed this moving phase. Composes with
    # any nucleation rule above.
    def _rule_require_placed_cell(self, candidates, placed_positions):
        """Keep only words covering at least one cell placed this moving phase.
        On its own this is the 'at least one placed cell' requirement, separable
        from nucleation's bridge-to-old rule."""
        new_cells = set(placed_positions)
        return [
            fw for fw in candidates
            if any(cell in new_cells for cell in fw.path)
        ]

    def _rule_placed_cell_optional(self, candidates, placed_positions):
        """No placed-cell requirement: pass the nucleated words through as-is."""
        return candidates

    def _current_piece(self):
        # A live word-piece (game_screen.player_word_piece) overrides the pool's
        # current piece until it's placed and _advance_piece clears the override.
        if self._override_piece is not None:
            return self._override_piece
        return self._piece_pool.current_piece()

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
    
    def _update_hover_visibility(self):
        piece = self._current_piece()
        if piece.placed:
            return
        positions = piece.get_cell_positions()
        self._board.hide_cells_for_hover(positions)
    
    def _clear_hover_visibility(self):
        piece = self._current_piece()
        positions = piece.get_cell_positions()
        self._board.restore_cells_from_hover(positions)
    
    def _piece_on_board(self, piece):
        """True only if every cell the piece occupies is on the grid. Off-board
        cells return None from get_cell, so this rejects a piece hanging off any
        edge. One half of the move/rotate/place gate; see _move_allowed."""
        return all(
            self._board.get_cell(x, y) is not None
            for (x, y) in piece.get_cell_positions()
        )

    def _overlapped_cells(self, piece):
        """The occupied board cells the piece currently sits on -- the cells a
        placement would cover. The piece's own cells aren't on the board yet, so
        this reports only settled obstacle / player cells. is_cell_occupied is
        common to the square and hex boards, so it stays grid-agnostic."""
        overlapped = set()
        for (x, y) in piece.get_cell_positions():
            if self._board.is_cell_occupied(x, y):
                overlapped.add((x, y))
        return overlapped

    def _overlap_allowed(self, overlapped):
        """Whether `overlapped` (the occupied cells a position would cover) is
        permitted by ALL FOUR independent overlap slots -- player
        (game_screen.cell_overlap_player), obstacle (..._obstacle), mission
        (..._mission) and fossilized (..._fossilized). A position holds only if
        none of them blocks it -- so a player-allowing, obstacle-blocking config
        still refuses to cover an obstacle. The single gate every move/place
        runs through."""
        return (
            self._cell_overlap_player_rule(overlapped)
            and self._cell_overlap_obstacle_rule(overlapped)
            and self._cell_overlap_mission_rule(overlapped)
            and self._cell_overlap_fossilized_rule(overlapped)
        )

    def _move_allowed(self, piece):
        """The shared move/rotate/place gate: a position is allowed only if every
        cell is on the grid AND the cells it covers satisfy the active cell-
        overlap rules. Driving the overlap rules here -- not just at placement --
        lets a blocking rule stop the piece from being moved onto a forbidden
        cell in the first place, so the player never drags it over one."""
        return self._piece_on_board(piece) and self._overlap_allowed(
            self._overlapped_cells(piece)
        )

    def _move_piece(self, dx, dy):
        piece = self._current_piece()
        self._clear_hover_visibility()
        piece.move(dx, dy)
        # Reject a move that would hang a cell off the grid or violate the cell-
        # overlap rule, restoring the prior position before refreshing the hover.
        if not self._move_allowed(piece):
            piece.move(-dx, -dy)
        self._update_hover_visibility()

    def _handle_move_click(self, x, y):
        """Left-click control (MOVING phase). Clicking a cell the current piece
        occupies rotates it clockwise; clicking any other on-board cell jumps the
        piece there. Clicks off the board, or while the piece is already placed,
        do nothing. The grid maps the pixel to a cell (cell_at), so this works
        the same on the square and hex boards."""
        piece = self._current_piece()
        cell = self._board.cell_at(x, y)
        if not piece.placed and cell is not None:
            if cell in piece.get_cell_positions():
                self._rotate_piece_cw()
            else:
                self._jump_piece_to(cell)

    def _jump_piece_to(self, cell):
        """Translate the current piece so its anchor cell lands on `cell` -- a
        direct jump, not a step-by-step walk through the cells in between. The
        anchor (grid_x, grid_y) is an occupied cell of every piece, so the click
        ends up under the piece. Routed through _move_piece, so an invalid
        landing (off board or a forbidden overlap) is rejected and the piece
        stays put, exactly like a keyboard move."""
        piece = self._current_piece()
        target_x, target_y = cell
        self._move_piece(target_x - piece.grid_x, target_y - piece.grid_y)

    def _rotate_piece_cw(self):
        piece = self._current_piece()
        self._clear_hover_visibility()
        piece.rotate_cw()
        if not self._move_allowed(piece):
            piece.rotate_ccw()  # off the grid or onto a forbidden cell; undo it
        self._update_hover_visibility()

    def _rotate_piece_ccw(self):
        piece = self._current_piece()
        self._clear_hover_visibility()
        piece.rotate_ccw()
        if not self._move_allowed(piece):
            piece.rotate_cw()
        self._update_hover_visibility()

    def _place_current_piece(self):
        piece = self._current_piece()
        # A piece can't be placed while any cell hangs off the grid; ignore the
        # place until the player brings it fully back on-board.
        if not self._piece_on_board(piece):
            return
        # Cells already on the board this placement would cover.
        overlapped = self._overlapped_cells(piece)
        # Cell-overlap rules: may the piece be placed when it covers those cells?
        # A blocking rule (obstacle or mission) refuses and aborts the place
        # (movement is gated the same way, so a blocked piece should never reach
        # here covering them).
        if not self._overlap_allowed(overlapped):
            return
        self._clear_hover_visibility()
        piece.place()

        placed_positions = []
        for gx, gy, cell, label, gram, overlay in piece.get_cell_data():
            self._board.place(gx, gy, cell, label, gram, overlay)
            placed_positions.append((gx, gy))
        # _begin_selection recolors these cells from the live piece's darker
        # active tint to the lighter placed tint and keeps them lit -- through
        # every further placement this moving phase -- to remind the player where
        # words nucleate, until they settle once selection leaves them behind
        # (see _mark_placed_cells / _settle_placed_cells).

        # Cell-overlap action rule: handle the cells just covered (e.g. drop a
        # covered obstacle from the obstacle-cell tracking so it counts as gone).
        self._cell_overlap_action_rule(overlapped)

        # Runs stages 1-3: auto selectors clear and advance immediately;
        # interactive ones enter the SELECTING phase and withhold the next piece
        # until the player hits Next piece (see _end_selection).
        self._begin_selection(placed_positions)

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
    
    def draw(self):
        # glClearColor wants 0-1 floats, but colors.yaml stores 0-255 channels,
        # so normalize. Clear to the board background, then restore the default
        # window background for the menu/title screens that just call clear().
        bg = get_color("board.background")
        win_bg = get_color("window.background")
        pyglet.gl.glClearColor(bg[0] / 255, bg[1] / 255, bg[2] / 255, 1)
        self._window.clear()
        pyglet.gl.glClearColor(win_bg[0] / 255, win_bg[1] / 255, win_bg[2] / 255, 1)
        
        self._board_batch.draw()
        self._obstacle_batch.draw()
        self._mission_batch.draw()
        self._piece_batch.draw()
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
    
    def update(self, dt):
        # During the opening reveal, drive the fade-in (paused while the menu is
        # open, like the moving timer below); when it finishes, hand off to the
        # active mode. No piece spawns and no timer runs until then.
        if self._phase == Phase.LOADING:
            if not self._menu_open:
                self._loading_anim.update(dt)
                if self._loading_anim.done:
                    self._finish_loading()
            return
        # Drive the active mode's per-tick hook only during MOVING (and never
        # while the pause menu is open), so a timed mode counts down only when the
        # player can actually act. Event-driven modes ignore this. SELECTING gets
        # its own hook, used only by a mode whose clock spans both phases (the
        # omniswap race variant); every other mode leaves it a no-op.
        if self._menu_open:
            return
        if self._phase == Phase.MOVING:
            self._moving_mode.update(dt)
        elif self._phase == Phase.SELECTING:
            self._moving_mode.update_during_select(dt)
    
    def _handle_menu_action(self, action):
        if action == "resume":
            self._menu_open = False
        elif action == "main_menu":
            self._screen_manager.switch_to(ScreenType.MAIN_MENU)
        elif action == "exit":
            self._window.close()
    
    def on_key_press(self, symbol, modifiers):
        # Log the raw press before any delegation so the session log holds the
        # complete control stream a replay re-feeds (record #2).
        L.log_20001(pyglet.window.key.symbol_string(symbol),
                    _mods_str(modifiers), self._phase.name)
        if self._menu_open:
            action = self._ingame_menu.on_key_press(symbol, modifiers)
            if action:
                self._handle_menu_action(action)
            return True
        
        # Escape backs out of the open disambiguation chooser instead of opening
        # the pause menu (one of the chooser back-out gestures alongside Backspace
        # / any letter). If cancel is disabled the back-out is inert and Escape
        # falls through to the menu as usual.
        if (symbol in self._keys["pause"] and self._phase == Phase.SELECTING
                and self._disambiguating() and self._backout_disambiguation()):
            return True

        if symbol in self._keys["pause"]:
            self._menu_open = True
            self._ingame_menu.reset()
            return True

        # During the opening reveal nothing on the board responds; only the pause
        # menu (handled above) works -- no move, rotate, place, or word entry.
        if self._phase == Phase.LOADING:
            return True

        # Once won, the game is frozen: no piece movement, rotation, placement,
        # or word entry -- only the menu (Escape, handled above) responds.
        if self._phase == Phase.VICTORY:
            return True

        # While selecting words, keys drive the entry pane; letters arrive
        # separately via on_text. Control scheme (anti-fat-finger): ENTER is the
        # one action key -- with text it submits the word (pane default), on an
        # empty field it ends selection (Next piece / omniswap surrender).
        # word_clear (spacebar) clears the typed word (a lingering failed attempt),
        # so it can no longer end the game by reflex. Old scheme (spacebar ended
        # selection):
        #   if symbol in self._keys["place"]:
        #       self._end_selection()
        #       return True
        #   return self._selecting_side_pane.on_key_press(symbol, modifiers)
        if self._phase == Phase.SELECTING:
            # The chooser owns the keyboard while it's open: cycle the highlight,
            # confirm the choice, or back out (word_clear / Backspace / Escape /
            # any letter, gated by game_screen.disambig_cancel). Backspace and a
            # letter also EDIT after backing out so the player flows straight into
            # hunting a different word; a swallowed stray key can't edit mid-choice.
            if self._disambiguating():
                if symbol in self._keys["word_cycle_prev"]:
                    self._cycle_disambiguation(-1)
                elif symbol in self._keys["word_cycle_next"]:
                    self._cycle_disambiguation(1)
                elif symbol in self._keys["word_submit"]:
                    self._confirm_disambiguation()
                elif symbol in self._keys["word_backspace"]:
                    # Back out and drop the last letter, so Backspace fixes a typo
                    # in the word that was up for confirmation.
                    if self._backout_disambiguation():
                        self._selecting_side_pane.on_key_press(symbol, modifiers)
                elif symbol in self._keys["word_clear"]:
                    self._backout_disambiguation()
                return True
            if symbol in self._keys["word_clear"]:       # spacebar -> clear field
                self._selecting_side_pane.clear_word()
                return True
            if (symbol in self._keys["selection_end"]
                    and self._selecting_side_pane.is_empty()):
                self._end_selection()                    # ENTER on empty -> end
                return True
            return self._selecting_side_pane.on_key_press(symbol, modifiers)

        # Word-hunt field: Backspace edits the typed hunt word (letters arrive via
        # on_text). Consumed only when the field handles it, so other keys fall
        # through to the moving mode.
        if self._moving_side_pane.on_key_press(symbol, modifiers):
            return True

        # MOVING phase: the active mode owns piece/cursor input.
        return self._moving_mode.on_key_press(symbol, modifiers)
    
    def on_text(self, text):
        # Typed characters only matter while selecting words; on_key_press
        # handles Backspace/Enter and the pane filters to letters.
        L.log_20002(text, self._phase.name)
        if self._menu_open:
            return
        if self._phase == Phase.SELECTING:
            # Typing a LETTER while the chooser is open backs out of it, then the
            # letter appends -- the player abandons the confirmation and keeps
            # hunting. If cancel is disabled the letter is swallowed (the chooser
            # keeps the keyboard until confirm). Gate on isalpha: Enter's '\r' (and
            # other control chars) are NOT edit gestures and must fall through so
            # on_key_press can CONFIRM the chooser -- this on_text fires before
            # on_key_press here, so a blind back-out would cancel every Enter.
            if (text.isalpha() and self._disambiguating()
                    and not self._backout_disambiguation()):
                return
            self._selecting_side_pane.on_text(text)
        elif self._phase == Phase.MOVING:
            # Typed letters feed the word-hunt field (movement/rotate keys are all
            # non-letters now, so they never leak in); highlighting updates live.
            self._moving_side_pane.on_text(text)

    def on_mouse_press(self, x, y, button, modifiers):
        # Log the board cell the pixel resolves to alongside the raw coord, so a
        # coordinate-scale desync shows up as clicks that stop matching cells.
        board = getattr(self, "_board", None)
        cell = board.cell_at(x, y) if board is not None else None
        L.log_20003(x, y, pyglet.window.mouse.buttons_string(button),
                    self._phase.name, cell)
        if self._menu_open:
            action = self._ingame_menu.on_mouse_press(x, y, button, modifiers)
            if action:
                self._handle_menu_action(action)
            return
        # Once the game has ended, a click dismisses the end-state overlay (if it's
        # still up), leaving the player looking at the final board. The game stays
        # frozen otherwise -- only the menu (Escape) responds.
        if self._phase == Phase.VICTORY:
            self._end_overlay_dismissed = True
            return
        if self._phase == Phase.SELECTING:
            # While the "select which one" chooser is open, the Submit label
            # confirms the highlighted candidate and Clear backs out (per
            # disambig_cancel); board clicks and gram-typing are inert so a click
            # can't edit the field mid-choice. Enter/arrows handle the keyboard.
            if self._disambiguating():
                if self._selecting_side_pane.hit_submit(x, y):
                    self._confirm_disambiguation()
                elif self._selecting_side_pane.hit_clear(x, y):
                    self._disambig_cancel_rule()
                return
            # Right-click manipulates a board gram during SELECTING too, when
            # game_screen.gram_manip_in_selecting is enabled (omniswap lives in
            # SELECT, so gram-doubling must reach here). Consumes the click before
            # the selection handling below, mirroring MOVING.
            if self._gram_manip_in_selecting and self._try_gram_manipulate(x, y, button):
                return
            self._selecting_side_pane.on_mouse_press(x, y, button, modifiers)
            # A left-click on the board (left of the pane) types that cell's gram
            # into the entry field, per the select-click rule. The pane handles
            # its own right-side button clicks above; this drives the board side.
            if button == self._buttons["select_primary"]:
                self._select_click_rule(x, y)
            # Stop here: the pane click may have ended selection (Next piece),
            # flipping the phase to MOVING. Without this return, the same click
            # would fall through to the MOVING handling below and be re-read as a
            # board move / word-piece swap at the Next-piece button's position.
            return
        # MOVING phase: the gram-manipulate button (right-click) transforms a
        # cell's gram, mode-agnostic; every other button goes to the active mode
        # (which owns piece/cursor input). _try_gram_manipulate keeps an UNASSIGNED
        # gram_manipulate (None) from swallowing clicks.
        if self._phase == Phase.MOVING:
            if not self._try_gram_manipulate(x, y, button):
                self._moving_mode.on_mouse_press(x, y, button)

    def on_mouse_motion(self, x, y, dx, dy):
        if self._menu_open:
            self._ingame_menu.on_mouse_motion(x, y, dx, dy)
