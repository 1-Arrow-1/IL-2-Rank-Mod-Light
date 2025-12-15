import os
from config import *

def get_rank_name(country, rank, year, base_path, locale):
    """
    Fetch rank name from the correct info.locale=XXX.txt file.
    Falls back to English if locale is missing.
    """
    # For Soviet ranks (country 101), always use the Russian locale
    lookup_locale = 'rus' if country == 101 else locale
    folder = os.path.join(base_path, f"{country*1000+rank}")
    info_file = os.path.join(folder, f"info.locale={lookup_locale}.txt")
    if not os.path.exists(info_file):
        info_file = os.path.join(folder, f"info.locale=eng.txt")
    if not os.path.exists(info_file):
        return ""
    with open(info_file, "r", encoding="utf-8") as f:
        for line in f:
            if "&name=" in line:
                return line.split('"')[1]
    return ""
    
def get_rank_title_path(country, rank, year, base, loc):
    folder = os.path.join(base, f"{country*1000+rank}")
    png    = "big.1943.png" if (country == 101 and year >= 1943) else "big.png"
    titlef = os.path.join(folder, f"info.locale={loc}.txt")
    imgf   = os.path.join(folder, png)
    title  = ""
    if os.path.exists(titlef):
        with open(titlef, "r", encoding="utf-8") as f:
            for line in f:
                if "&name=" in line:
                    title = line.split('"')[1]
                    break
    return imgf, title

def get_small_insignia_path(country, rank, year, base):
    folder = os.path.join(base, f"{country*1000+rank}")
    png    = "inline.1943.png" if (country == 101 and year >= 1943) else "inline.png"
    return os.path.join(folder, png)