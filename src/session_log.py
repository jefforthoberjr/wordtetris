"""Session logger -- captures a full play session under sessions/ for later
analysis and (eventually) deterministic replay.

Each session writes three sidecar files sharing one <id> (a timestamp + seed):
    <id>.meta   metadata block + a verbatim, comment-prefixed copy of every
                config/asset YAML loaded at runtime (written once, static)
    <id>.log    the body: one log line per event (streamed, flushed per line)
    <id>.dict   a snapshot of player_dictionary.txt at session start (for replay)

Each body line in <id>.log has the shape:

    [NNNNN] 134.456 | piece moved (12,3)->(12,1) | piece=L_TET via=click

    [NNNNN]   static log code (see log_codes.py; append-only, never reused)
    134.456   elapsed seconds since session start (monotonic)
    | ...  |  human-readable sentence (free text; ignored by parsers)
    | k=v     machine-readable fields (the analysis/replay payload)

This module owns the file lifecycle and the emit primitive only. The actual
codes + messages live in log_codes.py as inlined log_NNNNN() functions, so a
code is greppable by its number from the event site.

Logging is gated by the config `logging.enabled` toggle. When off -- or when no
session is open -- every emit() is a safe no-op, so call sites never need to
guard. This is the single edit point for the on-disk format."""
import random
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from config import CONFIG

# sessions/ lives at the repo root (this file is src/session_log.py).
_SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
# Asset YAMLs embedded verbatim into each header so a log reproduces the exact
# rule set it was played under, with no dependency on what the files say later.
_EMBED_FILES = ("config.yaml", "colors.yaml", "strings.yaml", "loading_animation.yaml")
# The player's lifetime word collection, snapshotted beside each log at session
# start so replay sees the dictionary as it was then (matching "new word"
# highlighting), not the since-grown live file. Same path PlayerDictionary uses.
_PLAYER_DICT_PATH = Path(__file__).resolve().parent.parent / "player_dictionary.txt"

# Module-level session state (one open session at a time; the game runs one
# game screen). _file is None whenever no session is open.
_file = None
_t0 = None
_seed = None
_session_id_str = None


def is_open():
    """Whether a session file is currently open for writing."""
    return _file is not None


def coverage_path():
    """Path of the starting-coverage CSV for the open session
    (sessions/<id>.coverage.csv), or None when no session is open. The
    starting-coverage rule writes here so the analysis file sits beside the log."""
    if _session_id_str is None:
        return None
    return _SESSIONS_DIR / f"{_session_id_str}.coverage.csv"


def current_seed():
    """The RNG seed chosen for the open session (or None). Recorded so a future
    seed-based replay can reproduce the same random draws; see start_session."""
    return _seed


def _logging_enabled():
    return bool(CONFIG.get("logging", {}).get("enabled", True))


def _now():
    """Monotonic seconds since this session started (0.0 if none)."""
    if _t0 is None:
        return 0.0
    return time.monotonic() - _t0


def _git_commit():
    """Short HEAD hash for the header, or 'unknown' if git isn't available."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True, text=True, timeout=2,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _fmt_value(value):
    """Render one field value for the `k=v` section: tuples become a
    space-free (a,b) so a coordinate stays one token; everything else is
    stringified and internal whitespace collapsed to keep one field one token."""
    if isinstance(value, tuple):
        return "(" + ",".join(_fmt_value(v) for v in value) + ")"
    return str(value).replace(" ", "_")


def _fmt_fields(fields):
    return " ".join(f"{k}={_fmt_value(v)}" for k, v in fields.items())


def emit(code, message, **fields):
    """Write one body line for log code `code`. No-op when no session is open,
    so every log_NNNNN() call site is safe regardless of the logging toggle."""
    if _file is None:
        return
    line = f"[{code:05d}] {_now():.3f} | {message}"
    if fields:
        line += " | " + _fmt_fields(fields)
    _file.write(line + "\n")
    # Flush each line so a crash still leaves a complete, analyzable prefix.
    _file.flush()


def _write_meta_file(session_id, now, window):
    """Write the session's metadata sidecar sessions/<id>.meta -- the metadata
    block + verbatim embedded YAML. Static, so it's written once and closed here;
    the body lines go to the separate <id>.log. Lines are '#'-prefixed so the
    whole file reads as comments."""
    meta = [
        "# ===== WORDTETRIS SESSION =====",
        f"# session_id : {session_id}",
        f"# started    : {now.isoformat()}",
        f"# git_commit : {_git_commit()}",
        # window.width/height are physical pixels on this build (see notes); record
        # both so a replay renders at the same physical size.
        f"# window     : {window.width}x{window.height} (physical)",
        f"# rng_seed   : {_seed}",
    ]
    with open(_SESSIONS_DIR / f"{session_id}.meta", "w", encoding="utf-8") as f:
        for line in meta:
            f.write(line + "\n")
        for name in _EMBED_FILES:
            f.write(f"# ----- {name} -----\n")
            path = _ASSETS_DIR / name
            try:
                for raw in path.read_text(encoding="utf-8").splitlines():
                    # Trim full-line comments and blank lines: keep only the active
                    # settings, not the YAML's own commentary/whitespace.
                    stripped = raw.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    f.write(f"# {raw}\n")
            except OSError as exc:
                f.write(f"# <could not read {name}: {exc}>\n")


def _session_id(now):
    return now.strftime("%Y-%m-%dT%H-%M-%S") + f"_{_seed & 0xFFFF:04x}"


def start_session(window):
    """Open a fresh session file and write its header. Closes any session left
    open (an abandoned game), seeds the global RNG so the run is reproducible,
    and records the seed in the header. No-op when logging is disabled.

    Seeding the global `random` here is the cheap, broad-strokes determinism
    foundation; the per-function Source seam (a later chunk) is what actually
    lets replay mock individual draws. Returns the session_id, or None."""
    global _file, _t0, _seed, _session_id_str
    if not _logging_enabled():
        return None
    if _file is not None:
        close(reason="superseded")
    # Draw a fresh seed from the auto-seeded RNG, then pin the RNG to it so every
    # subsequent random draw this session is reproducible from the header value.
    _seed = random.randrange(2 ** 32)
    random.seed(_seed)
    now = datetime.now().astimezone()
    session_id = _session_id(now)
    _session_id_str = session_id
    _SESSIONS_DIR.mkdir(exist_ok=True)
    _stash_player_dictionary(session_id)
    # Metadata goes to the <id>.meta sidecar (written once); body lines stream to
    # <id>.log. Same session_id/timestamp for both, computed once above.
    _write_meta_file(session_id, now, window)
    _file = open(_SESSIONS_DIR / f"{session_id}.log", "w", encoding="utf-8")
    _t0 = time.monotonic()
    return session_id


def _stash_player_dictionary(session_id):
    """Copy the current player_dictionary.txt to sessions/<id>.dict so replay can
    load the collection as it was at record time. No-op if the player has no
    collection yet."""
    if _PLAYER_DICT_PATH.exists():
        shutil.copy2(_PLAYER_DICT_PATH, _SESSIONS_DIR / f"{session_id}.dict")


def close(reason="closed"):
    """Flush and close the open session file (no-op if none). `reason` is only
    used for the trailing footer comment; the body's end-of-session log line is
    emitted by its log_NNNNN() code at the call site, before this runs."""
    global _file, _t0, _seed, _session_id_str
    if _file is None:
        return
    _file.write(f"# ===== END ({reason}) =====\n")
    _file.flush()
    _file.close()
    _file = None
    _t0 = None
    _seed = None
    _session_id_str = None
