"""Fetch the pinned RIFE engine binaries and model weights into resources/.

    python scripts/fetch_engines.py                  # all platforms
    python scripts/fetch_engines.py --platform lin64 mac
    python scripts/fetch_engines.py --force

Nothing here is ever "latest": the upstream release tag and the size of every
file are pinned, so a checkout is reproducible.

The engine executable is per-platform; the model weights in resources/models
are shared by all of them. The upstream engine archive bundles every RIFE model
(431 MB), so only the engine executable plus the requested model folders are
extracted - a checkout stays around 15 MB. Archives are cached in the user
cache dir, so re-runs do not re-download.
"""

import argparse
import os
import shutil
import sys
import urllib.error
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lib.progress import Progress  # noqa: E402

RESOURCES = os.path.join(ROOT, "resources")

RIFE_REPO = "nihui/rife-ncnn-vulkan"
RIFE_TAG = "20221029"                                  # never "latest"
RIFE_COMMIT = "a7532fc3f9f8f008cd6eecd6f2ffe2a9698e0cf7"
RELEASE_BASE = "https://github.com/%s/releases/download/%s" % (RIFE_REPO, RIFE_TAG)

# Platform -> (asset name, url, size)
ENGINE = {
    "win64": ("rife-ncnn-vulkan-20221029-windows.zip",
              RELEASE_BASE + "/rife-ncnn-vulkan-20221029-windows.zip", 431540241),
    "lin64": ("rife-ncnn-vulkan-20221029-ubuntu.zip",
              RELEASE_BASE + "/rife-ncnn-vulkan-20221029-ubuntu.zip", 431302796),
    "mac": ("rife-ncnn-vulkan-20221029-macos.zip",
            RELEASE_BASE + "/rife-ncnn-vulkan-20221029-macos.zip", 436537917),
}

# Files taken out of the engine archive for each platform (basenames).
ENGINE_FILES = {
    "win64": ("rife-ncnn-vulkan.exe", "vcomp140.dll"),
    "lin64": ("rife-ncnn-vulkan",),
    "mac": ("rife-ncnn-vulkan",),
}

# Model name -> ((filename, size) ...) exactly as shipped in the engine archive.
MODELS = {
    "rife-v4.6": (("flownet.bin", 10614320), ("flownet.param", 16749)),
    "rife-v4": (("flownet.bin", 10340416), ("flownet.param", 12999)),
}

DEFAULT_MODELS = ("rife-v4.6",)

_CHUNK = 1 << 20


def cache_dir():
    env = os.environ.get("FRAMEGEN_CACHE")
    if env:
        return env
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "framegen", "cache")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Caches/framegen")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "framegen")


def download(url, dest, expect_size=0):
    label = os.path.basename(dest)
    print("[fetch] downloading %s" % label, flush=True)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".part"
    pr = Progress(label)
    ok = False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "framegen-fetch"})
        with urllib.request.urlopen(req) as r:
            total = int(r.headers.get("Content-Length") or expect_size or 0)
            if total:
                pr.start(total)
            with open(tmp, "wb") as f:
                done = 0
                while True:
                    chunk = r.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    pr.update(done)
        ok = True
    except urllib.error.URLError as exc:
        raise SystemExit("error: download failed: %s\n  %s" % (url, exc))
    finally:
        pr.close()
        if not ok:
            try:
                os.remove(tmp)
            except OSError:
                pass
    size = os.path.getsize(tmp)
    if expect_size and size != expect_size:
        os.remove(tmp)
        raise SystemExit("error: %s has the wrong size (%d, expected %d)"
                         % (label, size, expect_size))
    shutil.move(tmp, dest)
    return dest


def engine_archive(plat):
    asset, url, size = ENGINE[plat]
    cache = os.path.join(cache_dir(), asset)
    if os.path.isfile(cache) and (not size or os.path.getsize(cache) == size):
        print("[fetch] cached %s" % asset)
        return cache
    return download(url, cache, expect_size=size)


def _extract(zf, members, dest):
    os.makedirs(dest, exist_ok=True)
    for name in members:
        base = os.path.basename(name)
        if not base:
            continue
        info = zf.getinfo(name)
        target = os.path.join(dest, base)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out, _CHUNK)
        if base.lower().endswith(".exe") or (info.external_attr >> 16) & 0o111:
            try:
                os.chmod(target, 0o755)
            except OSError:
                pass


def fetch_engine(plat, force=False):
    dest = os.path.join(RESOURCES, plat)
    exe = os.path.join(dest, ENGINE_FILES[plat][0])
    if os.path.isfile(exe) and not force:
        print("[fetch] engine %s already present" % plat)
        return
    zpath = engine_archive(plat)
    wanted = tuple(f.lower() for f in ENGINE_FILES[plat])
    with zipfile.ZipFile(zpath) as zf:
        hits = [n for n in zf.namelist() if os.path.basename(n).lower() in wanted]
        missing = [f for f in ENGINE_FILES[plat]
                   if f.lower() not in [os.path.basename(h).lower() for h in hits]]
        if missing:
            raise SystemExit("error: %s missing from %s" % (", ".join(missing), zpath))
        _extract(zf, hits, dest)
    print("[fetch] engine %s -> %s" % (plat, os.path.relpath(dest, ROOT)))


def fetch_model(name, plat="win64", force=False):
    files = MODELS.get(name)
    if not files:
        raise SystemExit("error: unknown model '%s' (known: %s)"
                         % (name, ", ".join(sorted(MODELS))))
    dest = os.path.join(RESOURCES, "models", name)
    if not force and all(os.path.isfile(os.path.join(dest, f)) for f, _ in files):
        print("[fetch] model %s already present" % name)
        return
    zpath = engine_archive(plat)
    needle = "/" + name.lower() + "/"
    with zipfile.ZipFile(zpath) as zf:
        members = [n for n in zf.namelist()
                   if ("/" + n.replace("\\", "/").lower()).find(needle) >= 0]
        if not members:
            raise SystemExit("error: model '%s' not found in %s" % (name, zpath))
        _extract(zf, members, dest)
    for fname, size in files:
        path = os.path.join(dest, fname)
        if not os.path.isfile(path) or os.path.getsize(path) != size:
            raise SystemExit("error: %s/%s is not the expected %d bytes" % (name, fname, size))
    print("[fetch] model %s -> %s" % (name, os.path.relpath(dest, ROOT)))


def main():
    ap = argparse.ArgumentParser(description="Fetch the pinned engines and model weights.")
    ap.add_argument("--platform", nargs="+", choices=list(ENGINE) + ["all"], default=["all"])
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--force", action="store_true", help="re-extract even if present")
    args = ap.parse_args()

    plats = list(ENGINE) if "all" in args.platform else args.platform
    for plat in plats:
        fetch_engine(plat, force=args.force)
    for name in [m.strip() for m in args.models.split(",") if m.strip()]:
        fetch_model(name, plats[0], force=args.force)


if __name__ == "__main__":
    main()
