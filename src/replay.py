"""Replay a recorded session log by re-running it through the real GameScreen.

    python replay.py sessions/<id>.log [--speed 2.0] [--invisible]

How it works: the log records the RNG seed and a verbatim config snapshot, so
re-seeding the global RNG with that seed and running the SAME code + config
reproduces every random draw (formation, piece queue, grams). The recorded input
events (keys / clicks / text) are then re-dispatched on their timeline into the
real handlers. Replay is watched, not interactive -- no live controls.

Faithfulness depends on matching code + config. The config snapshot is loaded
from the log (so config edits since don't matter); a git_commit mismatch is only
warned about, since reproducing old *code* would mean checking that commit out.

Known limit: the log stores wall-clock timestamps, not the per-frame dt sequence,
so timer-driven modes can drift slightly from the original run.

Structured so the pieces (config load, game build, input decode) are importable
and testable without running the windowed event loop."""
import argparse
import random
import sys
from pathlib import Path

import yaml

import config
import replay_log

# config globals must be patched BEFORE game_screen (and its transitive imports)
# read them at import time, so pyglet/game modules are imported lazily in run().
_EMBED_TO_GLOBAL = {
    "config.yaml": "CONFIG",
    "colors.yaml": "COLORS",
    "strings.yaml": "STRINGS",
    "loading_animation.yaml": "LOADING_ANIM",
}


def load_embedded_config(log):
    """Replace the config module's globals with the log's embedded snapshot, and
    force logging off (replay must not record a new file or re-seed). Must run
    before importing game_screen so every module reads the snapshot."""
    for name, attr in _EMBED_TO_GLOBAL.items():
        lines = log.embedded.get(name)
        if lines:
            setattr(config, attr, yaml.safe_load("\n".join(lines)))
    config.CONFIG.setdefault("logging", {})["enabled"] = False


def coverage_recorded_seconds(log):
    """The recorded starting-coverage compute time (log_06004 `seconds`), or 0.0
    if the session ran no coverage pass. Replay reproduces it as a scaled
    CALCULATING pause and offsets its own clock by it, since every recorded
    timestamp after the pass already includes this delay."""
    for ev in log.events_for(6004):
        try:
            return float(ev.fields["seconds"])
        except (KeyError, ValueError):
            return 0.0
    return 0.0


def build_game(log, visible=True, player_dict_path=None, coverage_sim_seconds=None):
    """Build a GameScreen seeded to reproduce the recorded session and started
    into its opening board. Returns (window, game_screen). Assumes
    load_embedded_config(log) has already run.

    `player_dict_path`, when given, points the player dictionary at the snapshot
    stashed beside the log at record time -- so first-time/"new word" green
    highlighting matches the original run rather than the player's current
    collection (which has since grown). The replay dictionary is always
    non-persisting: it tracks cleared words in memory (so green + the count stay
    right) but never writes to disk, so a playback can't corrupt the .dict
    snapshot (writing the run's own new words back into it would kill green on
    the next replay) nor mutate the live player_dictionary.txt when no stash
    exists."""
    import pyglet
    import source
    from controllers.screen_manager import ScreenManager
    from views.game_screen import GameScreen
    from models.player_dictionary import PlayerDictionary

    win = pyglet.window.Window(
        width=config.CONFIG["window"]["width"],
        height=config.CONFIG["window"]["height"],
        caption=f"REPLAY {log.session_id or ''}",
        visible=visible,
    )
    sm = ScreenManager()
    # Constructing GameScreen builds a throwaway opening board (consuming RNG),
    # exactly as at record time before on_enter re-seeded. So seed AFTER __init__
    # and BEFORE on_enter -- the same point start_session seeded during recording.
    gs = GameScreen(win, sm)
    # Always a non-persisting dict (persist=False): from the record-time stash if
    # we have one (green matches the original run), else the live file -- but in
    # neither case may replay write to disk. See build_game's docstring.
    if player_dict_path is not None:
        gs._player_dict = PlayerDictionary(path=player_dict_path, persist=False)
    else:
        gs._player_dict = PlayerDictionary(persist=False)
    # If the recorded session ran the (blocking) starting-coverage pass, replay
    # SIMULATES it: on_enter's coverage rule pauses for this scaled duration
    # showing CALCULATING, but never recomputes or rewrites the file.
    gs._coverage_sim_seconds = coverage_sim_seconds
    source.reset()
    random.seed(log.rng_seed)
    gs.on_enter()
    return win, gs


