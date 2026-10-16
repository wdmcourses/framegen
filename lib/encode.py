import os
import subprocess
import sys

from .config import (MKV_AUDIO, MP4_AUDIO, WEBM_AUDIO, ffmpeg,
                     ffmpeg_version)

MOVENC_EXT = (".mp4", ".m4v", ".mov")

# codec -> ordered software (encoder, pix_fmt) candidates.
SOFTWARE = {
    "h264": (("libx264", "yuv420p"),),
    "h265": (("libx265", "yuv420p"),),
    "hevc": (("libx265", "yuv420p"),),
    "av1": (("libsvtav1", "yuv420p"), ("libaom-av1", "yuv420p")),
    "vp9": (("libvpx-vp9", "yuv420p"),),
    "vp8": (("libvpx", "yuv420p"),),
    "ffv1": (("ffv1", "yuv420p"),),
}

# Hardware candidates per OS, best first. Every one is *probed* with a real
# one-frame encode before use, so a listed-but-unusable encoder (no driver, no
# hardware, wrong GPU) silently falls through to software.
HW = {
    "win32": {
        "h264": ("h264_nvenc", "h264_amf", "h264_qsv"),
        "h265": ("hevc_nvenc", "hevc_amf", "hevc_qsv"),
        "hevc": ("hevc_nvenc", "hevc_amf", "hevc_qsv"),
        "av1": ("av1_nvenc", "av1_amf", "av1_qsv"),
    },
    "linux": {
        "h264": ("h264_nvenc", "h264_vaapi", "h264_qsv"),
        "h265": ("hevc_nvenc", "hevc_vaapi", "hevc_qsv"),
        "hevc": ("hevc_nvenc", "hevc_vaapi", "hevc_qsv"),
        "av1": ("av1_nvenc", "av1_vaapi", "av1_qsv"),
    },
    "darwin": {
        "h264": ("h264_videotoolbox",),
        "h265": ("hevc_videotoolbox",),
        "hevc": ("hevc_videotoolbox",),
    },
}

NVENC = {"h264": "h264_nvenc", "h265": "hevc_nvenc", "hevc": "hevc_nvenc",
         "av1": "av1_nvenc"}

_AVAILABLE = None
_PROBED = {}


class Enc(object):
    """A resolved video encoder and how to drive it."""

    __slots__ = ("name", "pix", "device", "upload")

    def __init__(self, name, pix="yuv420p", device=None, upload=False):
        self.name = name
        self.pix = pix
        self.device = device        # VAAPI render node (global option)
        self.upload = upload        # needs format=...,hwupload

    @property
    def hardware(self):
        return self.name.endswith(("_nvenc", "_amf", "_qsv", "_vaapi", "_videotoolbox"))


def os_name():
    if sys.platform.startswith("win"):
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def available_encoders():
    global _AVAILABLE
    if _AVAILABLE is None:
        names = set()
        try:
            r = subprocess.run([ffmpeg(), "-hide_banner", "-encoders"],
                               capture_output=True, text=True)
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].startswith("V"):
                    names.add(parts[1])
        except OSError:
            pass
        _AVAILABLE = names
    return _AVAILABLE


def _make(name):
    if name.endswith("_vaapi"):
        device = os.environ.get("FRAMEGEN_VAAPI_DEVICE", "/dev/dri/renderD128")
        return Enc(name, pix="nv12", device=device, upload=True)
    return Enc(name)


def input_args(enc):
    """Global options that must precede the first -i."""
    if enc.device:
        return ["-vaapi_device", enc.device]
    return []


def filter_args(enc):
    """Extra output filters required by the encoder."""
    if enc.upload:
        return ["format=nv12,hwupload"]
    return []


