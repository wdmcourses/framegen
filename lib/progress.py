import sys
import time

_WIDTH = 28
_LABEL = 16
_LINE_INTERVAL = 0.5
_BAR_INTERVAL = 0.1


class Progress:
    """Progress reporter.

    Three modes:

    ``bar``   in-place bar on a TTY (default when the stream is a TTY);
    ``lines`` one ``progress   : <label> <done>/<total>`` line per update,
              flushed immediately, so a host application (e.g. a GUI that
              embeds framegen as a CLI plugin) can drive its own progress bar;
    ``off``   disabled.

    A host can parse the line mode with::

        ^progress\\s*:\\s*(\\w+)\\s+(\\d+)/(\\d+)
    """

    def __init__(self, label, stream=None, enabled=None, mode=None):
        self.label = label[:_LABEL]
        self.stream = stream if stream is not None else sys.stderr
        if mode is None:
            mode = "bar" if self._isatty() else "off"
        if enabled is False:
            mode = "off"
        elif enabled is True and mode == "off":
            mode = "bar"
        self.mode = mode
        self.enabled = mode != "off"
        self.total = 0
        self.last = 0.0
        self.shown = False
        self._last_done = None

    def _isatty(self):
        try:
            return bool(self.stream.isatty())
        except (AttributeError, ValueError):
            return False

    def start(self, total):
        self.total = max(0, int(total))
        self.update(0, force=True)

    def update(self, done, force=False):
        if not self.enabled:
            return
        now = time.time()
        interval = _LINE_INTERVAL if self.mode == "lines" else _BAR_INTERVAL
        if not force and now - self.last < interval and (self.total == 0 or done < self.total):
            return
        self.last = now
        self._render(done)

    def _render(self, done):
        if self.shown and done == self._last_done:
            return
        self._last_done = done
        if self.mode == "lines":
            label = self.label.strip()
            if self.total:
                text = "progress   : %s %d/%d\n" % (label, done, self.total)
            else:
                text = "progress   : %s %d\n" % (label, done)
        elif self.total:
            frac = min(1.0, max(0.0, done / float(self.total)))
            filled = int(round(frac * _WIDTH))
            bar = "#" * filled + "-" * (_WIDTH - filled)
            text = "\r%-*s [%s] %3d%%" % (_LABEL, self.label, bar, int(frac * 100))
        else:
            text = "\r%-*s %d" % (_LABEL, self.label, done)
        self.stream.write(text)
        self.stream.flush()
        self.shown = True

    def close(self):
        if not self.enabled or not self.shown:
            return
        self._render(self.total or 0)
        if self.mode == "bar":
            self.stream.write("\n")
            self.stream.flush()