# --- input decoding (record -> pyglet call) ----------------------------------
def _key_consts():
    import pyglet
    key = pyglet.window.key
    mods = {
        "SHIFT": key.MOD_SHIFT, "CTRL": key.MOD_CTRL,
        "ALT": key.MOD_ALT, "CMD": key.MOD_COMMAND,
    }
    return key, mods


def dispatch(gs, event):
    """Replay one recorded input event into the game's handlers."""
    import pyglet
    f = event.fields
    if event.code == 20001:                       # key press
        key, mod_map = _key_consts()
        symbol = getattr(key, f.get("key", ""), None)
        if symbol is None:
            return
        modifiers = 0
        if f.get("mods", "-") != "-":
            for name in f["mods"].split("+"):
                modifiers |= mod_map.get(name, 0)
        gs.on_key_press(symbol, modifiers)
    elif event.code == 20002:                     # text typed
        text = f.get("text", "").replace("\\n", "\n").replace("\\r", "\r").replace("_", " ")
        gs.on_text(text)
    elif event.code == 20003:                     # mouse click
        mouse = pyglet.window.mouse
        button = getattr(mouse, f.get("button", "LEFT"), mouse.LEFT)
        gs.on_mouse_press(int(f["x"]), int(f["y"]), button, 0)


def run(path, speed=1.0, visible=True):
    """Load, build, and play back the session at `path` in a window."""
    import pyglet

    log = replay_log.load(path)
    if log.rng_seed is None:
        print("error: log has no rng_seed; cannot reproduce randomness.", file=sys.stderr)
        return 1
    _warn_on_commit_mismatch(log)
    load_embedded_config(log)
    # The player-dictionary snapshot stashed beside the log at record time
    # (sessions/<id>.dict), if present, so green "new word" highlighting matches.
    from pathlib import Path
    stash = Path(path).with_suffix(".dict")
    # Recorded coverage time: drive the scaled CALCULATING pause (build_game) and
    # start the replay clock past it, so recorded input timestamps -- which already
    # include the pause -- line up without a dead gap at the opening.
    cov_seconds = coverage_recorded_seconds(log)
    win, gs = build_game(
        log, visible=visible,
        player_dict_path=str(stash) if stash.exists() else None,
        coverage_sim_seconds=(cov_seconds / speed if cov_seconds else None))

    inputs = log.events_for(20001, 20002, 20003)
    last_t = log.events[-1].t if log.events else 0.0
    state = {"i": 0, "t": cov_seconds, "done": False}

    @win.event
    def on_draw():
        win.clear()
        gs.draw()

    def tick(dt):
        # Once the run has played out, freeze on the final frame: stop advancing
        # the game and dispatching inputs, but keep the window open (the clock
        # stays scheduled so on_draw keeps presenting the last frame) until the
        # user closes it.
        if state["done"]:
            return
        state["t"] += dt * speed
        while state["i"] < len(inputs) and inputs[state["i"]].t <= state["t"]:
            dispatch(gs, inputs[state["i"]])
            state["i"] += 1
        gs.update(dt * speed)
        # Played out: the game reached its end state, or we ran several seconds
        # past the last recorded event (left-screen endings).
        ended = getattr(gs, "_phase", None) is not None and gs._phase.name == "VICTORY"
        if state["i"] >= len(inputs) and (ended or state["t"] > last_t + 5.0):
            state["done"] = True
            # Dismiss the end-state overlay so the freeze shows the bare final
            # board (same flag a click sets in the live VICTORY phase).
            gs._end_overlay_dismissed = True
            print("replay finished; close the window to exit.")

    pyglet.clock.schedule_interval(tick, 1.0 / config.CONFIG["game"]["ups"])
    pyglet.app.run()
    return 0


