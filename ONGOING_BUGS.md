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

**Status:** ROOT CAUSE FOUND (round 6, 2026-07-07) — pyglet stranded this non-M1
Apple Silicon Mac on its own "broken" macOS event loop. Fix applied as the
`window.osx_alt_loop` toggle (default on); awaiting playtest confirmation. See
round 6 near the bottom of this section for the full mechanism.

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

### Round 3 — window probe PROVES the OS never delivered the clicks (session `2026-07-06T20-08-27_8c93`)
Player reproduced again: **last minute** of the 360s game, ~1/3 of clicks "not
registering." The `[00014]` window probe was live and captured events (122 lines).
Analysis:
- **122 LEFT `[20003]` app-clicks ↔ 122 `[00014]` window probes — a PERFECT 1:1
  pairing.** Every left-click the app processed was seen at the window chokepoint
  first; zero left-clicks lacked a preceding `[00014]`. (The 5 extra `[20003]` are
  RIGHT-clicks / gram-manipulate, which the probe intentionally doesn't log.)
- **Zero** `[00014]` lines with `key_window=False` or `app_active=False` — the
  window was key and the app active for every delivered click. Focus was never lost.

So there is **not one** "OS delivered it but pyglet dropped it" case. The ~1/3
missing clicks produced **no `[00014]` at all** → the OS never delivered them to the
app. Sitting on the single chokepoint every event must cross and finding the missing
clicks absent is proof, as far as in-app instrumentation can reach, that **this is an
OS-level drop** — and NOT a focus / first-mouse problem (`acceptsFirstMouse:`→YES is
now firmly ruled out as the fix).

### CONFIRMED (updated)
- Not a freeze, not a coordinate bug, not a focus/first-mouse swallow.
- The missing clicks never reach the app's event queue (`nextEventMatchingMask`
  never returns them) → OS-level drop, focus intact.

### Leading hypothesis (round 3) — app starves its own event port
macOS delivers HID input to an app through a bounded Mach event port. If the app's
main thread services that port too slowly, WindowServer **drops** the excess events
— invisible to every in-app probe, focus untouched, rate scaling with how badly the
main thread lags. This fits ALL the evidence: worsens near the end of long (~6-min)
sessions (something accumulating grows per-frame work), comes in bursts during rapid
clicking, and never changes `key_window`/`app_active`. That points the root cause
BACK at an **in-app performance regression that accumulates over the session**
(leaked pyglet clock schedules, undeleted graphics/vertex objects, growing lists)
— not a macOS-specific hack. Note: the 2s heartbeat can't see this (pyglet's clock
keeps wall-time by growing `dt`, so cadence stays 2s even as frames slow); we must
measure actual frame time.

### Perf-metrics logging (APPLIED 2026-07-06) — the decisive next probe
`log_00015`, emitted on every 2s heartbeat (`main.py` update tick), sourced from
`debug_panel.perf_snapshot()`: update & draw time (min/avg/max ms), fps, ups, idle
%, process RAM, VRAM. Independent logging accumulators in `debug_panel.py` fed by
the same `end_draw/end_update/end_event` taps, so it records with the visual panel
hidden. Gated on `logging.perf_metrics`. Same session `.log`, interleaved so a
frame-time spike lines up with the `[00014]` click gap it (hypothetically) caused.
Decides the hypothesis cleanly:
- `update_max`/`draw_max` **climb** over the session (and RAM grows) → confirms the
  accumulation → slow-event-servicing → OS-drop chain. Next: hunt the leak
  (`schedule_once`/`schedule_interval` without unschedule, per-word graphics not
  deleted, growing collections).
- Frame time **flat** all session → NOT app-side. Points at hardware / trackpad /
  driver, and we stop chasing app code.

### Round 4 — perf metrics DISPROVE the app-slowness theory (session `2026-07-06T20-28-05_9dac`)
Player reproduced at ~90s / ~30s / last-few-seconds left. `log_00015` perf ran all
session (183 lines). Also new: **the red-X window close button needed a couple
clicks** to register.

Perf timeline (whole 368s game):
- `update_max` ~1–2 ms, `draw_max` ~1.3–1.9 ms — **flat**, no climb (early startup
  blip 4.3/3.9 ms only).
- **idle 93–95% the ENTIRE game** — the main thread is nearly always free.
- RAM flat (~155→190 MB, wobbles down at the end). No leak/accumulation.
- Delivered clicks still 100 `[00014]` ↔ 100 LEFT `[20003]`, all
  `key_window=True app_active=True`.

