"""MLB Stats Viewer — portable Windows app for browsing teams, players, and current-season stats."""

from __future__ import annotations

import sys
import tempfile
import threading
import traceback
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import customtkinter as ctk
from PIL import Image

import ai
import mlb_api
import settings as user_settings
import updater


def _error_log_path() -> Path:
    """Where to write a crash log when --windowed swallows exceptions."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "error.log"
    return Path(__file__).parent / "error.log"


def _install_global_excepthook() -> None:
    """Append uncaught exceptions to error.log next to the .exe so we can debug
    silent failures in the packaged --windowed build."""

    def hook(exc_type, exc, tb):
        try:
            with open(_error_log_path(), "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().isoformat(timespec='seconds')}]\n")
                traceback.print_exception(exc_type, exc, tb, file=f)
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


_install_global_excepthook()

APP_TITLE = "MLB Stats Viewer"
WINDOW_SIZE = "1180x760"
APP_VERSION = updater.VERSION

# Per-version release notes. Shown once on first launch of each version that
# the user updates into. Add a key per release; the dialog stays silent when
# the running VERSION has no matching key.
WHATS_NEW: dict[str, str] = {
    "1.0.1": (
        "cherry is cute\n\n"
        "What's new in this version:\n"
        "• Ask AI tab — chat with a local AI about players and games "
        "(works on your home network)\n"
        "• Fixed: you can now type in the search bar on all PCs\n"
        "• Fixed: Settings and Update windows now appear in front\n"
        "• Fixed: the AI chat and player pages no longer disappear when "
        "left open"
    ),
}

HITTING_FIELDS = [
    ("gamesPlayed", "Games"),
    ("plateAppearances", "Plate Appearances"),
    ("atBats", "At Bats"),
    ("runs", "Runs"),
    ("hits", "Hits"),
    ("doubles", "Doubles"),
    ("triples", "Triples"),
    ("homeRuns", "Home Runs"),
    ("rbi", "Runs Batted In"),
    ("totalBases", "Total Bases"),
    ("baseOnBalls", "Walks"),
    ("intentionalWalks", "Intentional Walks"),
    ("strikeOuts", "Strikeouts"),
    ("hitByPitch", "Hit By Pitch"),
    ("groundIntoDoublePlay", "Grounded Into Double Play"),
    ("stolenBases", "Stolen Bases"),
    ("caughtStealing", "Caught Stealing"),
    ("avg", "Batting Average"),
    ("obp", "On-Base Percentage"),
    ("slg", "Slugging Percentage"),
    ("ops", "On-Base Plus Slugging"),
    ("babip", "Batting Avg on Balls in Play"),
]

PACE_HITTING = [
    ("hits", "Hits"),
    ("homeRuns", "Home Runs"),
    ("rbi", "RBI"),
    ("runs", "Runs"),
    ("baseOnBalls", "Walks"),
    ("strikeOuts", "Strikeouts"),
    ("stolenBases", "Stolen Bases"),
]

PACE_PITCHING = [
    ("inningsPitched", "Innings"),
    ("strikeOuts", "Strikeouts"),
    ("baseOnBalls", "Walks"),
    ("earnedRuns", "Earned Runs"),
    ("hits", "Hits Allowed"),
]

PITCHING_FIELDS = [
    ("wins", "Wins"),
    ("losses", "Losses"),
    ("era", "Earned Run Average"),
    ("gamesPlayed", "Games"),
    ("gamesStarted", "Games Started"),
    ("completeGames", "Complete Games"),
    ("shutouts", "Shutouts"),
    ("saves", "Saves"),
    ("saveOpportunities", "Save Opportunities"),
    ("holds", "Holds"),
    ("blownSaves", "Blown Saves"),
    ("inningsPitched", "Innings Pitched"),
    ("battersFaced", "Batters Faced"),
    ("hits", "Hits Allowed"),
    ("runs", "Runs Allowed"),
    ("earnedRuns", "Earned Runs"),
    ("homeRuns", "Home Runs Allowed"),
    ("baseOnBalls", "Walks"),
    ("strikeOuts", "Strikeouts"),
    ("hitBatsmen", "Hit Batters"),
    ("wildPitches", "Wild Pitches"),
    ("balks", "Balks"),
    ("whip", "Walks + Hits per Inning"),
    ("strikeoutsPer9Inn", "Strikeouts per 9 Innings"),
    ("walksPer9Inn", "Walks per 9 Innings"),
    ("strikeoutWalkRatio", "Strikeout-to-Walk Ratio"),
]


def ensure_dialog_visible(top: ctk.CTkToplevel) -> None:
    """Force a CTkToplevel to the foreground.

    On some Windows + PyInstaller builds, a freshly created Toplevel opens behind
    the main window and never raises itself, making the dialog appear to be
    completely missing. This sequence (update_idletasks -> lift -> topmost flash
    -> focus_force) is the standard workaround."""
    try:
        top.update_idletasks()
        top.lift()
        top.attributes("-topmost", True)
        top.after(400, lambda: top.attributes("-topmost", False))
        top.focus_force()
    except Exception:
        pass


def run_in_thread(target: Callable[[], Any], on_done: Callable[[Any], None]) -> None:
    """Run a blocking callable in a thread, then schedule on_done on the Tk main loop."""

    def worker():
        try:
            result = target()
        except Exception as e:
            result = e
        try:
            App.instance.after(0, lambda: on_done(result))
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


class UpdateDialog(ctk.CTkToplevel):
    """Modal dialog: check status, show release notes, download + install."""

    def __init__(self, master: "App") -> None:
        super().__init__(master)
        self.app = master
        self.title(f"{APP_TITLE} — Updates")
        self.geometry("520x420")
        self.minsize(440, 320)
        self.transient(master)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self, text="Check for Updates",
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=18, pady=(16, 4), sticky="ew")

        ctk.CTkLabel(
            self, text=f"Current version: v{APP_VERSION}",
            font=ctk.CTkFont(size=12), text_color="gray60", anchor="w",
        ).grid(row=0, column=0, padx=18, pady=(46, 0), sticky="ew")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, padx=12, pady=8, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)

        self.footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer.grid(row=2, column=0, padx=18, pady=(0, 14), sticky="ew")
        self.footer.grid_columnconfigure(0, weight=1)

        self._result: dict[str, Any] | None = None
        self._show_checking()
        self.after(50, self._start_check)
        ensure_dialog_visible(self)

    def _clear_body(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        for w in self.footer.winfo_children():
            w.destroy()

    def _show_checking(self) -> None:
        self._clear_body()
        ctk.CTkLabel(
            self.body, text="Checking for updates…",
            font=ctk.CTkFont(size=14), text_color="gray70",
        ).grid(row=0, column=0, pady=40)

    def _start_check(self) -> None:
        run_in_thread(updater.check_for_update, self._on_check_done)

    def _on_check_done(self, result: Any) -> None:
        if isinstance(result, Exception):
            self._show_message("Error", f"Check failed: {result}", is_error=True)
            return
        self._result = result
        status = result.get("status")
        if status == "update_available":
            self._show_update_available(result)
        elif status == "no_update":
            self._show_message("You're up to date", result.get("message", ""))
        elif status == "not_configured":
            self._show_message("Updater not configured", result.get("message", ""), is_error=True)
        else:
            self._show_message("Update check failed", result.get("message", ""), is_error=True)

    def _show_message(self, heading: str, body: str, is_error: bool = False) -> None:
        self._clear_body()
        color = "tomato" if is_error else ("gray10", "gray90")
        ctk.CTkLabel(
            self.body, text=heading,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=color, anchor="w",
        ).grid(row=0, column=0, padx=6, pady=(6, 4), sticky="ew")
        ctk.CTkLabel(
            self.body, text=body, font=ctk.CTkFont(size=12),
            text_color="gray70", wraplength=470, justify="left", anchor="w",
        ).grid(row=1, column=0, padx=6, pady=(0, 6), sticky="ew")
        self.body.grid_rowconfigure(1, weight=1)
        ctk.CTkButton(self.footer, text="Close", command=self.destroy, width=110).grid(row=0, column=1)

    def _show_update_available(self, result: dict[str, Any]) -> None:
        self._clear_body()
        ctk.CTkLabel(
            self.body, text=f"Update available: v{result.get('latest', '?')}",
            font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
        ).grid(row=0, column=0, padx=6, pady=(6, 4), sticky="ew")
        ctk.CTkLabel(
            self.body, text=f"You're on v{result.get('current', '?')}.",
            font=ctk.CTkFont(size=12), text_color="gray70", anchor="w",
        ).grid(row=1, column=0, padx=6, pady=(0, 8), sticky="ew")

        notes = result.get("notes") or "(No release notes provided.)"
        notes_box = ctk.CTkTextbox(
            self.body, wrap="word", font=ctk.CTkFont(size=12), height=160,
        )
        notes_box.grid(row=2, column=0, padx=6, pady=4, sticky="nsew")
        notes_box.insert("1.0", notes)
        notes_box.configure(state="disabled")
        self.body.grid_rowconfigure(2, weight=1)

        if not updater.is_frozen():
            ctk.CTkLabel(
                self.body,
                text=(
                    "Note: in-place install only works in the packaged .exe build. "
                    "Running from source — please rebuild manually after pulling."
                ),
                font=ctk.CTkFont(size=11), text_color="gray60",
                wraplength=470, justify="left", anchor="w",
            ).grid(row=3, column=0, padx=6, pady=(6, 0), sticky="ew")

        ctk.CTkButton(self.footer, text="Later", width=90, fg_color="gray30",
                      hover_color="gray40", command=self.destroy).grid(row=0, column=1, padx=(0, 6))
        install_btn = ctk.CTkButton(
            self.footer, text="Download & Install", width=150,
            command=lambda: self._begin_download(result),
        )
        install_btn.grid(row=0, column=2)
        if not updater.is_frozen():
            install_btn.configure(state="disabled")

    def _begin_download(self, result: dict[str, Any]) -> None:
        self._clear_body()
        ctk.CTkLabel(
            self.body, text=f"Downloading v{result.get('latest', '?')}…",
            font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        ).grid(row=0, column=0, padx=6, pady=(6, 8), sticky="ew")

        self.progress = ctk.CTkProgressBar(self.body, mode="determinate")
        self.progress.set(0)
        self.progress.grid(row=1, column=0, padx=6, pady=8, sticky="ew")

        self.progress_label = ctk.CTkLabel(
            self.body, text="0%", font=ctk.CTkFont(size=12), text_color="gray70",
        )
        self.progress_label.grid(row=2, column=0, padx=6, pady=2)

        ctk.CTkButton(self.footer, text="Cancel", width=110, fg_color="gray30",
                      hover_color="gray40", command=self.destroy).grid(row=0, column=1)

        url = result["download_url"]
        dest = Path(tempfile.gettempdir()) / "MLB-Stats-Viewer.new.exe"

        def do_download():
            updater.download_update(url, dest, progress=self._on_progress)
            return dest

        run_in_thread(do_download, self._on_download_done)

    def _on_progress(self, done: int, total: int) -> None:
        def update_ui():
            if not self.winfo_exists():
                return
            if total > 0:
                frac = done / total
                self.progress.set(frac)
                self.progress_label.configure(
                    text=f"{frac * 100:.0f}%   ({done / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB)"
                )
            else:
                self.progress_label.configure(text=f"{done / 1024 / 1024:.1f} MB")
        try:
            self.after(0, update_ui)
        except Exception:
            pass

    def _on_download_done(self, result: Any) -> None:
        if isinstance(result, Exception):
            self._show_message("Download failed", str(result), is_error=True)
            return
        new_exe: Path = result
        self._clear_body()
        ctk.CTkLabel(
            self.body, text="Download complete.",
            font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        ).grid(row=0, column=0, padx=6, pady=(6, 4), sticky="ew")
        ctk.CTkLabel(
            self.body,
            text="The app will close, swap to the new version, and relaunch automatically.",
            font=ctk.CTkFont(size=12), text_color="gray70",
            wraplength=470, justify="left", anchor="w",
        ).grid(row=1, column=0, padx=6, pady=(0, 6), sticky="ew")

        if not updater.is_frozen():
            ctk.CTkLabel(
                self.body,
                text=f"(Dev mode) New file saved to:\n{new_exe}",
                font=ctk.CTkFont(size=11), text_color="gray60",
                wraplength=470, justify="left", anchor="w",
            ).grid(row=2, column=0, padx=6, pady=(8, 0), sticky="ew")
            ctk.CTkButton(self.footer, text="Close", command=self.destroy, width=110).grid(row=0, column=1)
            return

        def do_install():
            updater.install_and_restart(new_exe)

        ctk.CTkButton(
            self.footer, text="Install & Restart now", width=170,
            command=do_install,
        ).grid(row=0, column=1)


class WhatsNewDialog(ctk.CTkToplevel):
    """One-time release-notes popup, shown after the user installs a new version."""

    def __init__(self, master: "App", notes: list[tuple[str, str]]) -> None:
        super().__init__(master)
        self.title(f"{APP_TITLE} — What's New")
        self.geometry("440x300")
        self.minsize(380, 240)
        self.transient(master)
        self.grab_set()

        header = "What's new" if len(notes) == 1 else f"What's new in {len(notes)} updates"
        ctk.CTkLabel(
            self, text=header,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(padx=20, pady=(18, 4))

        ctk.CTkLabel(
            self, text=f"You're now on v{APP_VERSION}",
            font=ctk.CTkFont(size=12), text_color="gray60",
        ).pack(padx=20, pady=(0, 12))

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        for version, message in notes:
            entry = ctk.CTkFrame(body, fg_color=("gray88", "gray22"), corner_radius=6)
            entry.pack(fill="x", padx=4, pady=4)
            ctk.CTkLabel(
                entry, text=f"v{version}",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#1f6aa5", anchor="w",
            ).pack(anchor="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(
                entry, text=message,
                font=ctk.CTkFont(size=14),
                wraplength=360, justify="left", anchor="w",
            ).pack(anchor="w", padx=12, pady=(2, 10), fill="x")

        ctk.CTkButton(self, text="OK", width=100, command=self.destroy).pack(pady=(2, 14))

        ensure_dialog_visible(self)


class SettingsDialog(ctk.CTkToplevel):
    """Modal dialog for timezone + auto-refresh preferences."""

    def __init__(self, master: "App", on_changed: Callable[[], None]) -> None:
        super().__init__(master)
        self.app = master
        self.on_changed = on_changed
        self.title(f"{APP_TITLE} — Settings")
        self.geometry("460x520")
        self.minsize(420, 460)
        self.transient(master)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="Settings",
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=18, pady=(16, 16), sticky="ew")

        # Timezone
        ctk.CTkLabel(
            self, text="Display game times in:",
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w",
        ).grid(row=1, column=0, padx=18, pady=(0, 4), sticky="ew")

        current_tz = user_settings.get("timezone") or "system"
        current_label = user_settings.display_label_for(current_tz)
        self.tz_var = ctk.StringVar(value=current_label)
        tz_options = [label for label, _v in user_settings.TIMEZONE_CHOICES]
        self.tz_menu = ctk.CTkOptionMenu(
            self, values=tz_options, variable=self.tz_var, width=380,
        )
        self.tz_menu.grid(row=2, column=0, padx=18, pady=(0, 14), sticky="ew")

        # Auto-refresh
        ctk.CTkLabel(
            self, text="Live data refresh:",
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w",
        ).grid(row=3, column=0, padx=18, pady=(4, 4), sticky="ew")

        self.refresh_var = ctk.BooleanVar(value=bool(user_settings.get("auto_refresh")))
        ctk.CTkCheckBox(
            self,
            text="Auto-refresh games every minute (and live game detail every 30 seconds)",
            variable=self.refresh_var, onvalue=True, offvalue=False,
        ).grid(row=4, column=0, padx=18, pady=(0, 18), sticky="ew")

        # AI server settings
        ctk.CTkLabel(
            self, text="Local AI (Ollama) — used by the 'Ask AI' tab:",
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w",
        ).grid(row=5, column=0, padx=18, pady=(4, 4), sticky="ew")

        ai_grid = ctk.CTkFrame(self, fg_color="transparent")
        ai_grid.grid(row=6, column=0, padx=18, pady=(0, 6), sticky="ew")
        ai_grid.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(ai_grid, text="Server URL:", width=80, anchor="w").grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")
        self.ai_url_var = ctk.StringVar(value=user_settings.get("ai_base_url") or "")
        ctk.CTkEntry(ai_grid, textvariable=self.ai_url_var, placeholder_text="http://10.0.0.54:11434").grid(
            row=0, column=1, padx=0, pady=2, sticky="ew",
        )

        ctk.CTkLabel(ai_grid, text="Model:", width=80, anchor="w").grid(row=1, column=0, padx=(0, 6), pady=2, sticky="w")
        self.ai_model_var = ctk.StringVar(value=user_settings.get("ai_model") or "")
        ctk.CTkEntry(ai_grid, textvariable=self.ai_model_var, placeholder_text="llama3").grid(
            row=1, column=1, padx=0, pady=2, sticky="ew",
        )

        self.ai_test_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=11), text_color="gray60", anchor="w",
        )
        self.ai_test_label.grid(row=7, column=0, padx=18, pady=(0, 4), sticky="ew")

        ctk.CTkButton(
            self, text="Test AI connection", width=160, height=26,
            fg_color="gray30", hover_color="gray40",
            command=self._test_ai,
        ).grid(row=8, column=0, padx=18, pady=(0, 14), sticky="w")

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=9, column=0, padx=18, pady=(0, 16), sticky="ew")
        btn_row.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            btn_row, text="Cancel", width=100,
            fg_color="gray30", hover_color="gray40",
            command=self.destroy,
        ).grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(
            btn_row, text="Save", width=100, command=self._save,
        ).grid(row=0, column=2)

        ensure_dialog_visible(self)

    def _save(self) -> None:
        tz_id = user_settings.tz_id_for_label(self.tz_var.get())
        user_settings.save({
            "timezone": tz_id,
            "auto_refresh": bool(self.refresh_var.get()),
            "ai_base_url": self.ai_url_var.get().strip() or "http://10.0.0.54:11434",
            "ai_model": self.ai_model_var.get().strip() or "llama3",
        })
        self.destroy()
        try:
            self.on_changed()
        except Exception:
            pass

    def _test_ai(self) -> None:
        # Apply the entry values temporarily so ai.ping() uses what's typed
        user_settings.save({
            "ai_base_url": self.ai_url_var.get().strip() or "http://10.0.0.54:11434",
            "ai_model": self.ai_model_var.get().strip() or "llama3",
        })
        self.ai_test_label.configure(text="Testing…", text_color="gray60")

        def do_test():
            ok, msg = ai.ping()
            models = ai.list_models() if ok else []

            def update():
                if ok:
                    note = f"OK. Models available: {', '.join(models[:6])}" if models else "OK."
                    self.ai_test_label.configure(text=note, text_color="#42b883")
                else:
                    self.ai_test_label.configure(text=msg, text_color="tomato")
            try:
                self.after(0, update)
            except Exception:
                pass

        threading.Thread(target=do_test, daemon=True).start()


class SuggestionPopup(ctk.CTkFrame):
    """Floating typeahead dropdown anchored under the search entry."""

    MAX_RESULTS = 8

    def __init__(self, master: "App", on_select: Callable[[dict[str, Any]], None]) -> None:
        super().__init__(
            master,
            fg_color=("gray92", "gray18"),
            border_width=1,
            border_color=("gray70", "gray35"),
            corner_radius=6,
        )
        self.app = master
        self.on_select = on_select
        self.buttons: list[ctk.CTkButton] = []
        self._visible = False

    def show(self, x: int, y: int, width: int, suggestions: list[dict[str, Any]]) -> None:
        self._clear()
        if not suggestions:
            self.hide()
            return
        for p in suggestions:
            team = p.get("teamName") or "—"
            pos = p.get("position") or "—"
            label = f"  {p['fullName']}   ({pos}, {team})"
            btn = ctk.CTkButton(
                self,
                text=label,
                anchor="w",
                height=30,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray80", "gray30"),
                command=lambda pl=p: self._select(pl),
            )
            btn.bind("<Return>", lambda _e, pl=p: self._select(pl))
            btn._player = p  # type: ignore[attr-defined]
            btn.pack(fill="x", padx=2, pady=1)
            self.buttons.append(btn)
        self.place(x=x, y=y, width=width)
        self.lift()
        self._visible = True

    def show_message(self, x: int, y: int, width: int, message: str) -> None:
        """Show the popup with a single status message (e.g., 'Loading...' or 'No matches')."""
        self._clear()
        msg_label = ctk.CTkLabel(
            self, text=message,
            text_color="gray60",
            font=ctk.CTkFont(size=12),
            anchor="w",
        )
        msg_label.pack(fill="x", padx=10, pady=10)
        self.place(x=x, y=y, width=width)
        self.lift()
        self._visible = True

    def hide(self) -> None:
        if self._visible:
            self.place_forget()
            self._visible = False

    def is_visible(self) -> bool:
        return self._visible

    def focus_first(self) -> bool:
        if self.buttons:
            self.buttons[0].focus_set()
            return True
        return False

    def first(self) -> dict[str, Any] | None:
        if not self.buttons:
            return None
        return getattr(self.buttons[0], "_player", None)

    def _clear(self) -> None:
        for w in list(self.winfo_children()):
            w.destroy()
        self.buttons.clear()

    def _select(self, player: dict[str, Any]) -> None:
        self.hide()
        self.on_select(player)


class AIChat(ctk.CTkFrame):
    """In-pane chat with a local Ollama server. Streams replies token-by-token
    and feeds the currently-viewed player/game to the AI as system context."""

    SYSTEM_PROMPT = (
        "You are a helpful MLB stats assistant. Answer questions about Major "
        "League Baseball — players, teams, games, stats, history, and rules. "
        "Be concise and factual. If the user is currently viewing a specific "
        "player or game, you'll receive that context — use it to answer "
        "follow-up questions naturally."
    )

    def __init__(self, master, app: "App", context_text: str | None = None) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.context_text = context_text
        self.messages: list[dict[str, str]] = []
        self.streaming = False
        self.stop_flag = False
        self._stream_text = ""
        self._stream_label: ctk.CTkLabel | None = None
        self.realtime_context: str = self._build_realtime_context_basic()
        self._build_layout()
        # Asynchronously pull today's schedule (live scores, probable pitchers)
        # so the AI can answer "who's playing right now?" without needing tools.
        threading.Thread(target=self._refresh_realtime_context, daemon=True).start()

    def _build_layout(self) -> None:
        # Header row
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(4, 0))
        ctk.CTkLabel(
            header, text="Ask AI",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            header, text="Clear chat", width=90, height=26,
            fg_color="gray30", hover_color="gray40",
            command=self._clear_chat,
        ).pack(side="right", padx=(4, 0))

        # Connection status (gets filled in by background ping)
        self.status_label = ctk.CTkLabel(
            self, text=f"Connecting to {ai.get_base_url()} (model: {ai.get_model()})…",
            font=ctk.CTkFont(size=11), text_color="gray60", anchor="w",
        )
        self.status_label.pack(fill="x", padx=12, pady=(2, 6))

        # Optional context indicator (current player/game)
        if self.context_text:
            ctx_frame = ctk.CTkFrame(self, fg_color=("gray88", "gray22"), corner_radius=6)
            ctx_frame.pack(fill="x", padx=8, pady=(0, 6))
            ctk.CTkLabel(
                ctx_frame, text="Current context (sent to AI):",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="gray60", anchor="w",
            ).pack(anchor="w", padx=8, pady=(6, 0))
            ctk.CTkLabel(
                ctx_frame, text=self.context_text,
                font=ctk.CTkFont(size=11), text_color=("gray20", "gray85"),
                anchor="w", wraplength=560, justify="left",
            ).pack(anchor="w", padx=8, pady=(0, 6), fill="x")

        # Scrollable chat history
        self.history = ctk.CTkScrollableFrame(self, fg_color=("gray92", "gray16"))
        self.history.pack(fill="both", expand=True, padx=8, pady=4)

        # Input row
        input_row = ctk.CTkFrame(self, fg_color="transparent")
        input_row.pack(fill="x", padx=8, pady=(4, 8))
        self.input_var = ctk.StringVar()
        self.input_entry = ctk.CTkEntry(
            input_row, textvariable=self.input_var,
            placeholder_text="Ask about a player, game, stat, or anything MLB…",
            height=36,
        )
        self.input_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.input_entry.bind("<Return>", lambda _e: self._on_send())
        self.input_entry.bind("<Button-1>", lambda _e: self._focus_input(), add="+")

        self.send_btn = ctk.CTkButton(
            input_row, text="Send", width=80, command=self._on_send,
        )
        self.send_btn.pack(side="right")

        # Welcome / hint
        if self.context_text:
            suggestion = (
                "Tip: I can see today's MLB schedule and the player or game you're "
                "currently viewing. Try asking 'is this player hot or cold lately?', "
                "'who's playing right now?', or 'who's most likely to win tonight?'"
            )
        else:
            suggestion = (
                "Tip: I can see today's MLB schedule. Try asking 'who's playing right "
                "now?', 'what's the score?', or open a player page for player-specific "
                "questions."
            )
        self._add_assistant_bubble(suggestion)

        # Ping the server in the background, update status when done
        threading.Thread(target=self._ping_server, daemon=True).start()

        # Focus input so user can start typing immediately
        self.after(150, self._focus_input)

    def _focus_input(self) -> None:
        try:
            inner = getattr(self.input_entry, "_entry", None)
            (inner or self.input_entry).focus_set()
        except Exception:
            pass

    def _build_realtime_context_basic(self) -> str:
        """Immediately-available context (just today's date) used until the full
        schedule loads in the background."""
        now = datetime.now()
        return f"Today is {now.strftime('%A, %B %d, %Y')}."

    def _refresh_realtime_context(self) -> None:
        """Background-fetch today's MLB schedule and rebuild the realtime context."""
        now = datetime.now()
        try:
            games = mlb_api.get_schedule(now.strftime("%Y-%m-%d"))
        except Exception:
            return
        lines = [f"Today is {now.strftime('%A, %B %d, %Y')}."]
        if not games:
            lines.append("No MLB games are scheduled today.")
        else:
            lines.append(f"Today's MLB schedule ({len(games)} game{'s' if len(games) != 1 else ''}):")
            for g in games:
                away = g.get("away", {}) or {}
                home = g.get("home", {}) or {}
                status = g.get("status", "Scheduled")
                a_name = away.get("name", "?")
                h_name = home.get("name", "?")
                a_score = away.get("score")
                h_score = home.get("score")
                if a_score is not None and h_score is not None:
                    score_str = f" — {a_name} {a_score}, {h_name} {h_score}"
                else:
                    score_str = ""
                pitch_str = ""
                ap = away.get("pitcherName")
                hp = home.get("pitcherName")
                if ap and ap != "TBD" and hp and hp != "TBD":
                    pitch_str = f" (probables: {ap} vs {hp})"
                lines.append(f"  • {a_name} @ {h_name} [{status}]{score_str}{pitch_str}")
        new_ctx = "\n".join(lines)
        try:
            self.after(0, lambda: setattr(self, "realtime_context", new_ctx))
        except Exception:
            pass

    def _ping_server(self) -> None:
        ok, msg = ai.ping()
        models = ai.list_models() if ok else []
        configured = ai.get_model()
        model_ok = any(m == configured or m.split(":")[0] == configured for m in models)

        def update():
            if not self.winfo_exists():
                return
            if not ok:
                self.status_label.configure(
                    text=f"AI unavailable — {msg}  (Change URL/model in Settings.)",
                    text_color="tomato",
                )
                return
            if models and not model_ok:
                short = ", ".join(models[:4])
                more = "" if len(models) <= 4 else f"  (+{len(models) - 4} more)"
                self.status_label.configure(
                    text=(
                        f"Connected, but model '{configured}' is not on the server. "
                        f"Try one of: {short}{more}.  Update in Settings."
                    ),
                    text_color="#e0a020",
                )
                return
            self.status_label.configure(
                text=f"Connected: {ai.get_base_url()} (model: {configured})",
                text_color="#42b883",
            )

        try:
            self.after(0, update)
        except Exception:
            pass

    def _add_user_bubble(self, text: str) -> None:
        wrap = ctk.CTkFrame(self.history, fg_color="transparent")
        wrap.pack(fill="x", padx=4, pady=4)
        bubble = ctk.CTkFrame(wrap, fg_color="#1f6aa5", corner_radius=10)
        bubble.pack(side="right", padx=(40, 4))
        ctk.CTkLabel(
            bubble, text=text, text_color="white",
            wraplength=420, justify="left", anchor="w",
            font=ctk.CTkFont(size=12),
        ).pack(padx=10, pady=6)
        self._scroll_to_bottom()

    def _add_assistant_bubble(self, text: str) -> ctk.CTkLabel:
        wrap = ctk.CTkFrame(self.history, fg_color="transparent")
        wrap.pack(fill="x", padx=4, pady=4)
        bubble = ctk.CTkFrame(wrap, fg_color=("gray85", "gray28"), corner_radius=10)
        bubble.pack(side="left", padx=(4, 40))
        label = ctk.CTkLabel(
            bubble, text=text, text_color=("gray10", "gray95"),
            wraplength=420, justify="left", anchor="w",
            font=ctk.CTkFont(size=12),
        )
        label.pack(padx=10, pady=6)
        self._scroll_to_bottom()
        return label

    def _scroll_to_bottom(self) -> None:
        def do():
            try:
                self.history._parent_canvas.yview_moveto(1.0)
            except Exception:
                pass
        self.after(50, do)

    def _clear_chat(self) -> None:
        if self.streaming:
            self.stop_flag = True
        self.messages.clear()
        for w in list(self.history.winfo_children()):
            w.destroy()
        self._add_assistant_bubble("Chat cleared.")

    def _on_send(self) -> None:
        if self.streaming:
            return
        text = self.input_var.get().strip()
        if not text:
            return
        self.input_var.set("")
        self._add_user_bubble(text)
        self.messages.append({"role": "user", "content": text})

        # Build the message list with a system prompt and any available context.
        # Refresh realtime context each send so live scores/statuses stay current
        # for users who leave the chat open for a while.
        threading.Thread(target=self._refresh_realtime_context, daemon=True).start()

        sys_prompt = self.SYSTEM_PROMPT
        if self.realtime_context:
            sys_prompt += "\n\n" + self.realtime_context
        if self.context_text:
            sys_prompt += f"\n\nThe user is currently viewing this in the app: {self.context_text}"
        send_messages = [{"role": "system", "content": sys_prompt}, *self.messages]

        # Empty assistant bubble we'll stream into
        self._stream_label = self._add_assistant_bubble("…")
        self._stream_text = ""

        self.streaming = True
        self.stop_flag = False
        self.send_btn.configure(text="Stop", command=self._on_stop)

        def on_chunk(chunk: str) -> None:
            self._stream_text += chunk
            text_so_far = self._stream_text

            def update():
                if self._stream_label is not None and self.winfo_exists():
                    try:
                        self._stream_label.configure(text=text_so_far)
                    except Exception:
                        pass
                    self._scroll_to_bottom()
            try:
                self.after(0, update)
            except Exception:
                pass

        def on_done(err: str | None) -> None:
            final_text = self._stream_text
            had_err = err is not None

            def finish():
                if not self.winfo_exists():
                    return
                if had_err:
                    if self._stream_label is not None:
                        try:
                            self._stream_label.configure(
                                text=f"[AI error] {err}",
                                text_color="tomato",
                            )
                        except Exception:
                            pass
                else:
                    if final_text:
                        self.messages.append({"role": "assistant", "content": final_text})
                    else:
                        if self._stream_label is not None:
                            try:
                                self._stream_label.configure(text="(no response)")
                            except Exception:
                                pass
                self.streaming = False
                self._stream_label = None
                try:
                    self.send_btn.configure(text="Send", command=self._on_send)
                except Exception:
                    pass
            try:
                self.after(0, finish)
            except Exception:
                pass

        threading.Thread(
            target=ai.stream_chat,
            args=(send_messages, on_chunk, on_done, lambda: self.stop_flag),
            daemon=True,
        ).start()

    def _on_stop(self) -> None:
        self.stop_flag = True


class App(ctk.CTk):
    instance: "App"

    def report_callback_exception(self, exc, val, tb) -> None:
        """Catch errors raised inside Tk callbacks (button commands, after handlers,
        bindings) and log them to error.log. Without this, --windowed swallows them
        and the app appears to do nothing when a click fails."""
        try:
            with open(_error_log_path(), "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] tk callback error\n")
                traceback.print_exception(exc, val, tb, file=f)
        except Exception:
            pass

    def __init__(self) -> None:
        super().__init__()
        App.instance = self

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title(f"{APP_TITLE}  v{APP_VERSION}")
        self.geometry(WINDOW_SIZE)
        self.minsize(1000, 640)

        self.selected_team_id: int | None = None
        self.current_players: list[dict[str, Any]] = []
        self._suggest_after_id: str | None = None
        self._games_date: datetime | None = None
        self._current_game_pk: int | None = None
        self._games_refresh_after_id: str | None = None
        self._detail_refresh_after_id: str | None = None
        self._ai_context_text: str | None = None  # last player/game viewed, for AI
        # Tracks what currently occupies the right-hand detail pane so background
        # refreshes never wipe an open player profile, game view, or AI chat.
        self._detail_mode: str = "empty"  # one of: empty | player | game | ai

        self._build_layout()
        self._load_teams()
        self._prewarm_player_index()
        # Put the cursor in the search box on launch so typing works immediately
        # without the user having to click into it first.
        self.after(100, self._force_search_focus)
        self.after(300, self._maybe_show_whats_new)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=210)
        self.grid_columnconfigure(1, weight=0, minsize=260)
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, height=64, corner_radius=0)
        header.grid(row=0, column=0, columnspan=3, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="MLB Stats Viewer",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=14, sticky="w")

        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(
            header,
            textvariable=self.search_var,
            placeholder_text="Search players by name (e.g. Aaron Judge)...",
            height=36,
        )
        self.search_entry.grid(row=0, column=1, padx=10, pady=14, sticky="ew")
        self.search_entry.bind("<Return>", self._on_search_enter)
        self.search_entry.bind("<KeyRelease>", self._on_search_key)
        self.search_entry.bind("<Escape>", lambda _e: self._hide_suggestions())
        self.search_entry.bind("<Down>", self._focus_first_suggestion)
        # On some Windows + PyInstaller builds, clicking a CTkEntry visually puts a
        # cursor in the field but leaves the inner Tk Entry unfocused, so keystrokes
        # go nowhere. Forcing focus on the inner widget on click resolves this.
        self.search_entry.bind("<Button-1>", lambda _e: self._force_search_focus(), add="+")

        self.suggestions = SuggestionPopup(self, on_select=self._open_suggestion)

        ctk.CTkButton(header, text="Search", width=90, command=self._on_search).grid(
            row=0, column=2, padx=(0, 8), pady=14
        )
        ctk.CTkButton(
            header, text="Clear", width=70, fg_color="gray30", hover_color="gray40",
            command=self._on_clear_search,
        ).grid(row=0, column=3, padx=(0, 8), pady=14)
        ctk.CTkButton(
            header, text="Today's Games", width=130,
            fg_color=("#1f6aa5", "#1f6aa5"), hover_color=("#144870", "#144870"),
            command=lambda: self._show_games_view(datetime.now()),
        ).grid(row=0, column=4, padx=(0, 8), pady=14)
        ctk.CTkButton(
            header, text="Ask AI", width=90,
            fg_color=("#7b3fbf", "#7b3fbf"), hover_color=("#5a2e8d", "#5a2e8d"),
            command=self._on_open_ai_chat,
        ).grid(row=0, column=5, padx=(0, 8), pady=14)
        ctk.CTkButton(
            header, text="Settings", width=90,
            fg_color="gray30", hover_color="gray40",
            command=self._on_open_settings,
        ).grid(row=0, column=6, padx=(0, 8), pady=14)
        ctk.CTkButton(
            header, text="Check for Updates", width=140,
            fg_color="gray30", hover_color="gray40",
            command=self._on_check_for_updates,
        ).grid(row=0, column=7, padx=(0, 18), pady=14)

        self.teams_frame = ctk.CTkScrollableFrame(self, label_text="Teams")
        self.teams_frame.grid(row=1, column=0, padx=(10, 5), pady=(0, 10), sticky="nsew")

        self.players_label_var = ctk.StringVar(value="Players")
        self.players_frame = ctk.CTkScrollableFrame(self, label_text="Players")
        self.players_frame.grid(row=1, column=1, padx=5, pady=(0, 10), sticky="nsew")

        self.detail_frame = ctk.CTkFrame(self)
        self.detail_frame.grid(row=1, column=2, padx=(5, 10), pady=(0, 10), sticky="nsew")

        self._show_placeholder("Select a team or search for a player.")

        self.status_var = ctk.StringVar(value="Loading teams...")
        ctk.CTkLabel(self, textvariable=self.status_var, anchor="w", height=22).grid(
            row=2, column=0, columnspan=3, padx=14, sticky="ew"
        )

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _clear_frame(self, frame: ctk.CTkBaseClass) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _show_placeholder(self, text: str) -> None:
        self._detail_mode = "empty"
        self._clear_frame(self.detail_frame)
        ctk.CTkLabel(
            self.detail_frame, text=text, font=ctk.CTkFont(size=15), text_color="gray70"
        ).pack(expand=True, pady=60)

    def _load_teams(self) -> None:
        self._set_status("Loading teams...")
        run_in_thread(mlb_api.get_teams, self._on_teams_loaded)

    def _on_teams_loaded(self, result: Any) -> None:
        if isinstance(result, Exception):
            self._set_status(f"Failed to load teams: {result}")
            return
        teams: list[dict[str, Any]] = result
        for t in teams:
            btn = ctk.CTkButton(
                self.teams_frame,
                text=f"{t['abbreviation']:<4} {t['name']}",
                anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray85", "gray25"),
                command=lambda tid=t["id"], tname=t["name"]: self._on_team_selected(tid, tname),
            )
            btn.pack(fill="x", padx=4, pady=2)
        self._set_status(f"Loaded {len(teams)} teams. Click a team or use the search bar.")

    def _on_team_selected(self, team_id: int, team_name: str) -> None:
        self.selected_team_id = team_id
        self.players_frame.configure(label_text=f"Roster — {team_name}")
        self._clear_frame(self.players_frame)
        ctk.CTkLabel(self.players_frame, text="Loading roster...", text_color="gray70").pack(pady=20)
        self._set_status(f"Loading roster for {team_name}...")
        run_in_thread(
            lambda: mlb_api.get_roster(team_id),
            lambda r: self._on_roster_loaded(team_name, r),
        )

    def _on_roster_loaded(self, team_name: str, result: Any) -> None:
        self._clear_frame(self.players_frame)
        if isinstance(result, Exception):
            self._set_status(f"Failed to load roster: {result}")
            ctk.CTkLabel(self.players_frame, text="Failed to load roster.", text_color="tomato").pack(pady=20)
            return
        roster: list[dict[str, Any]] = result
        self.current_players = roster
        for p in roster:
            label = f"#{p['jerseyNumber']:>2}  {p['fullName']}  ({p['position']})" if p["jerseyNumber"] else f"     {p['fullName']}  ({p['position']})"
            ctk.CTkButton(
                self.players_frame,
                text=label,
                anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray85", "gray25"),
                command=lambda pid=p["id"]: self._on_player_selected(pid),
            ).pack(fill="x", padx=4, pady=1)
        self._set_status(f"{team_name}: {len(roster)} players on active roster.")

    def _on_search(self) -> None:
        query = self.search_var.get().strip()
        if not query:
            return
        self.players_frame.configure(label_text=f'Search: "{query}"')
        self._clear_frame(self.players_frame)
        ctk.CTkLabel(self.players_frame, text="Searching...", text_color="gray70").pack(pady=20)
        self._set_status(f"Searching for '{query}'...")
        run_in_thread(
            lambda: mlb_api.search_players(query),
            lambda r: self._on_search_results(query, r),
        )

    def _on_clear_search(self) -> None:
        self.search_var.set("")
        self._hide_suggestions()
        self._games_date = None
        self._current_game_pk = None
        self._cancel_games_refresh()
        self._cancel_detail_refresh()
        self.players_frame.configure(label_text="Players")
        self._clear_frame(self.players_frame)
        self._show_placeholder("Select a team or search for a player.")
        self._set_status("Ready.")

    def _show_games_view(self, date: datetime) -> None:
        """Switch the middle panel to today/selected-day MLB games."""
        self._hide_suggestions()
        self._games_date = date
        date_label = date.strftime("%a %b %d, %Y")
        self.players_frame.configure(label_text=f"Games — {date_label}")
        self._clear_frame(self.players_frame)
        self._render_date_nav(date)
        ctk.CTkLabel(self.players_frame, text="Loading games...", text_color="gray70").pack(pady=20)
        self._set_status(f"Loading games for {date_label}...")
        run_in_thread(
            lambda: mlb_api.get_schedule(date.strftime("%Y-%m-%d")),
            lambda r: self._on_games_loaded(date, r),
        )

    def _render_date_nav(self, date: datetime) -> None:
        nav = ctk.CTkFrame(self.players_frame, fg_color="transparent")
        nav.pack(fill="x", padx=4, pady=(2, 6))
        ctk.CTkButton(
            nav, text="◀ Prev", width=58, height=26,
            fg_color="gray30", hover_color="gray40",
            command=lambda: self._show_games_view(date - timedelta(days=1)),
        ).pack(side="left", padx=(2, 4))
        ctk.CTkButton(
            nav, text="Today", width=58, height=26,
            fg_color="gray30", hover_color="gray40",
            command=lambda: self._show_games_view(datetime.now()),
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            nav, text="Next ▶", width=58, height=26,
            fg_color="gray30", hover_color="gray40",
            command=lambda: self._show_games_view(date + timedelta(days=1)),
        ).pack(side="left", padx=(4, 4))
        ctk.CTkButton(
            nav, text="↻ Refresh", width=80, height=26,
            fg_color="#1f6aa5", hover_color="#144870",
            command=lambda: self._show_games_view(date),
        ).pack(side="right", padx=(4, 2))

    def _on_games_loaded(self, date: datetime, result: Any, is_refresh: bool = False) -> None:
        if self._games_date != date:
            return
        self._clear_frame(self.players_frame)
        self._render_date_nav(date)
        if isinstance(result, Exception):
            ctk.CTkLabel(self.players_frame, text=f"Failed to load games: {result}", text_color="tomato").pack(pady=20)
            self._set_status("Schedule load failed.")
            return
        games: list[dict[str, Any]] = result
        if not games:
            ctk.CTkLabel(self.players_frame, text="No games scheduled.", text_color="gray70").pack(pady=20)
            self._set_status(f"No games on {date.strftime('%a %b %d')}.")
            self._schedule_games_refresh()
            return
        for g in games:
            self._render_game_card(g)
        tz_label = user_settings.current_zone_label()
        self._set_status(f"{len(games)} game(s) on {date.strftime('%a %b %d, %Y')}  •  Times: {tz_label}")
        # Only show the hint in the detail pane on the FIRST load and only when the
        # pane is empty — never on a background refresh, so we don't wipe an open
        # player profile, game view, or AI chat.
        if not is_refresh and self._detail_mode == "empty":
            self._show_placeholder("Click 'View Game' on any card to open a live in-app view,\nor click a team / probable pitcher to navigate.")
        self._schedule_games_refresh()

    def _schedule_games_refresh(self) -> None:
        self._cancel_games_refresh()
        if not user_settings.get("auto_refresh"):
            return
        if self._games_date is None:
            return
        self._games_refresh_after_id = self.after(60_000, self._auto_refresh_games)

    def _auto_refresh_games(self) -> None:
        self._games_refresh_after_id = None
        if self._games_date is None:
            return
        date = self._games_date

        def fetch():
            return mlb_api.get_schedule(date.strftime("%Y-%m-%d"))

        run_in_thread(fetch, lambda r: self._on_games_loaded(date, r, is_refresh=True))

    def _cancel_games_refresh(self) -> None:
        if self._games_refresh_after_id is not None:
            try:
                self.after_cancel(self._games_refresh_after_id)
            except Exception:
                pass
            self._games_refresh_after_id = None

    def _cancel_detail_refresh(self) -> None:
        if self._detail_refresh_after_id is not None:
            try:
                self.after_cancel(self._detail_refresh_after_id)
            except Exception:
                pass
            self._detail_refresh_after_id = None

    def _render_game_card(self, game: dict[str, Any]) -> None:
        card = ctk.CTkFrame(self.players_frame, fg_color=("gray88", "gray20"), corner_radius=6)
        card.pack(fill="x", padx=4, pady=4)

        # Header: time + status + venue
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(8, 2))
        time_text = self._format_game_time(game.get("gameDate"))
        status = game.get("status", "")
        status_color = "#42b883" if "Progress" in status or status == "Live" else "gray60"
        ctk.CTkLabel(
            header, text=f"{time_text}  •  {status}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=status_color,
            anchor="w",
        ).pack(side="left")
        venue = game.get("venue") or ""
        if venue:
            ctk.CTkLabel(
                header, text=venue, font=ctk.CTkFont(size=10),
                text_color="gray60", anchor="e",
            ).pack(side="right")

        self._render_team_row(card, game.get("away", {}), is_home=False)
        self._render_team_row(card, game.get("home", {}), is_home=True)

        game_pk = game.get("gamePk")
        if game_pk is not None:
            ctk.CTkButton(
                card, text="View Game →", height=24,
                fg_color="#1f6aa5", hover_color="#144870",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda gpk=game_pk: self._show_game_detail(gpk),
            ).pack(fill="x", padx=10, pady=(2, 8))

    def _render_team_row(self, parent: ctk.CTkBaseClass, team: dict[str, Any], is_home: bool) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 4))

        prefix = "vs " if is_home else "@ "
        name = team.get("name") or "?"
        record = team.get("record") or ""
        score = team.get("score")

        team_id = team.get("id")
        team_btn = ctk.CTkButton(
            row,
            text=f"{prefix}{name}  ({record})" if record else f"{prefix}{name}",
            anchor="w",
            fg_color="transparent",
            text_color=("gray10", "gray90"),
            hover_color=("gray80", "gray28"),
            height=26,
            command=(lambda tid=team_id, tname=name: self._on_team_selected(tid, tname)) if team_id else None,
        )
        team_btn.pack(side="left", fill="x", expand=True)

        if score is not None:
            ctk.CTkLabel(
                row, text=str(score),
                font=ctk.CTkFont(size=15, weight="bold"),
                width=32, anchor="e",
            ).pack(side="right", padx=(4, 0))

        pitcher_name = team.get("pitcherName") or "TBD"
        pitcher_id = team.get("pitcherId")
        pitcher_text = f"  P: {pitcher_name}"
        pitcher_btn = ctk.CTkButton(
            parent,
            text=pitcher_text,
            anchor="w",
            fg_color="transparent",
            text_color="gray60",
            hover_color=("gray80", "gray28"),
            height=22,
            font=ctk.CTkFont(size=11),
            command=(lambda pid=pitcher_id: self._on_player_selected(pid)) if pitcher_id else None,
        )
        pitcher_btn.pack(fill="x", padx=10, pady=(0, 2))

    def _format_game_time(self, iso_utc: str | None) -> str:
        return user_settings.format_game_time(iso_utc)

    def _prewarm_player_index(self) -> None:
        """Background-load the full player list so the first keystroke is instant."""
        threading.Thread(target=mlb_api.get_all_players, daemon=True).start()

    def _build_player_context(self, bio: dict[str, Any], hit: dict[str, Any], pit: dict[str, Any]) -> str:
        """Compact one-line summary of a player passed to the AI as context."""
        parts: list[str] = []
        name = bio.get("fullName", "Unknown")
        team = (bio.get("currentTeam") or {}).get("name", "—")
        pos = (bio.get("primaryPosition") or {}).get("name", "—")
        parts.append(f"Player: {name} ({pos}, {team})")
        if hit:
            parts.append(
                f"Hitting (current season): G={hit.get('gamesPlayed')}, "
                f"AB={hit.get('atBats')}, H={hit.get('hits')}, "
                f"HR={hit.get('homeRuns')}, RBI={hit.get('rbi')}, "
                f"BB={hit.get('baseOnBalls')}, SO={hit.get('strikeOuts')}, "
                f"AVG={hit.get('avg')}, OBP={hit.get('obp')}, "
                f"SLG={hit.get('slg')}, OPS={hit.get('ops')}"
            )
        if pit:
            parts.append(
                f"Pitching (current season): W-L={pit.get('wins')}-{pit.get('losses')}, "
                f"ERA={pit.get('era')}, G={pit.get('gamesPlayed')}, "
                f"GS={pit.get('gamesStarted')}, IP={pit.get('inningsPitched')}, "
                f"K={pit.get('strikeOuts')}, BB={pit.get('baseOnBalls')}, "
                f"WHIP={pit.get('whip')}"
            )
        return " | ".join(parts)

    def _build_game_context(self, g: dict[str, Any]) -> str:
        """Compact summary of a game passed to the AI as context."""
        status = (g.get("status") or {}).get("detailed", "?")
        away = g.get("away", {}) or {}
        home = g.get("home", {}) or {}
        venue = g.get("venue", "")
        line = (
            f"Game: {away.get('name', '?')} ({away.get('runs', '-')}) @ "
            f"{home.get('name', '?')} ({home.get('runs', '-')}) — {status}"
        )
        if venue:
            line += f" at {venue}"
        if g.get("status", {}).get("isLive"):
            inning = g.get("currentInningOrdinal") or g.get("currentInning")
            half = g.get("inningHalf") or ""
            outs = g.get("outs", "?")
            line += f" | {half} {inning}, {outs} out(s)"
            cb = (g.get("currentBatter") or {}).get("name")
            cp = (g.get("currentPitcher") or {}).get("name")
            if cb:
                line += f" | At bat: {cb}"
            if cp:
                line += f" | Pitching: {cp}"
        return line

    def _force_search_focus(self) -> None:
        """Reliably focus the inner Tk Entry, working around a CTkEntry quirk where
        the wrapper holds visual focus but the inner widget does not receive keys."""
        try:
            inner = getattr(self.search_entry, "_entry", None)
            if inner is not None:
                inner.focus_set()
            else:
                self.search_entry.focus_set()
        except Exception:
            pass

    def _on_check_for_updates(self) -> None:
        dialog = UpdateDialog(self)
        dialog.focus()

    def _maybe_show_whats_new(self) -> None:
        """Show release notes for any versions newer than the last one the user has seen."""
        last_seen = user_settings.get("last_seen_version") or ""
        if last_seen == APP_VERSION:
            return
        last_t = updater.parse_version(last_seen) if last_seen else (0,)
        current_t = updater.parse_version(APP_VERSION)
        unseen: list[tuple[str, str]] = []
        for v, msg in sorted(WHATS_NEW.items(), key=lambda kv: updater.parse_version(kv[0])):
            vt = updater.parse_version(v)
            if last_t < vt <= current_t:
                unseen.append((v, msg))
        user_settings.save({"last_seen_version": APP_VERSION})
        if unseen:
            WhatsNewDialog(self, notes=unseen).focus()

    def _on_open_settings(self) -> None:
        SettingsDialog(self, on_changed=self._on_settings_changed).focus()

    def _on_open_ai_chat(self) -> None:
        self._current_game_pk = None
        self._cancel_detail_refresh()
        self._detail_mode = "ai"
        self._clear_frame(self.detail_frame)
        AIChat(self.detail_frame, app=self, context_text=self._ai_context_text).pack(
            fill="both", expand=True
        )

    def _on_settings_changed(self) -> None:
        """Settings were saved — refresh visible time-sensitive UI."""
        if self._games_date is not None:
            self._show_games_view(self._games_date)
        if self._current_game_pk is not None:
            self._show_game_detail(self._current_game_pk)

    def _show_game_detail(self, game_pk: int) -> None:
        self._current_game_pk = game_pk
        self._cancel_detail_refresh()
        self._detail_mode = "game"
        self._clear_frame(self.detail_frame)
        ctk.CTkLabel(
            self.detail_frame, text="Loading game...", text_color="gray70",
            font=ctk.CTkFont(size=14),
        ).pack(expand=True, pady=60)
        self._set_status(f"Loading game {game_pk}...")
        run_in_thread(
            lambda: mlb_api.get_game_detail(game_pk),
            lambda r: self._on_game_detail_loaded(game_pk, r),
        )

    def _on_game_detail_loaded(self, game_pk: int, result: Any) -> None:
        if self._current_game_pk != game_pk:
            return
        self._clear_frame(self.detail_frame)
        if isinstance(result, Exception):
            ctk.CTkLabel(self.detail_frame, text=f"Failed to load game: {result}", text_color="tomato").pack(pady=40)
            self._set_status("Game load failed.")
            return
        self._render_game_detail(result)
        status = (result.get("status") or {})
        is_live = status.get("isLive")
        label = "LIVE" if is_live else status.get("detailed", "")
        self._set_status(f"Game {game_pk} loaded  •  {label}")
        if is_live and user_settings.get("auto_refresh"):
            self._detail_refresh_after_id = self.after(30_000, lambda: self._show_game_detail(game_pk))

    def _render_game_detail(self, g: dict[str, Any]) -> None:
        self._ai_context_text = self._build_game_context(g)
        scroll = ctk.CTkScrollableFrame(self.detail_frame)
        scroll.pack(fill="both", expand=True, padx=8, pady=8)

        status = g.get("status", {}) or {}
        is_live = status.get("isLive")
        is_final = status.get("isFinal")
        status_text = status.get("detailed", "")
        status_color = "#42b883" if is_live else "gray70"

        # Header
        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(4, 4))
        ctk.CTkLabel(
            header, text=("LIVE  •  " if is_live else "") + status_text,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=status_color, anchor="w",
        ).pack(side="left")
        ctk.CTkButton(
            header, text="↻ Refresh", width=80, height=26,
            fg_color="#1f6aa5", hover_color="#144870",
            command=lambda: self._show_game_detail(g["gamePk"]),
        ).pack(side="right")

        time_text = self._format_game_time(g.get("datetime")) or ""
        venue = g.get("venue") or ""
        meta_text = "  •  ".join([t for t in (time_text, venue) if t])
        if meta_text:
            ctk.CTkLabel(scroll, text=meta_text, font=ctk.CTkFont(size=12),
                         text_color="gray60", anchor="w").pack(anchor="w", padx=10, pady=(0, 6))

        # Big score panel
        away = g.get("away", {}) or {}
        home = g.get("home", {}) or {}
        self._render_score_row(scroll, away, home)

        # Live state (count, bases, current play)
        if is_live:
            self._render_live_state(scroll, g)

        # Linescore inning-by-inning
        innings = g.get("innings") or []
        if innings:
            self._render_linescore(scroll, g, away, home, innings)

        # Browser links
        link_row = ctk.CTkFrame(scroll, fg_color="transparent")
        link_row.pack(fill="x", padx=8, pady=(12, 6))
        ctk.CTkButton(
            link_row, text="Open in MLB Gameday (free, in-browser)",
            command=lambda: webbrowser.open(mlb_api.gameday_url(g["gamePk"])),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            link_row, text="Open on MLB.tv (subscription)",
            fg_color="gray30", hover_color="gray40",
            command=lambda: webbrowser.open(mlb_api.mlbtv_url(g["gamePk"])),
        ).pack(side="left")

        # Box score tables for each team
        if is_live or is_final:
            self._render_team_box(scroll, away, "Away — " + (away.get("name") or "Away"))
            self._render_team_box(scroll, home, "Home — " + (home.get("name") or "Home"))

    def _render_score_row(self, parent, away, home) -> None:
        box = ctk.CTkFrame(parent, fg_color=("gray88", "gray20"), corner_radius=8)
        box.pack(fill="x", padx=8, pady=8)
        box.grid_columnconfigure(1, weight=1)

        def row(r, side_label, team, color):
            ctk.CTkLabel(
                box, text=side_label, font=ctk.CTkFont(size=10, weight="bold"),
                text_color="gray60", anchor="w", width=44,
            ).grid(row=r, column=0, padx=(12, 6), pady=4, sticky="w")
            ctk.CTkLabel(
                box, text=team.get("name") or "?",
                font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
            ).grid(row=r, column=1, padx=4, pady=4, sticky="w")
            ctk.CTkLabel(
                box, text=str(team.get("runs") if team.get("runs") is not None else "—"),
                font=ctk.CTkFont(size=28, weight="bold"), text_color=color,
                width=60, anchor="e",
            ).grid(row=r, column=2, padx=(8, 16), pady=4, sticky="e")

        away_runs = away.get("runs") or 0
        home_runs = home.get("runs") or 0
        away_color = "#42b883" if away_runs > home_runs else ("gray10", "gray90")
        home_color = "#42b883" if home_runs > away_runs else ("gray10", "gray90")
        row(0, "AWAY", away, away_color)
        row(1, "HOME", home, home_color)

    def _render_player_chip(self, parent, label_text: str, person: dict[str, Any]) -> None:
        chip = ctk.CTkFrame(parent, fg_color="transparent")
        chip.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(
            chip, text=label_text,
            font=ctk.CTkFont(size=11), text_color="gray60",
        ).pack(side="left", padx=(0, 4))
        pid = person.get("id")
        name = person.get("name") or "—"
        if pid:
            ctk.CTkButton(
                chip, text=name, height=22,
                fg_color="transparent",
                text_color=("#1f6aa5", "#7fc4ff"),
                hover_color=("gray80", "gray28"),
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda p=pid: self._on_player_selected(p),
            ).pack(side="left")
        else:
            ctk.CTkLabel(
                chip, text=name, font=ctk.CTkFont(size=12, weight="bold"),
            ).pack(side="left")

    def _render_live_state(self, parent, g) -> None:
        block = ctk.CTkFrame(parent)
        block.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(
            block, text="Live", font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#42b883", anchor="w",
        ).pack(anchor="w", padx=12, pady=(8, 2))

        half = (g.get("inningState") or g.get("inningHalf") or "").strip()
        ord_inn = g.get("currentInningOrdinal") or (str(g.get("currentInning") or ""))
        outs = g.get("outs", 0)
        balls = g.get("balls", 0)
        strikes = g.get("strikes", 0)
        bases = g.get("onBase") or {}
        runners = [
            label for label, key in [("1B", "first"), ("2B", "second"), ("3B", "third")]
            if bases.get(key)
        ]
        runner_text = "Bases: " + (", ".join(runners) if runners else "empty")

        line = f"{half} {ord_inn}    •    Count: {balls}-{strikes}    •    {outs} out{'s' if outs != 1 else ''}    •    {runner_text}"
        ctk.CTkLabel(block, text=line, font=ctk.CTkFont(size=12), anchor="w").pack(
            anchor="w", padx=12, pady=(0, 4)
        )

        people_row = ctk.CTkFrame(block, fg_color="transparent")
        people_row.pack(fill="x", padx=10, pady=(0, 4))

        for label_text, person in [
            ("At bat:", g.get("currentBatter") or {}),
            ("On deck:", g.get("onDeck") or {}),
            ("Pitching:", g.get("currentPitcher") or {}),
        ]:
            self._render_player_chip(people_row, label_text, person)

        play = (g.get("currentPlay") or {}).get("description")
        if play:
            ctk.CTkLabel(
                block, text=f"Last play: {play}", font=ctk.CTkFont(size=12),
                text_color=("gray10", "gray90"), anchor="w",
                wraplength=560, justify="left",
            ).pack(anchor="w", padx=12, pady=(2, 10))

    def _render_linescore(self, parent, g, away, home, innings) -> None:
        block = ctk.CTkFrame(parent)
        block.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(
            block, text="Linescore", font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        ).pack(anchor="w", padx=12, pady=(8, 4))

        table = ctk.CTkFrame(block, fg_color="transparent")
        table.pack(fill="x", padx=8, pady=(0, 10))

        scheduled = g.get("scheduledInnings") or 9
        max_inning = max(scheduled, max((i["num"] for i in innings if i.get("num")), default=0))

        # Header row: Team | 1 2 3 ... | R H E
        ctk.CTkLabel(table, text="", width=110, anchor="w").grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        for i in range(1, max_inning + 1):
            ctk.CTkLabel(
                table, text=str(i), width=28,
                font=ctk.CTkFont(size=10, weight="bold"), text_color="gray60",
            ).grid(row=0, column=i, padx=1, pady=2)
        for j, lbl in enumerate(["R", "H", "E"]):
            ctk.CTkLabel(
                table, text=lbl, width=32,
                font=ctk.CTkFont(size=11, weight="bold"),
            ).grid(row=0, column=max_inning + 1 + j, padx=(6 if j == 0 else 1, 1), pady=2)

        def cell(r, c, text, **kwargs):
            ctk.CTkLabel(table, text=text, **kwargs).grid(row=r, column=c, padx=1, pady=1)

        for r, (label, team, key) in enumerate([
            ("Away", away, "away_runs"), ("Home", home, "home_runs")
        ], start=1):
            cell(r, 0, f"{team.get('abbreviation') or team.get('name', label)}",
                 width=110, anchor="w", font=ctk.CTkFont(size=12, weight="bold"))
            innings_by_num = {i["num"]: i for i in innings if i.get("num")}
            for i in range(1, max_inning + 1):
                inning = innings_by_num.get(i)
                val = inning.get(key) if inning else None
                text = str(val) if val is not None else "—"
                cell(r, i, text, width=28, font=ctk.CTkFont(size=12))
            for j, k in enumerate(["runs", "hits", "errors"]):
                v = team.get(k)
                cell(r, max_inning + 1 + j, str(v) if v is not None else "—",
                     width=32, font=ctk.CTkFont(size=12, weight="bold"))

    def _render_team_box(self, parent, team, title) -> None:
        block = ctk.CTkFrame(parent)
        block.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(
            block, text=title, font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        ).pack(anchor="w", padx=12, pady=(8, 4))

        players = team.get("players") or []
        batters = [p for p in players if p.get("batting", {}).get("ab") is not None]
        pitchers = [p for p in players if p.get("pitching", {}).get("ip") is not None]
        batters.sort(key=lambda p: -(p.get("batting", {}).get("ab") or 0))
        pitchers.sort(key=lambda p: -(mlb_api.ip_to_float(p.get("pitching", {}).get("ip")) or 0))

        if batters:
            self._render_box_table(
                block, "Batters",
                ["Player", "Pos", "AB", "R", "H", "RBI", "BB", "K", "HR", "AVG"],
                [
                    [
                        p["name"], p.get("position", ""),
                        p["batting"].get("ab"), p["batting"].get("r"),
                        p["batting"].get("h"), p["batting"].get("rbi"),
                        p["batting"].get("bb"), p["batting"].get("k"),
                        p["batting"].get("hr"), p["batting"].get("avg"),
                    ]
                    for p in batters
                ],
                player_ids=[p.get("id") for p in batters],
            )
        if pitchers:
            self._render_box_table(
                block, "Pitchers",
                ["Player", "IP", "H", "R", "ER", "BB", "K", "ERA"],
                [
                    [
                        p["name"],
                        p["pitching"].get("ip"), p["pitching"].get("h"),
                        p["pitching"].get("r"), p["pitching"].get("er"),
                        p["pitching"].get("bb"), p["pitching"].get("k"),
                        p["pitching"].get("era"),
                    ]
                    for p in pitchers
                ],
                player_ids=[p.get("id") for p in pitchers],
            )

    def _render_box_table(self, parent, subtitle, headers, rows, player_ids) -> None:
        ctk.CTkLabel(
            parent, text=subtitle, font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray60", anchor="w",
        ).pack(anchor="w", padx=14, pady=(6, 2))

        tbl = ctk.CTkFrame(parent, fg_color="transparent")
        tbl.pack(fill="x", padx=8, pady=(0, 6))

        for c, h in enumerate(headers):
            tbl.grid_columnconfigure(c, weight=(2 if c == 0 else 1), uniform="box")
            ctk.CTkLabel(
                tbl, text=h, font=ctk.CTkFont(size=10, weight="bold"),
                text_color="gray60", anchor="w" if c == 0 else "center",
            ).grid(row=0, column=c, padx=2, pady=(2, 4), sticky="ew")

        for r, row in enumerate(rows, start=1):
            pid = player_ids[r - 1] if r - 1 < len(player_ids) else None
            for c, val in enumerate(row):
                text = "—" if val is None or val == "" else str(val)
                if c == 0 and pid:
                    btn = ctk.CTkButton(
                        tbl, text=text, anchor="w", height=22,
                        fg_color="transparent",
                        text_color=("gray10", "gray90"),
                        hover_color=("gray80", "gray28"),
                        font=ctk.CTkFont(size=11),
                        command=lambda p=pid: self._on_player_selected(p),
                    )
                    btn.grid(row=r, column=c, padx=2, pady=1, sticky="ew")
                else:
                    ctk.CTkLabel(
                        tbl, text=text, font=ctk.CTkFont(size=11),
                        anchor="w" if c == 0 else "center",
                    ).grid(row=r, column=c, padx=2, pady=1, sticky="ew")

    def _on_search_enter(self, _event=None) -> None:
        """Enter key: open the top suggestion if visible, else run the full search."""
        if self.suggestions.is_visible():
            top = self.suggestions.first()
            if top is not None:
                self.suggestions.hide()
                self._open_suggestion(top)
                return
        self._on_search()

    def _on_search_key(self, event) -> None:
        """Debounced typeahead — schedule a suggestions refresh ~120ms after typing."""
        if event.keysym in ("Return", "Escape", "Up", "Down", "Left", "Right", "Tab"):
            return
        if self._suggest_after_id is not None:
            try:
                self.after_cancel(self._suggest_after_id)
            except Exception:
                pass
        self._suggest_after_id = self.after(120, self._update_suggestions)

    def _update_suggestions(self) -> None:
        self._suggest_after_id = None
        query = self.search_var.get().strip()
        if len(query) < 2:
            self._hide_suggestions()
            return

        matches = mlb_api.search_players(query, limit=SuggestionPopup.MAX_RESULTS)
        index_size = mlb_api.player_index_size()

        self.update_idletasks()
        x = self.search_entry.winfo_rootx() - self.winfo_rootx()
        y = (
            self.search_entry.winfo_rooty()
            - self.winfo_rooty()
            + self.search_entry.winfo_height()
            + 2
        )
        width = self.search_entry.winfo_width()

        if matches:
            self.suggestions.show(x, y, width, matches)
        elif index_size == 0:
            # Index hasn't loaded yet — kick off a retry in the background so the
            # next keystroke can succeed even if the original prewarm failed.
            threading.Thread(target=mlb_api.get_all_players, daemon=True).start()
            self.suggestions.show_message(
                x, y, width, "Loading player list… try again in a few seconds.",
            )
        else:
            self.suggestions.show_message(
                x, y, width, f'No players match "{query}".',
            )

    def _hide_suggestions(self) -> None:
        self.suggestions.hide()

    def _focus_first_suggestion(self, _event=None) -> str | None:
        if self.suggestions.is_visible() and self.suggestions.focus_first():
            return "break"
        return None

    def _open_suggestion(self, player: dict[str, Any]) -> None:
        self.search_var.set(player["fullName"])
        self._on_player_selected(player["id"])

    def _on_search_results(self, query: str, result: Any) -> None:
        self._clear_frame(self.players_frame)
        if isinstance(result, Exception):
            self._set_status(f"Search failed: {result}")
            ctk.CTkLabel(self.players_frame, text="Search failed.", text_color="tomato").pack(pady=20)
            return
        matches: list[dict[str, Any]] = result
        self.current_players = matches
        if not matches:
            ctk.CTkLabel(self.players_frame, text="No players matched.", text_color="gray70").pack(pady=20)
            self._set_status(f"No matches for '{query}'.")
            return
        for p in matches:
            team = p.get("teamName") or "—"
            label = f"{p['fullName']}  ({p['position']}, {team})"
            ctk.CTkButton(
                self.players_frame,
                text=label,
                anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray85", "gray25"),
                command=lambda pid=p["id"]: self._on_player_selected(pid),
            ).pack(fill="x", padx=4, pady=1)
        self._set_status(f"{len(matches)} player(s) matched '{query}'.")

    def _on_player_selected(self, player_id: int) -> None:
        self._current_game_pk = None
        self._cancel_detail_refresh()
        self._detail_mode = "player"
        self._clear_frame(self.detail_frame)
        ctk.CTkLabel(
            self.detail_frame, text="Loading player...", text_color="gray70",
            font=ctk.CTkFont(size=14),
        ).pack(expand=True, pady=60)
        self._set_status(f"Loading player {player_id}...")

        def fetch():
            bio = mlb_api.get_player(player_id)
            hit = mlb_api.get_player_stats(player_id, "hitting")
            pit = mlb_api.get_player_stats(player_id, "pitching")
            hit_recent = mlb_api.get_player_recent_stats(player_id, "hitting", 7) if hit else {}
            pit_recent = mlb_api.get_player_recent_stats(player_id, "pitching", 7) if pit else {}
            arsenal = mlb_api.get_pitch_arsenal(player_id) if pit else {"season": None, "pitches": []}
            img = mlb_api.get_headshot(player_id)
            return {
                "bio": bio, "hit": hit, "pit": pit,
                "hit_recent": hit_recent, "pit_recent": pit_recent,
                "arsenal": arsenal, "img": img,
            }

        run_in_thread(fetch, lambda r: self._render_player(player_id, r))

    def _render_player(self, player_id: int, result: Any) -> None:
        self._clear_frame(self.detail_frame)
        if isinstance(result, Exception):
            ctk.CTkLabel(self.detail_frame, text=f"Failed to load player: {result}", text_color="tomato").pack(pady=40)
            self._set_status("Player load failed.")
            return

        bio: dict[str, Any] = result["bio"]
        hit: dict[str, Any] = result["hit"]
        pit: dict[str, Any] = result["pit"]
        hit_recent: dict[str, Any] = result.get("hit_recent") or {}
        pit_recent: dict[str, Any] = result.get("pit_recent") or {}
        arsenal: dict[str, Any] = result.get("arsenal") or {"season": None, "pitches": []}
        img: Image.Image | None = result["img"]

        if not bio:
            ctk.CTkLabel(self.detail_frame, text="No player data.", text_color="tomato").pack(pady=40)
            return

        self._ai_context_text = self._build_player_context(bio, hit, pit)

        scroll = ctk.CTkScrollableFrame(self.detail_frame)
        scroll.pack(fill="both", expand=True, padx=8, pady=8)
        scroll.grid_columnconfigure(1, weight=1)

        if img is not None:
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(160, 240))
            ctk.CTkLabel(scroll, image=ctk_img, text="").grid(
                row=0, column=0, rowspan=2, padx=(12, 18), pady=12, sticky="n"
            )
        else:
            placeholder = ctk.CTkFrame(scroll, width=160, height=240, fg_color="gray25")
            placeholder.grid(row=0, column=0, rowspan=2, padx=(12, 18), pady=12, sticky="n")
            placeholder.grid_propagate(False)
            ctk.CTkLabel(placeholder, text="No photo", text_color="gray70").place(relx=0.5, rely=0.5, anchor="center")

        name_box = ctk.CTkFrame(scroll, fg_color="transparent")
        name_box.grid(row=0, column=1, sticky="new", pady=(12, 6))
        ctk.CTkLabel(
            name_box,
            text=bio.get("fullName", "Unknown"),
            font=ctk.CTkFont(size=24, weight="bold"),
            anchor="w",
        ).pack(anchor="w")

        team = (bio.get("currentTeam") or {}).get("name", "—")
        pos = (bio.get("primaryPosition") or {}).get("name", "—")
        num = bio.get("primaryNumber") or "—"
        bats = bio.get("batSide", {}).get("description", "—") if bio.get("batSide") else "—"
        throws = bio.get("pitchHand", {}).get("description", "—") if bio.get("pitchHand") else "—"
        height = bio.get("height", "—")
        weight = f"{bio.get('weight', '—')} lbs" if bio.get("weight") else "—"
        age = bio.get("currentAge", "—")
        birthplace_parts = [bio.get("birthCity"), bio.get("birthStateProvince"), bio.get("birthCountry")]
        birthplace = ", ".join([p for p in birthplace_parts if p]) or "—"
        birthdate = bio.get("birthDate", "—")
        debut = bio.get("mlbDebutDate", "—")

        ctk.CTkLabel(
            name_box,
            text=f"#{num}  •  {pos}  •  {team}",
            font=ctk.CTkFont(size=14),
            text_color="gray60",
            anchor="w",
        ).pack(anchor="w", pady=(0, 6))

        info_text = (
            f"Bats: {bats}    Throws: {throws}\n"
            f"Height: {height}    Weight: {weight}    Age: {age}\n"
            f"Born: {birthdate} — {birthplace}\n"
            f"MLB Debut: {debut}"
        )
        ctk.CTkLabel(
            scroll, text=info_text, justify="left", anchor="w", font=ctk.CTkFont(size=13),
        ).grid(row=1, column=1, sticky="nw", padx=(0, 12))

        season = mlb_api.current_season()

        next_row = 2
        if hit:
            self._render_stat_block(scroll, f"Hitting — {season} Season", hit, HITTING_FIELDS, row=next_row)
            next_row += 1
            self._render_pace_section(
                scroll, "Per-Game Pace — Hitting", hit, hit_recent, PACE_HITTING, row=next_row,
            )
            next_row += 1
        if pit:
            self._render_stat_block(scroll, f"Pitching — {season} Season", pit, PITCHING_FIELDS, row=next_row)
            next_row += 1
            self._render_pace_section(
                scroll, "Per-Game Pace — Pitching", pit, pit_recent, PACE_PITCHING, row=next_row,
            )
            next_row += 1
        if arsenal.get("pitches"):
            self._render_pitch_arsenal(scroll, arsenal, row=next_row)
            next_row += 1
        if not hit and not pit:
            ctk.CTkLabel(
                scroll,
                text=f"No {season} season stats available yet for this player.",
                text_color="gray70",
                font=ctk.CTkFont(size=13),
            ).grid(row=next_row, column=0, columnspan=2, padx=12, pady=20, sticky="w")

        self._set_status(f"Loaded {bio.get('fullName', '')}.")

    def _render_stat_block(
        self,
        parent: ctk.CTkBaseClass,
        title: str,
        stats: dict[str, Any],
        fields: list[tuple[str, str]],
        row: int,
    ) -> None:
        block = ctk.CTkFrame(parent)
        block.grid(row=row, column=0, columnspan=2, sticky="ew", padx=12, pady=(14, 6))

        ctk.CTkLabel(
            block, text=title, font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
        ).pack(anchor="w", padx=12, pady=(10, 4))

        grid = ctk.CTkFrame(block, fg_color="transparent")
        grid.pack(fill="x", padx=8, pady=(0, 10))

        cols = 4
        cell_height = 92
        for i, (key, label) in enumerate(fields):
            r, c = divmod(i, cols)
            value = stats.get(key, "—")
            if value is None or value == "":
                value = "—"
            cell = ctk.CTkFrame(
                grid, fg_color=("gray85", "gray22"), corner_radius=6,
                height=cell_height,
            )
            cell.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")
            cell.grid_propagate(False)
            cell.grid_columnconfigure(0, weight=1)
            cell.grid_rowconfigure(0, weight=1)
            cell.grid_rowconfigure(1, weight=0)
            grid.grid_columnconfigure(c, weight=1, uniform="stats")
            ctk.CTkLabel(
                cell, text=label,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="gray60",
                wraplength=140,
                justify="center",
            ).grid(row=0, column=0, padx=6, pady=(8, 2), sticky="sew")
            ctk.CTkLabel(
                cell, text=str(value),
                font=ctk.CTkFont(size=17, weight="bold"),
            ).grid(row=1, column=0, padx=6, pady=(0, 10), sticky="new")

    def _render_pitch_arsenal(
        self,
        parent: ctk.CTkBaseClass,
        arsenal: dict[str, Any],
        row: int,
    ) -> None:
        pitches: list[dict[str, Any]] = arsenal.get("pitches", [])
        season = arsenal.get("season")
        current = mlb_api.current_season()
        title = f"Pitch Arsenal — {season} Season"
        if season is not None and season != current:
            title += "  (no current-season data yet)"

        block = ctk.CTkFrame(parent)
        block.grid(row=row, column=0, columnspan=2, sticky="ew", padx=12, pady=(14, 6))

        ctk.CTkLabel(
            block, text=title, font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
        ).pack(anchor="w", padx=12, pady=(10, 4))

        total = pitches[0].get("totalPitches") if pitches else None
        if total:
            ctk.CTkLabel(
                block,
                text=f"{total:,} total pitches tracked  •  sorted by usage",
                font=ctk.CTkFont(size=11),
                text_color="gray60",
                anchor="w",
            ).pack(anchor="w", padx=12, pady=(0, 4))

        grid = ctk.CTkFrame(block, fg_color="transparent")
        grid.pack(fill="x", padx=8, pady=(0, 10))

        cols = 4
        cell_height = 118
        for i, p in enumerate(pitches):
            r, c = divmod(i, cols)
            name = p.get("description") or "—"
            speed = p.get("averageSpeed")
            speed_text = f"{speed:.1f} mph" if isinstance(speed, (int, float)) else "—"
            pct = p.get("percentage")
            pct_text = f"{pct * 100:.1f}%" if isinstance(pct, (int, float)) else "—"
            count = p.get("count") or 0

            cell = ctk.CTkFrame(
                grid, fg_color=("gray85", "gray22"), corner_radius=6,
                height=cell_height,
            )
            cell.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")
            cell.grid_propagate(False)
            cell.grid_columnconfigure(0, weight=1)
            grid.grid_columnconfigure(c, weight=1, uniform="pitches")

            ctk.CTkLabel(
                cell, text=name,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="gray60",
                wraplength=140,
                justify="center",
            ).grid(row=0, column=0, padx=6, pady=(10, 0), sticky="ew")
            ctk.CTkLabel(
                cell, text=speed_text,
                font=ctk.CTkFont(size=22, weight="bold"),
            ).grid(row=1, column=0, padx=6, pady=(2, 0), sticky="ew")
            ctk.CTkLabel(
                cell, text=f"{pct_text} usage  •  {count:,} thrown",
                font=ctk.CTkFont(size=10),
                text_color="gray60",
            ).grid(row=2, column=0, padx=6, pady=(0, 10), sticky="ew")

    def _render_pace_section(
        self,
        parent: ctk.CTkBaseClass,
        title: str,
        season_stats: dict[str, Any],
        recent_stats: dict[str, Any],
        fields: list[tuple[str, str]],
        row: int,
    ) -> None:
        block = ctk.CTkFrame(parent)
        block.grid(row=row, column=0, columnspan=2, sticky="ew", padx=12, pady=(14, 6))

        ctk.CTkLabel(
            block, text=title, font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
        ).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            block,
            text="Average production per game. A guide to what to expect — not a prediction.",
            font=ctk.CTkFont(size=11), text_color="gray60", anchor="w",
        ).pack(anchor="w", padx=12, pady=(0, 8))

        season = mlb_api.current_season()
        self._render_pace_row(block, f"{season} Season", season_stats, fields)
        self._render_pace_row(block, "Last 7 Days", recent_stats, fields)

    def _render_pace_row(
        self,
        block: ctk.CTkBaseClass,
        period_label: str,
        stats: dict[str, Any],
        fields: list[tuple[str, str]],
    ) -> None:
        games = stats.get("gamesPlayed") or 0

        header = ctk.CTkFrame(block, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(2, 2))
        ctk.CTkLabel(
            header, text=period_label,
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w",
        ).pack(side="left")
        games_text = "1 game played" if games == 1 else f"{games} games played"
        ctk.CTkLabel(
            header, text=games_text,
            font=ctk.CTkFont(size=11), text_color="gray60", anchor="w",
        ).pack(side="left", padx=(8, 0))

        if games == 0:
            ctk.CTkLabel(
                block, text="No games in this period.",
                font=ctk.CTkFont(size=11), text_color="gray60", anchor="w",
            ).pack(anchor="w", padx=18, pady=(0, 8))
            return

        grid = ctk.CTkFrame(block, fg_color="transparent")
        grid.pack(fill="x", padx=10, pady=(0, 10))

        for c, (key, lbl) in enumerate(fields):
            total = stats.get(key)
            if key == "inningsPitched":
                ip = mlb_api.ip_to_float(total)
                pace = ip / games if ip is not None else None
            else:
                try:
                    pace = float(total) / float(games) if total is not None else None
                except (TypeError, ValueError):
                    pace = None
            pace_text = f"{pace:.2f}" if pace is not None else "—"

            cell = ctk.CTkFrame(grid, fg_color=("gray85", "gray22"), corner_radius=6, height=72)
            cell.grid(row=0, column=c, padx=3, pady=2, sticky="nsew")
            cell.grid_propagate(False)
            cell.grid_columnconfigure(0, weight=1)
            grid.grid_columnconfigure(c, weight=1, uniform="pace")

            ctk.CTkLabel(
                cell, text=f"{lbl} / Game",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="gray60",
                wraplength=120,
                justify="center",
            ).grid(row=0, column=0, padx=4, pady=(8, 0), sticky="ew")
            ctk.CTkLabel(
                cell, text=pace_text,
                font=ctk.CTkFont(size=18, weight="bold"),
            ).grid(row=1, column=0, padx=4, pady=(0, 8), sticky="ew")


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