# --- video export ------------------------------------------------------------
# pyglet's native framebuffer format -> ffmpeg raw input pixel format. We feed
# ffmpeg whatever format the color buffer already is (usually RGBA) so capture
# stays a cheap memcpy: asking pyglet to convert to RGB instead runs a
# pure-Python per-pixel loop that caps throughput at ~4 fps -- ffmpeg does the
# channel work far faster.
_PIXFMT = {"RGBA": "rgba", "RGB": "rgb24", "BGRA": "bgra", "BGR": "bgr24"}


def _spawn_ffmpeg(out_path, width, height, fps, pix_fmt, scale=1.0):
    """Start an ffmpeg subprocess reading raw `pix_fmt` frames on stdin and
    writing an H.264 .mp4. We shell out to the system ffmpeg (no Python encoding
    lib). Notes: pyglet's framebuffer rows are bottom-up, so `vflip` turns them
    top-first; `scale` downsizes by that factor (1.0 = full Retina size) for
    smaller/faster Discord clips; `trunc(...)*2` forces even dimensions, which
    yuv420p (needed for broad players like Discord) requires."""
    import subprocess
    vf = f"vflip,scale=trunc(iw*{scale}/2)*2:trunc(ih*{scale}/2)*2"
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", pix_fmt,
        "-s", f"{width}x{height}", "-r", str(fps),
        "-i", "-",
        "-an",
        "-vf", vf,
        "-pix_fmt", "yuv420p", "-crf", "18",
        "-movflags", "+faststart",
        out_path,
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def export_run(path, out_path, speed=1.0, fps=30, scale=1.0):
    """Render a recorded session to an .mp4 by driving the game on a FIXED
    timestep (speed/fps sim-seconds per output frame) and piping each rendered
    frame to ffmpeg. Unlike run(), this is decoupled from the wall clock, so the
    output is smooth regardless of how fast frames actually render. The window is
    shown during capture -- macOS needs it visible for reliable framebuffer
    readback (see the design decision recorded with this feature)."""
    import pyglet

    log = replay_log.load(path)
    if log.rng_seed is None:
        print("error: log has no rng_seed; cannot reproduce randomness.", file=sys.stderr)
        return 1
    _warn_on_commit_mismatch(log)
    load_embedded_config(log)
    stash = Path(path).with_suffix(".dict")
    cov_seconds = coverage_recorded_seconds(log)
    win, gs = build_game(
        log, visible=True,
        player_dict_path=str(stash) if stash.exists() else None,
        coverage_sim_seconds=(cov_seconds / speed if cov_seconds else None))

    inputs = log.events_for(20001, 20002, 20003)
    last_t = log.events[-1].t if log.events else 0.0
    dt = speed / fps
    win.set_vsync(False)  # don't throttle capture to the monitor refresh

    # ffmpeg is spawned lazily on the first frame, once we know the (physical,
    # possibly Retina-2x) framebuffer size and native format from the buffer.
    proc = {"p": None}

    def write_frame():
        win.switch_to()
        win.dispatch_events()
        win.clear()
        gs.draw()
        img = pyglet.image.get_buffer_manager().get_color_buffer().get_image_data()
        # Feed ffmpeg the buffer's native format (cheap memcpy); fall back to
        # RGBA only if it's something exotic we haven't mapped.
        fmt = img.format if img.format in _PIXFMT else "RGBA"
        raw = img.get_data(fmt, img.width * len(fmt))
        if proc["p"] is None:
            proc["p"] = _spawn_ffmpeg(out_path, img.width, img.height, fps, _PIXFMT[fmt], scale)
        proc["p"].stdin.write(raw)
        win.flip()

    # Play the recorded timeline on a fixed timestep -- one output frame per
    # step. Mirrors run()'s tick ordering (advance clock, dispatch due inputs,
    # update) so the rendered state matches a normal replay at each instant.
    i = 0
    t = cov_seconds
    frames = 0
    while t <= last_t:
        t += dt
        while i < len(inputs) and inputs[i].t <= t:
            dispatch(gs, inputs[i])
            i += 1
        gs.update(dt)
        write_frame()
        frames += 1

    # Hold on the final frame for a couple of seconds, with the end-state overlay
    # dismissed (same freeze as run()), so the clip doesn't cut off abruptly.
    gs._end_overlay_dismissed = True
    for _ in range(int(fps * 2)):
        write_frame()
        frames += 1

    p = proc["p"]
    if p is not None:
        p.stdin.close()
        p.wait()
    win.close()
    print(f"exported {frames} frames -> {out_path}")
    return 0


