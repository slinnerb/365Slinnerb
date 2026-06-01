# Releasing & Auto-Updates

This app can auto-update itself when you publish a new version to GitHub
Releases. Your friend (or anyone with the .exe) gets a "Check for Updates"
button — when you publish a new release, they click it, see the new version
+ release notes, click "Download & Install", and the app swaps itself out
and relaunches.

---

## One-time setup

1. **Create a free GitHub account** at <https://github.com/signup> if you
   don't have one. Note your username (e.g., `slinnerb`).

2. **Create a public repo** for the app:
   - Go to <https://github.com/new>
   - Repository name: `mlb-stats-viewer` (any name works — remember it)
   - Public (required so the auto-updater can fetch without auth)
   - Click **Create repository**

3. **Configure the updater** — open `updater.py` and edit the top:
   ```python
   GITHUB_OWNER = "your-github-username"   # <-- your username
   GITHUB_REPO  = "mlb-stats-viewer"       # <-- the repo name
   VERSION = "1.0.0"                       # current shipping version
   ```

4. **(Optional) Install the GitHub CLI** at <https://cli.github.com/> if
   you want the one-command release script. Then run `gh auth login`
   once and pick GitHub.com → HTTPS → login with browser.

5. **Push your code to the repo** (so people can see source — optional
   but standard). From this folder in a terminal:
   ```cmd
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/your-username/mlb-stats-viewer.git
   git push -u origin main
   ```

---

## Shipping a new version

Every time you want to push an update to your friend:

1. **Bump the version** in `updater.py`:
   ```python
   VERSION = "1.0.1"     # was "1.0.0"
   ```

2. **Build the portable .exe**:
   ```cmd
   build_portable.bat
   ```
   This produces `dist\MLB-Stats-Viewer.exe`.

3. **Publish the release** — two options:

   **Option A — one command** (requires `gh` CLI):
   ```cmd
   release.bat
   ```
   It reads the version from `updater.py`, tags `v1.0.1`, uploads the
   .exe, and prompts you for release notes.

   **Option B — manual via the web UI**:
   - Go to `https://github.com/your-username/mlb-stats-viewer/releases/new`
   - Tag: `v1.0.1` (must match VERSION, with a leading `v`)
   - Title: `v1.0.1` or anything descriptive
   - Description: what changed (this becomes the release notes in the app)
   - Drag `dist\MLB-Stats-Viewer.exe` into the assets box
   - Click **Publish release**

4. **That's it.** Your friend clicks "Check for Updates" in the app, sees
   "Update available: v1.0.1", and installs it. No actions needed on
   their machine other than clicking the button.

---

## How version comparison works

Tags are parsed as `vMAJOR.MINOR.PATCH` (e.g., `v1.0.1`). The app
compares the latest GitHub tag against `VERSION` in `updater.py`. If the
tag is higher (numerically), an update is offered. Suffixes like
`-beta` are ignored.

So the version sequence might be: `1.0.0 → 1.0.1 → 1.0.2 → 1.1.0 → 2.0.0`.

---

## What the install does (mechanically)

1. App downloads `MLB-Stats-Viewer.exe` to `%TEMP%`.
2. App writes a tiny `_update.bat` next to itself and launches it
   detached.
3. App exits.
4. `_update.bat` waits a second, deletes the old .exe, moves the new
   one into place, launches it, then deletes itself.

Total downtime is about 2 seconds.

---

## Sending the first build to your friend

1. Build with `build_portable.bat`.
2. Send them `dist\MLB-Stats-Viewer.exe` (USB, OneDrive link, email,
   whatever).
3. They double-click it. Windows SmartScreen may show a warning on
   first launch (unsigned .exe) — click "More info" → "Run anyway".
   Subsequent runs and updates won't show it.

From then on, they only need to click "Check for Updates" inside the
app — no more file transfers.
