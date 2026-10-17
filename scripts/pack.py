"""Assemble portable, fully self-contained framegen builds.

    python scripts/pack.py --platform win-x64
    python scripts/pack.py                     # all platforms
    python scripts/pack.py --no-python         # code + binaries only

By default every build embeds a portable Python interpreter (no pip packages
are needed: framegen is pure-stdlib), so the result runs on a machine with no
Python installed. Use --no-python to ship the launcher only (it then falls back
to a system ``python3``).
"""

import argparse
import os
import posixpath
import shutil
import sys
import tarfile
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archive import make_tar, make_zip  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCES = os.path.join(ROOT, "resources")
RUNTIMES = os.path.join(ROOT, "python")
DIST = os.path.join(ROOT, "dist")

PBS_TAG = "20261003"
PBS_VER = "3.13.16"
PBS_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/" + PBS_TAG
PBS_ASSET = "cpython-{ver}+{tag}-{triple}-install_only_stripped.tar.gz"

# Candidate binaries copied into resources/ of each build (present ones only).
BINARIES = {
    "win64": ("rife-ncnn-vulkan.exe", "ffmpeg.exe", "vcomp140.dll"),
    "lin64": ("rife-ncnn-vulkan", "ffmpeg"),
    "mac": ("rife-ncnn-vulkan", "ffmpeg"),
}

TARGETS = {
    "win-x64": {"platform_key": "win64", "triple": "x86_64-pc-windows-msvc",
                "launcher": "framegen.cmd", "archive": "zip"},
    "linux-x64": {"platform_key": "lin64", "triple": "x86_64-unknown-linux-gnu",
                  "launcher": "framegen", "archive": "tar.gz"},
    "mac-arm64": {"platform_key": "mac", "triple": "aarch64-apple-darwin",
                  "launcher": "framegen", "archive": "zip"},
}


def log(msg):
    print("[pack] " + msg, flush=True)


def download(url, dest):
    log("downloading " + os.path.basename(dest))
    with urllib.request.urlopen(url) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)


def extract_runtime(tar_path, dest):
    os.makedirs(dest, exist_ok=True)
    links = {}
    with tarfile.open(tar_path, "r:gz") as tf:
        for m in tf.getmembers():
            parts = m.name.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            name = parts[1]
            if m.issym() or m.islnk():
                links[name] = m.linkname[7:] if m.linkname.startswith("python/") else m.linkname
                continue
            m.name = name
            tf.extract(m, dest, filter="fully_trusted")
    for name in links:
        _materialize(dest, name, links)


def _materialize(dest, name, links):
    target = os.path.join(dest, *name.split("/"))
    if os.path.exists(target):
        return
    seen = set()
    cur = name
    while cur in links and cur not in seen:
        seen.add(cur)
        link = links[cur]
        if link.startswith("/"):
            cur = link.lstrip("/")
        else:
            cur = posixpath.normpath(posixpath.join(posixpath.dirname(cur), link))
    src = os.path.join(dest, *cur.split("/"))
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(src, target)
    elif os.path.isdir(src):
        os.makedirs(target, exist_ok=True)


def ensure_runtime(target):
    key = target["platform_key"]
    py = os.path.join(RUNTIMES, key)
    marker = os.path.join(py, ".framegen-ready")
    if os.path.isfile(marker):
        return py
    asset = PBS_ASSET.format(ver=PBS_VER, tag=PBS_TAG, triple=target["triple"])
    log("fetching runtime %s" % key)
    shutil.rmtree(py, ignore_errors=True)
    tmp = tempfile.mkdtemp(prefix="framegen-pbs-")
    try:
        tar_path = os.path.join(tmp, asset)
        download(PBS_URL + "/" + asset, tar_path)
        extract_runtime(tar_path, py)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with open(marker, "w") as f:
        f.write(PBS_VER + "+" + PBS_TAG + "\n")
    return py


def assemble(target, out_dir, with_python):
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    shutil.copy2(os.path.join(ROOT, "framegen.py"), out_dir)
    shutil.copytree(os.path.join(ROOT, "lib"), os.path.join(out_dir, "lib"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(os.path.join(ROOT, target["launcher"]), out_dir)

    res = os.path.join(out_dir, "resources")
    os.makedirs(res, exist_ok=True)
    src_plat = os.path.join(RESOURCES, target["platform_key"])
    for name in BINARIES[target["platform_key"]]:
        src = os.path.join(src_plat, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(res, name))
    models_src = os.path.join(RESOURCES, "models")
    if os.path.isdir(models_src):
        shutil.copytree(models_src, os.path.join(res, "models"),
                        ignore=shutil.ignore_patterns("__pycache__"))

    if with_python:
        shutil.copytree(ensure_runtime(target), os.path.join(out_dir, "python"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def archive(target, out_dir):
    label = os.path.basename(out_dir)
    if target["archive"] == "zip":
        dst = os.path.join(DIST, label + ".zip")
        make_zip(out_dir, dst)
    else:
        dst = os.path.join(DIST, label + ".tar.gz")
        make_tar(out_dir, dst)
    log("archive " + os.path.relpath(dst, ROOT))


def main():
    ap = argparse.ArgumentParser(description="Assemble portable framegen builds.")
    ap.add_argument("--platform", choices=list(TARGETS) + ["all"], default="all")
    ap.add_argument("--no-python", dest="with_python", action="store_false",
                    help="do not embed a portable Python interpreter")
    ap.add_argument("--no-archive", action="store_true")
    args = ap.parse_args()

    names = list(TARGETS) if args.platform == "all" else [args.platform]
    os.makedirs(DIST, exist_ok=True)
    for name in names:
        target = TARGETS[name]
        log("=== %s ===" % name)
        out_dir = os.path.join(DIST, "framegen-" + name)
        assemble(target, out_dir, args.with_python)
        log("built " + os.path.relpath(out_dir, ROOT))
        if not args.no_archive:
            archive(target, out_dir)


if __name__ == "__main__":
    main()
