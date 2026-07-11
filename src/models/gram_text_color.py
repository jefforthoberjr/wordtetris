from config import CONFIG, select_rule, get_color

# --- cell glyph color rules (board.cell_text_color) ----------------------
# Recolor each cell's gram GLYPHS to hint its POTENTIAL point value: a plain
# color for low-value grams grading toward a rich accent for high-value ones.
# The per-gram value reuses the scoring weights (the `scoring:` block) so the
# hint tracks the same knobs that actually award points. Selected by the YAML
# key board.cell_text_color; add a rule here + register it below to try a new
# hinting idea (this is the first: black -> dark gold by gram length/value).
# Rule functions take the cell's Gram and return an (r, g, b, a) color.

# Longest gram a cell can hold (quadgram); the gradient's full-accent end. A
# gram this long maps to the high color, a unigram to the plain color, and the
# in-between lengths interpolate -- so the hint is stable per gram regardless of
# what lengths happen to be on the board.
_GRADIENT_REF_MAX_LEN = 4


def _gram_score_value(letters):
    """The part of a cell's score that VARIES with its gram: per_letter for every
    letter plus per_extra_gram_letter for each letter beyond the first (the same
    weights Scorer.word_points_rule uses per cell). The constant per_cell /
    word_base terms are omitted -- they shift every cell equally, so they don't
    change the gradient. `letters` is the gram's letter count."""
    cfg = CONFIG.get("scoring", {})
    per_letter = cfg.get("per_letter", 0)
    per_extra = cfg.get("per_extra_gram_letter", 0)
    return per_letter * letters + per_extra * max(0, letters - 1)


def _score_fraction(letters):
    """Map a gram's letter count to a 0..1 position on the value gradient: 0 at a
    unigram's value, 1 at a full quadgram's. Returns 0 when the scoring weights
    make length irrelevant (no range to grade) or scoring is off, so the gradient
    gracefully collapses to the plain color."""
    if not CONFIG.get("scoring", {}).get("enabled", True):
        return 0.0
    lo = _gram_score_value(1)
    hi = _gram_score_value(_GRADIENT_REF_MAX_LEN)
    if hi <= lo:
        return 0.0
    t = (_gram_score_value(letters) - lo) / (hi - lo)
    return max(0.0, min(1.0, t))


def rule_cell_text_plain(gram):
    """No score hint (default): every gram uses the flat board.cell_text color --
    the original behavior, kept for restoring."""
    return get_color("board.cell_text")


def rule_cell_text_score_gradient(gram):
    """Grade each gram's glyph color from board.cell_text_low_value toward
    board.cell_text_high_value by its potential points -- longer, higher-scoring
    grams read richer (black -> dark gold by default). Alpha follows the low
    color."""
    low = get_color("board.cell_text_low_value")
    high = get_color("board.cell_text_high_value")
    t = _score_fraction(len(gram))
    rgb = tuple(round(low[i] + (high[i] - low[i]) * t) for i in range(3))
    alpha = low[3] if len(low) > 3 else 255
    return rgb + (alpha,)


# Active cell-glyph color rule, chosen by the YAML key board.cell_text_color.
_CELL_TEXT_COLOR_RULES = {
    "rule_cell_text_plain": rule_cell_text_plain,
    "rule_cell_text_score_gradient": rule_cell_text_score_gradient,
}


def cell_text_color(gram):
    """Glyph color for `gram`'s cell via the active board.cell_text_color rule.
    The single place both the square and hex pieces call, so the hint stays
    swappable from one YAML key. The rule is resolved per call (not cached at
    import) so a game mode's board.cell_text_color override takes effect: this
    module is imported before apply_game_mode swaps CONFIG, so an import-time
    binding would freeze the base config's rule -- see apply_game_mode."""
    return select_rule("board.cell_text_color", _CELL_TEXT_COLOR_RULES)(gram)
