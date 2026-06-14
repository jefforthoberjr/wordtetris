import math
import random
from collections import namedtuple
from enum import Enum
import pyglet
from views.ingame_menu import IngameMenu
from views.moving_side_pane import MovingSidePane
from views.selecting_side_pane import SelectingSidePane
from controllers.screen_manager import ScreenType
from models.piece_pool import PiecePool
from models.square_piece import SquarePiece, PIECE_TYPES
from models.square_piece import OBSTACLE_PIECE_TYPES as SQUARE_OBSTACLE_PIECE_TYPES
from models.square_piece import OBSTACLE_GRAM_PICK_RULE as SQUARE_OBSTACLE_GRAM_PICK_RULE
from models.square_piece import MISSION_PIECE_TYPES as SQUARE_MISSION_PIECE_TYPES
from models.square_piece import MISSION_GRAM_PICK_RULE as SQUARE_MISSION_GRAM_PICK_RULE
from models.hex_piece import HexPiece, PIECE_TYPES as HEX_PIECE_TYPES
from models.hex_piece import OBSTACLE_PIECE_TYPES as HEX_OBSTACLE_PIECE_TYPES
from models.hex_piece import OBSTACLE_GRAM_PICK_RULE as HEX_OBSTACLE_GRAM_PICK_RULE
from models.hex_piece import MISSION_PIECE_TYPES as HEX_MISSION_PIECE_TYPES
from models.hex_piece import MISSION_GRAM_PICK_RULE as HEX_MISSION_GRAM_PICK_RULE
from models.hex_domino import hex_neighbor
from models.hex_domino import HEX_UP, HEX_DOWN
from models.hex_domino import HEX_UP_LEFT, HEX_DOWN_LEFT
from models.hex_domino import HEX_UP_RIGHT, HEX_DOWN_RIGHT
from models.square_grid import SquareGrid
from models.hex_grid import HexGrid
from models.word_dictionary import is_word, is_prefix, select_maximal_paths
from models.wild_vowel import wild_expansions
from models.player_dictionary import PlayerDictionary
from config import select_rule, get_color, CONFIG


class Phase(Enum):
    """Game-screen phases. MOVING: a piece is live and the player moves/places
    it. SELECTING: a piece has been placed and the player is choosing which
    words to clear before the next piece spawns (interactive selection rules
    only; the auto selector never leaves MOVING). VICTORY: the active victory
    rule was met -- no live piece, no word entry; the player can only open the
    menu (Escape)."""
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


# Control key bindings (formerly config.json "controls"). These now live next to
# the rule functions, ready to be folded into rule bundles in a later refactor.
CONTROL_KEYS = {
    "move_left": "A",
    "move_right": "D",
    "move_up": "W",
    "move_down": "S",
    "rotate_clockwise": "LEFT",
    "rotate_counterclockwise": "RIGHT",
    "place": "SPACE",
    "pause": "ESCAPE",
}


def _get_key(action):
    key_name = CONTROL_KEYS[action]
    return getattr(pyglet.window.key, key_name)

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


