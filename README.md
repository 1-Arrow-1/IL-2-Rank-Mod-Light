# IL-2 Extended Rank Promotion Mod — Light Version (Source Release)

## Overview

The Extended Rank Promotion Mod (Light Version) extends the IL-2 Sturmovik: Great Battles career promotion system beyond the stock limit of rank 4, allowing promotions up to rank 13 for all supported countries.

This repository provides source code only.
Users must build the executable themselves.

The Light Version is intentionally minimal and headless:

- ❌ No UI
- ❌ No popups
- ❌ No certificates
- ❌ No modification of core game files

It relies exclusively on IL-2’s internal career promotion mechanism by inserting standard promotion events (event type = 6) into the career database.

## Key Features

- ✅ Extends promotions from rank 4 → rank 13
- ✅ Uses native IL-2 promotion logic
- ✅ Works for player and AI pilots
- ✅ Per-rank configurable promotion thresholds
- ✅ Country-specific rank ceilings
- ✅ JSGME compatible
- ✅ Source-only release (transparent & auditable)
- ✅ No UI, no graphics, no popups

## How It Works (Technical Summary)

IL-2 internally triggers promotions via career events of type 6.
By inserting these events into the career database (cp.db), the game itself handles:

- promotion messages
- career log entries
- rank assignment

This mod:

- monitors the career database while IL-2 is running
- evaluates promotion eligibility once per in-game day
- applies promotions using IL-2’s own event system

No UI injection, no memory hooks, no binary patching.

## Requirements

- IL-2 Sturmovik: Great Battles
- Windows
- Python 3.10+

### Required Python packages

```
psutil
pyinstaller
```

## Installation (Source Version)

### 1️⃣ Get the source code

Clone the repository or download it as a ZIP and extract it.

```
git clone https://github.com/
<your-repo>/il2-rank-mod-light.git
```

### 2️⃣ Install Python dependency

```
pip install psutil
pip install pyinstaller
```

### 3️⃣ Build the executable

A PyInstaller spec file is provided.

```
pyinstaller rank_promotion_checker_light.spec
```

After a successful build, the executable will be located in:

```
dist
```

### 4️⃣ Install via JSGME

- Unzip IL2 Rank mod light
- Copy the unzipped folder into your IL-2 MODS directory
- Copy rank_promotion_checker_light.exe into:

```
<IL-2 Game Directory>\MODS\IL-2 Rank mod light\data\Career
```

- Enable the mod using JGSME

### 5️⃣ Run the executable

Executable location:

```
\data\Career\rank_promotion_checker_light.exe
```

You can either:

- run rank_promotion_checker_light.exe manually before starting IL-2
- or copy it into your Windows Autostart folder (recommended):

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
```

Placing the EXE in Autostart ensures the mod always runs automatically when Windows starts.

## Configuration

All configuration is stored in:

```
\data\Career\promotion_config.json
```

## Promotion Thresholds

Each promotion step (rank 5 → rank 13) uses one threshold entry:

```
[ required_PCP, required_successful_sorties, max_failure_rate ]
```

Default thresholds:

```
"thresholds": [
[210, 80, 0.10],
[270, 100, 0.10],
[340, 130, 0.10],
[420, 160, 0.075],
[510, 200, 0.075],
[600, 250, 0.075],
[700, 350, 0.07],
[810, 450, 0.06],
[950, 600, 0.05]
]
```

## Limiting Maximum Rank

To stop promotions beyond a certain rank, set unreachable values for higher ranks:

```
[10000, 10000, 0.05]
```

You will never reach these values.

## Country-Specific Rank Caps

Maximum rank per country:

```
"max_ranks": {
"101": 13,
"102": 13,
"103": 13,
"201": 13
}
```

Country codes:

- 101 — USSR
- 102 — Great Britain
- 103 — USA
- 201 — Germany

## Logging

Logs are written to:

```
\data\Career\promotion_debug.log
```

## Notes

- Runs externally
- Does not modify core game files
- No multiplayer impact
- Fully reversible

For visual presentation, certificates, and UI popups, use the Full Version instead.

## Feedback

Feedback, bug reports, and testing results are very welcome.

Happy flying! ✈️
