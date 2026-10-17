import argparse
import os
import sys

from .config import DEFAULT_FPS, MAX_FPS, MIN_FPS, VIDEO_EXTS, ffmpeg
from .convert import convert


def collect_inputs(path):
    files = []
    for root, dirs, names in os.walk(path):
        dirs.sort()
        for name in sorted(names):
            if os.path.splitext(name)[1].lower() in VIDEO_EXTS:
                files.append(os.path.join(root, name))
    return files


def _unbuffered():
    """Flush on every newline so hosts see progress while we run."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except (AttributeError, ValueError):
            pass


def main():
    _unbuffered()
    ap = argparse.ArgumentParser(
        prog="framegen",
        description="Raise any video to a target frame rate (default 60 fps) with "
                    "neural frame interpolation (RIFE). Fully self-contained.")
    ap.add_argument("input", help="input video file or folder (with -r)")
    ap.add_argument("-f", "--fps", type=float, default=DEFAULT_FPS, metavar="FPS",
                    help="target frame rate (default %(default)s)")
    ap.add_argument("-o", "--output", help="output file (single input only)")
    ap.add_argument("-r", "--recursive", action="store_true",
                    help="process every video in a folder, recursively")
    ap.add_argument("-q", "--quiet", action="store_true", help="only print the output path")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="emit machine-readable progress lines for host apps")

    # Everything else is tuned automatically; these knobs still work but are
    # kept out of --help so the interface stays as simple as the job.
    hidden = dict(help=argparse.SUPPRESS)
    ap.add_argument("-c", "--codec", default="h264", **hidden)
    ap.add_argument("--crf", type=int, default=18, **hidden)
    ap.add_argument("-g", "--gpu", default="auto", **hidden)
    ap.add_argument("-e", "--engine", choices=["auto", "rife", "ffmpeg"],
                    default="auto", **hidden)
    ap.add_argument("-m", "--model", **hidden)
    ap.add_argument("--preset", default="medium", **hidden)
    ap.add_argument("--hw", choices=["auto", "nvenc", "none"], default="auto", **hidden)
    ap.add_argument("--lossless", action="store_true", **hidden)
    ap.add_argument("--faststart", action="store_true", **hidden)
    ap.add_argument("--frame-format", choices=["png", "webp"], default="png", **hidden)
    ap.add_argument("--tta", action="store_true", **hidden)
    ap.add_argument("--keep-temp", action="store_true", **hidden)
    ap.add_argument("--temp-dir", **hidden)
    args = ap.parse_args()

    if not MIN_FPS <= args.fps <= MAX_FPS:
        raise SystemExit("error: -f/--fps must be between %g and %g" % (MIN_FPS, MAX_FPS))
    ffmpeg()

    common = dict(target_fps=args.fps, model=args.model, gpu=args.gpu,
                  engine=args.engine, vcodec=args.codec, crf=args.crf,
                  preset=args.preset, hw=args.hw, tta=args.tta,
                  keep_temp=args.keep_temp, temp_dir=args.temp_dir, quiet=args.quiet,
                  faststart=args.faststart, lossless=args.lossless,
                  frame_format=args.frame_format, verbose=args.verbose)

    path = os.path.abspath(args.input)
    if not args.recursive:
        if not os.path.isfile(path):
            raise SystemExit("error: input not found: %s" % path)
        res = convert(path, output=args.output, **common)
        if args.quiet:
            print(res["output"])
        return

    if not os.path.isdir(path):
        raise SystemExit("error: -r requires a folder: %s" % path)
    if args.output:
        raise SystemExit("error: -o cannot be used with -r")
    inputs = collect_inputs(path)
    if not inputs:
        raise SystemExit("error: no supported video files found in %s" % path)

    done = 0
    failed = 0
    frames = 0
    seconds = 0.0
    for i, item in enumerate(inputs, 1):
        if not args.quiet:
            print("[%d/%d] %s" % (i, len(inputs), item))
        try:
            res = convert(item, output=None, detail=args.verbose, **common)
            done += 1
            frames += res["frames_out"]
            seconds += res["seconds"]
            if args.quiet:
                print(res["output"])
        except (SystemExit, Exception) as exc:
            failed += 1
            text = str(exc).strip()
            reason = (text.splitlines()[0] if text
                      else "%s (no message)" % type(exc).__name__)
            if not args.quiet:
                print("skipped    : %s (%s)" % (item, reason))
    if not args.quiet:
        print("summary    : %d processed, %d skipped, %d frame(s) written, %.1f s"
              % (done, failed, frames, seconds))
    if done == 0:
        sys.exit(1)
