MLB Stats Viewer
================

A portable Windows app for browsing MLB teams, players, current-season stats,
today's schedule, per-game pace, and pitch arsenals.
Data: free public MLB Stats API (statsapi.mlb.com). No API key needed.
An active internet connection is required.

How to run (development)
------------------------
Double-click run.bat
  - Edit the path to python.exe at the top of run.bat if your install is elsewhere.

How to build a portable .exe
----------------------------
Double-click build_portable.bat
  - Produces  dist\MLB-Stats-Viewer.exe  (single file, ~40-60 MB).
  - Copy that .exe anywhere (USB stick, OneDrive, another PC) and double-click.
  - First launch takes ~5 seconds while the bundled runtime unpacks.

How to use
----------
- Left column:        30 MLB teams.   Click one to load its active roster.
- Middle column:      Players.        Click a player to open their page.
- Search bar:         Live suggestions as you type; press Enter to open the
                      top match. Press Esc to dismiss the dropdown.
- Today's Games:      Header button. Shows today's MLB schedule with statuses,
                      scores, venues, and probable pitchers (clickable).
                      Use the date arrows to view other days.
- Check for Updates:  Header button. Pings GitHub Releases for a new build.
                      See RELEASING.md to set up the GitHub side once.
- Right pane:         Player page — headshot, full bio, current-season stats
                      (hitting and/or pitching with full stat names), per-game
                      pace + last-7-days form, and pitch arsenal with average
                      velocity for pitchers.

Auto-update / sharing
---------------------
- To send the app to a friend: build with build_portable.bat and give them
  dist\MLB-Stats-Viewer.exe.
- For them to receive updates: see RELEASING.md (free GitHub setup, one-time).
- After setup, every release is one command: release.bat (uses gh CLI).

Files
-----
main.py                Application + GUI
mlb_api.py             MLB Stats API wrapper (cached)
updater.py             Auto-update via GitHub Releases (configure repo here)
run.bat                Run from source
build_portable.bat     Build the single-file .exe
release.bat            Build + publish a new GitHub release in one go
requirements.txt       Python dependencies
RELEASING.md           Step-by-step GitHub setup + release workflow
