import os
import stat
import tarfile
import zipfile

MACHO = (b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf")
EXEC_NAMES = {"framegen"}


def is_exec(path):
    name = os.path.basename(path)
    if name in EXEC_NAMES or name.endswith(".sh"):
        return True
    try:
        with open(path, "rb") as f:
            head = f.read(4)
    except OSError:
        return False
    if head[:4] == b"\x7fELF":
        return True
    for magic in MACHO:
        if head[:4] == magic or head[:4] == magic[::-1]:
            return True
    return False


def make_zip(src, dst):
    prefix = os.path.basename(os.path.normpath(src))
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        _zip_dir(zf, src, src, prefix)


def _zip_dir(zf, base, root, prefix):
    for entry in sorted(os.listdir(base)):
        path = os.path.join(base, entry)
        rel = prefix + "/" + os.path.relpath(path, root).replace(os.sep, "/")
        if os.path.islink(path):
            info = zipfile.ZipInfo(rel)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, os.readlink(path).replace("\\", "/"))
        elif os.path.isdir(path):
            _zip_dir(zf, path, root, prefix)
        else:
            info = zipfile.ZipInfo(rel)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if is_exec(path) else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            with zf.open(info, "w") as out, open(path, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)


def make_tar(src, dst):
    prefix = os.path.basename(os.path.normpath(src))
    with tarfile.open(dst, "w:gz") as tf:
        _tar_dir(tf, src, src, prefix)


def _tar_dir(tf, base, root, prefix):
    for entry in sorted(os.listdir(base)):
        path = os.path.join(base, entry)
        name = prefix + "/" + os.path.relpath(path, root).replace(os.sep, "/")
        if os.path.islink(path):
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = os.readlink(path).replace("\\", "/")
            info.mode = 0o777
            info.size = 0
            tf.addfile(info)
        elif os.path.isdir(path):
            info = tf.gettarinfo(path, arcname=name)
            info.mode = 0o755
            tf.addfile(info, None)
            _tar_dir(tf, path, root, prefix)
        else:
            info = tf.gettarinfo(path, arcname=name)
            info.mode = 0o755 if is_exec(path) else 0o644
            with open(path, "rb") as f:
                tf.addfile(info, f)
