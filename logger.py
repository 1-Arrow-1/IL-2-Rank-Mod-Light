#import os
import time
import config

# --- Logging ---
def trim_log_to_last_n_missions(path, n):
    """
    Keep only the last n missions in the log file at 'path'.
    Silently ignores any errors.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Find all mission-start markers
        mission_idxs = [i for i, line in enumerate(lines) if "=== Mission Start:" in line]
        if len(mission_idxs) > n:
            # Trim to last n missions
            trim_start = mission_idxs[-n]
            lines = lines[trim_start:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines)
    except Exception:
        pass


def log(msg: str):
    with open(config.LOG_FILE, "a", encoding="utf-8") as f:
        f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg + "\n")
    trim_log_to_last_n_missions(config.LOG_FILE, 10)