from config import CONFIG


class Scorer:
    """Running point total for one game, plus the per-word scoring rule.

    Config-driven (the top-level `scoring:` block in config.yaml): every
    component is an independently tunable weight, so the point rules can be
    playtested by editing the YAML without touching code. The scorer is fed
    plain FACTS about a cleared word -- counts GameScreen already resolved
    against its cell-kind sets (obstacle / mission / sand-timer / fossilized) --
    so it stays decoupled from the board; see score_word_rule.

    Board-level bonuses (whole-board fill, seconds left at game end) are separate
    events GameScreen adds via add_bonus; they are not part of a word's score.
    Chunk 2 wires those callers -- the seam lives here so the running total stays
    the single source of truth.
    """

    def __init__(self):
        cfg = CONFIG.get("scoring", {})
        self._enabled = cfg.get("enabled", True)
        self._word_base = cfg.get("word_base", 0)
        self._per_cell = cfg.get("per_cell", 0)
        self._per_letter = cfg.get("per_letter", 0)
        self._per_extra_gram_letter = cfg.get("per_extra_gram_letter", 0)
        self._obstacle_cell_bonus = cfg.get("obstacle_cell_bonus", 0)
        self._mission_cell_bonus = cfg.get("mission_cell_bonus", 0)
        self._sand_timer_cell_bonus = cfg.get("sand_timer_cell_bonus", 0)
        self._fossil_reuse_bonus = cfg.get("fossil_reuse_bonus", 0)
        self._new_word_bonus = cfg.get("new_word_bonus", 0)
        self._total = 0

    @property
    def total(self):
        """The running point total for the current game."""
        return self._total

    def reset(self):
        """Zero the total for a new game."""
        self._total = 0

    def score_word_rule(self, word_length, gram_lengths, obstacle_cells,
                        mission_cells, sand_cells, fossil_reuse_cells, is_new):
        """Points for one cleared word; adds them to the running total and
        returns them (0 when scoring is disabled).

        `gram_lengths` is the letters-taken count per cell -- so len() is the
        cell count and each entry drives the longer-gram bonus (letters beyond
        the first in a cell). The *_cells args are how many of the word's cells
        are that kind; `is_new` is newness to the player's lifetime dictionary.
        """
        if not self._enabled:
            return 0
        points = self._word_base
        points += self._per_cell * len(gram_lengths)
        points += self._per_letter * word_length
        # Longer grams: every letter beyond the first in each cell.
        points += self._per_extra_gram_letter * sum(max(0, n - 1) for n in gram_lengths)
        points += self._obstacle_cell_bonus * obstacle_cells
        points += self._mission_cell_bonus * mission_cells
        points += self._sand_timer_cell_bonus * sand_cells
        points += self._fossil_reuse_bonus * fossil_reuse_cells
        if is_new:
            points += self._new_word_bonus
        self._total += points
        return points

    def add_bonus(self, points):
        """Add a board-level bonus (whole-board fill, end-of-game time left) to
        the running total and return it (0 when disabled). Chunk 2 wires the
        callers; kept here so the total stays the single source of truth."""
        if not self._enabled:
            return 0
        self._total += points
        return points
