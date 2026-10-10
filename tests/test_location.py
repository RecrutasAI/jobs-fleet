"""Every case here is a real location string from the dataset (2026-10-10)."""
import pytest

from fleet.location import parse

CASES = [
    # text, (country_iso, us_state, city, is_remote, is_us)
    ("Houston, TX, United States", ("US", "TX", "Houston", False, True)),
    ("South San Francisco, California, USA", ("US", "CA", "South San Francisco", False, True)),
    ("Chicago, IL, us", ("US", "IL", "Chicago", False, True)),
    ("Montréal, QC, ca", ("CA", None, "Montréal", False, False)),
    ("Montreal, Quebec, CA, H4S 2B4", ("CA", None, "Montreal", False, False)),
    ("Fresno, CA, United States", ("US", "CA", "Fresno", False, True)),
    ("Mateur, Bizerte Governorate, tn", ("TN", None, "Mateur", False, False)),
    ("East Syracuse, NY, US, 13057-0278", ("US", "NY", "East Syracuse", False, True)),
    ("St. Petersburg, FL, US", ("US", "FL", "St. Petersburg", False, True)),
    ("United States", ("US", None, None, False, True)),
    ("US", ("US", None, None, False, True)),
    ("Remote (US)", ("US", None, None, True, True)),
    ("Remote, United States", ("US", None, None, True, True)),
    ("Remote, US", ("US", None, None, True, True)),
    ("Remote- Canada ", ("CA", None, None, True, False)),
    ("Edmond, OK", ("US", "OK", "Edmond", False, True)),
    ("Salt Lake City, Utah", ("US", "UT", "Salt Lake City", False, True)),
    ("Massachusetts", ("US", "MA", None, False, True)),
    ("Texas, United States", ("US", "TX", None, False, True)),
    ("Wisconsin Wide, Wisconsin, United States", ("US", "WI", "Wisconsin Wide", False, True)),
    ("Atlanta, Georgia, us", ("US", "GA", "Atlanta", False, True)),
    ("Bengaluru, Karnataka, India", ("IN", None, "Bengaluru", False, False)),
    ("Stockholm, Sweden", ("SE", None, "Stockholm", False, False)),
    ("Paris, Paris, France", ("FR", None, "Paris", False, False)),
    ("Dublin, Co. Dublin, Ireland", ("IE", None, "Dublin", False, False)),
    ("Hermosillo, Son., mx", ("MX", None, "Hermosillo", False, False)),
    ("Pitești, AG, ro", ("RO", None, "Pitești", False, False)),
    ("Bouskoura, Casablanca-Settat, ma", ("MA", None, "Bouskoura", False, False)),
    ("Sault Ste. Marie, ON, ca", ("CA", None, "Sault Ste. Marie", False, False)),
    ("BC wide, British Columbia, Canada", ("CA", None, "BC wide", False, False)),
    ("Winnipeg, MB, Canada", ("CA", None, "Winnipeg", False, False)),
    ("United Kingdom", ("GB", None, None, False, False)),
    ("Remote", (None, None, None, True, False)),
    ("San Diego", (None, None, "San Diego", False, False)),   # city only: unknown stays unknown
    # Workday writes the country first (2026-10-10 strings)
    ("USA - PA - Oaks", ("US", "PA", "Oaks", False, True)),
    ("USA-Colorado-Fort Collins-4380 Ziegler Road", ("US", "CO", "Fort Collins", False, True)),
    ("USA-CA San Jose Innovation Drive", ("US", "CA", "San Jose Innovation Drive", False, True)),
    ("IND-Bangalore Electronic City - S1", ("IN", None, "Bangalore Electronic City", False, False)),
    ("IRL - Dublin", ("IE", None, "Dublin", False, False)),
    ("India - Bangalore", ("IN", None, "Bangalore", False, False)),
    ("Orlando area", (None, None, "Orlando area", False, False)),   # no country in the text: unknown
    ("2 Locations", (None, None, "2 Locations", False, False)),     # Workday summary: unknown
]


@pytest.mark.parametrize("text,expected", CASES)
def test_real_location_strings(text, expected):
    loc = parse(text)
    assert (loc.country_iso, loc.us_state, loc.city, loc.is_remote, loc.is_us) == expected


def test_several_locations():
    loc = parse("Ann Arbor, Michigan USA; South San Francisco, California, USA")
    assert loc.countries == ["US"] and loc.is_us and loc.us_state is None and loc.city is None
    loc = parse("Mexico City|Querétaro, Mexico")
    assert loc.countries == ["MX"]
    loc = parse("Saudi Arabia; United Arab Emirates")
    assert loc.countries == ["SA", "AE"] and not loc.is_us


def test_scraper_remote_flag_is_kept():
    assert parse("Austin, TX", is_remote=True).is_remote
    assert parse(None, is_remote=True).is_remote and parse(None).country_iso is None
