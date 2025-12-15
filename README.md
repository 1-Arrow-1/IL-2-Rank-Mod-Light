IL-2 Extended Rank Promotion Mod — Light Version (Source Release)
Overview

The Extended Rank Promotion Mod (Light Version) extends the IL-2 Sturmovik Great Battles career promotion system beyond the stock limit of rank 4, allowing promotions up to rank 13 for all supported countries.

This repository provides the source code only.
Users must build the executable themselves.

The Light Version is intentionally minimal and headless:

no UI

no popups

no certificates

no modification of core game files

It relies exclusively on IL-2’s internal career promotion mechanism by inserting standard promotion events (event type = 6) into the career database.

Key Features

✅ Extends promotions from rank 4 → rank 13

✅ Uses native IL-2 promotion logic

✅ Works for player and AI pilots

✅ Per-rank configurable promotion thresholds

✅ Country-specific rank ceilings

✅ JSGME compatible

✅ Source-only release (transparent & auditable)

✅ No UI, no graphics, no popups

How It Works (Technical Summary)

IL-2 internally triggers promotions via career events of type 6.
By inserting these events into the career database (cp.db), the game itself handles:

promotion messages

career log entries

rank assignment

This mod:

Monitors the career database while IL-2 is running

Evaluates promotion eligibility once per in-game day

Applies promotions using IL-2’s own event system

No UI injection, no memory hooks, no binary patching.

Requirements

IL-2 Sturmovik: Great Battles

Windows

Python 3.10+

Required Python packages:

psutil

Optional (for building):

pyinstaller

Installation (Source Version)

1️⃣ Clone or download the repository
git clone https://github.com/<your-repo>/il2-rank-mod-light.git


or download as ZIP and extract.

2️⃣ Install Python dependencies
pip install psutil

3️⃣ Build the executable

A PyInstaller spec file is provided.

pyinstaller rank_promotion_checker_light.spec


After a successful build, the executable will be located in:

dist/

4️⃣ Install via JSGME / OvGME

Copy the mod folder into your IL-2 MODS directory

Enable it using JGSME

5️⃣ Run the executable
<IL-2 Game Directory>\data\Career\rank_promotion_checker_light.exe

You can either:

Run rank_promotion_checker_light.exe manually before starting IL-2, or

Copy it into your Windows Autostart folder (recommended)

Placing the EXE in Autostart ensures the mod always runs automatically when Windows starts.

Configuration

All configuration is stored in:

<IL-2 Game Directory>\data\Career\promotion_config.json

Promotion Thresholds

Each promotion step (rank 5 → 13) uses one threshold entry:

"thresholds": [
  [210, 80,  0.10],
  [270, 100, 0.10],
  [340, 130, 0.10],
  [420, 160, 0.075],
  [510, 200, 0.075],
  [600, 250, 0.075],
  [700, 350, 0.07],
  [810, 450, 0.06],
  [950, 600, 0.05]
]


A promotion attempt is triggered if either:

PCP ≥ required PCP
OR

successful sorties ≥ required sorties AND

failure rate ≤ threshold

Limiting Maximum Rank

To stop promotions beyond a certain rank, set unreachable values:

[10000, 10000, 0.05]

Country-Specific Rank Caps
"max_ranks": {
  "101": 13,
  "102": 10,
  "103": 13,
  "201": 13
}


Country codes:

101 — USSR

102 — Great Britain

103 — USA

201 — Germany

Logging

Logs are written to:

<IL-2 Game Directory>\data\Career\promotion_debug.log


If you want visual presentation, certificates, and UI popups, use the Full Version instead.


Runs externally

Does not modify core game files

No multiplayer impact

Fully reversible

Feedback

Feedback, bug reports, and testing results are very welcome.
