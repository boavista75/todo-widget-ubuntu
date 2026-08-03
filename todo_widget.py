#!/usr/bin/env python3
"""
Desktop To-Do widget for Linux (X11 and Wayland).

Designed for Zorin OS 18 and other Ubuntu-based desktops.
Uses X11 window hints on Xorg, and gtk-layer-shell on Wayland when available.
"""

import json
import os
import sys
import uuid
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango

GtkLayerShell = None
try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell as _GtkLayerShell

    GtkLayerShell = _GtkLayerShell
except (ImportError, ValueError):
    pass

CONFIG_DIR = Path.home() / ".config" / "todo-widget"
APP_DIR = Path(__file__).resolve().parent
TASKS_FILE = CONFIG_DIR / "tasks.json"
LEGACY_DATA_FILE = CONFIG_DIR / "data.json"

DEFAULT_WIDTH = 360
DEFAULT_HEIGHT = 480


def resolve_css_path(dark: bool) -> Path:
    """Locate theme CSS: app directory first, then user config override."""
    filename = "style-dark.css" if dark else "style-light.css"
    for directory in (APP_DIR, CONFIG_DIR):
        css_path = directory / filename
        if css_path.is_file():
            return css_path
    raise FileNotFoundError(
        f"Could not find {filename} in {APP_DIR} or {CONFIG_DIR}"
    )


def get_display_backend() -> str:
    """Return 'wayland' or 'x11' for the active GDK backend."""
    display = Gdk.Display.get_default()
    if display is not None and display.get_name() == "wayland":
        return "wayland"

    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland":
        return "wayland"
    if session == "x11":
        return "x11"
    return "x11"


def layer_shell_is_supported() -> bool:
    """True only when Wayland compositor actually supports zwlr_layer_shell_v1."""
    if GtkLayerShell is None or get_display_backend() != "wayland":
        return False
    try:
        if hasattr(GtkLayerShell, "is_supported"):
            return bool(GtkLayerShell.is_supported())
        if hasattr(GtkLayerShell, "get_protocol_version"):
            return GtkLayerShell.get_protocol_version() > 0
    except Exception:
        return False
    return False


def is_dark_theme() -> bool:
    settings = Gtk.Settings.get_default()
    if settings is None:
        return True

    if settings.get_property("gtk-application-prefer-dark-theme"):
        return True

    theme_name = (settings.get_property("gtk-theme-name") or "").lower()
    return "dark" in theme_name


