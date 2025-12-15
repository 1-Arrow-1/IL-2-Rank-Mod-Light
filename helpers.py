import psutil
from datetime import datetime
from logger import log

# --- Helpers ---
def is_il2_running() -> bool:
    for p in psutil.process_iter(("name",)):
        try:
            if p.info["name"] and p.info["name"].lower() == "il-2.exe":
                return True
        except Exception:
            pass
    return False
        
def normalize_mission_date(date_str: str) -> str:
    """
    Normalize any mission date to canonical 'YYYY.MM.DD'.

    Accepts:
    - YYYY.MM.DD
    - YYYY-MM-DD
    - YYYY.MM.DD HH:MM:SS
    - YYYY-MM-DD HH:MM:SS
    """
    if not date_str:
        raise ValueError("Empty date string")

    base = date_str.strip()[:10]
    base = base.replace("-", ".")

    try:
        datetime.strptime(base, "%Y.%m.%d")
    except ValueError:
        raise ValueError(f"Unsupported mission date format: {date_str}")

    return base

def cleanup_orphaned_promotion_attempts(conn):
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM promotion_attempts
        WHERE pilotId NOT IN (SELECT id FROM pilot)
    """)
    conn.commit()
    log("[CLEANUP] Removed orphaned entries from promotion_attempts")