"""Central registry of session-log codes.

Each event in the game is logged through a thin, inlined log_NNNNN() function
defined here and called at the event site, e.g. log_00324(...). The number is
the searchable handle: grep "00324" to find both its definition and every call.

Rules for codes:
  * Append-only. Once a number is allocated its meaning is fixed forever; never
    renumber or repurpose. Retire a code by leaving it defined and unused.
  * Static numeric ranges by category:
        0xxxx  session lifecycle / metadata
        1xxxx  phase transitions
        2xxxx  player input & piece moves
        3xxxx  word pipeline (found / submitted / cleared / errors)
        4xxxx  timers
        5xxxx  end state / results
        6xxxx  setup / random-source outcomes (formation, pool order, deals)

Each function does nothing but call session_log.emit(); emit() is a no-op when
no session is open or logging is disabled, so call sites never need to guard.
The header (metadata + embedded config) is written by session_log.start_session,
not by a code -- log_00001 marks the first line of the LOG body."""
import session_log


# --- 0xxxx  session lifecycle ------------------------------------------------
def log_00001():
    """First body line: a session/game has begun. The header above it already
    holds the config snapshot, seed, and window size."""
    session_log.emit(1, "session started", seed=session_log.current_seed())


def log_00002(reason):
    """Last body line: the game reached an end state. `reason` is the end label
    (e.g. VICTORY / FINISHED) or how the session was left."""
    session_log.emit(2, "session ended", reason=reason)


# --- 1xxxx  phase transitions ------------------------------------------------
def _phase_name(phase):
    return getattr(phase, "name", "NONE")


def log_10001(old_phase, new_phase):
    """A game-screen phase change (LOADING / MOVING / SELECTING / VICTORY). The
    `from`->`to` track that segments the log into turns for timing analysis."""
    session_log.emit(10001, f"phase {_phase_name(old_phase)}->{_phase_name(new_phase)}",
                     **{"from": _phase_name(old_phase), "to": _phase_name(new_phase)})


# --- 2xxxx  player input -----------------------------------------------------
# Raw input events, logged at the handler entry before any delegation, so they
# are the complete control stream a replay re-feeds (replay record #2). Mouse
# motion is deliberately not logged -- it fires continuously and only drives
# hover preview, which a replay can recompute. Symbols are decoded to names at
# the call site (it owns the pyglet import); these just fix the line format.
def log_20001(key, mods, phase):
    """A key was pressed. `key` is the pyglet symbol name (A, ENTER, LEFT...),
    `mods` the held modifiers ('' if none), `phase` the phase it arrived in."""
    msg = f"key {key}" + (f"+{mods}" if mods else "")
    session_log.emit(20001, msg, key=key, mods=mods or "-", phase=phase)


def log_20002(text, phase):
    """A character was typed (word entry). Logged with repr-safe whitespace so a
    space/newline stays one token."""
    shown = text.replace(" ", "_").replace("\n", "\\n").replace("\r", "\\r")
    session_log.emit(20002, f"text '{shown}'", text=shown, phase=phase)


def log_20003(x, y, button, phase):
    """A mouse button was pressed at window pixel (x, y). `button` is the pyglet
    button name (LEFT / RIGHT / MIDDLE)."""
    session_log.emit(20003, f"{button} click ({x},{y})",
                     x=x, y=y, button=button, phase=phase)


# --- 3xxxx  word pipeline ----------------------------------------------------
def log_30001(word):
    """A word was submitted in the interactive SELECT phase (the normalized,
    upper-cased typed word). Auto-select has no submit -- its clears log as
    log_30002 only."""
    session_log.emit(30001, f"submitted {word}", word=word)


def log_30002(word, path, variation, is_new):
    """A word was cleared from the board (the single sink for every clear:
    interactive submit, phase-end batch, and auto-select). `path` is its cells,
    `variation` the gram grouping recorded, `is_new` whether it was new to the
    player's lifetime dictionary."""
    cells = ";".join(f"{x},{y}" for (x, y) in path)
    session_log.emit(30002, f"cleared {word}" + (" (new)" if is_new else ""),
                     word=word, cells=cells, variation=variation, new=is_new)


def log_30003(word, reason):
    """A submission was rejected. `reason` is a stable key (not_in_dictionary /
    not_on_board / too_short / not_involved / already_cleared /
    already_selected_one_way / every_way_selected) -- the incorrect-submission
    signal for analysis."""
    session_log.emit(30003, f"rejected {word}", word=word, reason=reason)


# --- 4xxxx  timers -----------------------------------------------------------
# Per-tick countdown values are NOT logged (60/sec is pure noise); only the
# meaningful boundaries -- the clock being (re)set to full and hitting zero.
def log_40001(seconds):
    """The countdown was (re)set to its full length, in whole seconds (game
    start, or a per-phase reset returning to MOVING)."""
    session_log.emit(40001, f"timer set {seconds}s", seconds=seconds)


def log_40002(variant, action):
    """The countdown reached zero. `variant` is the timer rule (race / per_phase)
    and `action` what zero triggered (ended_game / forced_select)."""
    session_log.emit(40002, f"timer expired ({action})", variant=variant, action=action)


# --- 5xxxx  end state / results ----------------------------------------------
def log_50001(result, words, obstacles_left, missions_left):
    """The game's final tally, emitted just before the session-end line. `result`
    is the end label (VICTORY / FINISHED); the rest are the closing board state
    for cross-session analysis."""
    session_log.emit(50001, f"result {result}: {words} words cleared",
                     result=result, words=words,
                     obstacles_left=obstacles_left, missions_left=missions_left)


# --- 6xxxx  setup / random-source outcomes -----------------------------------
def _gram_text(gram):
    """Render one gram for a log field: '*' for a wild vowel, '_' for an empty
    cell, else its letters."""
    if gram is None:
        return "_"
    if gram.is_wild:
        return "*"
    return gram.text or "_"


def _piece_type_name(p_type):
    """Short name of a piece-type enum member (e.g. 'T'), falling back to str."""
    return getattr(p_type, "name", str(p_type))


def log_06001(kind, types):
    """The resolved order of a piece pool. `kind` is which pool (player /
    obstacle / mission); `types` is the piece-type sequence the pool will deal."""
    order = ",".join(_piece_type_name(t) for t in types)
    session_log.emit(6001, f"{kind} pool order ({len(types)} pieces)",
                     kind=kind, order=order)


def log_06002(kind, cells):
    """One formation piece dropped onto the opening board. `kind` is the source
    (obstacle / mission / fill); `cells` is a list of (x, y, gram) -- the exact
    starting cells and grams, the raw material a replay reconstructs the opening
    board from. Wild vowels log as '*'."""
    spec = ";".join(f"{x},{y}:{_gram_text(g)}" for (x, y, g) in cells)
    session_log.emit(6002, f"{kind} piece placed ({len(cells)} cells)",
                     kind=kind, cells=spec)


def log_06003(piece):
    """A live piece dealt into play (jigsaw spawn / word-piece swap): its type
    and the cells + grams it carries at spawn. The player-pool twin of the
    formation deal in log_06002 -- this is where the upcoming letters are recorded."""
    cells = [(gx, gy, gram) for (gx, gy, _cell, _label, gram) in piece.get_cell_data()]
    spec = ";".join(f"{x},{y}:{_gram_text(g)}" for (x, y, g) in cells)
    session_log.emit(6003, f"{_piece_type_name(piece.piece_type)} piece spawned",
                     type=_piece_type_name(piece.piece_type), cells=spec)
