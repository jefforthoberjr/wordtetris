#!/usr/bin/env python3
"""Clip an end-of-game video (EndVideoOverlay / game_screen.end_video) from a raw
source into src/assets/video/, re-encoding to a profile pyglet's FFmpeg decoder can
play smoothly.

Why this exists: filmed/ripped sources vary (1080p60 High-profile with B-frames, odd
frame rates, etc.). A one-size clip command does NOT work -- a heavy source overruns
pyglet's threaded decoder and blits torn / smeared frames in game, even though it
plays fine in QuickTime. So each source gets analyzed UP FRONT, and we either apply a
per-source special case (SOURCES below) or auto-normalize to the goldeneye-class
target (720p, 30fps, Main profile, no B-frames). See TECH.md "CLIPPING END VIDEOS".

Usage:
    python tools/clip_end_video.py mario_flag_ending      # clip a registered source
    python tools/clip_end_video.py --probe ~/foo.mp4      # just analyze, don't clip

To add a new source: probe it (--probe), add an entry to SOURCES with its in/out
points and any special-case overrides, then run it by name.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "src" / "assets" / "video"

# The known-good "goldeneye-class" target every clip is normalized toward unless a
# source's special case overrides it. These are the traits of goldeneye.mp4, which
# plays smoothly: small frame, 30fps, Main profile, no B-frames.
TARGET_HEIGHT = 720          # downscale taller sources; -2 keeps aspect with even width
TARGET_FPS = 30              # cap frame rate; halves 60fps sources
TARGET_PROFILE = "main"      # simpler than High for the decoder
TARGET_LEVEL = "3.1"
DEFAULT_CRF = 20             # quality knob; lower = better/bigger

# Per-source special cases. Key = output stem (also the file written to assets/video/).
#   src:   raw source path (~ expanded)
#   start/end: clip in/out points in seconds (output seeking, frame-accurate)
#   crf:   optional quality override
#   force_normalize: True to always downscale/simplify even if the source looks light
#   vf_extra / v_extra: optional raw ffmpeg filter/video-arg tokens for oddball sources
SOURCES = {
    "mario_flag_ending": {
        "src": "~/Desktop/mario_flag_ending.mp4",
        "start": 6,
        "end": 20,
        # Source is 1920x1080 @ 60fps, High profile, B-frames -> smears in game.
        # Normalize hard to the goldeneye-class profile.
        "force_normalize": True,
    },
}


def ffprobe_stream(path):
    """Return the first video stream's key properties as a dict, or exit on error."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,avg_frame_rate,has_b_frames,level",
        "-of", "json", str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"ffprobe failed for {path}:\n{out.stderr}")
    streams = json.loads(out.stdout).get("streams", [])
    if not streams:
        sys.exit(f"No video stream found in {path}")
    return streams[0]


def fps_of(stream):
    """Parse a 'num/den' rate string (r_frame_rate) into a float."""
    rate = stream.get("r_frame_rate") or stream.get("avg_frame_rate") or "0/1"
    num, _, den = rate.partition("/")
    den = float(den) if den else 1.0
    return float(num) / den if den else 0.0


def describe(stream):
    return (f"{stream.get('width')}x{stream.get('height')} @ {fps_of(stream):.3f}fps, "
            f"profile={stream.get('profile')}, has_b_frames={stream.get('has_b_frames')}, "
            f"pix_fmt={stream.get('pix_fmt')}, level={stream.get('level')}")


def needs_normalize(stream):
    """Heavier than the goldeneye-class target -> pyglet may tear frames. Reasons list."""
    reasons = []
    if int(stream.get("height", 0)) > TARGET_HEIGHT:
        reasons.append(f"height {stream.get('height')} > {TARGET_HEIGHT}")
    if fps_of(stream) > TARGET_FPS + 0.5:
        reasons.append(f"fps {fps_of(stream):.1f} > {TARGET_FPS}")
    if str(stream.get("profile", "")).lower() not in ("main", "baseline", "constrained baseline"):
        reasons.append(f"profile {stream.get('profile')} heavier than Main")
    if int(stream.get("has_b_frames", 0)) > 0:
        reasons.append(f"has {stream.get('has_b_frames')} B-frame(s)")
    return reasons


def clip(name, spec):
    src = Path(os.path.expanduser(spec["src"]))
    if not src.exists():
        sys.exit(f"Source not found: {src}")
    out = OUT_DIR / f"{name}.mp4"

    print(f"== Source: {src}")
    src_stream = ffprobe_stream(src)
    print(f"   {describe(src_stream)}")

    reasons = needs_normalize(src_stream)
    normalize = spec.get("force_normalize", False) or bool(reasons)
    if reasons:
        print("   normalize because: " + "; ".join(reasons))
    elif normalize:
        print("   normalize: forced by source special case")
    else:
        print("   source is already goldeneye-class; light re-encode only")

    # Output seeking (-ss/-to AFTER -i) is frame-accurate and starts on a clean I-frame.
    cmd = ["ffmpeg", "-y", "-i", str(src),
           "-ss", str(spec["start"]), "-to", str(spec["end"])]

    filters = []
    if normalize:
        filters.append(f"scale=-2:{TARGET_HEIGHT}")
        filters.append(f"fps={TARGET_FPS}")
    if spec.get("vf_extra"):
        filters.append(spec["vf_extra"])
    if filters:
        cmd += ["-vf", ",".join(filters)]

    cmd += ["-c:v", "libx264", "-preset", "medium",
            "-crf", str(spec.get("crf", DEFAULT_CRF)), "-pix_fmt", "yuv420p"]
    if normalize:
        cmd += ["-profile:v", TARGET_PROFILE, "-level", TARGET_LEVEL, "-bf", "0", "-refs", "1"]
    if spec.get("v_extra"):
        cmd += list(spec["v_extra"])

    cmd += ["-c:a", "aac", "-movflags", "+faststart", str(out)]

    print("== Encoding: " + " ".join(cmd))
    if subprocess.run(cmd).returncode != 0:
        sys.exit("ffmpeg encode failed")

    print(f"== Wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")
    print(f"   {describe(ffprobe_stream(out))}")
    print("   Set a mode's rule: game_screen.end_video: " + out.name)


def main():
    ap = argparse.ArgumentParser(description="Clip an end-of-game video into assets/video/.")
    ap.add_argument("name", nargs="?", help="registered source name (see SOURCES)")
    ap.add_argument("--probe", metavar="PATH", help="just analyze a video and exit")
    args = ap.parse_args()

    if args.probe:
        p = Path(os.path.expanduser(args.probe))
        print(describe(ffprobe_stream(p)))
        reasons = needs_normalize(ffprobe_stream(p))
        print("normalize needed: " + ("; ".join(reasons) if reasons else "no (goldeneye-class)"))
        return

    if not args.name or args.name not in SOURCES:
        sys.exit("Give a registered source name. Known: " + ", ".join(SOURCES)
                 + "\n(or use --probe PATH to analyze a new one first)")
    clip(args.name, SOURCES[args.name])


if __name__ == "__main__":
    main()
