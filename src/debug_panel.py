import sys
import time
import pyglet
from pyglet.gl import gl_info, glGetIntegerv, GLint
import psutil
import ctypes


draw_times = []
draw_stats = {"min": 0.0, "max": 0.0, "avg": 0.0}
update_times = []
update_stats = {"min": 0.0, "max": 0.0, "avg": 0.0}
ram_samples = []
ram_stats = {"min": 0.0, "max": 0.0, "avg": 0.0, "current": 0.0}
vram_samples = []
vram_stats = {"min": 0.0, "max": 0.0, "avg": 0.0, "current": 0.0}
last_stats_update = time.perf_counter()
draw_start_time = None
update_start_time = None
event_start_time = None
start_time = None
uptime_seconds = 0
fps = 0
ups = 0
busy_time_ms = 0
idle_percent = 0

# Session performance logging: accumulators for the perf snapshot written to the
# session log every heartbeat (log_00015 in main.py's update tick). Kept SEPARATE
# from the visual panel's draw_times/update_times above -- those reset on their own
# 1s cadence and only while the panel is drawn, so a shared buffer would let panel
# and logger fight over the reset and would go stale with the panel hidden. These
# are fed by the same end_draw/end_update/end_event taps and reset by perf_snapshot.
_log_draw_times = []
_log_update_times = []
_log_busy_ms = 0.0

# Whether the panel is currently shown (F3 toggles it; see main.py). Held here,
# not in main.py, so the game can cheaply check it before doing panel-only work --
# e.g. GameScreen only recomputes its formable-word samples while the panel is up.
visible = False

# Example words the board can currently spell, pushed by the active game
# (GameScreen.set_debug_word_samples) while the panel is visible; None means "no
# game has reported any" (non-constellation modes never set it), which hides the
# section entirely. A short SAMPLE, never a count -- see sample_formable_words.
_word_samples = None

batch = None
panel = None
label = None
system_info = None
ram_overhead_info = None
process = None
has_nvidia_vram = False
has_ati_vram = False
vram_type = "integrated"

# NVIDIA extension constants
GL_GPU_MEMORY_INFO_CURRENT_AVAILABLE_VIDMEM_NVX = 0x9049
GL_GPU_MEMORY_INFO_TOTAL_AVAILABLE_MEMORY_NVX = 0x9048

# ATI extension constants
GL_TEXTURE_FREE_MEMORY_ATI = 0x87FC


def init(window, ram_deltas=None):
    global batch, panel, label, start_time, system_info, ram_overhead_info, process
    global has_nvidia_vram, has_ati_vram, vram_type
    
    start_time = time.perf_counter()
    batch = pyglet.graphics.Batch()
    process = psutil.Process()
    
    # Check for VRAM extensions
    extensions = gl_info.get_extensions()
    has_nvidia_vram = 'GL_NVX_gpu_memory_info' in extensions
    has_ati_vram = 'GL_ATI_meminfo' in extensions
    
    if has_nvidia_vram:
        vram_type = "nvidia"
    elif has_ati_vram:
        vram_type = "ati"
    else:
        vram_type = "integrated"
    
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    system_info = (
        f"-- Tech Stack --\n"
        f"  Python: {python_version}\n"
        f"  Pyglet: {pyglet.version}\n"
        f"  OpenGL: {gl_info.get_version()}\n"
        f"  Vendor: {gl_info.get_vendor()}\n"
        f"  GPU: {gl_info.get_renderer()}\n"
    )
    
    if ram_deltas:
        ram_overhead_info = (
            f"-- RAM Overhead --\n"
            f"  Python: {ram_deltas.get('baseline', 0) + ram_deltas.get('after_psutil', 0):.1f} MB\n"
            f"  Pyglet: {ram_deltas.get('after_pyglet', 0):.1f} MB\n"
            f"  OpenGL: {ram_deltas.get('after_window', 0):.1f} MB\n"
        )
    else:
        ram_overhead_info = ""
    
    panel = pyglet.shapes.Rectangle(
        x=window.width - 420,
        y=0,
        width=410,
        height=window.height,
        color=(200, 200, 200, 180),
        batch=batch
    )
    
    label = pyglet.text.Label(
        "",
        font_size=24,
        x=window.width - 410,
        y=window.height - 40,
        color=(0, 0, 0, 255),
        multiline=True,
        width=400,
        batch=batch
    )


