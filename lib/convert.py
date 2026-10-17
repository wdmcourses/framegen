import os
import shutil
import subprocess
import sys
import tempfile
import time

from . import rife as rife_mod
from .config import WEBM_VIDEO, ffmpeg, ffmpeg_version
from .encode import (MOVENC_EXT, audio_args, container_args, encoder,
                     filter_args, input_args, pick_container, subtitle_plan,
                     video_args)
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


def _run_ffmpeg_progress(cmd, total, progress, err="error: ffmpeg failed"):
    log = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log,
                                text=True, bufsize=1)
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("frame="):
                val = line.split("=", 1)[1]
                if val.isdigit() and progress is not None:
                    progress.update(int(val))
        proc.wait()
        if proc.returncode != 0:
            log.seek(0)
            tail = [l for l in log.read().strip().splitlines() if l.strip()][-5:]
            raise SystemExit("%s\n%s" % (err, "\n".join(tail)) if tail else err)
    finally:
        log.close()
    if progress is not None:
        progress.update(total or progress.total, force=True)


def _count_frames(directory, ext="png"):
    suffix = "." + ext
    return len([n for n in os.listdir(directory) if n.lower().endswith(suffix)])


def _verify_output(out):
    """A zero-exit ffmpeg can still leave an empty file behind (minterpolate
    does it when there is a single frame), so confirm a video really is there."""
    if not os.path.isfile(out) or os.path.getsize(out) == 0:
        raise SystemExit("error: nothing was written to %s" % out)
    probe_media(out)


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
    _run_ffmpeg_progress(cmd, n_expected, progress,
                         "error: ffmpeg could not decode %s" % src)


def _encode_from_frames(frames_dir, fps, src, out, vcodec, acodecs, subs,
                        ext, crf, preset, hw, n_out, progress,
                        frame_ext="png", faststart=False, lossless=False):
    enc = encoder(vcodec, "none" if lossless else hw)
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-v", "error", "-progress", "pipe:1"]
    cmd += input_args(enc)
    cmd += ["-framerate", "%g" % float(fps), "-start_number", "1",
            "-i", os.path.join(frames_dir, "%08d." + frame_ext)]
    if src is not None:
        cmd += ["-i", src]

    filters = filter_args(enc)
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += ["-map", "0:v:0"]

    if src is not None and acodecs:
        cmd += ["-map", "1:a"]
        cmd += audio_args(ext, acodecs)

    sub_codec, sub_idx = subs
    if src is not None and sub_codec:
        for idx in sub_idx:
            cmd += ["-map", "1:%d" % idx]
        cmd += ["-c:s", sub_codec]

    cmd += video_args(enc, crf, preset, lossless)
    if faststart and ext in MOVENC_EXT:
        cmd += ["-movflags", "+faststart"]
    cmd += container_args(ext, vcodec)
    cmd += ["-map_metadata", "1" if src is not None else "0",
            "-map_chapters", "1" if src is not None else "0", "-y", out]
    _run_ffmpeg_progress(cmd, n_out, progress,
                         "error: ffmpeg could not write %s" % out)


def _ffmpeg_engine(src, out, fps, vcodec, acodecs, subs, ext, crf, preset, hw,
                   duration, progress, interpolate=True, faststart=False,
                   lossless=False):
    """The fallback engine: minterpolate when frames must be synthesised, a
    plain rate conversion when frames only have to be dropped."""
    frames = int(round(duration * float(fps))) if duration else 0
    enc = encoder(vcodec, "none" if lossless else hw)
    if interpolate:
        filters = ["minterpolate=fps=%g:mi_mode=mci:mc_mode=aobmc:"
                   "me_mode=bidir:vsbmc=1" % float(fps)]
    else:
        filters = ["fps=%g" % float(fps)]
    filters += filter_args(enc)
    if progress is not None:
        progress.start(frames)
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-v", "error", "-progress", "pipe:1"]
    cmd += input_args(enc)
    cmd += ["-i", src, "-vf", ",".join(filters), "-map", "0:v:0"]
    if acodecs:
        cmd += ["-map", "0:a"]
        cmd += audio_args(ext, acodecs)
    sub_codec, sub_idx = subs
    if sub_codec:
        for idx in sub_idx:
            cmd += ["-map", "0:%d" % idx]
        cmd += ["-c:s", sub_codec]
    cmd += video_args(enc, crf, preset, lossless)
    if faststart and ext in MOVENC_EXT:
        cmd += ["-movflags", "+faststart"]
    cmd += container_args(ext, vcodec)
    cmd += ["-map_metadata", "0", "-map_chapters", "0", "-y", out]
    _run_ffmpeg_progress(cmd, frames, progress,
                         "error: ffmpeg could not write %s" % out)


