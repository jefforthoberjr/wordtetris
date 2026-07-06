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


# Window/environment events. Originally logged on the theory that a macOS focus
# or Space change desyncs the Retina coordinate scale (window.width is physical
# here) and misplaces clicks. That theory is DISPROVEN for the alt-tab freeze
# seen so far (scale stayed constant, clicks were correct but stopped being
# delivered) -- see ONGOING_BUGS.md. Still logged: the focus timeline is the key
# to that bug (a resignKey with no matching becomeKey precedes the freeze).
# Pair with log_20003's `cell` field and the log_00012 heartbeat.
def log_00010(active, width, height, scale):
    """Window focus changed: `active` True on gaining focus (on_activate), False
    on losing it (on_deactivate). Records the physical size and pixel/point ratio
    at that instant, so a focus-triggered coordinate desync is visible here."""
    state = "focus_gained" if active else "focus_lost"
    session_log.emit(10, f"window {state} ({width}x{height} @{scale}x)",
                     active=active, width=width, height=height, scale=scale)


def log_00011(width, height, scale):
    """The window resized (on_resize): new physical size + pixel ratio. On a
    non-resizable window a scale change here is the fingerprint of the Retina
    point/pixel desync that misplaces clicks; see log_00010."""
    session_log.emit(11, f"window resized ({width}x{height} @{scale}x)",
                     width=width, height=height, scale=scale)


def log_00012(count):
    """Periodic liveness heartbeat from the update tick (~every 2s while a session
    is open). Diagnoses the alt-tab freeze (ONGOING_BUGS.md): if heartbeats stop
    with no session-end footer the whole loop froze, and the last heartbeat's
    timestamp localizes it; if heartbeats keep coming after the last input then
    the clock is alive and only event delivery died. `count` just orders them --
    the line's own timestamp carries the timing."""
    session_log.emit(12, "heartbeat", count=count)


# macOS "have to click twice" probe (ONGOING_BUGS.md). Cocoa sends the view
# acceptsFirstMouse: ONLY when a mouseDown lands on a NON-active window; the
# default answer NO swallows that click to activate the window, so it never
# reaches on_mouse_press and produces no log_20003 -- the swallowed click is
# otherwise invisible. src/macos_first_mouse_probe.py adds the selector (still
# answering NO, so behavior is unchanged) purely to emit this line. Each one is a
# swallowed click; line up its timestamp with the log_00010 focus timeline and the
# player's "click twice" report. Only fires on macOS with logging.first_mouse_probe.
def log_00013(x, y, app_active):
    """A swallowed first-mouse click: `x,y` is the event's window-point location,
    `app_active` is NSApp.isActive() at that instant (was the app already active
    but the window not key, or the whole app inactive?)."""
    session_log.emit(13, f"first-mouse probe ({x},{y}) app_active={app_active}",
                     x=x, y=y, app_active=app_active)


# macOS window-level input probe (ONGOING_BUGS.md "click twice", round 2). pyglet
# pumps its own Cocoa loop and routes EVERY event through the window's sendEvent:,
# so this fires for every left-mouse-down that reaches the app -- the one
# chokepoint independent of which view hit-tests or whether the click is swallowed
# (unlike log_00013, which only fires on the acceptsFirstMouse: path and missed
# the real swallow). Read it against log_20003 (the app-level click):
#   * [00014] present, no matching [20003] after it -> the OS delivered the click
#     but pyglet's view dispatch dropped it (an in-app bug, no macOS-only fix).
#   * a click you KNOW you made with NO [00014] at all -> the OS never delivered it
#     to the app -> genuinely OS-level (an absence, so it leans on your report +
#     the surrounding [20003]/[00012] timestamps to bracket when).
# Coords are window POINTS (bottom-left origin), NOT the backing-pixel board coords
# log_20003 records -- they differ by the Retina scale, so correlate on TIMESTAMP,
# not on x,y. Only fires on macOS with logging.first_mouse_probe.
def log_00014(x, y, key_window, app_active):
    """A left-mouse-down reached the window's sendEvent:. `x,y` = window-point
    location; `key_window` = was this the key window; `app_active` = NSApp.isActive
    at that instant (distinguishes app-inactive from window-not-key)."""
    session_log.emit(14, f"window mouse-down ({x},{y}) key_window={key_window} "
                         f"app_active={app_active}",
                     x=x, y=y, key_window=key_window, app_active=app_active)


