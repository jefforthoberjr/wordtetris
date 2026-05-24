import psutil

process = psutil.Process()
measurements = {}


def get_ram_mb():
    return process.memory_info().rss / 1024 / 1024


def measure(label):
    measurements[label] = get_ram_mb()


def get_measurements():
    return measurements


def get_deltas():
    labels = list(measurements.keys())
    deltas = {}
    for i, label in enumerate(labels):
        if i == 0:
            deltas[label] = measurements[label]
        else:
            prev_label = labels[i - 1]
            deltas[label] = measurements[label] - measurements[prev_label]
    return deltas


# Measure baseline immediately when this module is imported
measure("baseline")
