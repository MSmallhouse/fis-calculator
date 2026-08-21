"""Tests for picking the right USSA points list.

These cover the parts that can be wrong *without* raising: a list that has been
uploaded but is not valid for competition yet, a year that fails to roll over in
January, or a csv whose first athlete gets eaten as a header row. None of those
show up as a failed lambda run, so the error alarm cannot catch them.

No network access - everything runs against fixtures.
"""

import io
import logging
import os
import zipfile
from datetime import date

import pytest

import ussa_points_download as ussa

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def listing():
    with open(f"{FIXTURES}/directory_index.html") as f:
        return f.read()


@pytest.fixture(scope="module")
def schedule():
    with open(f"{FIXTURES}/2026-27_AL_List_Schedule.pdf", "rb") as f:
        return ussa.parse_schedule(f.read(), 2026)


# --- reading the schedule pdf ------------------------------------------------

def test_schedule_has_every_list(schedule):
    assert len(schedule) == 45


@pytest.mark.parametrize("list_number,expected", [
    (1, date(2026, 7, 2)),
    (7, date(2026, 8, 13)),
    (8, date(2026, 8, 20)),
    (9, date(2026, 8, 27)),
])
def test_national_valid_dates(schedule, list_number, expected):
    assert schedule[list_number] == expected


def test_year_rolls_over_at_new_year(schedule):
    # the pdf prints "Dec. 31" and "Jan. 7" with no year on either
    assert schedule[27] == date(2026, 12, 31)
    assert schedule[28] == date(2027, 1, 7)
    assert schedule[45] == date(2027, 6, 1)


def test_dates_are_monotonic(schedule):
    dates = [schedule[n] for n in sorted(schedule)]
    assert dates == sorted(dates)


# --- reading the directory index ---------------------------------------------

def test_finds_the_published_lists(listing):
    assert ussa.find_available_lists(listing) == {27: {1, 2, 3, 4, 5, 6, 7, 8}}


def test_finds_the_schedule_pdf(listing):
    assert ussa.find_schedules(listing) == {2026: "2026-27_AL_List_Schedule.pdf"}


def test_ignores_the_fis_list_zips(listing):
    # flx*.zip sit in the same directory and must not be mistaken for nlx*.zip
    assert "flx0827.zip" in listing
    assert 8 in ussa.find_available_lists(listing)[27]


# --- choosing a list ---------------------------------------------------------

@pytest.fixture
def offline(monkeypatch, listing, schedule):
    monkeypatch.setattr(ussa, "fetch_directory_listing", lambda: listing)
    monkeypatch.setattr(ussa, "fetch_schedule", lambda *a, **k: schedule)


@pytest.mark.parametrize("today,expected", [
    (date(2026, 8, 12), "nlx0627.zip"),
    (date(2026, 8, 13), "nlx0727.zip"),   # list 7 becomes valid
    (date(2026, 8, 19), "nlx0727.zip"),   # list 8 is uploaded but not valid yet
    (date(2026, 8, 20), "nlx0827.zip"),   # list 8 becomes valid
    (date(2026, 8, 26), "nlx0827.zip"),
])
def test_picks_the_valid_list_not_the_newest(offline, today, expected):
    assert ussa.compose_download_url(logger, today=today).endswith(expected)


def test_holds_last_valid_list_when_next_is_unpublished(offline):
    # the schedule knows about list 28, but only 1-8 exist on the server
    assert ussa.compose_download_url(logger, today=date(2027, 1, 7)).endswith("nlx0827.zip")


def test_no_valid_list_yet_falls_back(offline):
    # before the season's first list takes effect there is nothing valid
    url = ussa.compose_download_url(logger, today=date(2026, 7, 1))
    assert url.endswith("nlx0827.zip")


# --- degrading when the server changes shape ---------------------------------

def test_probes_when_directory_index_is_gone(monkeypatch, schedule):
    def no_index():
        raise Exception("404")

    monkeypatch.setattr(ussa, "fetch_directory_listing", no_index)
    monkeypatch.setattr(ussa, "fetch_schedule", lambda *a, **k: schedule)
    monkeypatch.setattr(ussa, "list_exists", lambda n, season: season == 27 and n <= 8)

    # the valid date must still be respected, so list 7 rather than list 8
    assert ussa.compose_download_url(logger, today=date(2026, 8, 19)).endswith("nlx0727.zip")


def test_falls_back_to_newest_when_schedule_unreadable(monkeypatch, listing):
    def no_schedule(*a, **k):
        raise Exception("pdf is not a pdf")

    monkeypatch.setattr(ussa, "fetch_directory_listing", lambda: listing)
    monkeypatch.setattr(ussa, "fetch_schedule", no_schedule)

    # newest available, which may not be valid yet - deliberate, and logged
    assert ussa.compose_download_url(logger, today=date(2026, 8, 19)).endswith("nlx0827.zip")


def test_raises_when_there_are_no_lists_at_all(monkeypatch):
    monkeypatch.setattr(ussa, "fetch_directory_listing", lambda: "<html></html>")
    monkeypatch.setattr(ussa, "fetch_schedule", lambda *a, **k: {})

    with pytest.raises(Exception, match="no USSA points lists"):
        ussa.compose_download_url(logger, today=date(2026, 8, 19))


# --- reading the csvs --------------------------------------------------------

def build_zip(rows):
    """A stand-in for the real download: headerless csvs, same column layout."""
    csv = "\n".join(",".join(str(field) for field in row) for row in rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for prefix in ("NLM", "NLW", "NLO"):
            z.writestr(f"{prefix}0827.csv", csv)
    buffer.seek(0)
    return buffer


ATHLETE = ["C", "Abbott", "Reagan", "I", 6868612, "M", 2012,
           999.99, 216.13, 235.93, 452.41, 999.99, "Park City", "PCSS"]
OTHER = ["C", "Abelon", "Benji", "E", 7283463, "M", 2015,
         999.99, 999.99, 999.99, 999.99, 999.99, "Ski Butternut", "SB"]


def test_first_athlete_is_not_eaten_as_a_header(monkeypatch):
    # the csvs have no header row - a plain read_csv silently drops one athlete
    # per file, always the alphabetically first one
    zipped = build_zip([ATHLETE, OTHER])
    monkeypatch.setattr(ussa, "requests", _FakeRequests(zipped.getvalue()))

    df = ussa.get_points_df(logger, "http://example.test/nlx0827.zip")

    assert len(df) == 4  # 2 athletes x (mens + womens); NLO is ignored
    assert 6868612 in set(df["Fiscode"])


def test_rejects_an_html_error_page(monkeypatch):
    # a missing list is served as 200 + html, not a 404
    monkeypatch.setattr(ussa, "requests", _FakeRequests(b"<!DOCTYPE html><html>nope"))

    with pytest.raises(Exception, match="expected a zip"):
        ussa.get_points_df(logger, "http://example.test/nlx9927.zip")


class _FakeRequests:
    """Minimal stand-in for the requests module."""

    def __init__(self, content):
        self._content = content

    def get(self, url, **kwargs):
        return _FakeResponse(self._content)


class _FakeResponse:
    def __init__(self, content):
        self.content = content
        self.headers = {"content-type": "application/octet-stream"}

    def raise_for_status(self):
        return None