# Periodic performance snapshot, emitted with each ~2s heartbeat while a session is
# open (main.py update_game_tick), sourced from debug_panel's timing taps so it
# works whether or not the debug panel is visible. Diagnoses the "click twice"
# drops (ONGOING_BUGS.md, round 3): the OS discards mouse-downs when the app
# services its Cocoa event port too slowly, so if update_max / draw_max climb over
# a long session -- starving that port -- this is the smoking gun. Line up a spike
# here with a gap in the [00014] window mouse-downs. update/draw are (min,avg,max)
# ms over the window; fps/ups are per-second; ram_mb is process RSS; vram_mb is
# None on integrated GPUs. Gated on logging.perf_metrics.
def log_00015(update_ms, draw_ms, fps, ups, idle_pct, ram_mb, vram_mb):
    """`update_ms` and `draw_ms` are (min, avg, max) tuples in milliseconds."""
    umin, uavg, umax = update_ms
    dmin, davg, dmax = draw_ms
    vram_s = f"{vram_mb:.0f}" if vram_mb is not None else "n/a"
    session_log.emit(
        15,
        f"perf upd {umin:.1f}/{uavg:.1f}/{umax:.1f}ms "
        f"drw {dmin:.1f}/{davg:.1f}/{dmax:.1f}ms "
        f"fps={fps} ups={ups} idle={idle_pct:.0f}% ram={ram_mb:.0f}MB vram={vram_s}",
        update_min=round(umin, 3), update_avg=round(uavg, 3), update_max=round(umax, 3),
        draw_min=round(dmin, 3), draw_avg=round(davg, 3), draw_max=round(dmax, 3),
        fps=fps, ups=ups, idle_pct=round(idle_pct, 1), ram_mb=round(ram_mb, 1),
        vram_mb=(round(vram_mb, 1) if vram_mb is not None else None))


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


def log_20003(x, y, button, phase, cell):
    """A mouse button was pressed at window pixel (x, y). `button` is the pyglet
    button name (LEFT / RIGHT / MIDDLE). `cell` is the board cell that pixel
    resolves to ((cx,cy) tuple, or None off-board / no board yet), logged beside
    the raw pixel so a coordinate-scale desync -- a click no longer landing on
    the cell under the cursor -- is visible directly in the log."""
    cell_s = "-" if cell is None else f"{cell[0]},{cell[1]}"
    session_log.emit(20003, f"{button} click ({x},{y}) -> cell {cell_s}",
                     x=x, y=y, button=button, phase=phase, cell=cell_s)


def log_20004(cell, old, new, reason):
    """Outcome of a right-click gram-manipulate (game_screen._handle_gram_
    manipulate). `cell` is the board cell the MOUSE resolved to (None off-board),
    `old`/`new` the gram before/after, `reason` one of applied / off_board /
    fossilized / empty / rule_noop. log_20003 is the raw click; this says what the
    game DID with it, so a no-op (wrong cell under the mouse, fossilized, empty)
    is diagnosable from the log instead of by re-simulating."""
    cell_s = "-" if cell is None else f"{cell[0]},{cell[1]}"
    detail = f": {old}->{new}" if new is not None else ""
    session_log.emit(20004, f"gram-manip {reason} at {cell_s}{detail}",
                     cell=cell_s, old=old or "-", new=new or "-", reason=reason)


def log_20005(action, cell, other=None):
    """Outcome of an omniswap board click (game_screen.mode =
    rule_mode_omniswap_vs_timer). `action` is picked / canceled / swapped /
    word_piece / invalid_target / ignored; `cell` the click's board cell; `other`
    the pick-cursor's held cell on a swap (the source), else '-'. Makes the two-
    click swap's target model -- which cell the game thinks you're acting on --
    visible, the gap that hid the right-click doubling confusion."""
    cell_s = "-" if cell is None else f"{cell[0]},{cell[1]}"
    other_s = "-" if other is None else f"{other[0]},{other[1]}"
    session_log.emit(20005, f"omniswap {action} at {cell_s}",
                     action=action, cell=cell_s, other=other_s)