def set_word_samples(words):
    """Record the example words the board can currently spell (a short list), or
    None to hide the section. Rendered as the '-- Board words --' block. Pushed by
    the game only while the panel is visible, so it stays fresh without any
    per-frame work here."""
    global _word_samples
    _word_samples = words


def _word_samples_section():
    """The '-- Board words --' block, or '' when no game has reported samples.
    An empty list (a spellable-out board) reads '(none)'."""
    if _word_samples is None:
        return ""
    if _word_samples:
        body = "".join(f"  {w}\n" for w in _word_samples)
    else:
        body = "  (none)\n"
    return f"-- Board words --\n{body}"


def prepare():
    calc_stat_avgs()

    if vram_type == "integrated":
        vram_section = (
            f"-- VRAM ({vram_type}) --\n"
            f"  n/a\n"
        )
    else:
        vram_section = (
            f"-- VRAM ({vram_type}) --\n"
            f"  Min: {vram_stats['min']:.1f} MB\n"
            f"  Avg: {vram_stats['avg']:.1f} MB\n"
            f"  Max: {vram_stats['max']:.1f} MB\n"
        )
    
    label.text = (
        f"{_word_samples_section()}"
        f"Uptime: {uptime_seconds} s\n"
        f"Idle: {idle_percent:.0f}%\n"
        f"-- Draw (FPS: {fps}) --\n"
        f"  Min: {draw_stats['min']:.2f} ms\n"
        f"  Avg: {draw_stats['avg']:.2f} ms\n"
        f"  Max: {draw_stats['max']:.2f} ms\n"
        f"-- Update (UPS: {ups}) --\n"
        f"  Min: {update_stats['min']:.2f} ms\n"
        f"  Avg: {update_stats['avg']:.2f} ms\n"
        f"  Max: {update_stats['max']:.2f} ms\n"
        f"-- RAM --\n"
        f"  Min: {ram_stats['min']:.1f} MB\n"
        f"  Avg: {ram_stats['avg']:.1f} MB\n"
        f"  Max: {ram_stats['max']:.1f} MB\n"
        f"{ram_overhead_info}"
        f"{vram_section}"
        f"{system_info}"
    )


def draw():
    prepare()
    batch.draw()


def start_draw():
    global draw_start_time
    draw_start_time = time.perf_counter()


def end_draw():
    global draw_times, busy_time_ms

    end_time = time.perf_counter()
    draw_time_ms = (end_time - draw_start_time) * 1000
    draw_times.append(draw_time_ms)
    busy_time_ms += draw_time_ms
    _log_draw_times.append(draw_time_ms)
    _add_log_busy(draw_time_ms)


def start_update():
    global update_start_time
    update_start_time = time.perf_counter()


def end_update():
    global update_times, busy_time_ms

    end_time = time.perf_counter()
    update_time_ms = (end_time - update_start_time) * 1000
    update_times.append(update_time_ms)
    busy_time_ms += update_time_ms
    _log_update_times.append(update_time_ms)
    _add_log_busy(update_time_ms)


def start_event():
    global event_start_time
    event_start_time = time.perf_counter()


def end_event():
    global busy_time_ms

    end_time = time.perf_counter()
    event_time_ms = (end_time - event_start_time) * 1000
    busy_time_ms += event_time_ms
    _add_log_busy(event_time_ms)


def _add_log_busy(ms):
    global _log_busy_ms
    _log_busy_ms += ms


