"""
rank_promotion_checker_light.py
Lightweight "rank mod" runner:
- No UI, no certificates, no popups
- Watches IL-2 Career DB and applies existing promotion logic (once per in-game day)
- Inserts a type=6 promotion event per your specified schema
- Generates promotion_config.json on first run (asks for game_path and language only)
Build with PyInstaller (spec):  pyinstaller rank_promotion_checker_light.spec
"""

import os
import sys
import json
import time
import sqlite3
import tempfile
import atexit
import signal
import string
import argparse
from datetime import datetime
from typing import Dict, Any
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import psutil
from logger import log

# Optional deps (safe if missing at runtime)
try:
    import winreg
except Exception:
    winreg = None
   
   

import config
from config import POLL_INTERVAL, LOCALE_MAP
from helpers import is_il2_running, normalize_mission_date
from logger import log
from promotion import try_promote, set_promotion_config  # thresholds injected at runtime

DEFAULT_THRESHOLDS = [
    [210, 80,  0.10],
    [260, 100, 0.10],
    [310, 130, 0.10],
    [370, 160, 0.075],
    [430, 200, 0.075],
    [500, 250, 0.075],
    [580, 350, 0.07],
    [680, 450, 0.06],
    [800, 600, 0.05],
]

DEFAULT_MAX_RANKS = {'101': 13, '102': 13, '103': 13, '201': 13}

# --- Verbose flag & helper ---
VERBOSE = False
def vprint(*args, **kwargs):
    if VERBOSE:
        try:
            print(*args, **kwargs)
        except Exception:
            pass

# --- Single-instance locking ---
_GLOBAL_LOCK_PATH = None

def _has_stdin() -> bool:
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except Exception:
        return False