def _probe(name):
    if name in _PROBED:
        return _PROBED[name]
    if name not in available_encoders():
        _PROBED[name] = False
        return False
    enc = _make(name)
    cmd = [ffmpeg(), "-hide_banner", "-v", "error"] + input_args(enc)
    cmd += ["-f", "lavfi", "-i", "color=c=black:s=256x256:r=1:d=0.1", "-frames:v", "1"]
    if enc.upload:
        cmd += ["-vf", ",".join(filter_args(enc))]
    cmd += video_args(enc, 23, "medium", False) + ["-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20)
        ok = r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    _PROBED[name] = ok
    return ok


def _software(codec):
    candidates = SOFTWARE.get(codec)
    if not candidates:
        raise SystemExit("error: unknown video codec '%s'" % codec)
    available = available_encoders()
    for name, pix in candidates:
        if not available or name in available:
            return Enc(name, pix)
    raise SystemExit("error: none of %s is available in this ffmpeg build"
                     % ", ".join(c[0] for c in candidates))


def encoder(codec, hw):
    """Resolve an :class:`Enc`. hw: auto|nvenc|none."""
    codec = (codec or "h264").lower()
    if hw == "none":
        return _software(codec)
    if hw == "nvenc":
        name = NVENC.get(codec)
        if not name or not _probe(name):
            raise SystemExit("error: NVENC encoder for codec '%s' is not usable" % codec)
        return _make(name)
    for name in HW.get(os_name(), {}).get(codec, ()):
        if _probe(name):
            return _make(name)
    return _software(codec)


def pick_container(vcodec, acodec, src_ext):
    """Choose an output container that can hold the video and (copied) audio."""
    ext = (src_ext or "").lower()
    if (vcodec or "").lower() == "ffv1":
        return ".mkv"
    if acodec is None:
        return ext if ext in (".mp4", ".mkv", ".mov", ".webm") else ".mp4"
    if acodec in ("opus", "vorbis"):
        return ".webm" if ext == ".webm" else ".mkv"
    if acodec in MP4_AUDIO and ext in MOVENC_EXT:
        return ext
    if acodec in MP4_AUDIO:
        return ".mp4"
    if acodec in MKV_AUDIO:
        return ".mkv"
    return ".mkv"


def audio_copy_ok(ext, acodec):
    if acodec is None:
        return True
    if ext in MOVENC_EXT:
        return acodec in MP4_AUDIO
    if ext == ".webm":
        return acodec in WEBM_AUDIO
    if ext == ".mkv":
        return acodec in MKV_AUDIO
    return False


def subtitle_codec(ext, scodec):
    if ext == ".mkv":
        return "copy"
    if ext in MOVENC_EXT:
        if scodec in ("mov_text", "tx3g"):
            return "copy"
        return "mov_text"
    if ext == ".webm":
        return "webvtt" if scodec != "webvtt" else "copy"
    return None


def _nvenc_preset(preset):
    modern = ffmpeg_version() >= (5, 0)
    if preset in ("medium", "slow", "slower", "veryslow"):
        return "p5" if modern else "medium"
    return "p4" if modern else "fast"


def _vt_quality(crf):
    return max(1, min(100, 100 - int(crf * 1.8)))


def video_args(enc, crf, preset, lossless=False):
    name = enc.name
    args = ["-c:v", name]
    if not enc.upload:
        args += ["-pix_fmt", enc.pix]
    if lossless:
        if name == "libx264":
            return args + ["-qp", "0"]
        if name == "libx265":
            return args + ["-x265-params", "lossless=1"]
        if name == "ffv1":
            return args + ["-level", "3", "-g", "1"]
        if name.endswith("_nvenc"):
            return args + ["-tune", "lossless", "-rc", "constqp", "-qp", "0"]
        return args + ["-crf", "0"]
    if name == "ffv1":
        return args
    if name.endswith("_nvenc"):
        args += ["-preset", _nvenc_preset(preset), "-cq", str(crf), "-rc", "vbr"]
    elif name.endswith("_amf"):
        args += ["-quality", "quality", "-rc", "cqp",
                 "-qp_i", str(crf), "-qp_p", str(crf), "-qp_b", str(crf)]
    elif name.endswith("_qsv"):
        args += ["-global_quality", str(crf), "-look_ahead", "1"]
    elif name.endswith("_vaapi"):
        args += ["-rc_mode", "CQP", "-qp", str(crf)]
    elif name.endswith("_videotoolbox"):
        args += ["-q:v", str(_vt_quality(crf))]
    elif name == "libsvtav1":
        args += ["-crf", str(crf), "-preset", "6"]
    elif name == "libaom-av1":
        args += ["-crf", str(crf), "-b:v", "0", "-cpu-used", "6"]
    elif name in ("libvpx-vp9", "libvpx"):
        args += ["-crf", str(crf), "-b:v", "0"]
    else:
        args += ["-preset", preset, "-crf", str(crf)]
    return args
