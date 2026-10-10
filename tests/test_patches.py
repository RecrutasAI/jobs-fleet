import json

from fleet.patches import parse_bamboohr_widget

WIDGET = json.dumps({"version": None, "success": True, "departments": [
    {"id": 19933, "label": "ATL", "positions": [
        {"id": 996, "name": "BIM/VDC Manager ", "url": "https://aceelectric.bamboohr.com/careers/996",
         "location": "Greater Atlanta, GA"},
        {"id": 997, "name": "Foreman", "location": ""}]},
    {"id": 19937, "label": "STB", "positions": [
        {"id": 996, "name": "BIM/VDC Manager", "url": "x", "location": "dup"},
        {"id": 601, "name": "", "url": "no title"}]},
]})


def test_reads_json_widget():
    jobs = parse_bamboohr_widget(WIDGET, "aceelectric")
    assert [j["ats_id"] for j in jobs] == ["996", "997"]
    assert jobs[0] == {"ats_id": "996", "title": "BIM/VDC Manager",
                       "url": "https://aceelectric.bamboohr.com/careers/996",
                       "location": "Greater Atlanta, GA", "department": "ATL"}
    assert jobs[1]["url"] == "https://aceelectric.bamboohr.com/careers/997"
    assert jobs[1]["location"] is None


def test_html_falls_back_to_upstream_parser():
    assert parse_bamboohr_widget("<div class='BambooHR-ATS-board'></div>", "x") is None


def test_empty_board():
    assert parse_bamboohr_widget('{"departments": []}', "x") == []