**Conclusion: the app is healthy — NOT slow, NOT starved, NOT leaking.** The
round-3 "app starves its own Cocoa event port" hypothesis is **DISPROVEN**: a
94%-idle main thread with 1–2 ms frames is not failing to drain events. Stop
hunting leaks.

Two live clues now:
- **fps/ups sit at ~55–56, not 60, from the very first second** (constant, not
  degrading). Our `busy_ms` excludes `context.flip()` (it runs after `end_draw`),
  so the ~16 ms/frame of "idle" is the main thread BLOCKED in the vsync flip —
  during which pyglet is NOT pumping the Cocoa event queue.
- **The red-X also double-clicks.** In pyglet's custom macOS loop EVERY event —
  title-bar clicks included — is only processed when pyglet calls
  `NSApp.sendEvent_`. So a laggy red-X is the same event-pump gap as the board
  clicks, not a separate thing. It does argue the problem is at the event-pump /
  window level, not in game/board code.

### Leading hypothesis (round 4) — vsync flip-block starves the EVENT PUMP (not the CPU)
With vsync on, the main thread blocks in the buffer-swap most of each frame and
only pumps events ~56×/s. During rapid end-game clicking, mouse-downs landing in
the flip-block window can be missed/coalesced before the next poll. This is the
ORIGINAL leading hypothesis from the top of this file, now back on top because the
perf data cleared the app-slowness alternative. Note vsync-on means the app can be
"idle" (per our busy_ms) yet still not servicing input — idle ≠ responsive.

### Hardware ruled out (2026-07-07)
Player confirmed: on a **trackpad**, and the double-click-to-register was **not seen
in other apps** — only this game. So it's app/pyglet-specific, not a system-wide
input/hardware fault. Locus is this game's window + pyglet event pump → consistent
with the vsync flip-block theory.

### Candidate fix / decisive test — APPLIED as a toggle (2026-07-07)
`window.vsync` config knob (default `true` = unchanged behavior); `main.py` applies
it via `window.set_vsync(CONFIG["window"]["vsync"])` right after window creation.
Verified safe: pyglet's default event loop (`app.run`, `pyglet/app/base.py`)
clock-schedules both update and redraw at `game.ups` and sleeps between ticks via
`clock.get_sleep_time()`, so vsync-off stays paced (~60 fps, NO busy-spin), and the
inter-frame wait is an OS event-wait (`nextEventMatchingMask untilDate`) that wakes
on input — the mechanism expected to fix the drops. The chosen value is captured in
each session `.meta` snapshot, so an A/B is self-documenting.

**A/B test:** set `window.vsync: false`, play a full ~6-min game clicking hard near
the end. Confirmed if (a) the "click twice" + red-X lag are gone and (b) `[00015]`
`fps` rises toward the real target. If it does NOT help, vsync is not the (whole)
cause — revisit the event-pump path (does pyglet's cocoa `_poll_app_events` /
`dispatch_events` actually drain input during the inter-frame wait, or only between
scheduled ticks?) and the trackpad-tap event timing specifically.

### Round 5 — vsync OFF did NOT fix it, and revealed vsync was never the pacer (session `2026-07-07T04-41-09_3fdb`)
Ran with `window.vsync: false` (confirmed in `.meta`). Symptom recurred: last ~30s,
~1/4 of clicks dropped, none before.
- **fps stayed ~56 and idle ~94%, identical to vsync-on.** So vsync-off changed
  nothing about the loop rate → the flip-block was NOT what paced the loop or
  gated input. **vsync flip-block hypothesis DISPROVEN.** The ~16 ms/frame "idle"
  is the clock-scheduler sleep between ticks (redraw+update both at `game.ups`),
  not a GL block; input responsiveness is not vsync-gated.
- Delivered clicks in the last 45s: **every `[00014]` still pairs 1:1 with
  `[20003]`**, all `key_window=True app_active=True`. Missing clicks produced no
  `[00014]` → still an OS-level drop, focus intact.
- Two `[00010]` focus events fired this session — but at **252s / 254s** (a 2 s
  blur/refocus mid-game), NOT in the last-30s trouble window. Not the cause.
- Timer code has **no final-seconds behavior** (continuous countdown only), so
  "last 30s" is behavioral (end-game rush / cumulative playtime), not a code
  trigger.

### CONFIRMED (updated round 5)
Ruled out, with evidence: freeze, coordinate desync, focus/first-mouse swallow,
app-perf/accumulation/event-port starvation, AND vsync flip-block. The missing
clicks never enter the app's event queue. Cause is BELOW pyglet's pump — OS event
routing, the trackpad driver, or WindowServer — not identified yet.