def _stats(samples):
    """(min, avg, max) in ms over `samples`, or zeros when empty."""
    if not samples:
        return (0.0, 0.0, 0.0)
    return (min(samples), sum(samples) / len(samples), max(samples))


def perf_snapshot(window_seconds):
    """Snapshot the per-frame timing accumulated since the last call, then RESET the
    logging buffers. Returns a dict for log_00015. Works whether or not the debug
    panel is visible (independent of the panel's own 1s stat cadence).

    `window_seconds` is the wall time the samples span (the heartbeat period), used
    to turn counts into per-second fps/ups and the busy time into idle percent."""
    global _log_draw_times, _log_update_times, _log_busy_ms

    update_ms = _stats(_log_update_times)
    draw_ms = _stats(_log_draw_times)
    if window_seconds > 0:
        fps = round(len(_log_draw_times) / window_seconds)
        ups = round(len(_log_update_times) / window_seconds)
        idle_pct = max(0.0, 100.0 * (1.0 - _log_busy_ms / (window_seconds * 1000)))
    else:
        fps = ups = 0
        idle_pct = 0.0
    ram_mb = process.memory_info().rss / 1024 / 1024 if process else 0.0
    vram_mb = get_vram_usage_mb()

    _log_draw_times = []
    _log_update_times = []
    _log_busy_ms = 0.0

    return {"update_ms": update_ms, "draw_ms": draw_ms, "fps": fps, "ups": ups,
            "idle_pct": idle_pct, "ram_mb": ram_mb, "vram_mb": vram_mb}


def get_vram_usage_mb():
    if has_nvidia_vram:
        total = GLint()
        available = GLint()
        glGetIntegerv(GL_GPU_MEMORY_INFO_TOTAL_AVAILABLE_MEMORY_NVX, ctypes.byref(total))
        glGetIntegerv(GL_GPU_MEMORY_INFO_CURRENT_AVAILABLE_VIDMEM_NVX, ctypes.byref(available))
        used_kb = total.value - available.value
        return used_kb / 1024
    elif has_ati_vram:
        available = (GLint * 4)()
        glGetIntegerv(GL_TEXTURE_FREE_MEMORY_ATI, available)
        # ATI only reports available, not total/used
        return available[0] / 1024
    else:
        return None


def calc_stat_avgs():
    global draw_times, draw_stats, update_times, update_stats
    global ram_samples, ram_stats, vram_samples, vram_stats
    global last_stats_update, uptime_seconds, fps, ups, busy_time_ms, idle_percent
    
    now = time.perf_counter()
    
    # Sample RAM and VRAM each second
    current_ram = process.memory_info().rss / 1024 / 1024
    ram_samples.append(current_ram)
    
    current_vram = get_vram_usage_mb()
    if current_vram is not None:
        vram_samples.append(current_vram)
    
    if now - last_stats_update >= 1.0:
        if draw_times:
            draw_stats["min"] = min(draw_times)
            draw_stats["max"] = max(draw_times)
            draw_stats["avg"] = sum(draw_times) / len(draw_times)
        if update_times:
            update_stats["min"] = min(update_times)
            update_stats["max"] = max(update_times)
            update_stats["avg"] = sum(update_times) / len(update_times)
        if ram_samples:
            ram_stats["current"] = current_ram
            ram_stats["min"] = min(ram_samples)
            ram_stats["max"] = max(ram_samples)
            ram_stats["avg"] = sum(ram_samples) / len(ram_samples)
        if vram_samples:
            vram_stats["current"] = current_vram
            vram_stats["min"] = min(vram_samples)
            vram_stats["max"] = max(vram_samples)
            vram_stats["avg"] = sum(vram_samples) / len(vram_samples)
        fps = len(draw_times)
        ups = len(update_times)
        idle_percent = 100 - (busy_time_ms / 10)
        busy_time_ms = 0
        draw_times = []
        update_times = []
        ram_samples = []
        vram_samples = []
        last_stats_update = now
        uptime_seconds = int(now - start_time)
