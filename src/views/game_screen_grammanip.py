"""Cell gram manipulation: right-clicking a board cell to reshape its gram.

Extracted from views/game_screen.py to keep that file under the 2000-line limit.
Two halves live here and belong together:

  * The RULE FUNCTIONS (module level, game_screen.rightclick_*) -- pure
    text -> text transforms, one config slot per vowel/consonant SHAPE, plus the
    shape classifier that routes a gram to its slot.
  * GramManipMixin -- the dispatcher those rules are wired into, mixed into
    GameScreen so it runs with GameScreen's `self` (board, config rules, the hunt
    highlight) exactly as before.

The rule functions stay module-level (not methods) because they are pure and are
registered in _GRAM_MANIP_RULES by name; GameScreen imports that table and
rule_rightclick_none for its __init__ wiring.
"""

from config import select_rule
from models.gram import Gram
import log_codes as L


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

def rule_vv_collapse(text):
    """VV digram (a doubled vowel, EE): collapse to the single letter, VV -> V
    (EE -> E). The forward V -> VV lives in the unigram slot
    (rule_unigram_double), so the two together make the E <-> EE toggle -- the
    vowel mirror of rule_cc_collapse. Distinct vowels (EA) have nothing to dedup,
    so it returns None and the cell is left untouched."""
    if len(text) == 2 and text[0] == text[1]:
        return text[0]                 # EE -> E
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
    "rule_vv_collapse": rule_vv_collapse,
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

