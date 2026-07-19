"""Board-setup rules extracted from GameScreen: the LOADING opening-reveal, starting-coverage, starting-formation (scattered / fill / ideation-region) fills, grid construction and piece spawn/orient rules. A mixin -- every method runs with GameScreen's self and the registries in __init__ resolve these by name. Kept out of game_screen.py to bound its size (see AGENTS.md)."""

import math
import time
from collections import Counter, defaultdict
from views.game_phase import Phase
from views.loading_animation import LoadingAnimation, AlphaFade, WhiteFade
from models.piece_pool import PiecePool
# Piece-set / gram-pick accessors, resolved per call so a game mode's *.piece_set /
# *.gram_pick override takes effect (these modules import before apply_game_mode
# swaps CONFIG). Called at board-build time in _rule_use_square_grid / _rule_use_hex_grid.
from models.square_piece import (
    SquarePiece,
    player_piece_types as square_player_piece_types,
    obstacle_piece_types as square_obstacle_piece_types,
    obstacle_gram_pick_rule as square_obstacle_gram_pick_rule,
    mission_piece_types as square_mission_piece_types,
    mission_gram_pick_rule as square_mission_gram_pick_rule,
)
from models.hex_piece import (
    HexPiece,
    player_piece_types as hex_player_piece_types,
    obstacle_piece_types as hex_obstacle_piece_types,
    obstacle_gram_pick_rule as hex_obstacle_gram_pick_rule,
    mission_piece_types as hex_mission_piece_types,
    mission_gram_pick_rule as hex_mission_gram_pick_rule,
)
from models.square_unimo import SquareUnimoType
from models.hex_unimo import HexUnimoType
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
from models.square_grid import SquareGrid
from models.hex_grid import HexGrid
from models.word_dictionary import (
    is_word, is_prefix, is_obscure, select_maximal_paths, all_words)
from starting_coverage import write_coverage_csv
from config import select_rule, get_color, get_string, CONFIG
import session_log
import log_codes as L
from source import rand


