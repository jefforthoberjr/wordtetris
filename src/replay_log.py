"""Reader for recorded session logs -- the parse/load side of session_log.py.

Loads a session's metadata (seed, window size, the embedded config snapshot) and
its ordered body events. Used by the replay tool (replay.py) and by any analysis
script; it has no game/pyglet dependency so it loads fast and runs headless.

A session is two sidecar files sharing one <id>:

    <id>.meta                              <id>.log
    # ===== WORDTETRIS SESSION =====       [00001] 0.011 | session started | seed=3854665190
    # session_id : ...                     [20003] 1.204 | LEFT click (120,300) | x=120 y=300 ...
    # rng_seed   : 3854665190              ...
    # window     : 800x600 (physical)
    # ----- config.yaml -----
    # <active config lines>

load() takes the <id>.log path and reads the <id>.meta sidecar beside it (with a
fallback for the old single combined file split on a `# ===== LOG =====` marker).

Each body line is `[code] elapsed | message | k=v k=v` (the last ` | k=v` section
is optional). Field values are kept as strings; callers coerce as needed."""
import re
from pathlib import Path

# [00001] 12.345 | message text...   (the message may itself contain " | k=v")
_LINE_RE = re.compile(r"^\[(\d+)\] ([\d.]+) \| (.*)$")
# A header "# key : value" metadata line.
_META_RE = re.compile(r"^#\s*([a-z_]+)\s*:\s*(.*)$")
# A "# ----- name -----" embedded-file banner.
_EMBED_RE = re.compile(r"^#\s*-----\s*(.+?)\s*-----\s*$")
_LOG_MARKER = "# ===== LOG ====="


class Event:
    """One body line: its `code` (int), `t` (elapsed seconds, float), human
    `message`, and parsed `fields` dict (str -> str)."""
    __slots__ = ("code", "t", "message", "fields")

    def __init__(self, code, t, message, fields):
        self.code = code
        self.t = t
        self.message = message
        self.fields = fields

    def __repr__(self):
        return f"Event({self.code:05d}, t={self.t}, {self.fields})"


class ReplayLog:
    """A parsed session: header metadata + the ordered list of `events`."""

    def __init__(self):
        self.session_id = None
        self.started = None
        self.git_commit = None
        self.rng_seed = None
        self.window = None            # (width, height) ints, or None
        self.embedded = {}            # filename -> list of active config lines
        self.events = []              # list[Event], in file order

    def events_for(self, *codes):
        """The events whose code is one of `codes`, in order."""
        wanted = set(codes)
        return [e for e in self.events if e.code in wanted]


def _parse_fields(rest):
    """Split a body line's text after `[code] elapsed | ` into (message, fields).
    The last ` | ` section holds `k=v` tokens; a line may have no such section
    (then everything is the message). The message itself may legitimately contain
    a non-` | k=v ` pipe, so we only treat the FINAL section as fields when it
    actually looks like whitespace-separated k=v tokens."""
    if " | " not in rest:
        return rest, {}
    message, _, tail = rest.rpartition(" | ")
    tokens = tail.split(" ")
    fields = {}
    for tok in tokens:
        if "=" not in tok:
            # Not a fields section after all -- fold it back into the message.
            return rest, {}
        key, _, value = tok.partition("=")
        fields[key] = value
    return message, fields


def parse(meta_text, body_text):
    """Parse a session's `meta_text` (the <id>.meta sidecar) and `body_text`
    (the <id>.log body) into a ReplayLog."""
    log = ReplayLog()
    _parse_meta_text(log, meta_text)
    _parse_body_text(log, body_text)
    return log


def _parse_meta_text(log, text):
    """Read the header metadata + embedded config lines into `log`."""
    embed_target = None
    for raw in text.splitlines():
        # Tolerate the old combined format's marker (a sliced meta half may keep
        # it); everything after it is body, not metadata.
        if raw == _LOG_MARKER:
            break
        embed = _EMBED_RE.match(raw)
        if embed:
            embed_target = embed.group(1)
            log.embedded[embed_target] = []
            continue
        if embed_target is not None and raw.startswith("#"):
            # Inside an embedded file block: strip the "# " prefix.
            log.embedded[embed_target].append(raw[2:] if raw.startswith("# ") else raw[1:])
            continue
        meta = _META_RE.match(raw)
        if meta:
            _apply_meta(log, meta.group(1), meta.group(2))


def _parse_body_text(log, text):
    """Read the body log lines into `log.events`."""
    for raw in text.splitlines():
        m = _LINE_RE.match(raw)
        if not m:
            continue
        code = int(m.group(1))
        t = float(m.group(2))
        message, fields = _parse_fields(m.group(3))
        log.events.append(Event(code, t, message, fields))


def _apply_meta(log, key, value):
    if key == "session_id":
        log.session_id = value
    elif key == "started":
        log.started = value
    elif key == "git_commit":
        log.git_commit = value
    elif key == "rng_seed":
        try:
            log.rng_seed = int(value)
        except ValueError:
            log.rng_seed = None
    elif key == "window":
        # "800x600 (physical)"
        m = re.match(r"(\d+)x(\d+)", value)
        if m:
            log.window = (int(m.group(1)), int(m.group(2)))


def load(path):
    """Load and parse a session given its `<id>.log` body file. Reads metadata
    from the sibling `<id>.meta`. Falls back to the old single-file format (header
    + body in one file, split on the LOG marker) when no `.meta` sidecar exists,
    so previously recorded logs still load."""
    path = Path(path)
    body_text = path.read_text(encoding="utf-8")
    meta_path = path.with_suffix(".meta")
    if meta_path.exists():
        meta_text = meta_path.read_text(encoding="utf-8")
    elif _LOG_MARKER in body_text:
        # Old combined file: metadata above the marker, body below.
        meta_text, _, body_text = body_text.partition(_LOG_MARKER)
    else:
        meta_text = ""
    return parse(meta_text, body_text)
