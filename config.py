# config.py
import os
import sys
import json

# Resource path logic for PyInstaller bundles or script run
if getattr(sys, "frozen", False):
    RESOURCE_PATH = sys._MEIPASS
else:
    RESOURCE_PATH = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE       = "promotion_config.json"
POLL_INTERVAL     = 5  # seconds
LOG_FILE          = "promotion_debug.log"
LOCALE_MAP = {
    "RU": "rus", "CHS": "chs", "ENG": "eng", "DEU": "ger",
    "ESP": "spa", "POL": "pol", "FRA": "fra"
}
CEREMONY_MAP = {
    101: "Ceremony_RU.png",
    102: "Ceremony_GB.png",
    103: "Ceremony_US.png",
    201: "Ceremony_DE.png",
}

# --- Config ---
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try: 
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # ensure defaults for each country
            defaults = {'101':5,'102':5,'103':5,'201':5}
            cfg['max_ranks'] = {**defaults, **cfg.get('max_ranks', {})}
            # fallback values
            cfg['PROMOTION_COOLDOWN_DAYS'] = int(cfg.get('PROMOTION_COOLDOWN_DAYS', 2))
            cfg['PROMOTION_FAIL_THRESHOLD'] = int(cfg.get('PROMOTION_FAIL_THRESHOLD', 3))
            return cfg
        except Exception as e:
            print(f"Failed to load config: {e}")
    return {"max_ranks": {'101':5, '102':5, '103':5, '201':5},
        "PROMOTION_COOLDOWN_DAYS": 2,
        "PROMOTION_FAIL_THRESHOLD": 3
    }
