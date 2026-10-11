"""
Daily Gacha Tracker — Windows desktop app
Tracks whether configured game processes have run during the current local day.
No game account access, network requests, or task-completion detection.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import subprocess
import shutil
from datetime import datetime, date
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import psutil
except ImportError:
    psutil = None

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None

try:
    from winotify import Notification, audio
except ImportError:
    Notification = None
    audio = None


APP_NAME = "Daily Gacha Tracker"
APP_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "DailyGachaTracker"
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.json"
STARTUP_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
STARTUP_VBS = STARTUP_DIR / "Daily Gacha Tracker.vbs"
POLL_SECONDS = 5

DEFAULT_GAMES = [
    {"name": "Genshin Impact", "processes": ["GenshinImpact.exe"], "enabled": True},
    {"name": "Honkai: Star Rail", "processes": ["StarRail.exe"], "enabled": True},
    {"name": "Zenless Zone Zero", "processes": ["ZenlessZoneZero.exe"], "enabled": True},
    {"name": "Wuthering Waves", "processes": ["Client-Win64-Shipping.exe"], "enabled": True},
    {"name": "NIKKE", "processes": ["nikke.exe", "NIKKE.exe"], "enabled": True},
]

DEFAULT_CONFIG = {
    "reminder_time": "21:00",
    "reminder_enabled": True,
    "poll_seconds": POLL_SECONDS,
    "start_with_windows": False,
    "games": DEFAULT_GAMES,
}


def ensure_app_dir():
    APP_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, fallback):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return fallback


def save_json(path: Path, data):
    ensure_app_dir()
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    temp.replace(path)


def current_day():
    return date.today().isoformat()


def process_names_running():
    """Return process executable names currently visible to this user."""
    found = set()
    if psutil is None:
        return found
    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info.get("name")
            if name:
                found.add(name.casefold())
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return found


def parse_hhmm(value):
    try:
        hour, minute = value.strip().split(":", 1)
        hour, minute = int(hour), int(minute)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except (ValueError, AttributeError):
        pass
    return None


class DailyGachaTracker:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("760x590")
        self.root.minsize(660, 500)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_or_close)
        self.config = load_json(CONFIG_PATH, DEFAULT_CONFIG.copy())
        # Ensure any missing config keys from newer versions are present.
        self.config.setdefault("reminder_time", "21:00")
        self.config.setdefault("reminder_enabled", True)
        self.config.setdefault("poll_seconds", POLL_SECONDS)
        self.config.setdefault("start_with_windows", False)
        self.config.setdefault("games", DEFAULT_GAMES)
        self.state = load_json(STATE_PATH, {"day": current_day(), "opened": {}, "reminded": False})
        self._normalise_state()
        self.last_process_names = set()
        self.hidden = False
        self.running = True
        self.tray_icon = None
        self._build_ui()
        self._setup_tray()
        if self.config.get("start_with_windows", False):
            self.set_startup(True, quiet=True)
        self.refresh_processes()
        self.root.after(1000, self.tick)

    def _normalise_state(self):
        today = current_day()
        if self.state.get("day") != today:
            self.state = {"day": today, "opened": {}, "reminded": False}
            save_json(STATE_PATH, self.state)
        self.state.setdefault("opened", {})
        self.state.setdefault("reminded", False)

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="Daily Gacha Tracker", font=("Segoe UI", 19, "bold")).pack(side="left")
        ttk.Label(header, text="LOCAL ONLY", foreground="#4d7c0f").pack(side="right", padx=(8, 0))

        ttk.Label(
            outer,
            text="Tracks game launches only. It does not access game accounts or verify daily tasks.",
            wraplength=700,
        ).pack(anchor="w", pady=(5, 14))

        self.date_label = ttk.Label(outer, text="")
        self.date_label.pack(anchor="w", pady=(0, 8))

        columns = ("game", "status", "last_seen")
        self.tree = ttk.Treeview(outer, columns=columns, show="headings", height=7)
        self.tree.heading("game", text="Game")
        self.tree.heading("status", text="Today's status")
        self.tree.heading("last_seen", text="First detected")
        self.tree.column("game", width=230, anchor="w")
        self.tree.column("status", width=180, anchor="center")
        self.tree.column("last_seen", width=150, anchor="center")
        self.tree.pack(fill="both", expand=True)

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(12, 4))
        ttk.Button(controls, text="Check now", command=self.refresh_processes).pack(side="left")
        ttk.Button(controls, text="Settings", command=self.open_settings).pack(side="left", padx=8)
        ttk.Button(controls, text="Open data folder", command=self.open_data_folder).pack(side="left")
        self.status_label = ttk.Label(outer, text="Monitoring is active while the app runs, including when hidden to the tray.")
        self.status_label.pack(anchor="w", pady=(10, 0))

        note = ttk.Label(
            outer,
            text="Tip: process names can vary by launcher or game version. Use Settings to correct them.",
            foreground="#666666",
            wraplength=700,
        )
        note.pack(anchor="w", pady=(7, 0))

    def refresh_processes(self):
        self._normalise_state()
        if psutil is None:
            self.status_label.config(text="Missing dependency: install requirements with install.bat.")
            return
        running = process_names_running()
        self.last_process_names = running
        changed = False
        for game in self.config["games"]:
            if not game.get("enabled", True):
                continue
            aliases = [str(x).strip().casefold() for x in game.get("processes", []) if str(x).strip()]
            # Match case-insensitively. Client-Win64-Shipping.exe is used by Wuthering Waves;
            # process-name matching cannot distinguish another Unreal game with the same name.
            if aliases and any(alias.casefold() in running for alias in aliases):
                if game["name"] not in self.state["opened"]:
                    self.state["opened"][game["name"]] = datetime.now().strftime("%H:%M")
                    changed = True
        if changed:
            save_json(STATE_PATH, self.state)
        self.render_rows()
        self.status_label.config(
            text=f"Last checked: {datetime.now().strftime('%H:%M:%S')} · polling every {self.config.get('poll_seconds', POLL_SECONDS)} seconds"
        )

    def render_rows(self):
        self.date_label.config(text=f"Today: {datetime.now().strftime('%A, %d %B %Y')} (your Windows local date)")
        for item in self.tree.get_children():
            self.tree.delete(item)
        for game in self.config["games"]:
            if not game.get("enabled", True):
                status, seen = "Disabled", "—"
            elif game["name"] in self.state["opened"]:
                status, seen = "Opened today", self.state["opened"][game["name"]]
            else:
                status, seen = "Not detected today", "—"
            self.tree.insert("", "end", values=(game["name"], status, seen))

    def tick(self):
        if not self.running:
            return
        try:
            self.refresh_processes()
            self.maybe_remind()
        except Exception as exc:
            self.status_label.config(text=f"Tracker error: {exc}")
        delay = max(3, int(self.config.get("poll_seconds", POLL_SECONDS))) * 1000
        self.root.after(delay, self.tick)

    def maybe_remind(self):
        if not self.config.get("reminder_enabled", True) or self.state.get("reminded"):
            return
        target = parse_hhmm(self.config.get("reminder_time", "21:00"))
        if not target:
            return
        now = datetime.now()
        if (now.hour, now.minute) < target:
            return
        missing = [
            game["name"] for game in self.config["games"]
            if game.get("enabled", True) and game["name"] not in self.state["opened"]
        ]
        self.state["reminded"] = True
        save_json(STATE_PATH, self.state)
        if missing:
            message = "Not detected today: " + ", ".join(missing)
            self.notify("Daily Gacha Tracker", message)
            self.status_label.config(text=f"Reminder sent for {len(missing)} game(s) not detected today.")
        else:
            self.status_label.config(text="All enabled games have been detected today.")

    def notify(self, title, message):
        if Notification is not None:
            try:
                toast = Notification(app_id=APP_NAME, title=title, msg=message)
                if audio is not None:
                    toast.set_audio(audio.Default, loop=False)
                toast.show()
                return
            except Exception:
                pass
        # Fallback: a Windows message box if toast support is unavailable.
        try:
            messagebox.showinfo(title, message)
        except Exception:
            pass

    def open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Tracker settings")
        win.geometry("690x520")
        win.transient(self.root)
        win.grab_set()
        frame = ttk.Frame(win, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Reminder time (24-hour HH:MM)").grid(row=0, column=0, sticky="w", pady=5)
        reminder_var = tk.StringVar(value=self.config.get("reminder_time", "21:00"))
        ttk.Entry(frame, textvariable=reminder_var, width=10).grid(row=0, column=1, sticky="w", padx=8)
        reminder_enabled_var = tk.BooleanVar(value=self.config.get("reminder_enabled", True))
        ttk.Checkbutton(frame, text="Enable daily reminder", variable=reminder_enabled_var).grid(
            row=0, column=2, sticky="w", padx=8
        )
        startup_var = tk.BooleanVar(value=self.config.get("start_with_windows", False))
        ttk.Checkbutton(frame, text="Start with Windows (runs in the system tray)", variable=startup_var).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(30, 0)
        )

        ttk.Label(frame, text="Game process names", font=("Segoe UI", 10, "bold")).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(18, 4)
        )
        ttk.Label(
            frame,
            text="Enter executable names separated by commas, e.g. GenshinImpact.exe. Match the process name shown in Task Manager → Details.",
            wraplength=640,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 8))

        vars_by_name = {}
        enabled_by_name = {}
        row = 3
        for game in self.config["games"]:
            ttk.Label(frame, text=game["name"]).grid(row=row, column=0, sticky="w", pady=5)
            var = tk.StringVar(value=", ".join(game.get("processes", [])))
            ttk.Entry(frame, textvariable=var, width=52).grid(row=row, column=1, sticky="ew", padx=8, pady=5)
            enabled = tk.BooleanVar(value=game.get("enabled", True))
            ttk.Checkbutton(frame, text="Track", variable=enabled).grid(row=row, column=2, sticky="w")
            vars_by_name[game["name"]] = var
            enabled_by_name[game["name"]] = enabled
            row += 1
        frame.columnconfigure(1, weight=1)

        def save_settings():
            parsed = parse_hhmm(reminder_var.get())
            if not parsed:
                messagebox.showerror("Invalid time", "Enter a valid time such as 21:00.", parent=win)
                return
            self.config["reminder_time"] = f"{parsed[0]:02d}:{parsed[1]:02d}"
            self.config["reminder_enabled"] = reminder_enabled_var.get()
            self.config["start_with_windows"] = startup_var.get()
            try:
                self.set_startup(startup_var.get(), quiet=True)
            except OSError as exc:
                messagebox.showerror("Startup setting failed", str(exc), parent=win)
                return
            for game in self.config["games"]:
                raw = vars_by_name[game["name"]].get()
                game["processes"] = [x.strip() for x in raw.split(",") if x.strip()]
                game["enabled"] = enabled_by_name[game["name"]].get()
            save_json(CONFIG_PATH, self.config)
            self.render_rows()
            win.destroy()
            self.status_label.config(text="Settings saved.")
        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=3, sticky="e", pady=(18, 0))
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="Save settings", command=save_settings).pack(side="right", padx=8)

    def open_data_folder(self):
        ensure_app_dir()
        try:
            os.startfile(str(APP_DIR))
        except Exception as exc:
            messagebox.showerror("Could not open folder", str(exc))

    def _setup_tray(self):
        if pystray is None or Image is None:
            self.status_label.config(text="Tray support unavailable. Install dependencies with install.bat.")
            return
        icon_image = Image.new("RGB", (64, 64), "#2457a7")
        draw = ImageDraw.Draw(icon_image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=10, fill="#ffffff")
        draw.text((15, 20), "DG", fill="#2457a7")
        menu = pystray.Menu(
            pystray.MenuItem("Open dashboard", lambda icon, item: self.root.after(0, self.show_window), default=True),
            pystray.MenuItem("Check now", lambda icon, item: self.root.after(0, self.refresh_processes)),
            pystray.MenuItem("Exit", lambda icon, item: self.root.after(0, self.exit_app)),
        )
        self.tray_icon = pystray.Icon("daily_gacha_tracker", icon_image, APP_NAME, menu)
        threading.Thread(target=self.tray_icon.run, name="DGT-Tray", daemon=True).start()

    def show_window(self):
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()
        self.hidden = False

    def hide_or_close(self):
        self.root.withdraw()
        self.hidden = True
        self.status_label.config(text="Running in the background. Use the system-tray icon to reopen or exit.")

    def set_startup(self, enabled, quiet=False):
        """Create/remove a per-user Startup-folder launcher without admin rights."""
        if enabled:
            STARTUP_DIR.mkdir(parents=True, exist_ok=True)
            script = Path(__file__).resolve()
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            if not pythonw.exists():
                pythonw = Path(sys.executable)
            # VBScript launches silently; paths are quoted to support spaces.
            escaped_python = str(pythonw).replace('"', '""')
            escaped_script = str(script).replace('"', '""')
            content = f'Set shell = CreateObject("WScript.Shell")\nshell.Run """{escaped_python}"" """{escaped_script}""", 0, False\n'
            STARTUP_VBS.write_text(content, encoding="utf-8")
        else:
            try:
                STARTUP_VBS.unlink()
            except FileNotFoundError:
                pass
        self.config["start_with_windows"] = bool(enabled)
        save_json(CONFIG_PATH, self.config)

    def exit_app(self):
        if not self.running:
            return
        self.running = False
        save_json(STATE_PATH, self.state)
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()


def main():
    if sys.platform != "win32":
        print("Daily Gacha Tracker is designed for Windows 10/11.")
    ensure_app_dir()
    root = tk.Tk()
    app = DailyGachaTracker(root)
    root.mainloop()


if __name__ == "__main__":
    main()
