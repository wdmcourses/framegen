import json
import re
import subprocess
from fractions import Fraction

from .config import ffmpeg, ffprobe

_STREAM_RE = re.compile(r"\bStream #\d+:\d+[^:]*: (Video|Audio|Subtitle|Data|Attachment): ([A-Za-z0-9_]+)")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_SIZE_RE = re.compile(r"\b(\d{2,5})x(\d{2,5})\b")
_RATE_RE = re.compile(r"\b([\d.]+)\s*fps\b")
_HZ_RE = re.compile(r"\b(\d+)\s*Hz\b")
_NAMED_LAYOUTS = {"mono": 1, "stereo": 2, "quad": 4, "hexagonal": 6, "octagonal": 8}


def parse_rate(text):
    """'30000/1001' or '30' or '29.97' -> Fraction, or None."""
    if not text:
        return None
    text = str(text).strip()
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            num, den = float(num), float(den)
            if den == 0 or num == 0:
                return None
            return Fraction(num / den).limit_denominator(1000000)
        val = float(text)
        if val <= 0:
            return None
        return Fraction(val).limit_denominator(1000000)
    except (ValueError, ZeroDivisionError):
        return None


def _channels(layout):
    layout = (layout or "").strip()
    if layout in _NAMED_LAYOUTS:
        return _NAMED_LAYOUTS[layout]
    m = re.match(r"(\d+)\s+channels?", layout)
    if m:
        return int(m.group(1))
    return 2


def _probe_json(path):
    r = subprocess.run(
        [ffprobe(), "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", path],
        capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def _video_from_stream(s):
    fps = parse_rate(s.get("avg_frame_rate")) or parse_rate(s.get("r_frame_rate"))
    return {
        "codec_name": (s.get("codec_name") or "").lower(),
        "width": int(s.get("width") or 0),
        "height": int(s.get("height") or 0),
        "fps": fps,
        "nb_frames": int(s["nb_frames"]) if str(s.get("nb_frames", "")).isdigit() else None,
    }


def _audio_from_stream(s):
    return {
        "codec_name": (s.get("codec_name") or "").lower(),
        "channels": int(s.get("channels") or 2),
        "sample_rate": int(s.get("sample_rate") or 48000),
    }


def _probe_json_result(path):
    data = _probe_json(path)
    if not data:
        return None
    videos, audios, subtitles = [], [], []
    for s in data.get("streams", []):
        kind = s.get("codec_type")
        if kind == "video" and s.get("disposition", {}).get("attached_pic", 0) != 1:
            videos.append(_video_from_stream(s))
        elif kind == "audio":
            audios.append(_audio_from_stream(s))
        elif kind == "subtitle":
            subtitles.append({"index": s.get("index", 0), "codec_name": (s.get("codec_name") or "").lower()})
    if not videos:
        return None
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or 0.0) or 0.0
    if not duration and videos[0].get("nb_frames") and videos[0].get("fps"):
        duration = float(videos[0]["nb_frames"]) / float(videos[0]["fps"])
    return {"video": videos[0], "audios": audios,
            "subtitles": subtitles, "duration": duration}


def _probe_ffmpeg_result(path):
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True)
    err = r.stderr
    video = None
    audios = []
    for line in err.splitlines():
        m = _STREAM_RE.search(line)
        if not m:
            continue
        kind, codec = m.group(1).lower(), m.group(2).lower()
        if kind == "video" and video is None:
            size = _SIZE_RE.search(line)
            rate = _RATE_RE.search(line)
            video = {"codec_name": codec,
                     "width": int(size.group(1)) if size else 0,
                     "height": int(size.group(2)) if size else 0,
                     "fps": parse_rate(rate.group(1)) if rate else None,
                     "nb_frames": None}
        elif kind == "audio":
            hz = _HZ_RE.search(line)
            layout = line.split("Hz,", 1)[1].split(",")[0] if "Hz," in line else "stereo"
            audios.append({"codec_name": codec,
                           "channels": _channels(layout),
                           "sample_rate": int(hz.group(1)) if hz else 48000})
    if video is None:
        raise SystemExit("error: ffmpeg could not read a video stream from %s\n%s" % (path, err.strip()))
    dur = _DURATION_RE.search(err)
    duration = 0.0
    if dur:
        duration = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))
    return {"video": video, "audios": audios,
            "subtitles": [], "duration": duration}


def probe_media(path):
    if ffprobe():
        result = _probe_json_result(path)
        if result:
            return result
    return _probe_ffmpeg_result(path)
