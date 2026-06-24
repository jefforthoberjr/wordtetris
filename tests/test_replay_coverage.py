"""Replay's handling of the starting-coverage pass: the recorded compute time is
read from the log (log_06004) so replay can reproduce the CALCULATING pause,
scaled to playback speed, without recomputing. Only the headless extraction is
tested here; the actual simulated pause needs a live GameScreen/GL window.
"""
import replay_log
from replay import coverage_recorded_seconds

_META = "# rng_seed : 123\n# window : 800x600 (physical)\n"


def _log(body):
    return replay_log.parse(_META, body)


def test_reads_recorded_seconds_from_log():
    body = (
        "[00001] 0.011 | session started | seed=123\n"
        "[06004] 8.250 | starting coverage: 50/100 words formable | "
        "seconds=8.25 words=100 covered=50 combos=120\n"
        "[20003] 9.000 | LEFT click (10,20) | x=10 y=20 button=LEFT phase=MOVING\n"
    )
    assert coverage_recorded_seconds(_log(body)) == 8.25


def test_no_coverage_pass_returns_zero():
    body = "[00001] 0.011 | session started | seed=123\n"
    assert coverage_recorded_seconds(_log(body)) == 0.0
