# Daily Gacha Tracker (Windows)

A local Windows desktop app that tracks whether configured game processes have been detected during the current local calendar day.

## Scope

- Tracks launches for Genshin Impact, Honkai: Star Rail, Zenless Zone Zero, Wuthering Waves, and NIKKE.
- Sends one Windows notification at a configured time if enabled games have not been detected that day.
- Stores daily state and settings locally under `%APPDATA%\DailyGachaTracker`.
- Does **not** log into game accounts, inspect game memory, read game files, or check daily-task completion.
- Does not send activity data to a server.

## Install

1. Install Python 3.11+ from https://www.python.org/downloads/windows/ if it is not already installed. Enable **Add Python to PATH**.
2. Extract this folder.
3. Double-click `install.bat`.
4. Double-click `run.bat`.

## First run: verify process names

Game executable names can change and some Unreal Engine games may use generic executable names. Open **Settings** in the app and verify each game's process name:

1. Launch a game.
2. Open Windows Task Manager (`Ctrl+Shift+Esc`) and select **Details**.
3. Find the game's actual executable name.
4. Enter that exact name in the matching row in Daily Gacha Tracker's Settings. Wuthering Waves is configured to detect `Client-Win64-Shipping.exe`, as shown in your ActivityWatch screenshot.

Names are case-insensitive. Multiple aliases can be separated by commas. If two games use the same generic process name, the tracker cannot distinguish them from process names alone. In that case, disable that alias and we can add a more specific detection method.

## Reminders

The default reminder time is 21:00 local time. Change it in Settings. The app sends at most one reminder per local calendar day. If no games are missing, it does not send a notification.

The tracker continues running after you close its window; closing hides it to the system tray. Right-click the tray icon to open the dashboard, check now, or exit. In Settings, enable **Start with Windows** to launch it automatically when you sign in. This creates a per-user Startup-folder entry and does not require administrator rights.

## Data

- `config.json`: reminder settings and process names
- `state.json`: today's detected games and first detection time

Both are stored in `%APPDATA%\DailyGachaTracker`. Use **Open data folder** in the app to open the directory.

## Known limitations

- “Opened today” means the process name was detected. It does not prove you played for a meaningful duration.
- The day rolls over at local midnight, not each game's server reset time.
- The app must be running while you play to detect the launch. If a game is still running when the tracker starts, it should detect it on the next check. Historical ActivityWatch totals alone cannot be imported as proof that a game was launched today.
- `Client-Win64-Shipping.exe` is a generic Unreal Engine executable name. If another game with the same executable name is running at the same time, process-name-only detection cannot tell them apart.
- Notifications depend on Windows notification settings.
- Process aliases need to be verified on your installation.
