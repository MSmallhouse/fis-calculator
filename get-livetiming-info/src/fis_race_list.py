"""The list of races FIS is currently showing on its live page.

The site used to fetch https://www.fis-ski.com/DB/alpine-skiing/live.html
straight from the browser. FIS's new backend now answers every request with
`access-control-allow-origin: https://www.fis-ski.com` regardless of who asked,
so the browser fetches the bytes and then refuses to hand them to the page - a
200 that reads as a failure. Nothing client-side can get around that, hence
fetching here instead: CORS is a browser rule, not a server one.

Parsing lives here too, and deliberately does NOT use column positions. FIS has
reordered those columns at least twice (the event and category cells are
currently swapped relative to what the old frontend expected), so each cell is
identified by matching its text against the values we already know.
"""

import re

import requests
from bs4 import BeautifulSoup

# The sector filter is explicit rather than relying on the /DB/alpine-skiing/
# path prefix. Both return the same rows today, but this is the endpoint FIS's
# own UI drives, and an explicit filter survives the per-sector paths going away.
# Without any filter this page also lists ski jumping and nordic combined.
LIVE_PAGE_URL = (
    "https://www.fis-ski.com/DB/general/live.html"
    "?sectorcode=AL&categorycode=&gendercode=&disciplinecode=&nationcode="
)
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
}

# FIS race category -> the "min_penalty,adder" pair the calculator expects.
# Kept here rather than in the frontend so there is one source of truth: the
# parser needs these codes to recognise the category cell, and the caller needs
# the penalty. Update alongside the manual-entry dropdown in index.html.
CATEGORY_PENALTIES = {
    "OWG": "0,0", "WC": "0,0", "WSC": "0,0", "COM": "0,0", "WQUA": "0,0",
    "TRA": "0,0",
    "ANC": "15,0", "EC": "15,0", "ECOM": "15,0", "FEC": "15,0", "NAC": "15,0",
    "SAC": "15,0", "UVS": "15,0", "WJC": "15,0",
    "NC": "20,8",
    "EQUA": "23,0",
    "AWG": "23,8", "CISM": "23,8", "CORP": "23,8", "EYOF": "23,8", "FIS": "23,8",
    "FQUA": "23,8", "JUN": "23,8", "NJC": "23,8", "NJR": "23,8", "UNI": "23,8",
    "YOG": "23,8",
    "CIT": "40,8", "CITWC": "40,8",
    "ENL": "60,8",
}

EVENT_CODES = {
    "Slalom": "SLpoints",
    "Giant Slalom": "GSpoints",
    "Super G": "SGpoints",
    "Downhill": "DHpoints",
    "Downhill Training": "DHpoints",
}

CODEX_PATTERN = re.compile(r"^\d{3,5}$")

ALPINE_SECTOR_CODE = "AL"
# Other FIS sectors. Grass skiing (GS) is the dangerous one: it runs Slalom,
# Giant Slalom and Super G under the same names and the same FIS category codes
# as alpine, so neither the event name nor the category can tell them apart -
# only the sector can. None of these collide with a value in CATEGORY_PENALTIES.
OTHER_SECTOR_CODES = {"CC", "JP", "NK", "FS", "SB", "GS", "TM", "MA", "PA", "PC"}


def is_alpine_row(cells):
    """The sector column only appears when the page is NOT already filtered by
    sector, so absence of any sector code means the URL filter did the work.
    If a sector code is present, it has to be the alpine one."""
    sectors = [c for c in cells if c == ALPINE_SECTOR_CODE or c in OTHER_SECTOR_CODES]
    if not sectors:
        return True
    return ALPINE_SECTOR_CODE in sectors


def fetch_live_page():
    response = requests.get(LIVE_PAGE_URL, headers=REQUEST_HEADERS, timeout=20)
    response.raise_for_status()
    return response.text


def text_of(element):
    return element.get_text(strip=True) if element else ""


def parse_race_row(row):
    cells = [c.get_text(strip=True) for c in row.select(".split-row__item")]
    is_alpine = is_alpine_row(cells)

    # match on values we already know rather than on position - the columns move
    event = next((c for c in cells if c in EVENT_CODES), None)
    category = next((c for c in cells if c in CATEGORY_PENALTIES), None)
    codex = next((c for c in cells if CODEX_PATTERN.match(c)), None)

    date_element = row.select_one(".timezone-date")
    live_element = row.select_one(".live__content")

    return {
        "isAlpine": is_alpine,
        "codex": codex,
        "date": date_element.get("data-date") if date_element else None,
        "displayDate": text_of(date_element),
        "location": text_of(row.select_one(".split-row__item.bold")),
        "country": text_of(row.select_one(".country__name-short")),
        "gender": text_of(row.select_one(".gender__item")),
        "event": event,
        "eventCode": EVENT_CODES.get(event),
        "category": category,
        "minPenalty": CATEGORY_PENALTIES.get(category),
        "isLive": text_of(live_element).lower() == "live" if live_element else False,
    }


def get_race_list(logger):
    soup = BeautifulSoup(fetch_live_page(), "html.parser")
    rows = soup.select(".g-row")

    races, other_sector, unreadable = [], [], []
    for row in rows:
        race = parse_race_row(row)
        if not race["isAlpine"]:
            other_sector.append(race)
        elif race["codex"] and race["eventCode"] and race["minPenalty"] and race["date"]:
            races.append(race)
        else:
            # alpine, but something we could not read - the first sign FIS
            # changed the page again
            unreadable.append(race)

    if other_sector:
        # expected only if the sectorcode filter stops being honoured
        logger.info(f"FIS race list: skipped {len(other_sector)} non-alpine row(s)")
    if unreadable:
        logger.error(
            f"ERROR: FIS_RACE_LIST_UNPARSED {len(unreadable)} alpine row(s) "
            f"could not be read: {unreadable[:5]}"
        )
    logger.info(f"FIS race list: {len(races)} race(s) parsed from {len(rows)} row(s)")

    for race in races:
        race.pop("isAlpine", None)

    return {"races": races}
