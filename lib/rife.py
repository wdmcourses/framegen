import os
import subprocess
import time

from .config import THREADS, model_path, rife


def _gpu_arg(gpu):
    if gpu is None or gpu == "" or str(gpu).lower() == "auto":
        return None
    if str(gpu).lower() == "cpu":
        return "-1"
    return str(gpu)


def command(in_dir, out_dir, n_out, model=None, gpu="auto", threads=THREADS,
            tta=False, ext="png"):
    pattern = "%08d." + ext
    cmd = [rife(), "-i", in_dir, "-o", out_dir, "-n", str(int(n_out)),
           "-m", model_path(model), "-j", threads, "-f", pattern]
    g = _gpu_arg(gpu)
    if g is not None:
        cmd += ["-g", g]
    if tta:
        cmd += ["-x"]
    return cmd


def _count(out_dir, ext):
    suffix = "." + ext
    try:
        return sum(1 for name in os.listdir(out_dir) if name.lower().endswith(suffix))
    except OSError:
        return 0


def run(in_dir, out_dir, n_out, model=None, gpu="auto", threads=THREADS,
        tta=False, ext="png", progress=None):
    """Interpolate `in_dir` (an image sequence) into `n_out` frames in `out_dir`.

    The engine prints no progress, so we poll the output directory and report
    the number of frames written so far.
    """
    if os.path.isdir(out_dir):
        for name in os.listdir(out_dir):
            os.remove(os.path.join(out_dir, name))
    else:
        os.makedirs(out_dir)

    cmd = command(in_dir, out_dir, n_out, model=model, gpu=gpu,
                  threads=threads, tta=tta, ext=ext)
    if progress is not None:
        progress.start(n_out)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    last = -1
    while proc.poll() is None:
        time.sleep(0.5)
        if progress is not None:
            done = _count(out_dir, ext)
            if done != last:
                last = done
                progress.update(done)
    output, _ = proc.communicate()
    if progress is not None:
        progress.update(_count(out_dir, ext), force=True)
    if proc.returncode != 0:
        raise SystemExit("error: rife-ncnn-vulkan failed (exit %d)\n%s"
                         % (proc.returncode, (output or "").strip()))
    return out_dir
