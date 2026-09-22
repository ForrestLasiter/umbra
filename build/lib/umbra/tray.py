"""The umbra system-tray toggle - the "one switch".

A GTK AppIndicator that sits in the tray and lets you flip posture with a click;
each choice runs `umbra --pkexec ...`, so polkit shows one auth dialog and no root
shell is needed. This is the desktop face of the whole engine.

GUI dependencies (PyGObject + an AppIndicator) are imported only inside run(), so
importing this module (and unit-testing command_for) works anywhere, including a
machine with no desktop stack.
"""

from __future__ import annotations

import subprocess

# Profiles offered in the menu, in order.
_PROFILES = ["home", "travel", "paranoid"]


def command_for(action: str) -> list[str]:
    """The `umbra --pkexec ...` command a menu item runs. Pure/testable.

    action is a profile name, or the special "normal" / "panic".
    """
    base = ["umbra", "--pkexec"]
    if action == "normal":
        return base + ["normal"]
    if action == "panic":
        return base + ["panic"]
    # a profile: --confirm covers fail-mode=closed profiles (travel/paranoid)
    return base + ["--confirm", "apply", action]


def _launch(action: str) -> None:
    subprocess.Popen(command_for(action))


def run() -> int:
    """Start the tray. Returns non-zero with a message if the GUI stack is absent."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk
        try:
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3 as AppIndicator
        except (ValueError, ImportError):
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3 as AppIndicator
    except (ImportError, ValueError) as exc:
        print("umbra tray needs a desktop GUI stack (PyGObject + an AppIndicator).")
        print("  Debian/Kali:  sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1")
        print(f"  ({exc})")
        return 1

    from umbra import snapshots

    indicator = AppIndicator.Indicator.new(
        "umbra", "security-high",
        AppIndicator.IndicatorCategory.SYSTEM_SERVICES)
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

    def build_menu():
        menu = Gtk.Menu()

        active = snapshots.active_profile()
        header = Gtk.MenuItem(label=f"Active: {active or 'stock (normal)'}")
        header.set_sensitive(False)
        menu.append(header)
        menu.append(Gtk.SeparatorMenuItem())

        for name in _PROFILES:
            item = Gtk.MenuItem(label=("● " if name == active else "   ") + name.capitalize())
            item.connect("activate", lambda _w, n=name: _launch(n))
            menu.append(item)

        menu.append(Gtk.SeparatorMenuItem())
        restore = Gtk.MenuItem(label="Restore to stock")
        restore.connect("activate", lambda _w: _launch("normal"))
        menu.append(restore)

        panic = Gtk.MenuItem(label="PANIC — go dark now")
        panic.connect("activate", lambda _w: _launch("panic"))
        menu.append(panic)

        menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label="Quit tray")
        quit_item.connect("activate", lambda _w: Gtk.main_quit())
        menu.append(quit_item)

        menu.show_all()
        return menu

    indicator.set_menu(build_menu())

    # Refresh the "Active:" line and check-marks every few seconds.
    def refresh():
        indicator.set_menu(build_menu())
        return True
    GLib.timeout_add_seconds(4, refresh)

    Gtk.main()
    return 0
