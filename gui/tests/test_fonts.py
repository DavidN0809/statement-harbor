"""The panel's typefaces, served from gui/static/fonts by name only.

Atkinson Hyperlegible Next and Mono, under the SIL Open Font License, ship
inside the panel so no page ever fetches a font from the web. The route
answers the two names on its list and nothing else, and each font travels
with its license.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")

GUI = Path(__file__).resolve().parents[1]
REPO = GUI.parent
FONTS = GUI / "static" / "fonts"


@pytest.mark.parametrize("name", app_module.FONTS)
def test_each_font_is_served_whole_as_a_font(name):
    answer = app_module.font(name)
    assert answer.media_type == "font/ttf"
    body = answer.body
    assert body == (FONTS / name).read_bytes()
    assert body[:4] == b"\x00\x01\x00\x00", "not a TrueType font"
    assert "max-age" in answer.headers["cache-control"]


@pytest.mark.parametrize("name", ["../app.py", "..\\app.py", "app.py", "x.ttf",
                                  "OFL-AtkinsonHyperlegibleNext.txt", "", "%2e%2e%2fapp.py",
                                  "AtkinsonHyperlegibleNext.TTF"])
def test_nothing_but_the_two_fonts_is_served(name):
    with pytest.raises(app_module.HTTPException) as e:
        app_module.font(name)
    assert e.value.status_code == 404


def test_the_page_asks_for_exactly_the_fonts_the_route_serves():
    css = (GUI / "static" / "app.css").read_text(encoding="utf-8")
    asked = re.findall(r'url\("/fonts/([^"]+)"\)', css)
    assert sorted(asked) == sorted(app_module.FONTS)
    # Never from the web, which the house privacy promise rules out.
    assert "fonts.googleapis" not in app_module.HTML and "fonts.gstatic" not in app_module.HTML


def test_each_font_travels_with_its_license_and_notice_names_them():
    for name in app_module.FONTS:
        family = name[:-len(".ttf")]
        license_file = FONTS / ("OFL-%s.txt" % family)
        text = license_file.read_text(encoding="utf-8")
        assert "SIL Open Font License, Version 1.1" in text
        assert ("The %s Project Authors" % family.replace("AtkinsonHyperlegible", "Atkinson Hyperlegible ")) in text
    notice = " ".join((REPO / "NOTICE.md").read_text(encoding="utf-8").split())
    assert "Atkinson Hyperlegible Next and Atkinson Hyperlegible Mono" in notice
    assert "SIL Open Font License, Version 1.1" in notice and "gui/static/fonts/" in notice
