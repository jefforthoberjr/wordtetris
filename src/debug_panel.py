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

batch = None
panel = None
label = None
system_info = None
process = None
has_nvidia_vram = False
has_ati_vram = False
vram_type = "integrated"

# NVIDIA extension constants
GL_GPU_MEMORY_INFO_CURRENT_AVAILABLE_VIDMEM_NVX = 0x9049
GL_GPU_MEMORY_INFO_TOTAL_AVAILABLE_MEMORY_NVX = 0x9048

# ATI extension constants
GL_TEXTURE_FREE_MEMORY_ATI = 0x87FC


def init(window):
    global batch, panel, label, start_time, system_info, process
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


def start_update():
    global update_start_time
    update_start_time = time.perf_counter()


def end_update():
    global update_times, busy_time_ms
    
    end_time = time.perf_counter()
    update_time_ms = (end_time - update_start_time) * 1000
    update_times.append(update_time_ms)
    busy_time_ms += update_time_ms


def start_event():
    global event_start_time
    event_start_time = time.perf_counter()


def end_event():
    global busy_time_ms
    
    end_time = time.perf_counter()
    event_time_ms = (end_time - event_start_time) * 1000
    busy_time_ms += event_time_ms


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