def _same_dir(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _default_output(path, ext, fps):
    out_dir = os.getcwd()
    src_dir = os.path.dirname(os.path.abspath(path))
    root, _ = os.path.splitext(os.path.basename(path))
    suffix = "_%gfps" % float(fps) if _same_dir(src_dir, out_dir) else ""
    return os.path.join(out_dir, root + suffix + ext)


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


_ENGINE = None


def _probe_engine(model=None):
    """A bundled rife binary still has to *run*: on a machine without a usable
    GPU it exits non-zero, so the engine has to fall back to minterpolate."""
    work = tempfile.mkdtemp(prefix="framegen_engine_")
    try:
        src = os.path.join(work, "in")
        out = os.path.join(work, "out")
        os.makedirs(src)
        os.makedirs(out)
        cmd = [ffmpeg(), "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
               "-i", "color=c=black:s=64x64:r=1", "-frames:v", "2",
               os.path.join(src, "%08d.png")]
        try:
            if subprocess.run(cmd, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=60).returncode:
                return False
            cmd = rife_mod.command(src, out, 3, model=model)
            return subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=120).returncode == 0
        except (OSError, subprocess.TimeoutExpired, SystemExit):
            return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _engine_available(model=None):
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = _probe_engine(model)
    return _ENGINE


def _encode_retry(run, vcodec, hw, lossless, quiet):
    """Run an encode; if the auto-picked hardware encoder fails on this input,
    retry in software instead of leaving a broken file behind."""
    try:
        run(hw)
    except SystemExit:
        if hw != "auto" or not encoder(vcodec, "none" if lossless else hw).hardware:
            raise
        if not quiet:
            print("warning    : hardware encoder failed, retrying in software")
        run("none")


