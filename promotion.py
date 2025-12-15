"""
promotion.py (LIGHT VERSION)

Contains only the promotion decision + DB updates for the "Rank Mod Light" runner.

Exports:
- set_promotion_config(cfg)
- try_promote(conn, pid, rank, pcp, sorties, good, thresholds, current_date_str, is_player=True)

Assumptions:
- The caller (rank_promotion_checker_light.py) ensures the table promotion_attempts exists.
- Dates are normalized via helpers.normalize_mission_date() to 'YYYY.MM.DD'.
"""

from __future__ import annotations

import sqlite3
import random
from datetime import datetime
from typing import Sequence

from logger import log
from helpers import normalize_mission_date

# Defaults (overridden at runtime by set_promotion_config(cfg))
PROMOTION_COOLDOWN_DAYS = 2
PROMOTION_FAIL_THRESHOLD = 3


def set_promotion_config(cfg: dict) -> None:
    """
    Inject runtime configuration (cooldown/fail thresholds) from the light runner.
    Safe to call multiple times.
    """
    global PROMOTION_COOLDOWN_DAYS, PROMOTION_FAIL_THRESHOLD

    try:
        PROMOTION_COOLDOWN_DAYS = int(cfg.get("PROMOTION_COOLDOWN_DAYS", PROMOTION_COOLDOWN_DAYS))
    except Exception:
        pass

    try:
        PROMOTION_FAIL_THRESHOLD = int(cfg.get("PROMOTION_FAIL_THRESHOLD", PROMOTION_FAIL_THRESHOLD))
    except Exception:
        pass


def _parse_day(date_str: str) -> datetime:
    """
    Parse a mission day string into a datetime (midnight), after normalizing to 'YYYY.MM.DD'.
    """
    canonical = normalize_mission_date(str(date_str))
    return datetime.strptime(canonical, "%Y.%m.%d")


def try_promote(
    conn: sqlite3.Connection,
    pid: int,
    rank: int,
    pcp: float,
    sorties: int,
    good: int,
    thresholds: Sequence[Sequence[float]],
    current_date_str: str,
    is_player: bool = True,
) -> int:
    """
    Returns the (possibly updated) rankId for this pilot.

    Promotion rule per rank step:
      idx = rank - 4
      thresholds[idx] = [pcp_required, sorties_required, failure_rate_max]
      eligible if pcp >= pcp_required OR (sorties >= sorties_required AND failure_rate <= failure_rate_max)

    AI:
      - If eligible => promote immediately.

    Player:
      - Uses promotion_attempts to enforce cooldown after failed attempts
      - Chance-based promotion (decreases with rank), forced after PROMOTION_FAIL_THRESHOLD fails
    """

    # Coerce numeric inputs safely
    try:
        p = float(pcp)
    except Exception:
        p = 0.0
    try:
        s = int(sorties)
    except Exception:
        s = 0
    try:
        g = int(good)
    except Exception:
        g = 0

    failure = (s - g) / s if s > 0 else 1.0
    idx = int(rank) - 4

    # Only ranks >=4 are managed; thresholds index must exist
    if idx < 0 or idx >= len(thresholds):
        return rank

    pr, sr, fr = thresholds[idx]
    current_day = _parse_day(current_date_str)
    canonical_day_str = normalize_mission_date(current_date_str)  # store canonical in DB

    # Eligibility check
    if not (p >= pr or (s >= sr and failure <= fr)):
        log(f"Pilot {pid} does not meet threshold for rank {rank + 1}")
        return rank

    # --- AI logic: always promote if eligible ---
    if not is_player:
        promote_to = rank + 1
        conn.execute("UPDATE pilot SET rankId=? WHERE id=?", (promote_to, pid))
        conn.commit()
        log(f"[AI] Pilot {pid} promoted to rank {promote_to} (auto)")
        return promote_to

    # --- Player logic: cooldown + chance + attempts tracking ---
    cur = conn.cursor()
    cur.execute(
        """
        SELECT last_attempt, last_success, fail_count
        FROM promotion_attempts
        WHERE pilotId = ?
        """,
        (pid,),
    )
    row = cur.fetchone()

    last_attempt_day = None
    last_success = None
    fail_count = 0

    if row:
        try:
            # last_attempt may already be canonical; normalize anyway for safety
            last_attempt_day = _parse_day(row[0])
        except Exception:
            last_attempt_day = None

        last_success = row[1]
        fail_count = int(row[2] or 0)

        log(
            f"[DEBUG] Pilot {pid} promotion state — last_success={last_success}, "
            f"fail_count={fail_count}, last_attempt={last_attempt_day}, current_day={current_day}"
        )

        # Cooldown only after FAILED attempt (last_success == 0)
        if last_success == 0 and last_attempt_day is not None:
            days_since = (current_day - last_attempt_day).days
            log(
                f"[DEBUG] Cooldown comparison for pilot {pid}: days_since={days_since}, "
                f"required_cooldown={PROMOTION_COOLDOWN_DAYS}"
            )
            if days_since < PROMOTION_COOLDOWN_DAYS:
                log(f"Pilot {pid} in cooldown period ({days_since} days since last failed attempt).")
                return rank

    # Chance decreases with rank step; floor at 0.25
    base_chance = 0.9 - (0.05 * idx)
    chance = max(base_chance, 0.25)

    # Forced promotion after too many failures
    if fail_count >= PROMOTION_FAIL_THRESHOLD:
        promote_to = rank + 1
        conn.execute("UPDATE pilot SET rankId=? WHERE id=?", (promote_to, pid))
        cur.execute(
            """
            INSERT INTO promotion_attempts (pilotId, last_attempt, last_success, fail_count)
            VALUES (?, ?, 1, 0)
            ON CONFLICT(pilotId) DO UPDATE SET
                last_attempt=excluded.last_attempt,
                last_success=1,
                fail_count=0
            """,
            (pid, canonical_day_str),
        )
        conn.commit()
        log(f"[PLAYER] Pilot {pid} forced promotion to {promote_to} after {fail_count} failures.")
        return promote_to

    # Roll for promotion
    roll = random.random()
    log(f"[PLAYER] Pilot {pid}: roll={roll:.3f}, chance={chance:.3f} for rank {rank + 1}")

    if roll <= chance:
        promote_to = rank + 1
        conn.execute("UPDATE pilot SET rankId=? WHERE id=?", (promote_to, pid))
        cur.execute(
            """
            INSERT INTO promotion_attempts (pilotId, last_attempt, last_success, fail_count)
            VALUES (?, ?, 1, 0)
            ON CONFLICT(pilotId) DO UPDATE SET
                last_attempt=excluded.last_attempt,
                last_success=1,
                fail_count=0
            """,
            (pid, canonical_day_str),
        )
        conn.commit()
        log(f"[PLAYER] Pilot {pid} promoted to rank {promote_to}")
        return promote_to

    # Failed attempt: increment fail_count and record
    fail_count += 1
    cur.execute(
        """
        INSERT INTO promotion_attempts (pilotId, last_attempt, last_success, fail_count)
        VALUES (?, ?, 0, ?)
        ON CONFLICT(pilotId) DO UPDATE SET
            last_attempt=excluded.last_attempt,
            last_success=0,
            fail_count=excluded.fail_count
        """,
        (pid, canonical_day_str, fail_count),
    )
    conn.commit()
    log(f"[PLAYER] Pilot {pid} failed promotion. Fail count now {fail_count}")
    return rank