class BoardSetupMixin:
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
            # GLYPH axis: every cell's letter fades on the active glyphs scheme's
            # bucket (game_screen.loading_fade_glyphs_category) -- by length /
            # ideation / kind. This is where the fossilized-vs-unigram precedence is
            # settled: under an ideation scheme a fossil single letter fades as a
            # plain 'uni', under 'by_category' it fades as 'fossilized_glyph'.
            glyph_cat = self._loading_fade_glyphs_category_rule((x, y), cell)
            self._add_cell_label_fade_handle(handles[glyph_cat], cell)
            # BACKGROUND axis: a special kind fades its colored fill on its own
            # "<kind>_background" dial, so e.g. a seeded fossil's gray fill can reveal
            # last, apart from its letter. Plain cells have no separate background
            # axis yet (their white fill just rides with the glyph); a full parallel
            # loading_fade_backgrounds_category is deferred (see CONFIG_REFERENCE).
            kind = self._cell_kind((x, y))
            bg_cat = kind + "_background" if kind is not None else glyph_cat
            self._add_cell_background_fade_handles(handles[bg_cat], cell)
        self._loading_anim = LoadingAnimation(dict(handles))

    def _add_cell_background_fade_handles(self, into, cell):
        """The cell's BACKGROUND (fill) fade handles. The hex inner fill white-fades
        (held opaque, so it masks the black outer and no gray bleeds through
        mid-fade); the square's single BorderedRectangle alpha-fades. Split out from
        the glyph so a fossil's gray fill can reveal in its own (late) category."""
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

    def _add_cell_label_fade_handle(self, into, cell):
        """The cell's GLYPH fade handle (alpha ramp), if it has a label."""
        if cell.label is not None:
            into.append(AlphaFade(cell.label))

    def _cell_kind(self, pos):
        """The special kind of a placed cell for the opening reveal -- "fossilized"
        / "mission" / "obstacle" -- or None for a plain settled cell. Fossilized
        wins (it is the cell's permanent end state and its actual fill color; see
        _cell_resting_color), then mission, then obstacle. A kind drives the cell's
        BACKGROUND fill dial ("<kind>_background") and, under the by_category glyph
        scheme, its glyph dial ("<kind>_glyph") too; see _begin_loading. Plain cells
        (None) fall to the active loading_fade_glyphs_category scheme."""
        if pos in self._fossilized_cells:
            return "fossilized"
        if pos in self._mission_cells:
            return "mission"
        if pos in self._obstacle_cells:
            return "obstacle"
        return None

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

    # --- loading-fade GLYPH schemes (game_screen.loading_fade_glyphs_category) ---
    # Each maps one placed cell (pos, cell) to a GLYPH fade-category name (which must
    # have a slot in loading_animation.yaml). This is the glyph (letter) axis; the
    # background fill axis is keyed off the cell's kind (see _begin_loading /
    # _cell_kind). Swap which axis the letters group by. Category names carry a
    # _glyph suffix to say which part of the cell they fade.
    def _rule_loading_fade_by_length_glyph(self, pos, cell):
        """Bucket by gram length: settled_3plus_glyph / settled_2_glyph /
        settled_1_glyph (wild vowels -- empty text -- fade with the singles). The
        original reveal grouping."""
        length = len(cell.gram) if cell.gram is not None else 1
        if length >= 3:
            return "settled_3plus_glyph"
        if length == 2:
            return "settled_2_glyph"
        return "settled_1_glyph"

    def _rule_loading_fade_by_ideation_strength_glyph(self, pos, cell):
        """Bucket by ideation strength from the cleaned3 grades: 'strong_glyph'
        (graded y-strong) vs 'not_strong_glyph' (m / n, or no grade, e.g. a scrabble
        letter)."""
        grade = ideation_grade(cell.gram.text) if cell.gram is not None else None
        return "strong_glyph" if grade and grade["strong"] else "not_strong_glyph"

    def _rule_loading_fade_by_ideation_fix_glyph(self, pos, cell):
        """Bucket by *fix: 'prefix_glyph' / 'suffix_glyph' / 'midfix_glyph', else
        'no_fix_glyph'. Uses the gram's PRIMARY *fix (the bin the formation selected
        it for, else priority prefix>suffix>midfix) -- see _cell_primary_fix."""
        fix = self._cell_primary_fix(pos, cell)
        return fix + "_glyph" if fix else "no_fix_glyph"

    def _rule_loading_fade_by_ideation_length_strength_fix_glyph(self, pos, cell):
        """Composite reveal order: bucket each cell's glyph by gram LENGTH x ideation
        STRENGTH x *fix, e.g. 'tri_strong_pre_glyph'. Lets the opening reveal sweep
        through tri_strong_pre_glyph, tri_strong_mid_glyph, ... di_weak_suf_glyph,
        uni_glyph in whatever order their slots in loading_animation.yaml give them.
          length   -- tri (3+) / di (2); single letters are one 'uni' bucket (they
                      grade uniformly strong + all-fix, so splitting them is moot)
          strength -- strong (graded y) / weak (m / n / ungraded)
          *fix     -- pre / mid / suf from the gram's PRIMARY *fix (the bin it was
                      selected for, else priority), else nofix (no *fix / ungraded)"""
        gram = cell.gram
        length = len(gram) if gram is not None else 1
        if length == 1:
            return "uni_glyph"
        size = "tri" if length >= 3 else "di"
        grade = ideation_grade(gram.text) if gram is not None else None
        strength = "strong" if (grade and grade["strong"]) else "weak"
        fix = self._cell_primary_fix(pos, cell)
        fix_part = {"prefix": "pre", "suffix": "suf", "midfix": "mid"}.get(fix, "nofix")
        return "%s_%s_%s_glyph" % (size, strength, fix_part)

    def _rule_loading_fade_by_category_glyph(self, pos, cell):
        """Bucket the glyph by the cell's KIND: 'mission_glyph' / 'obstacle_glyph' /
        'fossilized_glyph' for special cells (see _cell_kind), else 'settled_glyph'
        for every plain letter. The one glyph scheme where a cell's kind drives its
        letter -- so a seeded fossil's letter reveals on its own dial rather than
        with the ideation sweep."""
        kind = self._cell_kind(pos)
        return kind + "_glyph" if kind is not None else "settled_glyph"

    def _finish_loading(self):
        """End LOADING: drop the animation, flip to MOVING, and start the active
        mode's first turn (spawn / timer). Called from update() once the reveal
        completes."""
        self._loading_anim = None
        self._set_phase(Phase.MOVING)
        self._moving_mode.start()
        # Start the whole-game countdown (if on) now that play has begun, so the
        # opening reveal doesn't burn clock time. A no-op when off / in a mode that
        # runs its own timer instead.
        self._start_game_timer()

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
    def _rule_formation_empty(self):
        """Leave the board completely empty -- no obstacle, mission, or player fill.
        For modes whose own field populates cells at runtime: MOVING_SHOOTING_GALLERY's
        ShootingField spawns fade-in gram batches into the empty grid. Pair with
        game_screen.victory: rule_victory_none (an empty board is not a win here)."""
        pass

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
        siblings -- see _fill_ideation_sidepanes. The trigram panes pack a single
        STRAIGHT edge column each (see _split_sidepane_trigrams)."""
        self._fill_ideation_trigram_sidepanes_mixed(self._split_sidepane_trigrams)

    def _rule_formation_fill_ideation_trigram_sidepanes_zigzag(self):
        """Like rule_formation_fill_ideation_trigram_sidepanes, but each trigram+
        pane ZIGZAGS down its two outermost columns -- alternating outer/inner
        column every row -- instead of packing one straight edge column, so the
        multigrams spread across two columns on either side. Same counts, random
        digram/unigram mix, forced picker and no obstacle/mission pieces. See
        _split_sidepane_trigrams_zigzag."""
        self._fill_ideation_trigram_sidepanes_mixed(self._split_sidepane_trigrams_zigzag)

    def _fill_ideation_trigram_sidepanes_mixed(self, split_rule):
        """Shared body of the no-digram-region side-pane formations: `split_rule`
        carves the trigram+ cells off the two edges (straight column vs zigzag), then
        the inner (non-pane) cells are shuffled and split into a random digram/unigram
        mix. Only the trigram pane SHAPE changes with `split_rule`; counts, mix and
        placement are identical."""
        cells = [(x, y)
                 for y in range(self._board.height)
                 for x in range(self._board.width)
                 if self._board.is_valid(x, y)]
        n_uni, n_di, n_tri = self._region_length_counts(len(cells))

        tri_left, tri_right, inner = split_rule(cells, n_tri)
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

    def _split_sidepane_trigrams_zigzag(self, cells, n_tri):
        """Zigzag twin of _split_sidepane_trigrams: same left/right split and same
        prefix:(midfix+suffix) budget (so the left/right counts are identical), but
        each side's trigram+ cells ZIGZAG down its two outermost columns -- outer
        column on even rows, inner column on odd rows, one cell per row (see
        _zigzag_pick) -- instead of packing a single straight edge column. `inner`
        is every leftover (non-trigram) cell."""
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

        tri_left = self._zigzag_pick(left, n_tri_left, "left")
        tri_right = self._zigzag_pick(right, n_tri_right, "right")
        chosen = set(tri_left) | set(tri_right)
        inner = [c for c in cells if c not in chosen]
        return tri_left, tri_right, inner

    def _zigzag_pick(self, cells, n, side):
        """Return `n` of `cells` forming a two-column ZIGZAG down the given `side`'s
        edge: the two outermost columns are threaded together so the outer column
        supplies even rows and the inner column supplies odd rows (top->down), one
        cell per row -- a single-width line that alternates left/right as it
        descends. `side` is "left" (outer = smallest px) or "right" (outer =
        largest px). If `n` exceeds what the two-column zigzag holds, the surplus
        falls back to the remaining cells by edge extremity. Deterministic
        (replay-safe): geometry only, no rand()."""
        if n <= 0:
            return []
        centers = {c: self._board.cell_center(c[0], c[1]) for c in cells}
        sign = 1 if side == "left" else -1   # order columns from the edge inward
        col_px = sorted({round(centers[c][0]) for c in cells}, key=lambda px: sign * px)
        outer_px = col_px[0]
        inner_px = col_px[1] if len(col_px) > 1 else col_px[0]
        # each column top->down (py desc; pyglet y-up so max py is the top of screen)
        outer_col = sorted([c for c in cells if round(centers[c][0]) == outer_px],
                           key=lambda c: -centers[c][1])
        inner_col = sorted([c for c in cells if round(centers[c][0]) == inner_px],
                           key=lambda c: -centers[c][1])
        result, used = [], set()
        for i in range(max(len(outer_col), len(inner_col))):
            col = outer_col if i % 2 == 0 else inner_col   # outer on even rows
            alt = inner_col if i % 2 == 0 else outer_col   # borrow if the row is missing
            cell = col[i] if i < len(col) else (alt[i] if i < len(alt) else None)
            if cell is not None and cell not in used:
                result.append(cell)
                used.add(cell)
            if len(result) >= n:
                return result
        # More trigrams than the two-column zigzag holds: fill inward by extremity.
        rest = sorted([c for c in cells if c not in used],
                      key=lambda c: (sign * centers[c][0], -centers[c][1]))
        result.extend(rest[:n - len(result)])
        return result

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
        self._player_piece_types = square_player_piece_types()
        # Single-cell shape a clicked-word piece uses on this grid (see
        # _swap_to_word_piece / game_screen.player_word_piece).
        self._unimo_type = SquareUnimoType.SINGLE
        # Obstacles get their own piece set + gram-pick (square_obstacle.* keys),
        # so they can differ from the playable pieces.
        self._obstacle_piece_types = square_obstacle_piece_types()
        self._obstacle_gram_pick_rule = square_obstacle_gram_pick_rule()
        # Missions: the obstacles' twin, own piece set + gram-pick (square_mission.*).
        self._mission_piece_types = square_mission_piece_types()
        self._mission_gram_pick_rule = square_mission_gram_pick_rule()
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
        self._player_piece_types = hex_player_piece_types()
        # Single-cell shape a clicked-word piece uses on this grid (see
        # _swap_to_word_piece / game_screen.player_word_piece).
        self._unimo_type = HexUnimoType.SINGLE
        # Obstacles get their own gram-pick (hex_obstacle.gram_pick); the hex set
        # has a single piece type, so obstacle types match the main set.
        self._obstacle_piece_types = hex_obstacle_piece_types()
        self._obstacle_gram_pick_rule = hex_obstacle_gram_pick_rule()
        # Missions: the obstacles' twin, own piece set + gram-pick (hex_mission.*).
        self._mission_piece_types = hex_mission_piece_types()
        self._mission_gram_pick_rule = hex_mission_gram_pick_rule()

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
