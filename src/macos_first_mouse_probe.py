"""macOS-only input instrumentation for the "have to click twice" bug (see
ONGOING_BUGS.md). Two behavior-preserving probes, both gated on
`logging.first_mouse_probe`; each logs then hands control straight back to pyglet
(via super), so neither changes any behavior.

1. acceptsFirstMouse: on PygletView  -> log_00013.
   Cocoa asks a view this ONLY when a mouseDown lands on a window that is not the
   active window -- one specific "swallow" path. Round 2 (ONGOING_BUGS.md) showed
   it can miss the real swallow: the player reproduced the bug and this fired zero
   times. We answer NO (== the NSView default, so nothing changes); returning True
   later would BE the macOS fix, held back until the swallow is confirmed.

2. sendEvent: on PygletWindow        -> log_00014.
   pyglet pumps its OWN Cocoa loop (`CocoaWindow._poll_app_events` /
   `dispatch_events`) and routes every event through `NSApp.sendEvent_` -> the
   window's sendEvent:. That is the ONE chokepoint every left-mouse-down crosses,
   independent of which view hit-tests or whether the click is swallowed. A
   [00014] with no matching [20003] = the OS delivered the click but pyglet's view
   dispatch dropped it (an in-app bug); a click made with NO [00014] at all = the
   OS never delivered it (genuinely OS-level).

Both add methods to pyglet's live, already-registered ObjC subclasses through
cocoapy's own @method machinery (class_addMethod works post-registration; the IMP
is retained in the subclass _imp_table so the callback is not GC'd). No-op off
macOS and when logging.first_mouse_probe is false.
"""
import ctypes
import sys

import log_codes as L

# AppKit NSEventType.leftMouseDown. pyglet's cocoapy doesn't export it; the value
# is a stable AppKit enum constant.
_NS_LEFT_MOUSE_DOWN = 1

_installed = False


def install(config):
    """Attach both input probes to pyglet's Cocoa classes. Idempotent, and safe to
    call before or after the window exists: the methods are added to the shared
    PygletView / PygletWindow classes, so any already-created instance picks them
    up via ObjC's dynamic dispatch.
    """
    global _installed
    if _installed or sys.platform != "darwin":
        return
    if not config.get("logging", {}).get("first_mouse_probe", False):
        return

    from pyglet.libs.darwin import cocoapy
    from pyglet.window.cocoa.pyglet_view import PygletView_Implementation
    from pyglet.window.cocoa.pyglet_window import PygletWindow_Implementation

    NSApplication = cocoapy.ObjCClass("NSApplication")

    _install_first_mouse_probe(cocoapy, NSApplication, PygletView_Implementation)
    _install_send_event_probe(cocoapy, NSApplication, PygletWindow_Implementation)

    _installed = True


def _install_first_mouse_probe(cocoapy, NSApplication, PygletView_Implementation):
    PygletView = PygletView_Implementation.PygletView

    # Trailing underscore -> the ':' of `acceptsFirstMouse:`. 'B@' = returns BOOL,
    # takes one object arg (the NSEvent); cocoapy inserts the hidden self/cmd.
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


def _install_send_event_probe(cocoapy, NSApplication, PygletWindow_Implementation):
    PygletWindow = PygletWindow_Implementation.PygletWindow

    # Trailing underscore -> the ':' of `sendEvent:`. 'v@' = returns void, takes one
    # object arg (the NSEvent). PygletWindow does not define sendEvent:, so this
    # overrides NSWindow's; we log then MUST call super, or the window stops
    # processing every event.
    @PygletWindow.method(b"v@")
    def sendEvent_(self, nsevent):
        try:
            if nsevent.type() == _NS_LEFT_MOUSE_DOWN:
                loc = nsevent.locationInWindow()
                key_window = bool(self.isKeyWindow())
                app_active = bool(NSApplication.sharedApplication().isActive())
                L.log_00014(int(loc.x), int(loc.y), key_window, app_active)
        except Exception:
            # Logging must never break event routing; fall through to super.
            pass
        cocoapy.send_super(self, "sendEvent:", nsevent.ptr,
                           superclass_name="NSWindow",
                           argtypes=[ctypes.c_void_p])