def convert(path, target_fps, output=None, model=None, gpu="auto", engine="auto",
            vcodec=None, crf=18, preset="medium", hw="auto", tta=False,
            keep_temp=False, temp_dir=None, quiet=False, faststart=False,
            lossless=False, frame_format="png", verbose=False, detail=True):
    src = os.path.abspath(path)
    if not os.path.isfile(src):
        raise SystemExit("error: input not found: %s" % src)

    info = probe_media(src)
    video = info["video"]
    audios = info["audios"]
    acodecs = [a["codec_name"] for a in audios]
    src_fps = video["fps"]
    width, height = video["width"], video["height"]
    duration = info["duration"]
    n_in = video["nb_frames"]
    if not n_in and duration and src_fps:
        n_in = int(round(duration * float(src_fps)))

    plan = build_plan(src_fps, target_fps)
    vcodec = (vcodec or "h264").lower()
    frame_ext = frame_format.lower()
    if frame_ext not in FRAME_CODECS:
        raise SystemExit("error: unknown frame format '%s'" % frame_format)

    ext = pick_container(vcodec, acodecs, os.path.splitext(src)[1])
    out = output or _default_output(src, ext, target_fps)
    out = _unique(os.path.abspath(out))
    ext = os.path.splitext(out)[1].lower()

    parent = os.path.dirname(out)
    if parent and not os.path.isdir(parent):
        raise SystemExit("error: output folder does not exist: %s" % parent)
    if temp_dir and not os.path.isdir(temp_dir):
        raise SystemExit("error: temp folder does not exist: %s" % temp_dir)
    if ext == ".webm" and vcodec not in WEBM_VIDEO:
        raise SystemExit("error: %s video cannot be stored in WebM "
                         "(use -c vp9 or another container)" % vcodec)

    subs = subtitle_plan(ext, [(s["index"], s["codec_name"])
                               for s in info.get("subtitles", [])])

    engine_note = ""
    forced_engine = engine == "rife"
    if engine == "auto":
        if plan.interpolate and _engine_available(model):
            engine = "rife"
        else:
            engine = "ffmpeg"
            if plan.interpolate:
                engine_note = " (rife unavailable)"
    if engine == "rife" and not _engine_available(model):
        raise SystemExit("error: rife is not usable on this machine "
                         "(no GPU or missing model); try --engine ffmpeg")

    if not quiet and detail:
        print("input      : %s" % src)
        print("video      : %s %dx%d, %s fps" % (video["codec_name"], width, height,
                                                 _fmt_fps(src_fps)))
        if audios:
            note = "" if len(audios) == 1 else " (+%d more)" % (len(audios) - 1)
            print("audio      : %s %s Hz, %s ch%s" % (audios[0]["codec_name"],
                                                     audios[0]["sample_rate"],
                                                     audios[0]["channels"], note))
        else:
            print("audio      : none")
        print("target     : %g fps (%s)" % (float(target_fps),
              ("x%s -> interpolate" % _fmt_ratio(plan.ratio)) if plan.interpolate else "resample only"))
        print("engine     : %s%s%s" % (engine, engine_note,
                                       " (lossless)" if lossless else ""))
        try:
            enc = encoder(vcodec, "none" if lossless else hw)
            print("encoder    : %s (%s)" % (enc.name, "GPU" if enc.hardware else "CPU"))
        except SystemExit:
            pass

    dropped = len(info.get("subtitles", [])) - len(subs[1])
    if dropped and not quiet:
        print("warning    : %d subtitle track(s) cannot be stored in %s and were dropped"
              % (dropped, ext))

    def _ffmpeg_path(interpolate=None):
        t0 = time.time()
        pr = _progress("interpolate", quiet, verbose)
        try:
            _encode_retry(
                lambda h: _ffmpeg_engine(
                    src, out, target_fps, vcodec, acodecs, subs, ext, crf,
                    preset, h, duration, pr if not quiet else None,
                    interpolate=plan.interpolate if interpolate is None else interpolate,
                    faststart=faststart, lossless=lossless),
                vcodec, hw, lossless, quiet)
        finally:
            pr.close()
        _verify_output(out)
        if not quiet:
            if detail:
                print("output     : %s" % out)
            else:
                print("  %-40s -> %s" % (os.path.basename(src), os.path.basename(out)))
        frames = int(round(duration * float(target_fps))) if duration else 0
        return {"output": out, "frames_in": n_in or 0, "frames_out": frames,
                "seconds": time.time() - t0}

    if engine == "ffmpeg":
        return _ffmpeg_path()

    work_root = temp_dir or tempfile.gettempdir()
    try:
        work = tempfile.mkdtemp(prefix="framegen_", dir=work_root)
    except OSError as exc:
        raise SystemExit("error: cannot create a temp folder in %s (%s)"
                         % (work_root, exc))
    if keep_temp and not quiet:
        print("temp       : %s" % work)
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
        if n_frames < 2:
            if not quiet:
                print("warning    : %d frame(s) only, nothing to interpolate; "
                      "converting the frame rate instead" % n_frames)
            return _ffmpeg_path(interpolate=False)
        t_decode = time.time() - t0

        n_out = plan.out_count(n_frames)
        n_out = max(n_out, n_frames)
        t0 = time.time()
        rp = _progress("interpolate", quiet, verbose)
        try:
            rife_mod.run(work_in, work_out, n_out, model=model, gpu=gpu,
                         tta=tta, ext=frame_ext, progress=rp if not quiet else None)
        except SystemExit:
            if forced_engine:
                raise
            if not quiet:
                print("warning    : interpolation engine failed, retrying with the ffmpeg fallback")
            return _ffmpeg_path()
        finally:
            rp.close()
        t_rife = time.time() - t0

        produced = _count_frames(work_out, frame_ext)
        t0 = time.time()
        ep = _progress("encode", quiet, verbose)
        ep.start(produced)
        try:
            _encode_retry(
                lambda h: _encode_from_frames(
                    work_out, target_fps, src, out, vcodec, acodecs, subs, ext,
                    crf, preset, h, produced,
                    ep if not quiet else None, frame_ext=frame_ext,
                    faststart=faststart, lossless=lossless),
                vcodec, hw, lossless, quiet)
        finally:
            ep.close()
        t_encode = time.time() - t0
        _verify_output(out)
        elapsed = t_decode + t_rife + t_encode
        if not quiet:
            if detail:
                print("frames     : %d -> %d" % (n_frames, produced))
                print("time       : decode %.1fs, interpolate %.1fs, encode %.1fs, total %.1fs"
                      % (t_decode, t_rife, t_encode, elapsed))
                print("output     : %s" % out)
            else:
                print("  %-40s %d -> %d frames, %.1fs -> %s"
                      % (os.path.basename(src), n_frames, produced, elapsed,
                         os.path.basename(out)))
        return {"output": out, "frames_in": n_frames, "frames_out": produced,
                "seconds": elapsed}
    finally:
        if not keep_temp:
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
