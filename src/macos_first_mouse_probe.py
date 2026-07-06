"""macOS-only instrumentation for the "have to click twice" bug (ONGOING_BUGS.md).

Cocoa sends a view `acceptsFirstMouse:` ONLY when a mouseDown lands on a window
that is NOT the active window. The default NSView answer is NO, which means that
first click is swallowed to activate the window and never reaches the app as a
`mouseDown_` -- so it produces no `log_20003` and is invisible in the session log.
That invisible swallow is exactly the "first click does nothing, second click
works" symptom.

pyglet 2.1.14's PygletView (an NSView subclass) does not implement the selector,
so we add it here through cocoapy's own `@PygletView.method` machinery. That calls
`class_addMethod` on the live, already-registered class (methods -- unlike ivars --
can be added post-registration) and retains the IMP in the subclass `_imp_table`,
so the callback is not garbage-collected.

We answer NO -- IDENTICAL to the current NSView default, so this changes NO
behavior; it is purely diagnostic -- and log each call via `log_00013`. Flipping
that return to True later would BE the macOS fix (see ONGOING_BUGS.md); it is held
back until these logs prove the swallow is actually happening.

No-op off macOS and when `logging.first_mouse_probe` is false.
"""
import sys

import log_codes as L


_installed = False


def install(config):
    """Attach the acceptsFirstMouse: logging probe to pyglet's Cocoa view.

    Idempotent, and safe to call before or after the window exists: the method is
    added to the shared PygletView class, so any already-created view picks it up
    via ObjC's dynamic dispatch.
    """
    global _installed
    if _installed or sys.platform != "darwin":
        return
    if not config.get("logging", {}).get("first_mouse_probe", False):
        return

    from pyglet.libs.darwin import cocoapy
    from pyglet.window.cocoa.pyglet_view import PygletView_Implementation

    PygletView = PygletView_Implementation.PygletView
    NSApplication = cocoapy.ObjCClass("NSApplication")

    # The trailing underscore in the function name becomes the ':' of the
    # `acceptsFirstMouse:` selector. Encoding 'B@' = returns BOOL, takes one object
    # arg (the NSEvent); cocoapy inserts the hidden self/cmd. Mirrors
    # canBecomeKeyView ('B') and mouseDown_ ('v@') in pyglet_view.py.
    @PygletView.method(b"B@")
    def acceptsFirstMouse_(self, nsevent):
        try:
            loc = nsevent.locationInWindow()
            app_active = bool(NSApplication.sharedApplication().isActive())
            L.log_00013(int(loc.x), int(loc.y), app_active)
        except Exception:
            # Instrumentation must never disturb input handling.
            pass
        # NO == the NSView default, so behavior is unchanged. Returning True here
        # is the actual macOS fix (ONGOING_BUGS.md) -- do not, until confirmed.
        return False

    _installed = True
