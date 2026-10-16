"""Build lean, pinnable mirror archives for `framegen -i`.

Downloads the *pinned* upstream engine release and repacks only what is needed
(the engine executable + its runtime DLLs) plus the chosen model folders, so the
published mirror stays small (< 100 MB per asset) and the installer never pulls
the 400 MB all-models release.

    python scripts/build_release.py --platform win64
    python scripts/build_release.py --platform all --models rife-v4.6,rife-v4

Output goes to dist/mirror/ and a ready-to-paste MANIFEST block with sha256
hashes is printed at the end.
"""

import argparse
import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import manifest  # noqa: E402
from lib.config import cache_dir  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = cache_dir()
OUT = os.path.join(ROOT, "dist", "mirror")


def log(msg):
    print("[build] " + msg, flush=True)


def download(url, dest):
    log("downloading " + os.path.basename(dest))
    req = urllib.request.Request(url, headers={"User-Agent": "framegen-build"})
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def engine_archive(plat):
    """Return a local path to the pinned engine archive (cache first)."""
    asset, url, size = manifest.ENGINE[plat]
    cache = os.path.join(CACHE, asset)
    if os.path.isfile(cache) and (not size or os.path.getsize(cache) == size):
        log("using cached " + asset)
        return cache
    os.makedirs(CACHE, exist_ok=True)
    download(url, cache)
    return cache


def _find_dir(names, needle):
    needle = needle.strip("/").lower()
    return [n for n in names
            if ("/" + n.replace("\\", "/").lower()).find("/" + needle + "/") >= 0]


def build_engine(plat):
    zpath = engine_archive(plat)
    wanted = tuple(f.lower() for f in manifest.ENGINE_FILES[plat])
    out = os.path.join(OUT, "framegen-engine-%s.zip" % plat)
    with zipfile.ZipFile(zpath) as zf:
        members = [n for n in zf.namelist() if os.path.basename(n).lower() in wanted]
        missing = [f for f in manifest.ENGINE_FILES[plat]
                   if f.lower() not in [os.path.basename(m).lower() for m in members]]
        if missing:
            raise SystemExit("error: %s missing from %s" % (", ".join(missing), zpath))
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
            for n in members:
                info = zipfile.ZipInfo(os.path.basename(n))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o755 << 16
                zo.writestr(info, zf.read(n))
    log("built " + os.path.relpath(out, ROOT))
    return out


def build_model(name, plat="win64"):
    zpath = engine_archive(plat)
    out = os.path.join(OUT, "framegen-model-%s.zip" % name)
    with zipfile.ZipFile(zpath) as zf:
        members = _find_dir(zf.namelist(), name)
        if not members:
            raise SystemExit("error: model '%s' not found in %s" % (name, zpath))
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
            for n in members:
                info = zipfile.ZipInfo(os.path.basename(n))
                info.compress_type = zipfile.ZIP_DEFLATED
                zo.writestr(info, zf.read(n))
    log("built " + os.path.relpath(out, ROOT))
    return out


def main():
    ap = argparse.ArgumentParser(description="Build lean mirror archives.")
    ap.add_argument("--platform", choices=list(manifest.ENGINE) + ["all"], default="all")
    ap.add_argument("--models", default=",".join(manifest.DEFAULT_MODELS))
    ap.add_argument("--skip-engine", action="store_true")
    args = ap.parse_args()

    plats = list(manifest.ENGINE) if args.platform == "all" else [args.platform]
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    os.makedirs(OUT, exist_ok=True)

    produced = []
    if not args.skip_engine:
        for plat in plats:
            produced.append(build_engine(plat))
    for name in models:
        produced.append(build_model(name, plats[0]))

    print("\n# paste into lib/manifest.py (FRAMEGEN_MIRROR=<base url>)")
    for path in produced:
        print("# %-40s sha256=%s" % (os.path.basename(path), sha256(path)))


if __name__ == "__main__":
    main()
