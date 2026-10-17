from fractions import Fraction

from .config import MAX_FPS, MIN_FPS


class Plan(object):
    def __init__(self, src_fps, target_fps, interpolate, ratio):
        self.src_fps = src_fps
        self.target_fps = target_fps
        self.interpolate = interpolate
        self.ratio = ratio          # target / source (Fraction)

    def out_count(self, n_frames):
        """Output frames produced from a run of `n_frames` source frames."""
        if not self.interpolate:
            return n_frames
        return int(round(n_frames * self.ratio))


def build_plan(src_fps, target_fps):
    if src_fps is None or src_fps <= 0:
        raise SystemExit("error: could not determine the source frame rate")
    src = Fraction(src_fps).limit_denominator(1000000)
    tgt = Fraction(target_fps).limit_denominator(1000000)
    if tgt < MIN_FPS or tgt > MAX_FPS:
        raise SystemExit("error: target fps must be between %g and %g" % (MIN_FPS, MAX_FPS))

    ratio = tgt / src
    if ratio <= 1:
        return Plan(src, tgt, False, ratio)
    return Plan(src, tgt, True, ratio)
