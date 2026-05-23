import time
import pyglet


draw_times = []
draw_stats = {"min": 0.0, "max": 0.0, "avg": 0.0}
update_times = []
update_stats = {"min": 0.0, "max": 0.0, "avg": 0.0}
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


def init(window):
    global batch, panel, label, start_time
    
    start_time = time.perf_counter()
    batch = pyglet.graphics.Batch()
    
    panel = pyglet.shapes.Rectangle(
        x=window.width - 220,
        y=window.height - 200,
        width=210,
        height=190,
        color=(200, 200, 200, 180),
        batch=batch
    )
    
    label = pyglet.text.Label(
        "",
        font_size=12,
        x=window.width - 210,
        y=window.height - 20,
        color=(0, 0, 0, 255),
        multiline=True,
        width=200,
        batch=batch
    )


def prepare():
    calc_stat_avgs()
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
        f"  Max: {update_stats['max']:.2f} ms"
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


def calc_stat_avgs():
    global draw_times, draw_stats, update_times, update_stats
    global last_stats_update, uptime_seconds, fps, ups, busy_time_ms, idle_percent
    
    now = time.perf_counter()
    
    if now - last_stats_update >= 1.0:
        if draw_times:
            draw_stats["min"] = min(draw_times)
            draw_stats["max"] = max(draw_times)
            draw_stats["avg"] = sum(draw_times) / len(draw_times)
        if update_times:
            update_stats["min"] = min(update_times)
            update_stats["max"] = max(update_times)
            update_stats["avg"] = sum(update_times) / len(update_times)
        fps = len(draw_times)
        ups = len(update_times)
        idle_percent = 100 - (busy_time_ms / 10)
        busy_time_ms = 0
        draw_times = []
        update_times = []
        last_stats_update = now
        uptime_seconds = int(now - start_time)
