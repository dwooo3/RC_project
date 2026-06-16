"""Suite-wide pytest config — deterministic Qt isolation between tests.

Several UI modules build *top-level* Qt widgets (``PricingWorkspace``,
``PricingDetailScreen``, ``BasketBuilderPanel``, …) without ever destroying
them. When a test function returns, Python drops the local reference, but the
underlying C++ ``QWidget`` is not freed until (a) CPython garbage-collects the
wrapper *and* (b) Qt processes the resulting ``DeferredDelete`` event. With no
running event loop in tests, (b) never happens on its own, and (a) is
non-deterministic — so leaked widgets pile up in ``QApplication.topLevelWidgets()``
and can still be alive (or mid-teardown) while a *later* test builds its own
workspace. The exact interleaving shifts with GC timing and machine load, which
is why the pricing-workspace UI tests fail only intermittently inside the full
suite yet pass in isolation or on re-run.

The autouse fixture below makes widget lifetime deterministic: after every test
it closes each leftover top-level widget and *drains* Qt's deferred-delete queue,
so the next test starts from clean global Qt state regardless of GC timing. It
is a no-op for tests that never touched Qt (it only acts once PySide6 has been
imported and a ``QApplication`` exists), so non-UI tests pay nothing.
"""
import gc
import os
import sys

import pytest

# Match the UI modules: head-less rendering so the suite never needs a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _drain(app) -> None:
    """Force Qt to run everything queued, including pending ``deleteLater``s."""
    from PySide6.QtCore import QEvent

    for _ in range(3):  # a few passes: deletions can post further deletions
        app.processEvents()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def _qt_isolation():
    """Destroy leaked top-level widgets and drain deferred deletes after each test."""
    yield

    qtwidgets = sys.modules.get("PySide6.QtWidgets")
    if qtwidgets is None:          # Qt never loaded in this run → nothing to clean.
        return
    app = qtwidgets.QApplication.instance()
    if app is None:
        return

    # Force CPython to drop the Python wrappers the finished test just released,
    # so their C++ QWidgets become deletable now rather than at some later,
    # load-dependent GC pass — this determinism is what the close/drain below
    # relies on (the root cause documented in this module's docstring).
    gc.collect()

    for widget in list(app.topLevelWidgets()):
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            # C++ side already gone (sip wrapper outlived its object) — skip.
            pass

    try:
        _drain(app)
    except RuntimeError:
        pass
    gc.collect()                   # reap wrappers freed by the drain
