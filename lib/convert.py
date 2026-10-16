import os
import shutil
import subprocess
import sys
import tempfile
import time

from . import rife as rife_mod
from .config import ffmpeg, ffmpeg_version
from .encode import (MOVENC_EXT, audio_copy_ok, encoder, filter_args,
                     input_args, pick_container, subtitle_codec, video_args)
from .plan import build_plan
from .probe import probe_media
from .progress import Progress

FRAME_CODECS = {
    "png": ["-c:v", "png"],
    "webp": ["-c:v", "libwebp", "-lossless", "1", "-compression_level", "0"],
}


def _progress(label, quiet, verbose):
    """Pick a progress reporter: line mode when --verbose, bar on a TTY."""
    if quiet:
        return Progress(label, enabled=False)
    if verbose:
        return Progress(label, stream=sys.stdout, mode="lines")
    return Progress(label)


def _run_ffmpeg_progress(cmd, total, progress):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, bufsize=1)
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("frame="):
            val = line.split("=", 1)[1]
            if val.isdigit() and progress is not None:
                progress.update(int(val))
    proc.wait()
    if proc.returncode != 0:
        raise SystemExit("error: ffmpeg failed while writing output")
    if progress is not None:
        progress.update(total or progress.total, force=True)


def _count_frames(directory, ext="png"):
    suffix = "." + ext
    return len([n for n in os.listdir(directory) if n.lower().endswith(suffix)])


def _fps_passthrough():
    """Keep the decoded frame count exact; the option name depends on ffmpeg."""
    if ffmpeg_version() >= (5, 0):
        return ["-fps_mode", "passthrough"]
    return ["-vsync", "0"]


def _decode_frames(src, work_in, n_expected, progress, frame_ext):
    os.makedirs(work_in, exist_ok=True)
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-v", "error",
           "-progress", "pipe:1", "-i", src, "-map", "0:v:0"]
    cmd += _fps_passthrough()
    cmd += ["-start_number", "1"]
    cmd += FRAME_CODECS.get(frame_ext, FRAME_CODECS["png"])
    cmd += [os.path.join(work_in, "%08d." + frame_ext)]
    _run_ffmpeg_progress(cmd, n_expected, progress)


def _encode_from_frames(frames_dir, fps, src, out, vcodec, acodec, scodecs,
                        ext, crf, preset, hw, retime, n_out, progress,
                        frame_ext="png", faststart=False, lossless=False):
    enc = encoder(vcodec, "none" if lossless else hw)
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-v", "error", "-progress", "pipe:1"]
    cmd += input_args(enc)
    cmd += ["-framerate", "%g" % float(fps), "-start_number", "1",
            "-i", os.path.join(frames_dir, "%08d." + frame_ext)]
    if src is not None:
        cmd += ["-i", src]

    filters = []
    if retime is not None:
        filters.append("fps=%g" % float(retime))
    filters += filter_args(enc)
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += ["-map", "0:v:0"]

    if src is not None and acodec is not None:
        cmd += ["-map", "1:a:0?"]
        if audio_copy_ok(ext, acodec):
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "192k"]

    if src is not None and scodecs:
        cmd += ["-map", "1:s?"]
        want = None
        for sc in scodecs:
            cand = subtitle_codec(ext, sc)
            if cand:
                want = cand
                break
        if want:
            cmd += ["-c:s", want]

    enc = encoder(vcodec, "none" if lossless else hw)
    cmd += video_args(enc, crf, preset, lossless)
    if faststart and ext in MOVENC_EXT:
        cmd += ["-movflags", "+faststart"]
    cmd += ["-map_metadata", "0", "-map_chapters", "0", "-y", out]
    _run_ffmpeg_progress(cmd, n_out, progress)


def _minterpolate(src, out, fps, vcodec, acodec, scodecs, ext, crf, preset, hw,
                  duration, progress, faststart=False, lossless=False):
    frames = int(round(duration * float(fps))) if duration else 0
    enc = encoder(vcodec, "none" if lossless else hw)
    filters = ["minterpolate=fps=%g:mi_mode=mci:mc_mode=aobmc:"
               "me_mode=bidir:vsbmc=1" % float(fps)]
    filters += filter_args(enc)
    if progress is not None:
        progress.start(frames)
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-v", "error", "-progress", "pipe:1"]
    cmd += input_args(enc)
    cmd += ["-i", src, "-vf", ",".join(filters), "-map", "0:v:0"]
    if acodec is not None:
        cmd += ["-map", "0:a:0?"]
        if audio_copy_ok(ext, acodec):
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
    if scodecs:
        cmd += ["-map", "0:s?"]
        want = None
        for sc in scodecs:
            cand = subtitle_codec(ext, sc)
            if cand:
                want = cand
                break
        if want:
            cmd += ["-c:s", want]
    cmd += video_args(enc, crf, preset, lossless)
    if faststart and ext in MOVENC_EXT:
        cmd += ["-movflags", "+faststart"]
    cmd += ["-map_metadata", "0", "-map_chapters", "0", "-y", out]
    _run_ffmpeg_progress(cmd, frames, progress)


def _default_output(path, ext, fps, where=None):
    root, _ = os.path.splitext(os.path.basename(path))
    return os.path.join(where or os.getcwd(), "%s_%gfps%s" % (root, float(fps), ext))


def _unique(path):
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    n = 1
    while True:
        cand = "%s (%d)%s" % (root, n, ext)
        if not os.path.exists(cand):
            sys.stderr.write("warning: %s exists, writing to %s\n"
                             % (os.path.basename(path), os.path.basename(cand)))
            sys.stderr.flush()
            return cand
        n += 1


