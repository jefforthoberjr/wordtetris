# ONGOING BUGS

Unresolved bugs under active investigation, with the evidence gathered so far.
Each entry records what is CONFIRMED, what is DISPROVEN, the leading hypothesis,
and candidate fixes not yet applied. Update the disproven/confirmed lists as new
session logs come in rather than starting over.

---

## BUG: Alt-tab freeze — clicks stop responding (macOS)

**Status:** open. Instrumentation added (see below); root cause not yet fixed.

### Symptom
After several Cmd+Tab (alt-tab) switches away from and back to the game during a
session, the window stops responding to clicks — clicking board cells does
nothing. Reported case: trying to click cells near the bottom-right of the board
at the end of a session, nothing happened. The app then has to be force-quit.

### Evidence — session `2026-07-05T21-22-08_210b`
(hex grid, `rule_mode_omniswap_vs_timer`, 1600x1200 physical @2.0x, pyglet 2.1.14)

Facts established from the log:

- `session_log.emit()` flushes every line, so every event the app *processed* is
  on disk — nothing is lost to buffering.
- `on_mouse_press` logs its `[20003]` line unconditionally as its first action
  (`game_screen.py`). The failing end-of-session clicks produced **zero** log
  lines → those clicks never reached the app's handler. This is an
  **event-delivery failure, not a coordinate or game-logic bug**.
- The log has **no `# ===== END =====` footer** (`session_log.close()` was never
  called) → the app was force-killed, consistent with a frozen window.
- Focus timeline (`[00010]`): `150.010` resignKey → `153.461` becomeKey (clean
  round trip), then `248.479` resignKey → **no becomeKey ever**. pyglet dispatches
  `on_activate` from Cocoa `windowDidBecomeKey_` and `on_deactivate` from
  `windowDidResignKey_` (`pyglet/window/cocoa/pyglet_delegate.py`). So after the
  last alt-tab the window's key-status handshake was left half-done.
- Despite that, mouse AND keyboard events kept working from 255–259s (a full
  word, LEST, was played). Then at **259.921s everything went silent at once** —
  no mouse, no keys, no focus events, no shutdown. Signature of the **main event
  loop / Cocoa event pump stalling**, not of a stuck key-status alone.

### CONFIRMED
- It is a freeze / event-delivery stall, not a misplaced click.
- The stall follows a botched key-window focus handshake after alt-tab (a
  `resignKey` with no matching `becomeKey`).

### DISPROVEN (for this manifestation)
- **Retina coordinate-scale desync.** The earlier working theory (see the
  `main.py` focus-logging comment and `log_codes.py` log_00010/00011 comments)
  was that an alt-tab / Space switch changes the physical/point pixel ratio and
  misplaces clicks onto the wrong cell. In this session the scale stayed `2.0`
  the entire time (all three `[00010]` lines report `@2.0x`, no `[00011]` resize
  at all), and the coordinate math is provably correct: e.g. `cell_center(7,0)` =
  (995.9, 150) and the click `(1000,150)` resolved to cell `7,0` dead-center;
  bottom-row clicks like `(757,1005)→(5,6)` also mapped correctly earlier in the
  same session. Clicks were not misplaced — they stopped being delivered.

### Leading hypothesis
The pyglet main loop stalls after the window is occluded / re-focused via
alt-tab. Prime suspect: a **blocking buffer-swap (vsync flip) on an occluded
window** — macOS pauses the display link for a hidden/occluded window, and with
vsync on the flip inside the draw step can block, freezing the whole loop
(clock-scheduled `update_game_tick` included). Intermittent, matching that some
alt-tabs recovered fine and one did not.

### Candidate fixes — NOT yet applied
- **Disable vsync in the main game**, driving redraws from the clock, the way
  `replay.py` already does (`win.set_vsync(False)`). Removes the vsync-flip block
  mechanism. Deferred by request (real rendering-behavior change; would be made a
  `config.yaml` toggle preserving vsync-on). *This is the most promising next
  step when we revisit.*
- **Reassert key status on focus regain**: call `window.activate()`
  (`NSApp.activateIgnoringOtherApps_` + `makeKeyAndOrderFront_`) from an
  `on_show` / `on_expose` handler so a botched alt-tab return can't leave the
  window stuck.

### Instrumentation added to help pin it (applied 2026-07-05)
- **`on_close` → clean session close** (`main.py`): OS window-close now calls
  `log_00002` + `session_log.close()`, so a *clean* quit leaves an
  `# ===== END =====` footer. A log ending WITHOUT the footer = force-kill /
  freeze. (Caveat: Cmd+Q via the Cocoa menu, `terminate_`, still bypasses this.)
- **Heartbeat `[00012]`** (`main.py` `update_game_tick`): a liveness line emitted
  every ~2s while a session is open. How to read the next occurrence:
  - Heartbeats **stop** with no END footer → the whole loop froze; the last
    heartbeat timestamp localizes the freeze to within ~2s.
  - Heartbeats **continue** past the last input, then the log ends → the clock is
    alive but event *delivery* died (points away from a vsync flip-block, toward
    Cocoa event routing / key-window).

### Next time it happens
Grab the new session log and check: (1) is there an END footer? (2) when does the
last `[00012]` heartbeat land relative to the last input and the last `[00010]`
focus line? That single comparison decides between "loop froze" and "events
stopped being delivered," which selects between the two candidate fixes above.