def _cleanup_lock(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
        
def _cfg_path_for(gp: str) -> str:
    return os.path.join(gp, "data", "Career", "promotion_config.json")

def _load_cfg_if_valid(cfg_path: str):
    try:
        if not os.path.isfile(cfg_path):
            return None
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        gp = cfg.get("game_path") or ""
        if not gp:
            return None
        # validate cp.db still exists under this game
        if not os.path.isfile(os.path.join(gp, "data", "Career", "cp.db")):
            return None
        # normalize
        if 'thresholds' not in cfg or not isinstance(cfg['thresholds'], list):
            cfg['thresholds'] = DEFAULT_THRESHOLDS
        mr = cfg.get('max_ranks') or {}
        cfg['max_ranks'] = {**DEFAULT_MAX_RANKS, **{str(k): int(v) for k, v in mr.items()}}
        cfg['PROMOTION_COOLDOWN_DAYS'] = int(cfg.get('PROMOTION_COOLDOWN_DAYS', 2))
        cfg['PROMOTION_FAIL_THRESHOLD'] = int(cfg.get('PROMOTION_FAIL_THRESHOLD', 3))
        return cfg
    except Exception:
        return None

def _locate_existing_config():
    # 1) If user previously chose a path, we’ll find the config next to cp.db
    #    by scanning the same candidate roots we use elsewhere.
    try:
        for gp in find_game_path_candidates():
            cfg_path = _cfg_path_for(gp)
            cfg = _load_cfg_if_valid(cfg_path)
            if cfg:
                # point logger to the correct Career log
                career_dir = os.path.join(gp, "data", "Career")
                config.CONFIG_FILE = cfg_path
                config.LOG_FILE = os.path.join(career_dir, "promotion_debug.log")
                return cfg
    except Exception:
        pass
    return None

        
def tk_first_run_wizard(locale_map) -> tuple[str | None, str | None]:
    """
    One top-level for language + game path.
    Validates that <path>/data/Career/cp.db exists and that we can write to <path>/data/Career.
    Writes promotion_config.json immediately on OK.
    Returns (language, game_path) or (None, None) if cancelled.
    """
    if not tk:
        return None, None

    def _validate_path(p: str) -> bool:
        if not p:
            return False
        cp = os.path.join(p, "data", "Career", "cp.db")
        return os.path.isdir(p) and os.path.isfile(cp)

    # Root + top
    root = tk.Tk()
    root.withdraw()
    top = tk.Toplevel(root)
    top.title("Rank Mod Light - First-time Setup")
    top.resizable(False, False)
    try:
        top.attributes("-topmost", True)
    except Exception:
        pass

    frm = ttk.Frame(top, padding=12)
    frm.grid(row=0, column=0, sticky="nsew")

    ttk.Label(frm, text="Language:").grid(row=0, column=0, padx=(0,8), pady=(0,8), sticky="w")
    codes = sorted(locale_map.keys())
    lang_var = tk.StringVar(value="ENG" if "ENG" in codes else (codes[0] if codes else "ENG"))
    lang_cb = ttk.Combobox(frm, textvariable=lang_var, values=codes, state="readonly", width=10)
    lang_cb.grid(row=0, column=1, padx=(0,0), pady=(0,8), sticky="w")
    lang_cb.focus_set()

    ttk.Label(frm, text="IL-2 Game Folder:").grid(row=1, column=0, padx=(0,8), pady=(0,8), sticky="w")
    path_var = tk.StringVar(value="")
    path_entry = ttk.Entry(frm, textvariable=path_var, width=54)
    path_entry.grid(row=1, column=1, padx=(0,0), pady=(0,8), sticky="w")

    def browse():
        p = filedialog.askdirectory(parent=top, title="Select IL-2 game folder")
        if p:
            path_var.set(p)

    ttk.Button(frm, text="Browse…", command=browse).grid(row=1, column=2, padx=(8,0), pady=(0,8), sticky="w")

    status_var = tk.StringVar(value="")
    ttk.Label(frm, textvariable=status_var, foreground="#b00").grid(row=2, column=0, columnspan=3, sticky="w")

    btns = ttk.Frame(frm); btns.grid(row=3, column=0, columnspan=3, pady=(12,0), sticky="e")
    result = {"lang": None, "path": None}

    def on_ok():
        lang = lang_var.get().strip().upper()
        gp = path_var.get().strip().strip('" ')
        if lang not in locale_map:
            status_var.set("Please choose a valid language.")
            return

        cpdb = os.path.join(gp, "data", "Career", "cp.db")
        if not (os.path.isdir(gp) and os.path.isfile(cpdb)):
            status_var.set(f"Invalid folder: cp.db not found at:\n{cpdb}")
            return

        career_dir = os.path.join(gp, "data", "Career")
        cfg_path  = os.path.join(career_dir, "promotion_config.json")
        log_path  = os.path.join(career_dir, "promotion_debug.log")

        cfg_obj = {
            "game_path": os.path.normpath(gp),
            "language": lang,
            "max_ranks": dict(DEFAULT_MAX_RANKS),
            "thresholds": DEFAULT_THRESHOLDS,
            "PROMOTION_COOLDOWN_DAYS": 2,
            "PROMOTION_FAIL_THRESHOLD": 3,
        }

        # Try write now; if permission denied, offer elevation here
        try:
            os.makedirs(career_dir, exist_ok=True)
            probe = os.path.join(career_dir, "_perm_test.tmp")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            try: os.remove(probe)
            except Exception: pass

            # point logger to Career before writing
            config.CONFIG_FILE = cfg_path
            config.LOG_FILE = log_path

            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg_obj, f, indent=2)

            try:
                log(f"[SETUP] Wrote promotion_config.json to: {cfg_path}")
            except Exception:
                pass

        except PermissionError:
            try:
                if messagebox.askyesno(
                    "Administrator required",
                    "Windows prevents writing to this folder.\nRestart with Administrator privileges now?",
                    parent=top
                ):
                    top.destroy(); root.destroy()
                    relaunch_as_admin()
                    return
                else:
                    status_var.set("Cannot write to this folder. Run as Administrator or choose a different install path.")
                    return
            except Exception:
                top.destroy(); root.destroy()
                relaunch_as_admin()
                return
        except Exception as e:
            status_var.set(f"Save failed: {e}")
            return

        # Success
        print(f"[SETUP] Selected language={lang}, game_path={gp}")  # dev visibility
        result["lang"] = lang
        result["path"] = gp
        top.destroy()
        root.quit()
        
    def on_cancel():
        result["lang"] = None
        result["path"] = None
        top.destroy()
        root.quit()
        
    ttk.Button(btns, text="Cancel", command=on_cancel).pack(side="right", padx=(8,0))
    ttk.Button(btns, text="OK", command=on_ok).pack(side="right")

    top.protocol("WM_DELETE_WINDOW", on_cancel)

    # Ignore Ctrl+C while wizard is up (prevents KeyboardInterrupt from killing mainloop)
    old_sigint = None
    try:
        import signal as _sig
        old_sigint = _sig.getsignal(_sig.SIGINT)
        _sig.signal(_sig.SIGINT, _sig.SIG_IGN)
    except Exception:
        old_sigint = None

    try:
        top.grab_set()
        top.lift(); top.focus_force()
        root.mainloop()  # drive the hidden root; OK/Cancel destroys top
    finally:
        try:
            if old_sigint is not None:
                import signal as _sig
                _sig.signal(_sig.SIGINT, old_sigint)
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    return result["lang"], result["path"]


