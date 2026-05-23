import time
import pyglet


frame_times = []
frame_stats = {"min": 0.0, "max": 0.0, "avg": 0.0}
last_stats_update = time.perf_counter()
frame_start_time = None

batch = None
panel = None
label = None


def init(window):
    global batch, panel, label
    
    batch = pyglet.graphics.Batch()
    
    panel = pyglet.shapes.Rectangle(
        x=window.width - 180,
        y=window.height - 80,
        width=170,
        height=70,
        color=(200, 200, 200, 180),
        batch=batch
    )
    
    label = pyglet.text.Label(
        "Min:  0.00 ms\nAvg:  0.00 ms\nMax:  0.00 ms",
        font_size=12,
        x=window.width - 170,
        y=window.height - 20,
        color=(0, 0, 0, 255),
        multiline=True,
        width=160,
        batch=batch
    )


def prepare():
    label.text = (
        f"Min:  {frame_stats['min']:.2f} ms\n"
        f"Avg:  {frame_stats['avg']:.2f} ms\n"
        f"Max:  {frame_stats['max']:.2f} ms"
    )


def draw():
    prepare()
    batch.draw()


def start_frame():
    global frame_start_time
    frame_start_time = time.perf_counter()


def end_frame():
    global frame_times, frame_stats, last_stats_update
    
    end_time = time.perf_counter()
    frame_time_ms = (end_time - frame_start_time) * 1000
    frame_times.append(frame_time_ms)
    
    if end_time - last_stats_update >= 1.0:
        if frame_times:
            frame_stats["min"] = min(frame_times)
            frame_stats["max"] = max(frame_times)
            frame_stats["avg"] = sum(frame_times) / len(frame_times)
        frame_times = []
        last_stats_update = end_time