def default_data() -> dict:
    return {
        "tasks": [],
        "window": {"x": 80, "y": 80, "width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT},
    }


def load_data() -> dict:
    source = TASKS_FILE
    if not source.exists() and LEGACY_DATA_FILE.exists():
        source = LEGACY_DATA_FILE

    if not source.exists():
        return default_data()

    try:
        with source.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return default_data()

    if isinstance(data, list):
        data = {"tasks": data, "window": default_data()["window"]}

    data.setdefault("tasks", [])
    data.setdefault("window", default_data()["window"])
    return data


def save_data(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TASKS_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    tmp.replace(TASKS_FILE)


def apply_label_style(label: Gtk.Label, text: str, done: bool) -> None:
    """Apply strikethrough via Pango and muted style via CSS class."""
    attr_list = Pango.AttrList()
    if done:
        attr_list.insert(Pango.attr_strikethrough_new(True))
    label.set_attributes(attr_list)
    label.set_text(text)

    style_ctx = label.get_style_context()
    if done:
        style_ctx.add_class("done")
    else:
        style_ctx.remove_class("done")


class TodoWidget(Gtk.Window):
    def __init__(self):
        super().__init__(title="To-Do Widget")
        self.data = load_data()
        self._drag_x = 0
        self._drag_y = 0
        self._dragging = False
        self._win_x = 0
        self._win_y = 0
        self._window_save_idle_id = 0
        self._css_provider: Gtk.CssProvider | None = None
        self._screen: Gdk.Screen | None = None
        self._theme_box: Gtk.Box | None = None
        self._backend = get_display_backend()
        self._use_layer_shell = layer_shell_is_supported()
        self._margin_x = 0
        self._margin_y = 0

        self._configure_window()
        self._build_ui()
        self.render_all_tasks()

        win = self.data["window"]
        self.set_default_size(win.get("width", DEFAULT_WIDTH), win.get("height", DEFAULT_HEIGHT))
        self._apply_window_position()

        self.connect("destroy", self._on_destroy)
        self.connect("configure-event", self._on_configure)
        self.connect("map-event", self._on_map)
        self.add_events(Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.connect("button-release-event", self._on_window_button_release)
        self.show_all()

    def _on_window_button_release(self, _widget, event) -> bool:
        if event.button == 1 and not self._use_layer_shell:
            GLib.timeout_add(100, self._save_position_after_drag)
        return False

    def _on_map(self, _widget, _event) -> bool:
        """Re-apply saved position after the window is mapped."""
        self._apply_window_position()
        return False

    def _apply_window_position(self) -> None:
        win = self.data["window"]
        x = int(win.get("x", 80))
        y = int(win.get("y", 80))

        if self._use_layer_shell:
            self._margin_x = x
            self._margin_y = y
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, x)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, y)
        else:
            self.move(x, y)

    def _configure_window(self) -> None:
        """Apply platform-specific window configuration for desktop widget behavior."""
        self.set_decorated(False)
        self.set_resizable(True)
        self.set_accept_focus(True)
        self.set_can_focus(True)

        if self._use_layer_shell:
            self._configure_window_layer_shell()
        elif self._backend == "x11":
            self._configure_window_x11()
        else:
            self._configure_window_wayland_fallback()

        self._screen = self.get_screen()
        visual = self._screen.get_rgba_visual()
        if visual is not None and self._screen.is_composited():
            self.set_visual(visual)
        self.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0, 0, 0, 0))

        self._setup_theme_listeners()
        self._apply_theme()

    def _configure_window_x11(self) -> None:
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_below(True)
        self.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self.stick()

    def _configure_window_layer_shell(self) -> None:
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        GtkLayerShell.set_namespace(self, "todo-widget")

    def _configure_window_wayland_fallback(self) -> None:
        """Standard GTK hints for Wayland compositors without Layer Shell (e.g. GNOME/Mutter)."""
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_below(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)

    def _setup_theme_listeners(self) -> None:
        settings = Gtk.Settings.get_default()
        if settings is None:
            return
        settings.connect("notify::gtk-application-prefer-dark-theme", self._on_theme_changed)
        settings.connect("notify::gtk-theme-name", self._on_theme_changed)

    def _on_theme_changed(self, *_args) -> None:
        self._apply_theme()

    def _apply_theme(self) -> None:
        if self._screen is None:
            return

        dark = is_dark_theme()

        if self._css_provider is not None:
            Gtk.StyleContext.remove_provider_for_screen(self._screen, self._css_provider)

        self._css_provider = Gtk.CssProvider()
        css_path = resolve_css_path(dark)
        self._css_provider.load_from_path(str(css_path))
        Gtk.StyleContext.add_provider_for_screen(
            self._screen,
            self._css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        if self._theme_box is not None:
            ctx = self._theme_box.get_style_context()
            if dark:
                ctx.add_class("theme-dark")
                ctx.remove_class("theme-light")
            else:
                ctx.add_class("theme-light")
                ctx.remove_class("theme-dark")

        self._refresh_widget_styles()

    def _refresh_widget_styles(self, widget: Gtk.Widget | None = None) -> None:
        """Redraw the widget tree so the new CSS provider takes effect."""
        if widget is None:
            widget = self
        widget.queue_draw()
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                self._refresh_widget_styles(child)

    def _attach_drag_target(self, widget: Gtk.Widget) -> None:
        """Allow dragging the window by clicking this non-interactive surface."""
        widget.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON1_MOTION_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
        )
        widget.connect("button-press-event", self._on_drag_begin)
        widget.connect("motion-notify-event", self._on_drag_motion)
        widget.connect("button-release-event", self._on_drag_end)

    def _build_ui(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.get_style_context().add_class("todo-window")
        self._theme_box = outer
        self.add(outer)
        self._attach_drag_target(outer)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        panel.get_style_context().add_class("todo-panel")
        outer.pack_start(panel, True, True, 8)
        self._attach_drag_target(panel)

        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scrolled.set_shadow_type(Gtk.ShadowType.NONE)
        self.scrolled.get_style_context().add_class("todo-scrolled")
        panel.pack_start(self.scrolled, True, True, 0)
        self._attach_drag_target(self.scrolled)

        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.list_box.get_style_context().add_class("todo-list")
        self.scrolled.add(self.list_box)
        self._attach_drag_target(self.list_box)

        input_area = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        input_area.get_style_context().add_class("todo-input-area")
        panel.pack_start(input_area, False, False, 0)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Click to quickly add a task")
        self.entry.set_hexpand(True)
        self.entry.get_style_context().add_class("todo-entry")
        self.entry.connect("activate", self._on_entry_activate)
        input_area.pack_start(self.entry, True, True, 0)

        self.add_btn = Gtk.Button(label="↑")
        self.add_btn.get_style_context().add_class("todo-add-btn")
        self.add_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.add_btn.set_tooltip_text("Add task")
        self.add_btn.connect("clicked", self._on_add_button_clicked)
        input_area.pack_start(self.add_btn, False, False, 0)

    def _on_add_button_clicked(self, _button: Gtk.Button) -> None:
        self._on_add_task(self.entry)

    def _refresh_list_ui(self) -> None:
        for child in self.list_box.get_children():
            child.show_all()
        self.scrolled.queue_resize()

    def render_all_tasks(self) -> None:
        """Rebuild the task list from saved data."""
        for child in list(self.list_box.get_children()):
            self.list_box.remove(child)

        for task in self.data.get("tasks", []):
            row = self._make_task_row(task)
            self.list_box.pack_start(row, False, False, 0)
            row.show_all()

        self.scrolled.queue_resize()

    def _make_task_row(self, task: dict) -> Gtk.EventBox:
        task_id = task["id"]

        card = Gtk.EventBox()
        card.get_style_context().add_class("todo-card")
        card._task_id = task_id  # type: ignore[attr-defined]

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.get_style_context().add_class("todo-row")

        checkbox = Gtk.CheckButton()
        checkbox.set_active(task.get("done", False))
        checkbox.connect("toggled", self._on_task_toggled, task_id)

        label = Gtk.Label()
        label.set_halign(Gtk.Align.START)
        label.set_hexpand(True)
        label.set_line_wrap(True)
        label.set_xalign(0)
        label.get_style_context().add_class("todo-label")
        apply_label_style(label, task.get("text", ""), task.get("done", False))

        delete_btn = Gtk.Button(label="×")
        delete_btn.get_style_context().add_class("todo-delete")
        delete_btn.set_relief(Gtk.ReliefStyle.NONE)
        delete_btn.connect("clicked", self._on_delete_task, task_id)

        row.pack_start(checkbox, False, False, 0)
        row.pack_start(label, True, True, 0)
        row.pack_start(delete_btn, False, False, 0)
        card.add(row)
        self._attach_drag_target(card)
        self._attach_drag_target(row)
        self._attach_drag_target(label)

        card._label = label  # type: ignore[attr-defined]
        return card

    def _find_row_by_id(self, task_id: str) -> Gtk.EventBox | None:
        for child in self.list_box.get_children():
            if getattr(child, "_task_id", None) == task_id:
                return child
        return None

    def _save_tasks_now(self) -> None:
        save_data(self.data)

    def _on_entry_activate(self, entry: Gtk.Entry) -> None:
        self._on_add_task(entry)

    def _on_add_task(self, entry: Gtk.Entry) -> None:
        text = entry.get_text().strip()
        if not text:
            return

        task = {"id": str(uuid.uuid4()), "text": text, "done": False}
        self.data["tasks"].insert(0, task)

        row = self._make_task_row(task)
        self.list_box.pack_start(row, False, False, 0)
        row.show_all()
        self._refresh_list_ui()

        entry.set_text("")
        self._save_tasks_now()

    def _on_task_toggled(self, checkbox: Gtk.CheckButton, task_id: str) -> None:
        done = checkbox.get_active()
        for task in self.data["tasks"]:
            if task["id"] != task_id:
                continue
            task["done"] = done
            row = self._find_row_by_id(task_id)
            if row is not None:
                apply_label_style(row._label, task["text"], done)  # type: ignore[attr-defined]
            break

        self._refresh_list_ui()
        self._save_tasks_now()

    def _on_delete_task(self, _button: Gtk.Button, task_id: str) -> None:
        row = self._find_row_by_id(task_id)
        if row is not None:
            self.list_box.remove(row)

        self.data["tasks"] = [t for t in self.data["tasks"] if t["id"] != task_id]
        self._refresh_list_ui()
        self._save_tasks_now()

    def _on_drag_begin(self, _widget, event) -> bool:
        if event.button != 1:
            return False

        if self._use_layer_shell:
            self._dragging = True
            self._drag_x, self._drag_y = event.x_root, event.y_root
            self._margin_x = int(self.data["window"].get("x", 80))
            self._margin_y = int(self.data["window"].get("y", 80))
            return True

        if self._backend == "x11":
            self._dragging = True
            self._drag_x, self._drag_y = event.x_root, event.y_root
            self._win_x, self._win_y = self.get_position()
            return True

        # Wayland fallback (GNOME): ask the compositor to handle the move.
        self.begin_move_drag(
            event.button,
            int(event.x_root),
            int(event.y_root),
            event.time,
        )
        return True

    def _on_drag_motion(self, _widget, event) -> bool:
        if not self._dragging:
            return False
        if not (event.state & Gdk.ModifierType.BUTTON1_MASK):
            return False

        dx = int(event.x_root - self._drag_x)
        dy = int(event.y_root - self._drag_y)
        self._drag_x, self._drag_y = event.x_root, event.y_root

        if self._use_layer_shell:
            self._margin_x = max(0, self._margin_x + dx)
            self._margin_y = max(0, self._margin_y + dy)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, self._margin_x)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, self._margin_y)
        else:
            self._win_x += dx
            self._win_y += dy
            self.move(self._win_x, self._win_y)

        return True

    def _on_drag_end(self, _widget, event) -> bool:
        if event.button != 1:
            return False
        self._dragging = False
        GLib.timeout_add(50, self._save_position_after_drag)
        return False

    def _save_position_after_drag(self) -> bool:
        self._save_window_position_now()
        return False

    def _save_window_position_now(self) -> None:
        if self._use_layer_shell:
            x, y = self._margin_x, self._margin_y
        else:
            x, y = self.get_position()
        width, height = self.get_size()
        self.data["window"] = {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
        }
        save_data(self.data)

    def _on_configure(self, _widget, event) -> bool:
        if self._use_layer_shell:
            x, y = self._margin_x, self._margin_y
        else:
            x, y = self.get_position()
        self.data["window"] = {
            "x": x,
            "y": y,
            "width": event.width,
            "height": event.height,
        }
        self._schedule_window_save()
        return False

    def _schedule_window_save(self) -> None:
        if self._window_save_idle_id:
            GLib.source_remove(self._window_save_idle_id)
        self._window_save_idle_id = GLib.timeout_add(400, self._do_window_save)

    def _do_window_save(self) -> bool:
        self._window_save_idle_id = 0
        save_data(self.data)
        return False

    def _on_destroy(self, _widget) -> None:
        if self._screen is not None and self._css_provider is not None:
            Gtk.StyleContext.remove_provider_for_screen(self._screen, self._css_provider)
        save_data(self.data)
        Gtk.main_quit()


def main() -> int:
    backend = get_display_backend()
    if backend == "wayland":
        if GtkLayerShell is None:
            print(
                "Note: gtk-layer-shell is not installed.\n"
                "Using a standard Wayland window (limited positioning).\n"
                "Install for layer-shell compositors (Sway, etc.):\n"
                "  sudo apt install libgtk-layer-shell0 gir1.2-gtklayershell-0.1\n",
                file=sys.stderr,
            )
        elif not layer_shell_is_supported():
            print(
                "Note: Your Wayland compositor (e.g. GNOME/Mutter on Zorin) does not\n"
                "support the Layer Shell protocol. Using a standard window instead.\n"
                "For full desktop-widget behavior (drag position, keep-below), log in\n"
                "with 'Zorin on Xorg' at the login screen.\n",
                file=sys.stderr,
            )

    TodoWidget()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
