import os
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile

from . import manifest
from .config import MODELS_DIR, RESOURCES_DIR, cache_dir, platform_key
from .progress import Progress

_CHUNK = 1 << 20


def _human(n):
    if not n:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0


def download(url, dest, expect_size=0, label=None):
    """Download ``url`` to ``dest`` (atomically) with a progress bar."""
    label = label or os.path.basename(dest)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".part"
    pr = Progress(label)
    ok = False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "framegen-install"})
        with urllib.request.urlopen(req) as r:
            total = int(r.headers.get("Content-Length") or expect_size or 0)
            if expect_size and total and total != expect_size:
                total = expect_size
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
        raise SystemExit("error: %s has wrong size (%d, expected %d)" % (label, size, expect_size))
    shutil.move(tmp, dest)
    return dest


def _mirror_url(asset):
    if not manifest.MIRROR:
        return None
    return manifest.MIRROR + "/" + asset


def _find_dir(names, needle):
    needle = needle.strip("/").lower()
    return [n for n in names
            if ("/" + n.replace("\\", "/").lower()).find("/" + needle + "/") >= 0]


def _extract(zf, members, dest):
    os.makedirs(dest, exist_ok=True)
    for name in members:
        info = zf.getinfo(name)
        target = os.path.join(dest, os.path.basename(name))
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out, _CHUNK)
        if name.endswith(".exe") or (info.external_attr >> 16) & 0o111:
            try:
                os.chmod(target, 0o755)
            except OSError:
                pass


def _engine_archive(plat, quiet=False):
    """Path to the pinned upstream engine archive, using the local cache."""
    asset, url, size = manifest.ENGINE[plat]
    cache = os.path.join(cache_dir(), asset)
    if os.path.isfile(cache) and (not size or os.path.getsize(cache) == size):
        if not quiet:
            print("engine     : using cached %s" % cache)
        return cache
    download(url, cache, expect_size=size, label="engine " + plat)
    return cache


def install_engine(plat, force=False, quiet=False):
    """Install the engine executable for ``plat`` into resources/<plat>/."""
    exe = manifest.ENGINE_EXE.get(plat)
    if not exe:
        raise SystemExit("error: no engine build for platform %s" % plat)
    dest_dir = os.path.join(RESOURCES_DIR, plat)
    target = os.path.join(dest_dir, exe)
    if os.path.isfile(target) and not force:
        if not quiet:
            print("engine     : already installed (%s)" % os.path.relpath(target, RESOURCES_DIR))
        return target

    os.makedirs(dest_dir, exist_ok=True)
    mirror = _mirror_url("framegen-engine-%s.zip" % plat)
    if mirror:
        tmp = tempfile.mkdtemp(prefix="framegen-eng-")
        try:
            zpath = os.path.join(tmp, "engine.zip")
            download(mirror, zpath, label="engine " + plat)
            with zipfile.ZipFile(zpath) as zf:
                _extract(zf, zf.namelist(), dest_dir)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        zpath = _engine_archive(plat, quiet=quiet)
        wanted = tuple(f.lower() for f in manifest.ENGINE_FILES[plat])
        with zipfile.ZipFile(zpath) as zf:
            hits = [n for n in zf.namelist() if os.path.basename(n).lower() in wanted]
            missing = [f for f in manifest.ENGINE_FILES[plat]
                       if f.lower() not in [os.path.basename(h).lower() for h in hits]]
            if missing:
                raise SystemExit("error: %s missing from the engine archive"
                                 % ", ".join(missing))
            _extract(zf, hits, dest_dir)
    if not quiet:
        print("engine     : installed %s" % os.path.relpath(target, RESOURCES_DIR))
    return target


def install_model(name, archive=None, force=False, quiet=False):
    """Install model ``name`` from the mirror, or from the engine ``archive``."""
    files = manifest.MODELS.get(name)
    if not files:
        raise SystemExit("error: unknown model '%s' (known: %s)"
                         % (name, ", ".join(sorted(manifest.MODELS))))
    dest = os.path.join(MODELS_DIR, name)
    if all(os.path.isfile(os.path.join(dest, f)) for f, _ in files) and not force:
        if not quiet:
            print("model      : %s already installed" % name)
        return dest

    mirror = _mirror_url("framegen-model-%s.zip" % name)
    if mirror:
        tmp = tempfile.mkdtemp(prefix="framegen-model-")
        try:
            zpath = os.path.join(tmp, "model.zip")
            download(mirror, zpath, label="model " + name)
            with zipfile.ZipFile(zpath) as zf:
                _extract(zf, zf.namelist(), dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        if archive is None:
            archive = _engine_archive(platform_key(), quiet=quiet)
        with zipfile.ZipFile(archive) as zf:
            members = _find_dir(zf.namelist(), name)
            if not members:
                raise SystemExit("error: model '%s' not found inside %s"
                                 % (name, os.path.basename(archive)))
            _extract(zf, members, dest)

    for fname, size in files:
        path = os.path.join(dest, fname)
        if not os.path.isfile(path) or os.path.getsize(path) != size:
            raise SystemExit("error: %s/%s is not the expected %d bytes" % (name, fname, size))
    if not quiet:
        print("model      : installed %s (%s)" % (name, _human(sum(s for _, s in files))))
    return dest


def install(models=None, force=False, quiet=False):
    plat = platform_key()
    names = list(models or manifest.DEFAULT_MODELS)
    archive = None
    install_engine(plat, force=force, quiet=quiet)
    if not manifest.MIRROR:
        archive = _engine_archive(plat, quiet=True)
    for name in names:
        install_model(name, archive=archive, force=force, quiet=quiet)
    if not quiet:
        print("ready      : engine + %s" % ", ".join(names))
    return True
