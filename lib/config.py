import os
import re
import shutil
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCES_DIR = os.path.join(APP_DIR, "resources")


def platform_key():
    if sys.platform.startswith("win"):
        return "win64"
    if sys.platform == "darwin":
        return "mac"
    return "lin64"


PLATFORM_DIR = os.path.join(RESOURCES_DIR, platform_key())
MODELS_DIR = os.path.join(RESOURCES_DIR, "models")

DEFAULT_FPS = 60.0
MAX_FPS = 480.0
MIN_FPS = 1.0
THREADS = "2:2:2"

# Default NCNN model shipped with the engine (see resources/models).
DEFAULT_MODEL = "rife-v4.6"
FALLBACK_MODELS = ("rife-v4.6", "rife-v4.6-lite", "rife-anime", "rife-v4")

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
RIFE = "rife-ncnn-vulkan"

VIDEO_EXTS = frozenset({
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".flv",
    ".ts", ".mts", ".m2ts", ".m2t", ".mpg", ".mpeg", ".ogv", ".3gp",
    ".3g2", ".f4v", ".ipod", ".psp", ".ismv",
})

MP4_AUDIO = frozenset({"aac", "mp3", "ac3", "eac3", "alac", "opus"})
MKV_AUDIO = frozenset({
    "aac", "mp3", "ac3", "eac3", "opus", "vorbis", "flac", "alac", "mp2",
    "dts", "truehd", "mlp", "wmav1", "wmav2",
    "pcm_s16le", "pcm_s24le", "pcm_s16be", "pcm_s24be", "pcm_s32le", "pcm_u8",
})
WEBM_VIDEO = frozenset({"vp8", "vp9", "av1"})
WEBM_AUDIO = frozenset({"opus", "vorbis"})


def exe_name(name):
    return name + ".exe" if os.name == "nt" else name


def tool(name):
    exe = exe_name(name)
    for cand in (os.path.join(PLATFORM_DIR, exe), os.path.join(RESOURCES_DIR, exe)):
        if os.path.isfile(cand):
            return cand
    found = shutil.which(name)
    if found:
        return found
    raise SystemExit("error: %s not found (expected in %s or on PATH)" % (name, PLATFORM_DIR))


_FFMPEG = None
_FFPROBE = None
_FFMPEG_VER = None


def ffmpeg():
    global _FFMPEG
    if _FFMPEG is None:
        _FFMPEG = tool(FFMPEG)
    return _FFMPEG


def ffmpeg_version():
    """(major, minor) of the resolved ffmpeg, or (0, 0) when unknown."""
    global _FFMPEG_VER
    if _FFMPEG_VER is None:
        _FFMPEG_VER = (0, 0)
        try:
            r = subprocess.run([ffmpeg(), "-hide_banner", "-version"],
                               capture_output=True, text=True)
            m = re.search(r"ffmpeg version (\d+)\.(\d+)", r.stdout)
            if m:
                _FFMPEG_VER = (int(m.group(1)), int(m.group(2)))
        except OSError:
            pass
    return _FFMPEG_VER


def ffprobe():
    """ffprobe path, or None when only ffmpeg is bundled."""
    global _FFPROBE
    if _FFPROBE is None:
        try:
            _FFPROBE = tool(FFPROBE)
        except SystemExit:
            _FFPROBE = ""
    return _FFPROBE or None


def rife():
    return tool(RIFE)


def model_path(name=None):
    name = name or DEFAULT_MODEL
    for cand in (name,) + (FALLBACK_MODELS if name == DEFAULT_MODEL else ()):
        path = os.path.join(MODELS_DIR, cand)
        if os.path.isdir(path):
            return path
    available = []
    if os.path.isdir(MODELS_DIR):
        available = sorted(d for d in os.listdir(MODELS_DIR)
                           if os.path.isdir(os.path.join(MODELS_DIR, d)))
    raise SystemExit("error: model '%s' not found in %s%s"
                     % (name, MODELS_DIR,
                        ("\navailable: " + ", ".join(available)) if available else ""))