def _warn_on_commit_mismatch(log):
    """Warn (don't fail) if the working tree isn't the commit the log was made on
    -- replay reproduces randomness from the seed, but only against matching code."""
    import subprocess
    from pathlib import Path
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent), capture_output=True,
            text=True, timeout=2,
        )
        current = out.stdout.strip()
    except Exception:
        current = ""
    if current and log.git_commit and current != log.git_commit:
        print(f"warning: log recorded at commit {log.git_commit}, "
              f"replaying on {current}; randomness/behavior may differ.",
              file=sys.stderr)


# sessions/ lives at the repo root (this file is src/replay.py).
_SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"


def resolve_recent_log(n):
    """Return the path to the n-th most recent session log (0 = most recent).
    Session filenames are ISO-timestamp prefixed, so lexical sort is
    chronological."""
    logs = sorted(_SESSIONS_DIR.glob("*.log"), reverse=True)
    if not logs:
        raise SystemExit(f"no session logs found in {_SESSIONS_DIR}")
    if n >= len(logs):
        raise SystemExit(f"-{n}: only {len(logs)} session log(s) available "
                         f"(valid range 0..{len(logs) - 1})")
    return str(logs[n])


def _extract_recent_flag(argv):
    """Pull a -N selector (-0, -1, ...) out of argv. argparse would treat these
    as unknown options, so handle them before parsing. Returns (n, remaining)."""
    n = None
    remaining = []
    for tok in argv:
        if len(tok) >= 2 and tok[0] == "-" and tok[1:].isdigit():
            n = int(tok[1:])
        else:
            remaining.append(tok)
    return n, remaining


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    recent_n, argv = _extract_recent_flag(argv)

    parser = argparse.ArgumentParser(description="Replay a recorded session log.")
    parser.add_argument("logfile", nargs="?",
                        help="path to a sessions/<id>.log file; omit and use "
                             "-N to pick the N-th most recent session "
                             "(-0 = most recent, -1 = the one before, ...)")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="playback speed multiplier (default 1.0)")
    parser.add_argument("--invisible", action="store_true",
                        help="run without showing the window (for testing)")
    parser.add_argument("--export", metavar="OUT.mp4",
                        help="render the replay to an .mp4 (via ffmpeg) instead "
                             "of playing it live; window is shown during capture")
    parser.add_argument("--fps", type=int, default=30,
                        help="frames per second for --export (default 30)")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="--export downscale factor (e.g. 0.5 = half size, "
                             "smaller file & faster encode; default 1.0)")
    args = parser.parse_args(argv)

    if recent_n is not None:
        if args.logfile is not None:
            parser.error("give either a logfile or a -N selector, not both")
        logfile = resolve_recent_log(recent_n)
    elif args.logfile is not None:
        logfile = args.logfile
    else:
        parser.error("a logfile or a -N selector (e.g. -0) is required")

    if args.export:
        return export_run(logfile, args.export, speed=args.speed, fps=args.fps,
                          scale=args.scale)
    return run(logfile, speed=args.speed, visible=not args.invisible)


if __name__ == "__main__":
    sys.exit(main())
