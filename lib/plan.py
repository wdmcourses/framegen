from fractions import Fraction

from .config import MAX_FPS, MIN_FPS

# Aim for source chunks of roughly this many frames when interpolating in
# bounded passes so temporary storage never holds the whole movie at once.
CHUNK_TARGET = 240


class Plan(object):
    def __init__(self, src_fps, target_fps, interpolate, ratio, p=1, q=1, n_in=0):
        self.src_fps = src_fps
        self.target_fps = target_fps
        self.interpolate = interpolate
        self.ratio = ratio          # target / source (Fraction)
        self.p = p                  # output frames per chunk  (ratio reduced)
        self.q = q                  # source frames per chunk  (ratio reduced)
        self.n_in = n_in            # source frame count

    @property
    def speed(self):
        return float(self.ratio)

    def out_count(self, n_frames):
        """Output frames produced from a run of `n_frames` source frames."""
        if not self.interpolate:
            return n_frames
        return int(round(n_frames * self.ratio))


def build_plan(src_fps, target_fps, n_in=0):
    if src_fps is None or src_fps <= 0:
        raise SystemExit("error: could not determine the source frame rate")
    src = Fraction(src_fps).limit_denominator(1000000)
    tgt = Fraction(target_fps).limit_denominator(1000000)
    if tgt < MIN_FPS or tgt > MAX_FPS:
        raise SystemExit("error: target fps must be between %g and %g" % (MIN_FPS, MAX_FPS))

    ratio = tgt / src
    if ratio <= 1:
        return Plan(src, tgt, False, ratio, 1, 1, n_in)
    p, q = ratio.numerator, ratio.denominator
    return Plan(src, tgt, True, ratio, p, q, n_in)


def chunk_sizes(plan, n_in):
    """Split `n_in` source frames into chunks of whole p/q groups.

    Each item is (chunk_index, first_in, in_count, out_count). Because a chunk
    is always a multiple of q source frames it maps to an exact number of
    output frames, so there is no drift and no duplicated/dropped frames
    across chunk boundaries.
    """
    if not plan.interpolate:
        return [(0, 0, n_in, n_in)]
    q, p = plan.q, plan.p
    groups = max(1, CHUNK_TARGET // q)
    step = groups * q
    chunks = []
    idx = 0
    a = 0
    while a < n_in:
        take = min(step, n_in - a)
        # keep every chunk (except the last) a multiple of q
        if take < step and take % q:
            take -= take % q
        if take <= 0:
            take = min(q, n_in - a)
        out = take * p // q
        chunks.append((idx, a, take, out))
        a += take
        idx += 1
    return chunks