def _engine_available():
    try:
        rife_mod.rife()
        return True
    except SystemExit:
        return False


def convert(path, target_fps, output=None, model=None, gpu="auto", engine="auto",
            vcodec=None, crf=18, preset="medium", hw="auto", tta=False,
            keep_temp=False, temp_dir=None, quiet=False, faststart=False,
            lossless=False, frame_format="png", verbose=False, next_to_input=False):
    src = os.path.abspath(path)
    if not os.path.isfile(src):
        raise SystemExit("error: input not found: %s" % src)

    info = probe_media(src)
    video = info["video"]
    audio = info["audio"]
    src_fps = video["fps"]
    width, height = video["width"], video["height"]
    duration = info["duration"]
    n_in = video["nb_frames"]
    if not n_in and duration and src_fps:
        n_in = int(round(duration * float(src_fps)))

    plan = build_plan(src_fps, target_fps, n_in or 0)
    vcodec = (vcodec or "h264").lower()
    frame_ext = frame_format.lower()
    if frame_ext not in FRAME_CODECS:
        raise SystemExit("error: unknown frame format '%s'" % frame_format)

    ext = pick_container(vcodec, audio["codec_name"] if audio else None,
                         os.path.splitext(src)[1])
    out = output or _default_output(src, ext, target_fps,
                                    os.path.dirname(src) if next_to_input else None)
    out = _unique(os.path.abspath(out))
    ext = os.path.splitext(out)[1].lower()

    acodec = audio["codec_name"] if audio else None
    scodecs = [s["codec_name"] for s in info.get("subtitles", [])]

    if engine == "auto":
        if plan.interpolate and _engine_available():
            engine = "rife"
        else:
            engine = "ffmpeg"
    if engine == "rife" and not _engine_available():
        raise SystemExit("error: rife-ncnn-vulkan not found; try --engine ffmpeg")

    if not quiet:
        print("input      : %s" % src)
        print("video      : %s %dx%d, %s fps" % (video["codec_name"], width, height,
                                                 _fmt_fps(src_fps)))
        print("audio      : %s" % (("%s %s Hz, %s ch" % (acodec, audio["sample_rate"], audio["channels"]))
                                   if audio else "none"))
        print("target     : %g fps (%s)" % (float(target_fps),
              ("x%s -> interpolate" % _fmt_ratio(plan.ratio)) if plan.interpolate else "resample only"))
        print("engine     : %s%s" % (engine, " (lossless)" if lossless else ""))
        try:
            print("encoder    : %s" % encoder(vcodec, "none" if lossless else hw).name)
        except SystemExit:
            pass

    if engine == "ffmpeg":
        pr = _progress("interpolate", quiet, verbose)
        try:
            _minterpolate(src, out, target_fps, vcodec, acodec, scodecs, ext,
                          crf, preset, hw, duration, pr if not quiet else None,
                          faststart=faststart, lossless=lossless)
        finally:
            pr.close()
        if not quiet:
            print("output     : %s" % out)
        return out

    work_root = temp_dir or tempfile.gettempdir()
    work = tempfile.mkdtemp(prefix="framegen_", dir=work_root)
    work_in = os.path.join(work, "in")
    work_out = os.path.join(work, "out")
    try:
        t0 = time.time()
        dp = _progress("decode", quiet, verbose)
        dp.start(n_in or 0)
        try:
            _decode_frames(src, work_in, n_in or 0, dp if not quiet else None, frame_ext)
        finally:
            dp.close()
        n_frames = _count_frames(work_in, frame_ext)
        if n_frames == 0:
            raise SystemExit("error: no frames were decoded from %s" % src)
        t_decode = time.time() - t0

        n_out = plan.out_count(n_frames)
        n_out = max(n_out, n_frames)
        t0 = time.time()
        rp = _progress("interpolate", quiet, verbose)
        try:
            rife_mod.run(work_in, work_out, n_out, model=model, gpu=gpu,
                         tta=tta, ext=frame_ext, progress=rp if not quiet else None)
        finally:
            rp.close()
        t_rife = time.time() - t0

        produced = _count_frames(work_out, frame_ext)
        t0 = time.time()
        ep = _progress("encode", quiet, verbose)
        ep.start(produced)
        try:
            _encode_from_frames(work_out, target_fps, src, out, vcodec, acodec,
                                scodecs, ext, crf, preset, hw, None, produced,
                                ep if not quiet else None, frame_ext=frame_ext,
                                faststart=faststart, lossless=lossless)
        finally:
            ep.close()
        t_encode = time.time() - t0
        if not quiet:
            print("frames     : %d -> %d" % (n_frames, produced))
            print("time       : decode %.1fs, interpolate %.1fs, encode %.1fs, total %.1fs"
                  % (t_decode, t_rife, t_encode, t_decode + t_rife + t_encode))
            print("output     : %s" % out)
        return out
    finally:
        if keep_temp:
            print("temp       : %s" % work)
        else:
            shutil.rmtree(work, ignore_errors=True)


def _fmt_fps(fps):
    if fps is None:
        return "?"
    val = float(fps)
    if abs(val - round(val)) < 1e-3:
        return str(int(round(val)))
    return "%.3f" % val


def _fmt_ratio(ratio):
    val = float(ratio)
    if abs(val - round(val)) < 1e-3:
        return str(int(round(val)))
    return "%.3f" % val