class GramManipMixin:
    """Right-click gram manipulation for GameScreen (see module docstring)."""

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

    # Right-click TARGET rules -- which of the two things under the cursor a
    # gram-manipulate click may reshape. They are independent slots (both on is
    # the normal setup) because they are different game verbs: reshaping a
    # SETTLED cell edits the board you already committed to, while reshaping the
    # ACTIVE piece is part of choosing what to commit -- the difference between
    # fixing the board and aiming the piece you are about to drop.
    #
    # game_screen.rightclicks_on_placed_piece
    def _rule_rightclicks_actionable_on_placed_piece(self):
        """Right-click reshapes the gram in a SETTLED board cell (the original
        behavior, and the only one before the active-piece slot existed)."""
        return True

    def _rule_rightclicks_inert_on_placed_piece(self):
        """Right-click leaves settled board cells alone -- once a gram is placed
        its letters are final."""
        return False

    # game_screen.rightclicks_on_active_piece
    def _rule_rightclicks_actionable_on_active_piece(self):
        """Right-click reshapes the gram in the LIVE (unplaced) piece under the
        cursor, so a doubling can be applied BEFORE the piece is committed -- the
        F of a live SINGLE becomes FF while you are still choosing where it goes
        (SHERI + FF), instead of only after it lands."""
        return True

    def _rule_rightclicks_inert_on_active_piece(self):
        """Right-click never touches the live piece -- gram-manipulation is a
        board-only verb (the original behavior)."""
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
        """Right-click a cell during MOVING (controls.yaml mouse.gram_manipulate):
        transform its gram via the game_screen.rightclick_* rule for its
        vowel/consonant SHAPE (see _apply_shape_rule) or wild-ness. A rule
        returning None (e.g. rule_rightclick_none, or a shape with no rule) is a
        no-op. Mode-agnostic -- the MOVING modes never see this button.

        TWO possible targets share the cursor, each with its own on/off slot:
        the LIVE piece (game_screen.rightclicks_on_active_piece) and the SETTLED
        board cell (game_screen.rightclicks_on_placed_piece). The live piece wins
        when both could match, because it is drawn ON TOP of the board -- the
        player is right-clicking the letter they can see. In practice the board
        cell under a live piece is empty anyway (a piece's cells only join the
        board when it is placed), which is exactly why an active-piece right-click
        used to read as 'empty' and do nothing.

        Empty and fossilized cells are left alone, the same as the swap rules."""
        cell = self._board.cell_at(x, y)
        if cell is None:
            L.log_20004(None, None, None, "off_board")
            return
        # The live piece first -- it is on top, and it hides the board cell under
        # it. Returns True once it owns the click (even for a no-op), so a click
        # on the piece never falls through to the cell beneath it.
        if self._rightclick_on_active_piece and self._manipulate_active_piece(cell):
            return
        if not self._rightclick_on_placed_piece:
            L.log_20004(cell, None, None, "placed_target_off", target="placed")
            return
        if self._is_fossilized(cell):
            L.log_20004(cell, None, None, "fossilized", target="placed")
            return
        gram = self._board.gram_at(*cell)
        if gram is None:
            L.log_20004(cell, None, None, "empty", target="placed")
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
            L.log_20004(cell, gram.text, None, "rule_noop", target="placed")
            return
        self._board.relabel_cell(cell[0], cell[1], new_text)
        L.log_20004(cell, gram.text, new_text, "applied", target="placed")
        # The gram changed under an active hunt: re-light so the new letters
        # reflect the typed word (relabel_cell already re-synced the overlay).
        if self._moving_side_pane.hunt_text():
            self._refresh_hunt_highlight()

    def _manipulate_active_piece(self, cell):
        """Right-click target #1 (game_screen.rightclicks_on_active_piece): the
        LIVE piece. If the piece currently under player control covers `cell`,
        reshape THAT cell's gram with the same shape rules the board path uses and
        return True -- the click is consumed, no-op or not, since the piece sits on
        top of the board cell. Returns False when there is nothing to act on (no
        live piece, the piece is already placed or hidden, or it doesn't cover
        this coordinate), leaving the click to the board path.

        The piece carries its own grams and labels until it settles, so the edit
        goes through piece.relabel_gram_at rather than board.relabel_cell; a WILD
        cell renders as a sprite with no letters to rewrite, so it refuses."""
        piece = self._current_piece()
        if piece is None or piece.placed or not getattr(piece, "visible", True):
            return False
        index = piece.cell_index_at(*cell)
        if index is None:
            return False
        gram = piece.get_cell_data()[index][4]
        if gram.is_wild:
            new_text = self._rightclick_rules["vowelwild"](gram.text)
        elif len(gram) == 1:
            new_text = self._rightclick_rules["unigram"](gram.text)
        else:
            new_text = self._apply_shape_rule(
                self._piece_cvk_key(piece, index), gram.text)
        if new_text is None:
            L.log_20004(cell, gram.text, None, "rule_noop", target="active")
            return True
        if not piece.relabel_gram_at(cell[0], cell[1], new_text):
            # Only a wild (sprite) cell refuses at this point; record it rather
            # than silently dropping the click.
            L.log_20004(cell, gram.text, None, "piece_refused", target="active")
            return True
        L.log_20004(cell, gram.text, new_text, "applied", target="active")
        # Same re-light as the board path: the piece's letters feed the hunt
        # highlight too, and relabel_gram_at already re-texted its overlay.
        if self._moving_side_pane.hunt_text():
            self._refresh_hunt_highlight()
        return True

    def _piece_cvk_key(self, piece, index):
        """The CVK front/back alternation key for a LIVE piece cell. Board cells
        key by coordinate, but a live piece MOVES, so keying it that way would
        scramble the alternation as the player slides it around -- key it by cell
        INDEX instead. The piece slots are dropped as soon as a different piece
        becomes live, so a fresh piece starts from the default 'back' double
        rather than inheriting its predecessor's side."""
        if self._cvk_piece is not piece:
            self._cvk_piece = piece
            for key in [k for k in self._cvk_double_side if k[0] == "piece"]:
                del self._cvk_double_side[key]
        return ("piece", index)

    def _apply_shape_rule(self, cvk_key, text):
        """Route a right-click on a 2+ letter gram to its shape's config slot
        (see _gram_manip_family). `cvk_key` identifies the cell for the ONE
        stateful rule below -- a board coordinate for a settled cell, or
        ('piece', index) for a live piece cell (see _piece_cvk_key); no other
        shape reads it. cc/cv/vc/vv/ck own the digrams (and the doubled
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
                return rule(text, self._advance_cvk_side(cvk_key))
            return rule(text)          # 4-letter collapse; side is irrelevant
        return self._rightclick_rules[family](text)

    def _advance_cvk_side(self, cell):
        """Pick which consonant the next CVK double touches, flipping from the
        side this cell doubled last so repeated doubles alternate MMER/MERR. A
        fresh cell defaults to 'back' (MER -> MERR), the corpus-favored double."""
        side = "front" if self._cvk_double_side.get(cell) == "back" else "back"
        self._cvk_double_side[cell] = side
        return side