### Next steps (round 5)
1. **FREE discriminator — swap the input device.** Play one full game with an
   external USB/Bluetooth MOUSE instead of the trackpad. If drops vanish → it's
   trackpad-driver / tap-to-click specific (below our code; stop chasing app-side).
   If they persist → OS routing / pyglet pump, and (2) is warranted. The player is
   on a trackpad and does NOT see this in other apps, so a device swap cleanly
   splits "trackpad hardware/driver" from "everything else."
2. **Ground-truth input observer BELOW pyglet.** A listen-only session-level
   `CGEventTap` (or NSEvent global+local monitor) logging every physical
   left-mouse-down independent of pyglet's pump. Then: physical tap with no
   `[00014]` and no tap seen by the observer → hardware/driver never generated it;
   tap seen by the observer but no `[00014]` → the OS generated it but pyglet's
   loop never dequeued it (an in-app/pyglet bug). Heavier: needs Accessibility
   permission + run-loop integration into pyglet's custom loop. Do (1) first.

### Round 6 — ROOT CAUSE FOUND: pyglet gives non-M1 Apple Silicon its own "broken" event loop (2026-07-07)
Instead of building the round-5 probes, we read pyglet's macOS event-loop code. It
resolves ALL prior evidence (OS-level drop below the pump, focus intact, app healthy,
worsens over a long session, bursts under rapid clicking, red-X also laggy).

pyglet ships **two** macOS event loops (`pyglet/app/cocoa.py`):
- **`EventLoop`** (standard): pumps input via
  `nextEventMatchingMask_untilDate_inMode_dequeue_`, one event per `step()`
  (`CocoaPlatformEventLoop.step`, `NSDefaultRunLoopMode`).
- **`CocoaAlternateEventLoop`**: drives pyglet off the built-in `NSApp.run()` loop via
  an `NSTimer`. pyglet's OWN docstring on it (`cocoa.py:108-113`):
  > *"nextEventMatchingMask_untilDate_inMode_dequeue_ is very broken with ctypes calls.
  > Events eventually stop working properly after X returns."*
  That single sentence IS this bug: after enough calls the standard pump silently stops
  delivering some clicks — worsening with session length, exactly what we logged.

The selection gate (`pyglet/app/__init__.py:53`):
```python
if (platform.machine() == 'arm64' and "M1" in get_chip_model()) or pyglet.options.osx_alt_loop:
    from pyglet.app.cocoa import CocoaAlternateEventLoop as EventLoop
```
pyglet only auto-picks the GOOD loop when the chip string contains the literal `"M1"`.
This machine reports **`Apple M3`** → `"M1" in "Apple M3"` is **False** → it silently
fell through to the BROKEN loop. Verified live:
```
chip_model: 'Apple M3'   M1 in chip?: False
--> EventLoop class actually selected: EventLoop
```
The hardcoded `"M1"` is a pyglet oversight that strands every M2/M3/M4 Mac on the loop
their own code condemns. Not a trackpad/driver issue, not app perf, not vsync, not
focus — all consistent with rounds 1-5, now explained.

### CONFIRMED (round 6)
- Standard pyglet macOS `EventLoop` (the `nextEventMatchingMask` ctypes pump) is what
  ran on this M3, and pyglet's own source says it "eventually stops working."
- Setting `pyglet.options.osx_alt_loop = True` (before `pyglet.app` import) flips the
  app to `CocoaAlternateEventLoop`. Verified: selection changes to the alt loop.

### Fix — APPLIED as a toggle (2026-07-07), pending playtest confirmation
`window.osx_alt_loop` config knob (default `true`). `main.py` sets
`pyglet.options.osx_alt_loop` from it immediately after `from config import CONFIG`,
BEFORE any import pulls in `pyglet.app` (the loop class is locked at that import). With
it on, pyglet uses `NSApp.run()` on every Apple chip, sidestepping the broken pump.
Captured in `.meta` for A/B. Left vsync exactly as-is so this test isn't confounded.

**A/B test:** play a full ~6-min game clicking hard near the end with
`window.osx_alt_loop: true`. Confirmed if the "click twice" + laggy red-X are gone.
If they persist, set it `false` (back to stock selection = broken loop here) to confirm
the symptom returns, which would prove the loop is the variable; if it does NOT return
under `false` either, the loop wasn't the cause and we resume round-5 next-steps (mouse
swap / CGEventTap).

---

### (Superseded) Instrumentation proposed to PROVE the first-mouse theory
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