# --- 3xxxx  word pipeline ----------------------------------------------------
def log_30001(word):
    """A word was submitted in the interactive SELECT phase (the normalized,
    upper-cased typed word). Auto-select has no submit -- its clears log as
    log_30002 only."""
    session_log.emit(30001, f"submitted {word}", word=word)


def log_30002(word, path, variation, is_new, is_obscure=False, points=0):
    """A word was cleared from the board (the single sink for every clear:
    interactive submit, phase-end batch, and auto-select). `path` is its cells,
    `variation` the gram grouping recorded, `is_new` whether it was new to the
    player's lifetime dictionary, `is_obscure` whether it was valid only via the
    obscure tier (a new obscure word lists orange), `points` the score the word
    earned (see models/scoring.py)."""
    cells = ";".join(f"{x},{y}" for (x, y) in path)
    tag = " (new)" if is_new else ""
    if is_obscure:
        tag += " (obscure)"
    session_log.emit(30002, f"cleared {word} (+{points})" + tag,
                     word=word, cells=cells, variation=variation,
                     new=is_new, obscure=is_obscure, points=points)


def log_30003(word, reason):
    """A submission was rejected. `reason` is a stable key (not_in_dictionary /
    not_on_board / too_short / not_involved / already_cleared /
    already_selected_one_way / every_way_selected) -- the incorrect-submission
    signal for analysis."""
    session_log.emit(30003, f"rejected {word}", word=word, reason=reason)


def log_30004(word, path, index, total):
    """The player confirmed a spelling in the "select which one" chooser (a game_
    screen.clear_disambiguation cycle rule): the word had `total`
    clearable paths and the highlighted one (`index`, 0-based) was chosen. `path`
    is the chosen cells. Purely descriptive -- a replay reproduces the choice from
    the logged cycle keys (log_20001), so this is for human/analysis reading; the
    clear itself still logs as log_30002."""
    cells = ";".join(f"{x},{y}" for (x, y) in path)
    session_log.emit(30004, f"chose spelling {index + 1}/{total} for {word}",
                     word=word, cells=cells, index=index, total=total)


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


# --- 5xxxx  end state / results & scoring milestones -------------------------
def log_50002(bonus, cells):
    """The whole board became filled (game_screen.fill_board), awarding the
    one-time fill bonus. `bonus` is the points added; `cells` the board-cell
    count that were filled. A mid-game scoring milestone, not an end state."""
    session_log.emit(50002, f"board filled: +{bonus} ({cells} cells)",
                     bonus=bonus, cells=cells)


def log_50001(result, words, obstacles_left, missions_left, score=0):
    """The game's final tally, emitted just before the session-end line. `result`
    is the end label (VICTORY / FINISHED); `score` is the final point total; the
    rest are the closing board state for cross-session analysis."""
    session_log.emit(50001, f"result {result}: {words} words cleared, {score} points",
                     result=result, words=words,
                     obstacles_left=obstacles_left, missions_left=missions_left,
                     score=score)


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


def log_06004(seconds, stats):
    """The starting-coverage enumeration finished (game_screen.starting_coverage_
    dictionary = on): the blocking pass that wrote sessions/<id>.coverage.csv.
    `seconds` is its wall-clock cost -- a replay re-reads this and simulates the
    delay (scaled) WITHOUT recomputing or rewriting the file. `stats` carries the
    word / formable / grouping counts for cross-board analysis."""
    session_log.emit(6004,
                     f"starting coverage: {stats['covered']}/{stats['words']} words "
                     f"formable ({stats['combos']} groupings) in {seconds:.3f}s",
                     seconds=round(seconds, 3), words=stats["words"],
                     covered=stats["covered"], combos=stats["combos"])


def log_06003(piece):
    """A live piece dealt into play (jigsaw spawn / word-piece swap): its type
    and the cells + grams it carries at spawn. The player-pool twin of the
    formation deal in log_06002 -- this is where the upcoming letters are recorded."""
    cells = [(gx, gy, gram) for (gx, gy, _cell, _label, gram, _overlay) in piece.get_cell_data()]
    spec = ";".join(f"{x},{y}:{_gram_text(g)}" for (x, y, g) in cells)
    session_log.emit(6003, f"{_piece_type_name(piece.piece_type)} piece spawned",
                     type=_piece_type_name(piece.piece_type), cells=spec)
