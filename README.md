# Desktop To-Do Widget (X11)

A lightweight, borderless desktop to-do list widget for **Zorin OS 18** and other Ubuntu-based distros running **Xorg** (not Wayland).

The window stays on all workspaces, below other windows, and is hidden from the taskbar and workspace pager — using standard GTK3 / X11 hints (`_NET_WM_WINDOW_TYPE_DESKTOP`, sticky, below, skip taskbar/pager).

## Features

- Add tasks with Enter
- Check off tasks (strikethrough)
- Delete tasks with ×
- Semi-transparent dark panel with rounded corners
- Auto-saves to `~/.config/todo-widget/tasks.json`
- Drag the header bar to reposition the widget

## Requirements

- Xorg session (not Wayland)
- Python 3.10+
- GTK 3 and PyGObject

## Install dependencies (Zorin OS / Ubuntu)

```bash
sudo apt update
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-pango-1.0
```

No pip packages are required — everything uses system GTK bindings.

## Run

```bash
cd /path/to/todo-widget
chmod +x todo_widget.py
GDK_BACKEND=x11 python3 todo_widget.py
```

`GDK_BACKEND=x11` forces GTK to use X11 even if a Wayland compositor is present. On a pure Xorg login session you can omit it.

## Run at startup

### Option A — Autostart entry (recommended)

```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/todo-widget.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=To-Do Widget
Comment=Desktop to-do list widget
Exec=env GDK_BACKEND=x11 /usr/bin/python3 /home/USERNAME/Documents/Projects/todo-widget/todo_widget.py
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
EOF
```

Replace `/home/USERNAME/...` with the actual path to `todo_widget.py`.

### Option B — Zorin Startup Applications

1. Open **Startup Applications** (or **Session and Startup**).
2. Click **Add**.
3. Name: `To-Do Widget`
4. Command:

   ```bash
   env GDK_BACKEND=x11 python3 /home/USERNAME/Documents/Projects/todo-widget/todo_widget.py
   ```

5. Save and reboot or log out/in to test.

## Ensure you are on Xorg

At the Zorin login screen, click the gear icon and choose **Zorin on Xorg** (not Wayland) before signing in.

Verify:

```bash
echo $XDG_SESSION_TYPE   # should print: x11
```

## Data file

Tasks and window position are stored in:

```
~/.config/todo-widget/tasks.json
```

You can back up or edit this file manually if needed.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Widget not below other windows | Confirm Xorg session; some WMs ignore hints on Wayland |
| Window has no transparency | Enable compositing (Zorin has this by default) |
| Widget missing after reboot | Check the autostart `.desktop` path and `GDK_BACKEND=x11` |
| `ImportError: No module named gi` | Run the `apt install` command above |

## App preview
<img width="771" height="587" alt="image" src="https://github.com/user-attachments/assets/034c9374-495e-4338-acdd-5ab7de93d6fa" />