class GameScreen:
    GRID_WIDTH = 14
    PIECE_POOL_SIZE = 100
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
    SETTLED_CELL_COLOR = get_color("board.cell_fill")

    def __init__(self, window, screen_manager):
        self._window = window
        self._screen_manager = screen_manager

        self._keys = {
            "move_left": _get_key("move_left"),
            "move_right": _get_key("move_right"),
            "move_up": _get_key("move_up"),
            "move_down": _get_key("move_down"),
            "rotate_clockwise": _get_key("rotate_clockwise"),
            "rotate_counterclockwise": _get_key("rotate_counterclockwise"),
            "place": _get_key("place"),
            "pause": _get_key("pause"),
        }
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
            side_pane_x, 0, side_pane_width, window.height
        )

        # Victory overlay: a solid panel + big "VICTORY" centered over the grid
        # region (the left square). Built once and drawn only in the VICTORY
        # phase. Sized off the window so it scales with the framebuffer.
        self._victory_batch = pyglet.graphics.Batch()
        grid_cx = math.floor(self._grid_area_size / 2)
        grid_cy = math.floor(window.height / 2)
        panel_w = math.floor(self._grid_area_size * 0.7)
        panel_h = math.floor(window.height * 0.22)
        self._victory_panel = pyglet.shapes.Rectangle(
            grid_cx - math.floor(panel_w / 2), grid_cy - math.floor(panel_h / 2),
            panel_w, panel_h, color=get_color("victory.panel"),
            batch=self._victory_batch,
        )
        self._victory_label = pyglet.text.Label(
            "VICTORY", font_size=math.floor(window.height / 8),
            x=grid_cx, y=grid_cy, anchor_x="center", anchor_y="center",
            color=get_color("victory.text"), batch=self._victory_batch,
        )

        # The player's lifetime word collection, persisted across every game.
        # Words cleared for the first time ever are shown green and autosaved.
        self._player_dict = PlayerDictionary()

        # Minimum word to clear (letters + cells); see _WORD_LENGTH_RULES.
        self._word_length_rule = select_rule("game_screen.word_length", _WORD_LENGTH_RULES)

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
        cell_overlap_action_rules = {
            "rule_old_cells_get_delete": self._rule_old_cells_get_delete,
        }
        self._cell_overlap_action_rule = select_rule(
            "game_screen.cell_overlap_action", cell_overlap_action_rules
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
        setup_formation_rules = {
            "rule_formation_scattered": self._rule_formation_scattered,
            "rule_formation_mission_center_obstacle_ring": self._rule_formation_mission_center_obstacle_ring,
        }
        self._setup_formation_rule = select_rule(
            "game_screen.setup_formation", setup_formation_rules
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
        self._placements_until_select = self._select_trigger_count
        skip_select_rules = {
            "rule_skip_select_if_isolated": self._rule_skip_select_if_isolated,
            "rule_never_skip_select": self._rule_never_skip_select,
        }
        self._skip_select_rule = select_rule(
            "game_screen.skip_select_isolated", skip_select_rules
        )

        # Select-phase board-click rule (game_screen.select_click): what a click
        # on a board cell does while SELECTING. The type-gram rule appends the
        # clicked cell's gram to the entry field as a typing shortcut -- no
        # validation, so repeats and non-adjacent cells are all fine; the word
        # rules still run only on submit. The none rule disables board clicks.
        select_click_rules = {
            "rule_select_click_type_gram": self._rule_select_click_type_gram,
            "rule_select_click_none": self._rule_select_click_none,
        }
        self._select_click_rule = select_rule(
            "game_screen.select_click", select_click_rules
        )

        # Interactive selectors build their UI in the right-pane region (same
        # spot as the side pane; shown only while SELECTING).
        self._selecting_side_pane = self._selector.create_ui(
            self._moving_side_pane.x, 0, self._moving_side_pane.width, window.height,
            on_submit=self._on_submit_word, on_next=self._end_selection,
        )
        self._phase = Phase.MOVING
        # Candidate word-paths for the move being selected (interactive only):
        # the full path list plus a word -> path map (first path wins a tie).
        self._candidates = []
        self._candidate_words = {}
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
        # rule_nucleate_none qualifies nothing, which disables clearing entirely.
        nucleation_rules = {
            "rule_adjacent_to_placed_pieces": self._rule_adjacent_to_placed_pieces,
            "rule_nucleate_none": self._rule_nucleate_none,
        }
        self._nucleation_rule = select_rule(
            "game_screen.word_nucleation", nucleation_rules
        )

        self._start_new_game()

    def _start_new_game(self):
        """Begin a fresh game: rebuild the board and piece pools and drop a new
        random set of obstacles. Called once at construction and again every
        time the player (re)enters from the menu via "Start Game".

        Each game gets brand-new batches so every shape from the previous game
        (grid lines, placed pieces, obstacles) is released together for GC,
        rather than piling up invisible behind the new board."""
        self._phase = Phase.MOVING
        if self._selecting_side_pane is not None:
            self._selecting_side_pane.begin()
            self._dictionary_count_rule(self._selecting_side_pane, len(self._player_dict))
        self._board_batch = pyglet.graphics.Batch()
        self._piece_batch = pyglet.graphics.Batch()
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
        self._moving_side_pane.reset()
        self._dictionary_count_rule(self._moving_side_pane, len(self._player_dict))
        # Fresh per game: restart the selection-trigger countdown and show it.
        self._placements_until_select = self._select_trigger_count
        self._moving_side_pane.set_phase_label(self._placements_until_select)

        # Lay out the opening obstacle + mission pieces per the active starting-
        # formation rule (game_screen.setup_formation): it builds the obstacle and
        # mission pools at the counts the formation calls for and places every
        # piece (recording cells in _obstacle_cells / _mission_cells). These use
        # their own piece set + gram-pick rules (square_obstacle.* / hex_obstacle.*
        # and the mission twins) and their own batches. Separate from the
        # per-piece player spawn rule. Rebuilt every game, so each game gets a
        # fresh opening.
        self._setup_formation_rule()

        self._piece_pool = PiecePool(
            self.PIECE_POOL_SIZE, self._cell_size, self._piece_batch,
            self._piece_class, self._piece_types,
            cell_color=self.ACTIVE_PIECE_CELL_COLOR
        )
        self._init_first_piece()

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
        self._scatter_pool(self._obstacle_pool, occupied, self._obstacle_cells)
        self._scatter_pool(self._mission_pool, occupied, self._mission_cells)

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
            self._mission_pool, center, self._mission_cells, occupied
        )
        for cell in ring:
            self._place_one_setup_piece(
                self._obstacle_pool, cell, self._obstacle_cells, occupied
            )

    def _build_obstacle_pool(self, count):
        """(Re)build the obstacle pool with `count` pieces, using the obstacle
        piece set / gram-pick / batch / tint set up by the grid builder."""
        self._obstacle_pool = PiecePool(
            count, self._cell_size, self._obstacle_batch,
            self._piece_class, self._obstacle_piece_types,
            gram_pick_rule=self._obstacle_gram_pick_rule,
            cell_color=self.OBSTACLE_CELL_COLOR
        )

    def _build_mission_pool(self, count):
        """(Re)build the mission pool with `count` pieces (the obstacles' twin,
        using the mission piece set / gram-pick / batch / tint)."""
        self._mission_pool = PiecePool(
            count, self._cell_size, self._mission_batch,
            self._piece_class, self._mission_piece_types,
            gram_pick_rule=self._mission_gram_pick_rule,
            cell_color=self.MISSION_CELL_COLOR
        )

    def _scatter_pool(self, pool, occupied, track_cells):
        """Place every piece in `pool` at a random on-board spot clear of
        `occupied`, recording each cell in `occupied` (so later pieces avoid it)
        and `track_cells` (its victory/encoding set). The scattered formation's
        per-pool worker."""
        while True:
            piece = pool.current_piece()
            self._orient_rule(piece)
            self._position_scattered(piece, occupied)
            self._settle_setup_piece(piece, track_cells, occupied)
            if pool.advance() is None:
                break

    def _place_one_setup_piece(self, pool, cell, track_cells, occupied):
        """Place the pool's current piece at a specific `cell` -- for formation
        rules that lay pieces at fixed coordinates -- record it, and advance the
        pool."""
        piece = pool.current_piece()
        self._orient_rule(piece)
        piece.set_position(*cell)
        self._settle_setup_piece(piece, track_cells, occupied)
        pool.advance()

    def _settle_setup_piece(self, piece, track_cells, occupied):
        """Drop an already-positioned setup piece onto the board: place it, record
        each of its cells in `occupied` (so later setup pieces avoid it) and
        `track_cells` (its victory/encoding set), and reveal it."""
        piece.place()
        for gx, gy, cell, label, gram in piece.get_cell_data():
            self._board.place(gx, gy, cell, label, gram)
            occupied.add((gx, gy))
            track_cells.add((gx, gy))
        piece.set_visible(True)

    def _position_scattered(self, piece, occupied):
        """Pick a random on-board anchor whose cells are all on the grid and clear
        of `occupied`. Retries a bounded number of times, then keeps the last spot
        rather than looping forever on a crowded board. Independent of the player
        spawn rule -- starting pieces lay themselves out, they don't spawn live."""
        for _ in range(100):
            x = random.randint(0, self.GRID_WIDTH - 1)
            y = random.randint(0, self._board_height - 1)
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
        self._piece_types = PIECE_TYPES
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
        self._piece_types = HEX_PIECE_TYPES
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
    
    def _spawn_piece(self, piece):
        """Apply the current spawn orientation, then positioning rule."""
        self._orient_rule(piece)
        self._spawn_rule(piece)

    def _rule_orient_default(self, piece):
        """Spawn in the piece's default orientation (rotation state 0)."""
        pass

    def _rule_orient_random(self, piece):
        """Spawn in a random rotation: turn clockwise a random number of times."""
        turns = random.randrange(piece.rotation_count)
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
            x = random.randint(0, self.GRID_WIDTH - 1)
            y = random.randint(0, self._board_height - 1)
            piece.set_position(x, y)
            if self._move_allowed(piece):
                return
    
    def _rule_square_movement(self, symbol, modifiers):
        """Square grid: A/D/W/S nudge the piece by one cell. Returns handled."""
        handled = True
        if symbol == self._keys["move_left"]:
            self._move_piece(-1, 0)
        elif symbol == self._keys["move_right"]:
            self._move_piece(1, 0)
        elif symbol == self._keys["move_up"]:
            self._move_piece(0, 1)
        elif symbol == self._keys["move_down"]:
            self._move_piece(0, -1)
        else:
            handled = False
        return handled

    def _rule_hex_movement_holdshift(self, symbol, modifiers):
        """Flat-top hex: A=up-left, Shift+A=down-left, D=up-right,
        Shift+D=down-right, W=up, S=down. Returns handled."""
        shift = (modifiers & pyglet.window.key.MOD_SHIFT) != 0
        handled = True
        if symbol == self._keys["move_left"]:
            self._move_piece_hexdir(HEX_DOWN_LEFT if shift else HEX_UP_LEFT)
        elif symbol == self._keys["move_right"]:
            self._move_piece_hexdir(HEX_DOWN_RIGHT if shift else HEX_UP_RIGHT)
        elif symbol == self._keys["move_up"]:
            self._move_piece_hexdir(HEX_UP)
        elif symbol == self._keys["move_down"]:
            self._move_piece_hexdir(HEX_DOWN)
        else:
            handled = False
        return handled

    def _rule_hex_movement_arrows(self, symbol, modifiers):
        """Flat-top hex, arrow-key chords: up+A=up-left, down+A=down-left,
        up+D=up-right, down+D=down-right, W=up, S=down. A/D alone do nothing.
        Returns handled."""
        up = self._key_state[pyglet.window.key.UP]
        down = self._key_state[pyglet.window.key.DOWN]
        handled = True
        if symbol == self._keys["move_left"]:
            if up:
                self._move_piece_hexdir(HEX_UP_LEFT)
            elif down:
                self._move_piece_hexdir(HEX_DOWN_LEFT)
            else:
                handled = False
        elif symbol == self._keys["move_right"]:
            if up:
                self._move_piece_hexdir(HEX_UP_RIGHT)
            elif down:
                self._move_piece_hexdir(HEX_DOWN_RIGHT)
            else:
                handled = False
        elif symbol == self._keys["move_up"]:
            self._move_piece_hexdir(HEX_UP)
        elif symbol == self._keys["move_down"]:
            self._move_piece_hexdir(HEX_DOWN)
        else:
            handled = False
        return handled

    def _move_piece_hexdir(self, direction):
        """Move the piece to its hex neighbor in the given direction index."""
        piece = self._current_piece()
        nx, ny = hex_neighbor(piece.grid_x, piece.grid_y, direction)
        self._move_piece(nx - piece.grid_x, ny - piece.grid_y)

    def _rule_repeat_allow(self, word):
        """Allow a word to clear even if it cleared before (original behavior)."""
        return True

    def _rule_repeat_block(self, word):
        """Block a word that has already been cleared earlier this game."""
        return word not in self._cleared_word_history

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
                cell.square.color = self.SETTLED_CELL_COLOR
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

    def _rule_old_cells_get_delete(self, overlapped):
        # Cell-overlap action rule: the cells a placement covers are treated as
        # gone. The board already overwrote their contents in place(); this drops
        # any covered starting-obstacle / mission coordinates from their tracking
        # sets so a covered obstacle (or mission) counts as cleared for its
        # victory rule.
        self._obstacle_cells.difference_update(overlapped)
        self._mission_cells.difference_update(overlapped)

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
        """Transition to the VICTORY state: settle the last placed piece (so no
        cell is left tinted) and stop play. The VICTORY overlay is drawn by
        draw(); the right pane reverts to the cleared-word list automatically
        since the phase is no longer SELECTING."""
        self._phase = Phase.VICTORY
        self._settle_placed_cells()

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
    def _rule_select_click_type_gram(self, x, y):
        """Type the clicked cell's gram into the entry field -- a typing
        shortcut, nothing more. No path/nucleation/word checks: any occupied
        cell counts, including repeats and non-adjacent cells. The word rules
        still apply only when the player submits. Clicks off the board or on an
        empty cell (no gram) do nothing; a wild cell has no fixed letters, so it
        contributes nothing to type."""
        cell = self._board.cell_at(x, y)
        if cell is None:
            return
        gram = self._board.gram_at(*cell)
        if gram is None:
            return
        self._selecting_side_pane.type_gram(gram.text)

    def _rule_select_click_none(self, x, y):
        """Board clicks do nothing while selecting (click-to-type disabled)."""
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
            # Still mid-phase: leave the placed pieces lit and bring on the next.
            self._advance_piece()
            return
        # Selection turn: skip it if none of the placed pieces touch the board.
        # The accumulated set (not just the last piece) is the adjacency test, so
        # a word bridging any placed piece keeps the turn.
        if self._skip_select_rule(self._move_placed):
            self._settle_placed_cells()
            self._advance_piece()
            return
        if not self._selector.interactive:
            self._clear_paths(self._selector.choose(self._candidates))
            self._settle_placed_cells()
            # The clear may have met the victory condition; only spawn the next
            # piece if it didn't.
            if not self._check_victory():
                self._advance_piece()
        else:
            self._phase = Phase.SELECTING
            self._selecting_side_pane.begin()
            self._dictionary_count_rule(self._selecting_side_pane, len(self._player_dict))

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
        self._candidates = self._nucleation_rule(found, live_placed)
        # Of several ways to spell the same word (different paths, or different
        # wild-vowel expansions), keep the one covering the fewest cells, so a
        # typed word makes the most compact clear -- e.g. a single wild as "OA"
        # over two wilds as "O"+"A" -- leaving more cells in play.
        by_word = {}
        for fw in self._candidates:
            by_word.setdefault(fw.word, []).append(fw)
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
        return random.choice(smallest)

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
        """Stage 4: clear the chosen FoundWords. Gates each through the repeat
        rule, removes the cells, records history, and shows the words in the side
        pane. Returns the words actually cleared."""
        to_clear = set()
        cleared_words = []
        # The gram grouping each cleared word was made of, captured here -- before
        # the obstacle pruning below -- so an obstacle gram still reads as one.
        cleared_variations = []
        for fw in found_words:
            word = fw.word
            if self._repeat_rule(word):
                cleared_words.append(word)
                cleared_variations.append(self._encode_variation(fw))
                to_clear.update(fw.path)
        for (x, y) in to_clear:
            self._board.clear_cell(x, y)
        # A starting obstacle or mission cell, once cleared, stays
        # counted as gone even if a later piece reoccupies its coordinate.
        self._obstacle_cells.difference_update(to_clear)
        self._mission_cells.difference_update(to_clear)
        for word in cleared_words:
            self._cleared_word_history.add(word)
        if cleared_words:
            # Record each word + its gram grouping in the player's lifetime
            # dictionary (instant autosave). add() returns True only for words
            # never collected before, so they list green; a word re-collected
            # with a new grouping saves the grouping but stays black (the count
            # didn't grow).
            new_flags = []
            for word, variation in zip(cleared_words, cleared_variations):
                new_flags.append(self._player_dict.add(word, variation))
            self._moving_side_pane.add_cleared_words(cleared_words, new_flags)
            self._dictionary_count_rule(self._moving_side_pane, len(self._player_dict))
        return cleared_words

    def _on_submit_word(self, typed):
        """Interactive submit (Enter or the Submit control). If the typed word is
        a clearable candidate, clear it and recompute; otherwise show the single
        most specific reason it can't be cleared."""
        word = typed.strip().upper()
        if not word:
            return
        found = self._candidate_words.get(word)
        if found is not None and self._repeat_rule(word):
            # Capture newness before _clear_paths adds the word to the player's
            # dictionary, so the entry pane can list it green.
            is_new = not self._player_dict.contains(word)
            self._clear_paths([found])
            self._selecting_side_pane.accept_word(word, is_new)
            self._dictionary_count_rule(self._selecting_side_pane, len(self._player_dict))
            self._recompute_candidates()
            # This clear may have won the game immediately (e.g. it removed the
            # last obstacle/mission cell); if so, stop here rather than ending
            # selection.
            if self._check_victory():
                return
            # Leave SELECT once the placed piece is no longer adjacent to the
            # board -- its remaining cells were consumed or stranded -- mirroring
            # the adjacency gate in _begin_selection. Keyed on adjacency, not the
            # candidate count, so the transition never reveals whether a word is
            # still formable.
            if not self._piece_touches_existing(self._move_placed):
                self._end_selection()
            return
        self._selecting_side_pane.show_errors([self._submission_error(word)])

    def _submission_error(self, word):
        """The single most specific reason `word` can't be cleared right now,
        walking the pipeline from the typed word inward: a non-word, a word not
        on the board at all, a board word too short to clear, a board word that
        doesn't touch the placed piece, or one already cleared this game."""
        if not is_word(word):
            return "Word is not in the dictionary"
        if word not in self._board_words_any:
            return "Word isn't on the board"
        if word not in self._length_ok_words:
            return "Word is too short"
        if word not in self._candidate_words:
            return "Word didn't involve placed piece"
        return "Word already cleared"

    def _advance_piece(self):
        """Spawn the next piece and resume play (or do nothing if the pool is
        exhausted). Checks victory first, so a win is caught before the next
        piece spawns (rule_victory_grid_empty's 'before spawning' point)."""
        if self._check_victory():
            return
        next_piece = self._piece_pool.advance()
        if next_piece:
            self._spawn_piece(next_piece)
            next_piece.set_visible(True)
            self._update_hover_visibility()

    def _end_selection(self):
        """Leave the SELECTING phase (the Next piece control, or once the piece
        is no longer adjacent to the board) and spawn the next piece. Settles the
        placed piece's remaining cells from light blue back to the board color."""
        self._settle_placed_cells()
        self._phase = Phase.MOVING
        self._advance_piece()

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

    def _collect_words(self, cell, prev_direction, path, text, segments, found, apply_length=True):
        """Pathfinding walk: step forward from `cell` (snaking via the board's
        forward_neighbors), collecting every dictionary word reachable. Grid-
        agnostic -- each board supplies its own snake geometry. `prev_direction`
        is the step taken to reach `cell` (None at the start), which a board's
        pathfinding rule may use to veto sharp twists (the square grid ignores
        it). Prunes as soon as the letters so far begin no word.

        A wild-vowel cell contributes any of its vowel runs rather than one fixed
        gram, so the walk branches over each run (`segments` records the run
        actually taken, so a matched word knows its exact spelling)."""
        gram = self._board.gram_at(*cell)
        if gram is None:
            return
        if gram.is_wild:
            options = wild_expansions()
        else:
            options = [gram.text]
        path = path + [cell]
        for option in options:
            text2 = text + option
            if not is_prefix(text2):
                continue
            segments2 = segments + [option]
            if is_word(text2) and (not apply_length or self._word_length_rule(text2, path)):
                found.append(FoundWord(path, segments2, text2))
            for nxt, direction in self._board.forward_neighbors(*cell, prev_direction):
                # Never step backwards onto a cell already in this word's path.
                # The right/down rules can't revisit (their directions are
                # monotonic), so this guard only bites for rules that allow
                # turning back, like rule_snake_anydirection; it also keeps that
                # walk from looping.
                if nxt not in path:
                    self._collect_words(nxt, direction, path, text2, segments2, found, apply_length)

    # --- Nucleation rules (game_screen.word_nucleation) --------------------
    # Stage 2: of every word _find_words turned up, decide which count for the
    # move just made. The gate between pathfinding and selection.
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

    def _rule_nucleate_none(self, found, placed_positions):
        """No word ever qualifies, which disables clearing entirely."""
        return []

    def _current_piece(self):
        return self._piece_pool.current_piece()
    
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
        permitted by ALL THREE independent overlap slots -- player
        (game_screen.cell_overlap_player), obstacle (..._obstacle) and mission
        (..._mission). A position holds only if none of them blocks it -- so a
        player-allowing, obstacle-blocking config still refuses to cover an
        obstacle. The single gate every move/place runs through."""
        return (
            self._cell_overlap_player_rule(overlapped)
            and self._cell_overlap_obstacle_rule(overlapped)
            and self._cell_overlap_mission_rule(overlapped)
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
        for gx, gy, cell, label, gram in piece.get_cell_data():
            self._board.place(gx, gy, cell, label, gram)
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
        # Entering from the menu ("Start Game") begins a fresh game, which lays
        # down a new random obstacle set.
        self._start_new_game()
    
    def on_exit(self):
        pass
    
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
        # The right pane swaps between the game-long cleared-word list (MOVING)
        # and the word-entry UI (SELECTING).
        if self._phase == Phase.SELECTING:
            self._selecting_side_pane.draw()
        else:
            self._moving_side_pane.draw()

        # On a win, the VICTORY panel sits over the grid; the pane above already
        # reverted to the cleared-word list (phase is no longer SELECTING).
        if self._phase == Phase.VICTORY:
            self._victory_batch.draw()

        if self._menu_open:
            self._ingame_menu.draw()
    
    def update(self, dt):
        pass
    
    def _handle_menu_action(self, action):
        if action == "resume":
            self._menu_open = False
        elif action == "main_menu":
            self._screen_manager.switch_to(ScreenType.MAIN_MENU)
        elif action == "exit":
            self._window.close()
    
    def on_key_press(self, symbol, modifiers):
        if self._menu_open:
            action = self._ingame_menu.on_key_press(symbol, modifiers)
            if action:
                self._handle_menu_action(action)
            return True
        
        if symbol == self._keys["pause"]:
            self._menu_open = True
            self._ingame_menu.reset()
            return True

        # Once won, the game is frozen: no piece movement, rotation, placement,
        # or word entry -- only the menu (Escape, handled above) responds.
        if self._phase == Phase.VICTORY:
            return True

        # While selecting words, keys drive the entry pane (Backspace/Enter);
        # letters arrive separately via on_text. The place key (spacebar) ends
        # selection, same as clicking Next piece.
        if self._phase == Phase.SELECTING:
            if symbol == self._keys["place"]:
                self._end_selection()
                return True
            return self._selecting_side_pane.on_key_press(symbol, modifiers)

        if self._current_piece().placed:
            return False

        if self._movement_rule(symbol, modifiers):
            return True

        if symbol == self._keys["rotate_clockwise"]:
            self._rotate_piece_cw()
            return True
        elif symbol == self._keys["rotate_counterclockwise"]:
            self._rotate_piece_ccw()
            return True
        elif symbol == self._keys["place"]:
            self._place_current_piece()
            return True
        
        return False
    
    def on_text(self, text):
        # Typed characters only matter while selecting words; on_key_press
        # handles Backspace/Enter and the pane filters to letters.
        if self._menu_open:
            return
        if self._phase == Phase.SELECTING:
            self._selecting_side_pane.on_text(text)

    def on_mouse_press(self, x, y, button, modifiers):
        if self._menu_open:
            action = self._ingame_menu.on_mouse_press(x, y, button, modifiers)
            if action:
                self._handle_menu_action(action)
            return
        if self._phase == Phase.SELECTING:
            self._selecting_side_pane.on_mouse_press(x, y, button, modifiers)
            # A left-click on the board (left of the pane) types that cell's gram
            # into the entry field, per the select-click rule. The pane handles
            # its own right-side button clicks above; this drives the board side.
            if button == pyglet.window.mouse.LEFT:
                self._select_click_rule(x, y)
        # MOVING: left-click drives the current piece -- click a cell it occupies
        # to rotate, click another on-board cell to jump it there. Right-click
        # places the piece, the same as the place key.
        if self._phase == Phase.MOVING and button == pyglet.window.mouse.LEFT:
            self._handle_move_click(x, y)
        elif self._phase == Phase.MOVING and button == pyglet.window.mouse.RIGHT:
            self._place_current_piece()

    def on_mouse_motion(self, x, y, dx, dy):
        if self._menu_open:
            self._ingame_menu.on_mouse_motion(x, y, dx, dy)