def acquire_global_lock(app_name: str = "rank_promotion_checker_light"):
    """Acquire single-instance lock using a temp-file with PID inside, with logging."""
    global _GLOBAL_LOCK_PATH
    lock_dir = tempfile.gettempdir()
    lock_path = os.path.join(lock_dir, f"{app_name}.lock")
    _GLOBAL_LOCK_PATH = lock_path

    try:
        if os.path.exists(lock_path):
            try:
                with open(lock_path, "r", encoding="utf-8") as f:
                    pid_str = f.read().strip()
                other_pid = int(pid_str) if pid_str.isdigit() else None
            except Exception:
                other_pid = None

            # If another live process owns the lock → log and exit
            if other_pid and psutil and psutil.pid_exists(other_pid):
                try:
                    log(f"[LOCK] Another instance is running (pid={other_pid}). Exiting.")
                finally:
                    pass
                sys.exit(0)

            # Stale lock → remove
            try:
                os.remove(lock_path)
                log(f"[LOCK] Removed stale lock: {lock_path}")
            except Exception as e:
                log(f"[LOCK] Could not remove stale lock ({lock_path}): {e}")

        # Create/own the lock
        with open(lock_path, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        log(f"[LOCK] Acquired: {lock_path} (pid={os.getpid()})")

    except Exception as e:
        log(f"[LOCK] Unexpected error acquiring lock: {e}")

    atexit.register(lambda: _cleanup_lock(_GLOBAL_LOCK_PATH))
    try:
        signal.signal(signal.SIGINT,  lambda *_: (_cleanup_lock(_GLOBAL_LOCK_PATH), sys.exit(0)))
        signal.signal(signal.SIGTERM, lambda *_: (_cleanup_lock(_GLOBAL_LOCK_PATH), sys.exit(0)))
    except Exception:
        pass


def acquire_installation_lock(career_dir: str):
    """Per-installation lock placed in the Career directory."""
    if not career_dir:
        return
    path = os.path.join(career_dir, "rank_mod_light.lock")
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                pid_str = f.read().strip()
            other_pid = int(pid_str) if pid_str.isdigit() else None
            if other_pid and psutil and psutil.pid_exists(other_pid):
                # This installation already managed
                sys.exit(0)
    except Exception:
        pass
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        return
    atexit.register(lambda: _cleanup_lock(path))

# --- Windows elevation helpers ---
def is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def relaunch_as_admin():
    """
    Relaunch the current program with admin rights.
    - Works for both PyInstaller EXE (sys.frozen) and plain Python scripts.
    """
    try:
        import ctypes, os
        if getattr(sys, 'frozen', False):
            # PyInstaller EXE → relaunch the EXE itself
            exe = sys.executable
            params = " ".join([f'"{a}"' for a in sys.argv[1:]])
        else:
            # Running as a .py → relaunch python.exe with the script path
            exe = sys.executable
            script = os.path.abspath(sys.argv[0])
            params = " ".join([f'"{script}"'] + [f'"{a}"' for a in sys.argv[1:]])

        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        if int(rc) <= 32:
            raise OSError(f"ShellExecuteW failed: rc={rc}")
    except Exception as e:
        try:
            log(f"[PERM] Elevation failed: {e}")
        except Exception:
            pass
    finally:
        # Always exit current process; elevated child (if any) will continue.
        sys.exit(0)


def ensure_write_access_or_elevate(dir_path: str):
    """Try to write to dir; if PermissionError and non-admin, relaunch elevated."""
    try:
        os.makedirs(dir_path, exist_ok=True)
        tmp = os.path.join(dir_path, "_perm_test.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("ok")
        try:
            os.remove(tmp)
        except Exception:
            pass
        return True
    except PermissionError:
        if os.name == "nt" and not is_admin():
            relaunch_as_admin()
        raise

# --- Auto-detection of IL-2 game path ---
def _steam_common_dirs_from_registry():
    candidates = []
    if not winreg:
        return candidates
    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
    ]
    for hive, key, value in reg_paths:
        try:
            with winreg.OpenKey(hive, key) as rk:
                path, _ = winreg.QueryValueEx(rk, value)
                if path and os.path.isdir(path):
                    candidates.append(os.path.join(path, "steamapps", "common"))
        except Exception:
            pass
    return candidates

def _candidate_game_dirs():
    vprint("[AUTO] Building candidate search list across Steam and drives A..Z")
    names = [
        "IL-2 Sturmovik Battle of Stalingrad",
        "IL-2 Sturmovik Great Battles",
    ]
    defaults = [
        os.path.join(r"C:\Program Files (x86)\Steam", "steamapps", "common"),
        os.path.join(r"C:\Program Files\Steam", "steamapps", "common"),
    ]
    steam_common_dirs = set(defaults + _steam_common_dirs_from_registry())

    candidates = []
    for common in steam_common_dirs:
        for name in names:
            gp = os.path.join(common, name)
            candidates.append(gp)

    for drive in string.ascii_uppercase:
        root = f"{drive}:\\"
        p1 = os.path.join(root, "Games", "IL-2 Sturmovik Great Battles")
        p2 = os.path.join(root, "Program Files (x86)", "1C Game Studios", "IL-2 Sturmovik Great Battles")
        candidates.extend([p1, p2])

    # De-duplicate while preserving order
    seen = set()
    out = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out

def _cpdb_exists(path):
    return os.path.isfile(os.path.join(path, "data", "Career", "cp.db"))

def find_game_path_candidates():
    candidates_all = _candidate_game_dirs()
    vprint("[AUTO] Candidate game dirs (constructed):")
    for c in candidates_all:
        vprint("   ", c)
    filtered = [p for p in candidates_all if os.path.isdir(p)]
    vprint("[AUTO] Existing directories:")
    for c in filtered:
        vprint("   ", c)
    with_cpdb = [p for p in filtered if _cpdb_exists(p)]
    vprint("[AUTO] With cp.db present:")
    for c in with_cpdb:
        vprint("   ", c)
    return with_cpdb

def autodetect_game_path():
    vprint("[AUTO] Attempting auto-detect of IL-2 installation...")
    cands = find_game_path_candidates()
    if cands:
        vprint("[AUTO] Selected installation:", cands[0])
        return cands[0]
    vprint("[AUTO] No installation found via auto-detect.")
    return None

# --- Option A: hide console after initial setup (if config exists and not verbose) ---
def hide_console_if_configured(cfg_exists: bool, verbose: bool):
    """Hide the console window if a valid config already exists and verbose mode is off."""
    if verbose or not cfg_exists:
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
            ctypes.windll.kernel32.FreeConsole()
            sys.stdout = open(os.devnull, 'w')
            sys.stderr = open(os.devnull, 'w')
    except Exception:
        pass

def ensure_config_interactive() -> Dict[str, Any]:
    """
    First tries to load an existing promotion_config.json (so the wizard is not shown again).
    If none found, runs the Tk wizard which writes the file immediately.
    """
    # Try existing config first
    cfg = _locate_existing_config()
    if cfg:
        log(f"[SETUP] Loaded existing config from {config.CONFIG_FILE}")
        return cfg

    # No config on disk → run the wizard (this writes promotion_config.json)
    if not tk:
        log("[ERROR] Tk not available; cannot prompt for first-time setup.")
        return {"game_path": "", "language": "ENG",
                "thresholds": DEFAULT_THRESHOLDS, "max_ranks": dict(DEFAULT_MAX_RANKS),
                "PROMOTION_COOLDOWN_DAYS": 2, "PROMOTION_FAIL_THRESHOLD": 3}

    lang, gp = tk_first_run_wizard(LOCALE_MAP)
    if not lang or not gp:
        log("[ABORT] Setup cancelled; exiting.")
        return {"game_path": "", "language": "ENG",
                "thresholds": DEFAULT_THRESHOLDS, "max_ranks": dict(DEFAULT_MAX_RANKS),
                "PROMOTION_COOLDOWN_DAYS": 2, "PROMOTION_FAIL_THRESHOLD": 3}

    # Wizard already validated and wrote the config. Point globals and load it.
    career_dir = os.path.join(gp, "data", "Career")
    config.CONFIG_FILE = os.path.join(career_dir, "promotion_config.json")
    config.LOG_FILE    = os.path.join(career_dir, "promotion_debug.log")

    cfg = _load_cfg_if_valid(config.CONFIG_FILE)
    if not cfg:
        # ultra-safe fallback: compose and write once
        cfg = {
            "game_path": gp, "language": lang,
            "max_ranks": dict(DEFAULT_MAX_RANKS),
            "thresholds": DEFAULT_THRESHOLDS,
            "PROMOTION_COOLDOWN_DAYS": 2,
            "PROMOTION_FAIL_THRESHOLD": 3,
        }
        with open(config.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        log(f"[SETUP] Wrote promotion_config.json to: {config.CONFIG_FILE}")

    return cfg

def db_path_from_config(cfg: Dict[str, Any]) -> str:
    return os.path.join(cfg['game_path'], "data", "Career", "cp.db")


def to_midnight(date_str: str) -> str:
    d = normalize_mission_date(str(date_str))
    return f"{d} 00:00:00"


def resolve_squadron_config_id(cur: sqlite3.Cursor, pilot_squadron_row_id: int) -> int:
    row = cur.execute("SELECT configID FROM squadron WHERE id = ?", (pilot_squadron_row_id,)).fetchone()
    return int(row[0]) if row and row[0] is not None else -1


def resolve_event_career_id(cur: sqlite3.Cursor, pilot_squadron_row_id: int) -> int:
    """Return the squadron.careerId for the pilot's squadron row id."""
    row = cur.execute(
        "SELECT careerId FROM squadron WHERE id = ?",
        (pilot_squadron_row_id,)
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else -1


def insert_promotion_event(conn: sqlite3.Connection, pilot_id: int, new_rank: int, mission_date: str) -> bool:
    """
    Insert a type=6 promotion event per Alex's specification.
    Returns True if inserted, False if a duplicate already existed.
    """
    cur = conn.cursor()

    # Pilot info
    prow = cur.execute("""
        SELECT name, lastName, squadronId, personageId
        FROM pilot WHERE id = ?
    """, (pilot_id,)).fetchone()
    if not prow:
        log(f"[WARN] Pilot {pilot_id} not found for event insert")
        return False
    name, last_name, pilot_squadron_row_id, personage_id = prow
    full_name = f"{name} {last_name}".strip()

    # Map to event.squadronId = squadron.configId
    event_squadron_id = resolve_squadron_config_id(cur, pilot_squadron_row_id)

    # Resolve event.careerId via squadron.careerId (pilot's squadron row)
    career_id = resolve_event_career_id(cur, pilot_squadron_row_id)
    if career_id < 0:
        log(f"[WARN] No careerId on squadron id {pilot_squadron_row_id}; writing -1 for event.careerId")

    promo_date = to_midnight(mission_date)
       
    # Atomic insert with de-dup guard
    cur.execute("""
        INSERT INTO event(
            date, type, pilotId, rankId, missionId,
            squadronId, careerId,
            ipar1, ipar2, ipar3, ipar4,
            tpar1, tpar2, tpar3, tpar4,
            isDeleted
        )
        SELECT
            ?, 6, ?, ?, -1,
            ?, ?,
            ?, -1, -1, -1,
            ?, '', '', '',
            0
        WHERE NOT EXISTS (
            SELECT 1 FROM event
            WHERE type=6 AND pilotId=? AND rankId=? AND date=? AND missionId=-1
        )
    """, (
        promo_date,
        pilot_id, new_rank,
        event_squadron_id, career_id,
        new_rank,
        full_name,
        pilot_id, new_rank, promo_date
    ))

    if cur.rowcount == 0:
        log(f"[SKIP] Duplicate promotion event for pilot {pilot_id} rank {new_rank} date {promo_date}")
        return False

    conn.commit()
    log(f"[EVENT] Inserted type=6 for pilot {pilot_id} → rank {new_rank} on {promo_date}")
    return True


def build_squadron_country_map(cur: sqlite3.Cursor) -> Dict[int, int]:
    # squadron.configId // 1000 yields the country code
    cur.execute("SELECT id, configID FROM squadron")
    return {row[0]: (row[1] // 1000) for row in cur.fetchall()}

def get_active_player_id_light(conn: sqlite3.Connection, mission_squadron: int):
    """
    Returns the id of the real player pilot in the current mission's squadron,
    preferring the one with most recent mission activity, mirroring the original logic.
    """
    cur = conn.cursor()
    # Candidates: pilots with a non-empty personageId in this squadron
    cur.execute("""
        SELECT id FROM pilot
        WHERE personageId <> '' AND squadronId = ?
    """, (mission_squadron,))
    candidates = [row[0] for row in cur.fetchall()]
    log(f"Possible player candidates in squadron {mission_squadron}: {candidates}")

    if not candidates:
        log("No active player found for this squadron.")
        return None

    # Latest mission for this squadron
    cur.execute("""
        SELECT id FROM mission
        WHERE squadronId = ?
        ORDER BY id DESC
        LIMIT 1
    """, (mission_squadron,))
    mission_row = cur.fetchone()
    latest_mission_id = mission_row[0] if mission_row else None

    # Prefer the candidate who has an event in the latest mission
    if latest_mission_id:
        for pid in sorted(candidates, reverse=True):  # Prefer higher id if multiple
            cur.execute("""
                SELECT 1 FROM event WHERE pilotId = ? AND missionId = ? LIMIT 1
            """, (pid, latest_mission_id))
            if cur.fetchone():
                log(f"Selected active player id: {pid} (has event in latest mission {latest_mission_id})")
                return pid

    # Fallback: highest id
    selected_pid = max(candidates)
    log(f"Selected active player id: {selected_pid} (fallback to highest id)")
    return selected_pid


def check_all_pilots_light(conn: sqlite3.Connection,
                           thresholds,
                           max_ranks: Dict[str, int],
                           language: str,
                           mission_squadron: int,
                           squadron_country_map: Dict[int, int],
                           mission_date: str) -> None:
    """
    Light version: applies promotion logic and writes type=6 events.
    No UI (only at initial setup), no popups.
    Promotions obey country ceilings from max_ranks.
    """
    cur = conn.cursor()

    # Ensure promotion_attempts table exists (for player promotion tracking)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS promotion_attempts (
            pilotId INTEGER PRIMARY KEY,
            last_attempt TEXT,
            last_success INTEGER,
            fail_count INTEGER DEFAULT 0
        )
    """)

    active_player_id = get_active_player_id_light(conn, mission_squadron)
    if active_player_id:
        migrate_player_stats_by_description_if_needed(conn, active_player_id)
    cur.execute("""
        SELECT id, rankId, pcp, sorties, goodSorties, squadronId, personageId, name, lastName
        FROM pilot
        WHERE isDeleted = 0
    """)

    for (pid, rank, pcp, sorties, good, pilot_sq, personage_id, first, last) in cur.fetchall():
        # Determine pilot country from squadron map (default to 201 if missing)
        pilot_country = squadron_country_map.get(pilot_sq, 201)
        max_rank_allowed = int(max_ranks.get(str(pilot_country), 13))

        # Only ranks >=4 are managed by mod; respect ceiling
        if rank < 4 or rank >= max_rank_allowed:
            continue

        is_player = (pid == active_player_id)
        new_rank = try_promote(conn, pid, rank, pcp, sorties, good, thresholds, mission_date, is_player=is_player)

        if new_rank != rank:
            # Write a type=6 event
            insert_promotion_event(conn, pid, new_rank, mission_date)


def monitor_db_light(db_path: str, thresholds, max_ranks: Dict[str, int], language: str) -> None:
    """
    Monitor Career DB and trigger promotion checks once per in-game day.
    """
    last_mid = -1
    last_date = None
    log(f"Opening DB: {db_path}")
    while is_il2_running():
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()

            # Build squadron→country map up front (cheap)
            squadron_country = build_squadron_country_map(cur)

            # Prime last mission/date on first loop
            if last_mid == -1:
                cur.execute("SELECT id, date FROM mission ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                if row:
                    last_mid = int(row[0])
                    last_date = normalize_mission_date(str(row[1])) if row[1] else None
                    log(f"Primed from latest mission: id={last_mid}, date={last_date}")
                else:
                    last_mid, last_date = -1, None
                    log("No missions found yet. Waiting...")

            # Check for new missions
            cur.execute("SELECT id, date, squadronId FROM mission WHERE id > ? ORDER BY id ASC", (last_mid,))
            for mid, date_str, squadron_id in cur.fetchall():
                log(f"=== Mission Start: {mid} ({date_str}) ===")
                last_mid = int(mid)
                if date_str is None:
                    continue

                current_date = normalize_mission_date(str(date_str))

                if current_date != last_date:
                    last_date = current_date
                    # Note: campaign_country not needed for light flow
                    # Run the promotion pass once per new in-game day
                    check_all_pilots_light(conn, thresholds, max_ranks, language,
                                           mission_squadron=squadron_id,
                                           squadron_country_map=squadron_country,
                                           mission_date=last_date)

        except Exception as e:
            log(f"[ERROR] monitor_db_light: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

        time.sleep(POLL_INTERVAL)


EXCLUDE_PILOT_COLS = {
    "id",
    "squadronId",
    "name",
    "lastName",
    "birthDay",
    "description",
    "commonStat",
    "personageId",
    "avatarPath",
    "AILevel",
    "insDate",
    "isDeleted",
}

def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rankmod_player_migrations (
            oldPilotId INTEGER,
            newPilotId INTEGER PRIMARY KEY,
            migratedOn TEXT
        )
    """)

def _pilot_columns(conn: sqlite3.Connection) -> list[str]:
    cur = conn.cursor()
    return [row[1] for row in cur.execute("PRAGMA table_info(pilot)") if row and row[1]]

def _row_as_dict(cur: sqlite3.Cursor, sql: str, params: tuple) -> dict | None:
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        return None
    return {d[0]: row[i] for i, d in enumerate(cur.description)}

def _find_previous_player_by_description(conn: sqlite3.Connection, new_pid: int) -> int | None:
    """
    Find the previous player pilot row as:
      - same pilot.description as new_pid
      - id < new_pid
      - closest lower id (ORDER BY id DESC LIMIT 1)
    """
    cur = conn.cursor()

    new_meta = cur.execute("""
        SELECT description, name, lastName
        FROM pilot
        WHERE id=? AND isDeleted=0
    """, (new_pid,)).fetchone()
    if not new_meta:
        return None

    new_desc, new_name, new_last = new_meta
    if not new_desc:
        return None

    row = cur.execute("""
        SELECT id
        FROM pilot
        WHERE isDeleted=0
          AND description = ?
          AND name = ?
          AND lastName = ?
          AND id < ?
        ORDER BY id DESC
        LIMIT 1
    """, (new_desc, new_name, new_last, new_pid)).fetchone()

    return int(row[0]) if row else None

def migrate_player_stats_by_description_if_needed(conn: sqlite3.Connection, new_pid: int) -> bool:
    """
    Overwrite ALL pilot columns from the previous player row into the new player row,
    except the explicit excluded identity/campaign columns in EXCLUDE_PILOT_COLS.

    Uses player.description (exact match) and "closest lower id" to identify old player.
    Runs only once per new_pid (marker table rankmod_player_migrations).
    """
    _ensure_migration_table(conn)

    # idempotency: do not migrate twice into the same new player id
    if conn.execute(
        "SELECT 1 FROM rankmod_player_migrations WHERE newPilotId=? LIMIT 1",
        (new_pid,)
    ).fetchone():
        return False

    old_pid = _find_previous_player_by_description(conn, new_pid)
    if not old_pid:
        return False

    cur = conn.cursor()
    new_row = _row_as_dict(cur, "SELECT * FROM pilot WHERE id=? AND isDeleted=0", (new_pid,))
    old_row = _row_as_dict(cur, "SELECT * FROM pilot WHERE id=? AND isDeleted=0", (old_pid,))
    if not new_row or not old_row:
        return False

    cols = _pilot_columns(conn)
    copy_cols = [c for c in cols if c not in EXCLUDE_PILOT_COLS]
    if not copy_cols:
        return False

    # Only migrate if anything differs (per your requirement)
    if not any(old_row.get(c) != new_row.get(c) for c in copy_cols):
        return False

    set_clause = ", ".join([f"{c}=?" for c in copy_cols])
    values = [old_row.get(c) for c in copy_cols] + [new_pid]

    try:
        conn.execute("BEGIN")

        # Overwrite all carry-over stats
        cur.execute(f"UPDATE pilot SET {set_clause} WHERE id=?", tuple(values))

        # Optional but recommended: carry over mod tracking state
        cur.execute("""
            INSERT INTO promotion_attempts (pilotId, last_attempt, last_success, fail_count)
            SELECT ?, last_attempt, last_success, fail_count
            FROM promotion_attempts
            WHERE pilotId=?
            ON CONFLICT(pilotId) DO UPDATE SET
                last_attempt=excluded.last_attempt,
                last_success=excluded.last_success,
                fail_count=excluded.fail_count
        """, (new_pid, old_pid))

        # Mark as done
        cur.execute("""
            INSERT INTO rankmod_player_migrations (oldPilotId, newPilotId, migratedOn)
            VALUES (?, ?, datetime('now'))
        """, (old_pid, new_pid))

        conn.commit()
        log(f"[MIGRATE] Player carry-over: copied stats oldPid={old_pid} → newPid={new_pid} "
            f"(excluded={sorted(EXCLUDE_PILOT_COLS)})")
        return True

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        log(f"[MIGRATE][ERROR] Failed carry-over oldPid={old_pid} → newPid={new_pid}: {e}")
        return False

def update_personage_max_rank(db_path: str):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("UPDATE personage SET maxRank=13")
        conn.commit()
        log("[INIT] Set personage.maxRank=13 for all rows")
    except Exception as e:
        log(f"[WARN] Could not update personage.maxRank: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

def main():
    # CLI args
    parser = argparse.ArgumentParser(prog='rank_promotion_checker_light', description='IL-2 Rank Mod Light')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose diagnostics for path detection and flow')
    args = parser.parse_args()
    global VERBOSE
    VERBOSE = bool(args.verbose)
    if VERBOSE:
        print('[INFO] Verbose mode enabled')

    # If config already exists, we can safely hide the console (unless verbose)
    gp_probe = autodetect_game_path()
    cfg_exists = False
    if gp_probe:
        career_probe = os.path.join(gp_probe, 'data', 'Career')
        cfg_exists = os.path.isfile(os.path.join(career_probe, 'promotion_config.json'))
    hide_console_if_configured(cfg_exists, VERBOSE)

    # 1) Ensure config exists and is complete (may trigger elevation)
    cfg = ensure_config_interactive()
    if not cfg.get("game_path"):
        log("[ABORT] First-time setup incomplete; exiting.")
        return

    # point the logger explicitly (just in case)
    config.LOG_FILE = os.path.join(cfg['game_path'], 'data', 'Career', 'promotion_debug.log')

    log(f"[START] Rank Mod Light starting with game_path={cfg['game_path']}")


    thresholds = cfg['thresholds']
    max_ranks = cfg['max_ranks']
    language = cfg['language']

    # 2) Compute db path
    db_path = db_path_from_config(cfg)

    # now take the lock (this will log if it exits)
    acquire_global_lock()
    acquire_installation_lock(os.path.join(cfg['game_path'], 'data', 'Career'))
    set_promotion_config(cfg)
    update_personage_max_rank(db_path_from_config(cfg))

    log("Waiting for IL-2 to start…")

    while True:
        while not is_il2_running():
            time.sleep(POLL_INTERVAL)
        log("IL-2 detected. Starting monitor…")
        monitor_db_light(db_path, thresholds, max_ranks, language)
        log("IL-2 closed. Monitoring will restart on next launch.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # make sure it goes to the Career log
        try:
            log(f"[FATAL] {e}")
        except Exception:
            pass
        # silent exit (no popups)
        sys.exit(1)
