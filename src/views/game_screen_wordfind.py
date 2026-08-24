"""Word-finding and word-gating rules extracted from GameScreen.

WordFindMixin holds stage-1 pathfinding (_find_words / _collect_words), the
gram-usage, fossil-walk, nucleation, placed-cell, fossil-requirement and
fossil-seeding rules. It is a mixin: every method runs with GameScreen's `self`,
so it reaches the board, fossil set and companion rule hooks unchanged. Kept out
of game_screen.py purely to bound that file's size (see AGENTS.md)."""

import random

from views.found_word import FoundWord
from models.word_dictionary import is_word, is_prefix
from models.wild_vowel import wild_expansions
from starting_coverage import sample_formable_words, sample_multigram_words
from config import CONFIG
import log_codes as L


class WordFindMixin:
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
        """Walk: fossilized cells are walkable; the word gate enforces freshness.
        MOVING_PLANT rides this rule: the green stem cells (fossilized, carrying the
        root gram) stay walkable so a prefix can snake onto them, and the fossil-word
        gate still demands one fresh prefix cell."""
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

    def _rule_nucleate_within_highlight(self, found, placed_positions):
        """Line blast: keep only words whose path lies WHOLLY inside the currently
        highlighted line(s) -- the cells of a just-completed row/column
        (self._line_blast_highlight). Placement plays no part (there is no
        placed-piece tie); the highlighted set is the entire SELECT domain, so a word
        that steps to any cell outside it is dropped. Empty highlight -> nothing
        qualifies (SELECT isn't open in line blast without a completed line)."""
        highlight = self._line_blast_highlight
        if not highlight:
            return []
        return [fw for fw in found if all(cell in highlight for cell in fw.path)]

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

    # --- Fossil requirement rules (game_screen.fossil_requirement) ----------
    # Stage 2c: an independent filter on the placed-cell-filtered words -- whether
    # a word must cover at least one fossilized cell. Composes with the nucleation
    # and placed-cell rules above. The first-word-skip knob
    # (game_screen.fossil_requirement_first_word) can waive it until the opening
    # word clears, so the game can bootstrap its first fossils.
    def _rule_require_fossil_cell(self, candidates):
        """Keep only words covering at least one fossilized cell -- unless the
        first-word-skip rule waives the requirement (no word cleared yet)."""
        if self._fossil_first_word_rule():
            return candidates
        return [
            fw for fw in candidates
            if any(self._is_fossilized(cell) for cell in fw.path)
        ]

    def _rule_fossil_cell_optional(self, candidates):
        """No fossil requirement: pass the words through as-is."""
        return candidates

    # --- Fossil first-word-skip rules (game_screen.fossil_requirement_first_word)
    # Enable/disable knob read by _rule_require_fossil_cell: whether to waive the
    # fossil requirement while the opening word of the game hasn't cleared yet.
    def _rule_fossil_skip_first_word(self):
        """Waive the fossil requirement until the first word clears this game."""
        return self._words_cleared_this_game == 0

    def _rule_fossil_no_skip(self):
        """Never waive: the fossil requirement holds from the very first word."""
        return False

    # --- Fossil start-of-game seeding (game_screen.fossil_requirement_first_word)
    # Companion to the waive predicate above, driven by the same knob: what (if
    # anything) to fossilize at game start so the fossil requirement is satisfiable
    # from word one without waiving it. Called once per game in _start_new_game.
    def _rule_fossil_seed_none(self):
        """No start-of-game fossil (the skip-first-word / no-skip variants)."""
        pass

    def _rule_fossil_seed_center(self):
        """Fossilize one random occupied cell at, or edge-adjacent to, the board
        center at game start. The candidate set is the center cell plus its
        immediate neighbors (four on square, six on hex -- physical adjacency);
        empty candidates are skipped so the seed always lands on a real gram. With
        a fossil present from the start, the fossil requirement can hold from the
        very first word (this variant pairs with rule_fossil_no_skip's never-waive
        predicate). The draw uses the session RNG, so a replay reproduces the same
        seeded cell. No-op if no candidate near the center carries a gram (e.g. an
        empty opening board), leaving the requirement unsatisfiable until a fossil
        appears -- a config combination the player owns."""
        cx, cy = self._board.center_cell()
        candidates = [(cx, cy)] + self._board.neighbors(cx, cy)
        occupied = [c for c in candidates if self._board.gram_at(*c) is not None]
        if not occupied:
            return
        cell = random.choice(occupied)
        self._fossilize_cell(cell)
        L.log_06005(cell)

    # --- idea-belt stocking categories (idea_belt.stock_category_weight.*) --
    # WHICH pictures the right-pane idea belt stocks its ring with. One rule per
    # stocking CATEGORY (models.idea_pool.STOCK_CATEGORIES); every category
    # carrying weight is scanned once per game by _stock_idea_belt, once the
    # opening formation is down (the earliest moment there is a board to scan).
    # Each takes the deck's words and returns the subset that category matches on
    # the board; the pool then blends the categories in their configured weights,
    # with the blind category taking whatever is left.
    #
    # NOTE these are the game's one deliberate exception to the
    # no-word-availability-hints rule: a stocked belt is telling a young player
    # "these are things you can make right now". That is the point of belt mode; it
    # is why no non-belt mode gives these any weight, and why weight on the blind
    # category keeps some un-makeable pictures on the conveyor so the belt never
    # reads as a complete solution list.
    def _rule_idea_stock_category_spellable_any_gram(self, words):
        """Target the deck words the board's GRAMS can supply -- can `word` be cut
        into a sequence of grams the board actually carries, ignoring where those
        cells sit. The loose sense of "available": it holds in the type-anywhere
        modes (constellation / omniswap) exactly, and elsewhere reads as "the
        letters are out there", which survives a sparse opening board that an
        adjacency scan would find nearly nothing on.

        Reuses the same gram gathering and matcher the F3 word sample and the
        constellation end-detection run on, over the DECK's words (a few hundred)
        rather than the dictionary, with the limit set high enough to take every
        match rather than a sample."""
        grams = self._constellation_usable_grams()
        if not grams:
            return []
        return sample_formable_words(words, grams, self._constellation_accept(),
                                     len(words))

    def _rule_idea_stock_category_spellable_multigram(self, words):
        """Target the deck words that USE the board's multigrams: same gram-supply
        cut as spellable_any_gram, but only counting a word when one of the cuts
        the board can actually supply leans on the fat cells -- at least one 3+
        letter gram, or at least two digrams (starting_coverage.uses_multigrams).

        This is the belt's teaching category. Players new to the game decompose
        words letter by letter and never think to read SHARK as SH + ARK, so the
        big cells sit on the board unused; a ring of pictures whose words only work
        THROUGH those cells is what gets the idea going. It is deliberately
        narrower than spellable_any_gram (every match here is also a match there),
        which is why it claims its words first when both categories are stocked."""
        grams = self._constellation_usable_grams()
        if not grams:
            return []
        return sample_multigram_words(words, grams, self._constellation_accept(),
                                      len(words))

    def _rule_idea_stock_category_spellable_by_path(self, words):
        """Target the deck words the board can spell for real, by PATH: stage-1
        pathfinding, filtered to the deck. The strict sense of "available" -- every
        stocked picture has a walkable word on the board right now -- which also
        makes it the strongest hint, and on a sparse opening board it can come back
        nearly empty (the blind slots then fill the ring). One full pathfind, once
        per game, at formation time."""
        wanted = set(words)
        return sorted({fw.word for fw in self._find_words() if fw.word in wanted})

    def _stock_idea_belt(self):
        """Stock this game's belt ring, after the opening formation has filled the
        board. A no-op when the belt is off or when no stocking category carries
        weight (the belt has already dealt itself a blind ring). Runs one scan per
        weighted category -- each is a few-hundred-word pass, once per game.
        See views/idea_belt.restock."""
        if self._idea_belt is None:
            return
        rules = CONFIG.get("rules", {})
        words = self._idea_belt.deck_words()
        stock = {}
        for category, rule in self._idea_stock_category_rules.items():
            key = "idea_belt.stock_category_weight." + category
            if float(rules.get(key, 0)) > 0:
                stock[category] = rule(words)
        if not stock:
            return
        matched = {}
        for category, found in stock.items():
            matched[category] = len(found)
        L.log_06010(len(words), matched, self._idea_belt.restock(stock))

