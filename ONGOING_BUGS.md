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

---

## BUG: "Have to click twice" — first click swallowed (macOS)

**Status:** open. Root cause identified with strong circumstantial evidence; a
behavior-preserving instrumentation step is proposed to PROVE it before any
(macOS-only) fix is applied.

### Symptom
Toward the end of a session, clicks feel like they need to be issued **twice** —
the first click does nothing, the second one lands. Distinct from the alt-tab
freeze above: the game keeps running normally, it's just that individual clicks
are intermittently dropped. Reported with no alt-tabbing that the player noticed.

### Evidence — session `2026-07-06T19-10-18_8127`
(`rule_mode_omniswap_vs_timer`, race timer)

- The session **ended cleanly**: a `# ===== END (FINISHED) =====` footer is
  present, the end came from the race timer (`[40002] timer expired
  (ended_game)` → `[10001] MOVING->VICTORY` → `[50001] FINISHED: 15 words, 645
  points`), NOT a force-kill. So this is **not** the freeze bug.
- The `[00012]` heartbeat ran the **entire** session — 183 beats at a steady ~2s
  cadence right to the end. The main loop never stalled.
- **Every** logged click did something: all 120 `[20003]` click lines are each
  followed by a real `[20005]` omniswap action. There are **zero** dead clicks in
  the log.
- `game_screen.on_mouse_press` logs its `[20003]` line **unconditionally, as its
  first statement** (before any phase/state check). So any click the app receives
  is always logged. The player's dead first-clicks produced **no** `[20003]`
  line → they never reached the app. Delivery was dropped **below** the app, in
  the OS / pyglet event layer.
- **Zero** `[00010]` focus lines this whole session — pyglet did not even log
  clean window-key transitions (consistent with the botched-handshake behavior
  noted in the freeze bug above).

### CONFIRMED
- Not a freeze (loop alive, clean END footer) and not a coordinate/game-logic bug
  (every delivered click logged and acted correctly).
- The dropped clicks never reached the app — an OS/pyglet event-delivery drop.

### Leading hypothesis
macOS **first-mouse swallow**. pyglet 2.1.14's Cocoa view
(`pyglet/window/cocoa/pyglet_view.py`, class `PygletView` : `NSView`) does **not**
override `acceptsFirstMouse:`, and `NSView`'s default return is **NO**. When the
window is not the *active* window, macOS consumes the first click merely to
activate the window and does not deliver it to the view as `mouseDown_`; the
second click gets through. The app is easily made non-active without a full
alt-tab: notification banner, menu bar / clock, Spotlight, a Space / Mission
Control nudge, or a click onto another display.

### Candidate fix — NOT yet applied (macOS-only; hold until proven)
Override `acceptsFirstMouse:` on `PygletView` to return `YES` (via a small ObjC
monkeypatch at startup, behind a `config.yaml` toggle — we don't edit the venv's
pyglet source). This is the standard macOS remedy for "click twice." Deferred by
request: it's a macOS-specific change, so we want direct proof the swallow is
actually happening before applying it.

### Round 2 — probe was live and caught NOTHING (session `2026-07-06T19-40-28_de16`)
Player reproduced the "click twice" in the **last ~30s** again (a 360s race game;
symptom hit ~330–360s). The `first_mouse_probe` was confirmed active (the `.meta`
config snapshot shows `first_mouse_probe: true`, so `install()` ran on macOS).
Result:
- **Zero `[00013]`** first-mouse lines the whole session.
- **Zero `[00010]`** focus lines — *including at startup*, so pyglet's
  `on_activate`/`on_deactivate` are simply not firing in this environment; their
  absence is not evidence either way.
- Every logged click in the final 30s worked perfectly (picks/swaps clean, words
  ROD @352s and SON @360s played), heartbeats dead-steady at 2.0s to the end.
- The `PygletTextView` subview is zero-frame (`init` with no `setFrame`), so board
  clicks hit-test to `PygletView` — the class we DID patch. So this is not a
  simple "wrong view" coverage gap.

What this tells us: the swallowed clicks (if that's the mechanism) do **not** pass
through `PygletView.acceptsFirstMouse:`. Combined with "reproduces near the ~6-min
mark both times, no end-game escalation exists in the code," the common factor is
**session duration**, not a specific final-seconds mechanic. `acceptsFirstMouse:`
returning YES is therefore **not confirmed** as the fix — do not apply it yet.

### Definitive probe — window-level `sendEvent:` (APPLIED 2026-07-06)
pyglet pumps its OWN Cocoa loop (`CocoaWindow._poll_app_events` /
`dispatch_events` in `pyglet/window/cocoa/__init__.py`): every event is pulled via
`NSApp.nextEventMatchingMask_...` and handed to `NSApp.sendEvent_(event)`, which
routes to the window's `sendEvent:`. That is the ONE chokepoint every mouse-down
crosses, regardless of which view hit-tests or whether it gets swallowed.
`PygletWindow` (`pyglet/window/cocoa/pyglet_window.py`) does NOT override
`sendEvent:`, so `src/macos_first_mouse_probe.py` now adds one: it logs every
left-mouse-down as `log_00014` (window-point x,y + `isKeyWindow` + `NSApp.isActive`)
then calls `send_super` — no ObjC blocks, no behavior change. Gated on the same
`logging.first_mouse_probe` flag as the `[00013]` probe. Verified: it fires on a
left-mouse-down, ignores non-mouse events, and forwards to super so the window
keeps working.

Reading the NEXT reproduction (compare `[00014]` against the app-level `[20003]`;
join on TIMESTAMP, since `[00014]` is window points and `[20003]` is backing
pixels — the numbers differ by the Retina scale):
- A dead click **appears** as `[00014]` but yields no `[20003]` → the OS delivered
  it; pyglet's view dispatch dropped it → an in-app/pyglet bug, fixable without a
  macOS-only hack.
- A click you KNOW you made with **no `[00014]` at all** → `nextEventMatchingMask`
  never returned it → the OS never delivered it to the app → genuinely OS-level
  (then `acceptsFirstMouse:`→YES and/or a focus-reassert are the right class of
  fix). This branch is an *absence*, so it leans on your report plus the
  surrounding `[00014]`/`[20003]`/`[00012]` timestamps to bracket when.
- Also check the flags on the `[00014]` lines that DO appear near the trouble:
  `key_window=False` or `app_active=False` would be the first positive sign the
  window/app was losing focus around then (the `[00010]` focus log is dead in this
  environment, so these flags are our focus signal now).

### Instrumentation proposed to PROVE it (behavior-preserving)
Override `acceptsFirstMouse:` but keep returning **NO** (no behavior change — the
swallow still happens exactly as today) and **log every invocation**. macOS calls
`acceptsFirstMouse:` on the view precisely when a mouseDown lands on an
*inactive* window — so each log line is a direct, timestamped record of one
otherwise-invisible swallowed click. Correlate its timestamps with the player's
"click twice" moments. Complement with app-active-state logging
(`applicationDidBecomeActive/resignActive`, window `becomeMain/resignMain`) for
the surrounding timeline, since our current `[00010]` key-status logging isn't
catching these transitions. Only after this confirms the swallow do we flip the
return to `YES` (the fix).
