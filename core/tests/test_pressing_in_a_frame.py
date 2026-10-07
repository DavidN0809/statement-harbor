"""paperpull_core.pressing on a control inside a frame, in a real browser.

The look of what sits on top of a control ran only in a page's main frame,
so a control inside a frame could not be checked, and M&T pressed its year
headings, which sit in a frame of its statements page, through page script
with nothing checked. Now a control in a frame is read in that frame's own
world, by the box Playwright reports carried into the frame's coordinates,
and each frame around it has to be the thing on top in its own parent at
the point to be pressed. After the press the point is read again in the
control's frame and in each frame around it.

Every page here replaces eval as American Express does, so what is read is
read in the module's own worlds. Each document writes what was pressed in it
into a line of its own, read back through a locator. The control sits far
down a frame that sits far down the page, so nothing is read before it is
brought to the middle of the window. Every word on these pages is made up.
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from paperpull_core import pressing
from paperpull_core.words import words_for

sync_api = pytest.importorskip("playwright.sync_api")

WORDS = words_for("Example Bank")
CANARY = "Quillonby"
# Playwright's time for its press here.
TIMEOUT = 2000

HEAD = """<!doctype html><html><head><meta charset="utf-8"><title>made up</title>
<script>window.eval = function () { throw new Error('eval is disabled'); };
function said(what) { document.getElementById('log').textContent += what + ';'; }</script>
<style>html, body { margin: 0; font: 16px sans-serif; }
.cover { position: fixed; left: 0; top: 0; width: 100vw; height: 100vh; z-index: 10;
         background: rgba(0, 0, 0, .25); }</style>
</head><body><output id="log"></output>
"""

# A frame far down the page, with a border and padding, so its window does
# not begin where its element does.
FRAME = ('<iframe id="%s" name="%s" src="%s" style="border: 3px solid; padding: 6px; '
         'width: 500px; height: 300px%s"></iframe>')


def frame_tag(name, src, style=""):
    return FRAME % (name, name, src, style)
SPACE = '<div style="height: 1500px"></div>'

# The control, far down its frame.
CONTROL = ('<div style="height: 900px"></div><button id="go" type="button" '
           'onclick="said(\'go\')%s">Statements of 2024</button><div style="height: 900px"></div>')
COVER = ('<div class="cover" role="dialog" aria-label="Chat with %s" onclick="said(\'cover\')" '
         'onmousedown="said(\'cover-down\')"><span>%s</span></div>' % (CANARY, CANARY))


class _Site:
    def __init__(self):
        self.pages = {}


def _handler(site):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            body = site.pages.get(self.path.split("?")[0].lstrip("/"), "").encode("utf-8")
            self.send_response(200 if body else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    return Handler


@pytest.fixture(scope="module")
def playwright():
    # One Playwright for both browsers, since two cannot share a thread.
    with sync_api.sync_playwright() as p:
        yield p


def _launch(playwright, args):
    try:
        b = playwright.chromium.launch(headless=True, args=args)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    yield b
    b.close()


@pytest.fixture(scope="module")
def browser(playwright):
    yield from _launch(playwright, [])


@pytest.fixture(scope="module")
def isolated(playwright):
    """A browser that draws a frame of another site in a process of its
    own, as a person's own Chrome or Edge does."""
    yield from _launch(playwright, ["--site-per-process"])


@pytest.fixture()
def site():
    """A site of this test's own, answering at 127.0.0.1 and at localhost,
    which are two sites to the browser."""
    s = _Site()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(s))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    s.here = "http://127.0.0.1:%d/" % port
    s.other = "http://localhost:%d/" % port
    yield s
    httpd.shutdown()
    httpd.server_close()


def opened(browser, site, main, **frames):
    """The page `main` in a tab 1000 by 600, with each named document in
    `frames` served for it, and every frame drawn."""
    for name, body in frames.items():
        site.pages[name] = HEAD + body + "</body></html>"
    site.pages["main"] = HEAD + main + "</body></html>"
    context = browser.new_context(viewport={"width": 1000, "height": 600})
    page = context.new_page()
    page.goto(site.here + "main")
    page.wait_for_load_state("load")
    return page


def said(frame):
    return [p for p in frame.locator("#log").inner_text().split(";") if p]


def press(page, frame, **given):
    args = dict(css="button", what="the heading of the year 2024", words=WORDS, timeout=TIMEOUT,
                frame=frame)
    args.update(given)
    pressing.click(page, frame.locator("#go"), **args)


def framed(site, main_extra="", inner_extra="", onclick="", style="", host=None):
    """The usual page, a frame far down it, holding the control far down."""
    main = SPACE + frame_tag("f", (host or site.here) + "inner", style) + SPACE + main_extra
    return main, {"inner": CONTROL % onclick + inner_extra}


def test_eval_is_refused_in_the_page_and_in_the_frame(browser, site):
    """Not vacuous. Playwright's own evaluate fails in both documents, so
    whatever reads them reads them another way."""
    main, frames = framed(site)
    page = opened(browser, site, main, **frames)
    for frame in (page.main_frame, page.frame(name="f")):
        with pytest.raises(Exception, match="eval is disabled"):
            frame.evaluate("1 + 1")


def test_a_control_in_a_frame_with_nothing_on_top_is_pressed_once(browser, site):
    """The control is 2,400 pixels down a window 600 tall, so it is found
    at the point only once it and its frame were brought to the middle."""
    main, frames = framed(site)
    page = opened(browser, site, main, **frames)
    frame = page.frame(name="f")
    press(page, frame)
    assert said(frame) == ["go"]
    assert said(page.main_frame) == []


def test_something_over_the_control_inside_its_frame_means_nothing_is_pressed(browser, site):
    main, frames = framed(site, inner_extra=COVER)
    page = opened(browser, site, main, **frames)
    frame = page.frame(name="f")
    with pytest.raises(pressing.Covered) as stopped:
        press(page, frame)
    stop = stopped.value
    assert stop.reason == "something on the page is over the control"
    assert "over_the_frame" not in stop.facts
    assert stop.facts["over_it"]["role"] == "dialog" and stop.facts["fixed"] is True
    assert CANARY not in " ".join(stop.lines) + repr(stop.facts)
    assert stop.after_a_press is False
    assert said(frame) == []
    assert said(page.main_frame) == []


def test_something_over_the_frame_in_the_page_means_nothing_is_pressed(browser, site):
    """The page's own chat window sits over the frame, where Playwright's
    check inside the frame cannot see it."""
    main, frames = framed(site, main_extra=COVER)
    page = opened(browser, site, main, **frames)
    frame = page.frame(name="f")
    with pytest.raises(pressing.Covered) as stopped:
        press(page, frame)
    stop = stopped.value
    assert stop.reason == "something on the page is over the control"
    assert stop.facts["over_the_frame"] is True
    assert stop.facts["over_it"]["role"] == "dialog" and stop.facts["fixed"] is True
    assert stop.lines[0] == ("Something on the page covers the heading of the year 2024, "
                             "so nothing was pressed.")
    assert CANARY not in " ".join(stop.lines) + repr(stop.facts)
    assert said(frame) == []
    assert said(page.main_frame) == []


def test_something_over_another_part_of_the_frame_leaves_the_control_to_be_pressed(
        browser, site):
    """A box pinned to the window's lower right corner, over the frame's
    corner and not over the middle of the window, where the control is
    brought."""
    corner = ('<div style="position: fixed; right: 0; bottom: 0; width: 200px; height: 60px; '
              'z-index: 10; background: #06c" onclick="said(\'corner\')">Offer</div>')
    main, frames = framed(site, main_extra=corner)
    page = opened(browser, site, main, **frames)
    frame = page.frame(name="f")
    press(page, frame)
    assert said(frame) == ["go"]
    assert said(page.main_frame) == []


@pytest.mark.parametrize("where", ["nowhere", "inner", "middle", "page"])
def test_a_frame_in_a_frame_is_read_up_to_the_page(browser, site, where):
    """The control's frame sits inside a frame of the page. A cover in any
    of the three documents means nothing is pressed, and one in a document
    around the control's frame is said to be over the frame."""
    middle = ('<div style="height: 400px"></div>' + frame_tag("in", site.here + "inner")
              + '<div style="height: 400px"></div>' + (COVER if where == "middle" else ""))
    main = (SPACE + frame_tag("f", site.here + "middle", "; width: 700px; height: 500px")
            + SPACE + (COVER if where == "page" else ""))
    page = opened(browser, site, main, middle=middle,
                  inner=CONTROL % "" + (COVER if where == "inner" else ""))
    frame = page.frame(name="in")
    assert frame.parent_frame == page.frame(name="f")
    if where == "nowhere":
        press(page, frame)
        assert said(frame) == ["go"]
        return
    with pytest.raises(pressing.Covered) as stopped:
        press(page, frame)
    assert stopped.value.facts.get("over_the_frame", False) is (where != "inner")
    assert said(frame) == []
    for other in (page.frame(name="f"), page.main_frame):
        assert said(other) == []


@pytest.mark.parametrize("where", ["nowhere", "inner", "page"])
def test_a_frame_of_another_site_drawn_by_a_process_of_its_own(isolated, site, where):
    """A person's own browser draws a frame of another site in a process of
    its own. The frame is reached through a session of its own, and
    Playwright reports boxes in it from where its element's border begins,
    not where its window does, so the box is carried across that way."""
    main, frames = framed(site, host=site.other,
                          main_extra=COVER if where == "page" else "",
                          inner_extra=COVER if where == "inner" else "")
    page = opened(isolated, site, main, **frames)
    frame = page.frame(name="f")
    assert frame.url.startswith(site.other)
    # Not vacuous. Playwright has a session of its own only for a frame
    # drawn by a process of its own.
    page.context.new_cdp_session(frame).detach()
    if where == "nowhere":
        press(page, frame)
        assert said(frame) == ["go"]
        return
    with pytest.raises(pressing.Covered) as stopped:
        press(page, frame)
    assert stopped.value.facts.get("over_the_frame", False) is (where == "page")
    assert said(frame) == []
    assert said(page.main_frame) == []


@pytest.mark.parametrize("drawn, why", [("transform: scale(0.8)", "frame scaled"),
                                        ("transform: rotate(3deg)", "frame")])
def test_a_frame_not_drawn_at_its_own_size_and_square_is_not_read(browser, site, drawn, why):
    """A point does not carry across into a frame drawn at another size
    than its own window, or turned, so nothing is pressed."""
    main, frames = framed(site, style="; " + drawn + "; transform-origin: 0 0")
    page = opened(browser, site, main, **frames)
    frame = page.frame(name="f")
    with pytest.raises(pressing.Unread) as stopped:
        press(page, frame)
    assert stopped.value.facts == {"why": why}
    assert said(frame) == []


def test_two_frames_alike_are_not_told_apart_so_nothing_is_pressed(browser, site):
    """Two frames of the page with the same address and the same name. Which
    one the control is in cannot be told, so nothing is pressed."""
    main = (SPACE + frame_tag("f", site.here + "inner") + frame_tag("f", site.here + "inner")
            + SPACE)
    page = opened(browser, site, main, inner=CONTROL % "")
    second = page.frames[2]
    assert second.name == "f" and second.parent_frame == page.main_frame
    with pytest.raises(pressing.Unread) as stopped:
        press(page, second)
    assert stopped.value.facts == {"why": "frame"}
    assert said(second) == [] and said(page.frames[1]) == []


def test_a_control_the_selector_does_not_find_in_its_frame_is_not_pressed(browser, site):
    main, frames = framed(site)
    page = opened(browser, site, main, **frames)
    frame = page.frame(name="f")
    with pytest.raises(pressing.Unread) as stopped:
        press(page, frame, css="a")
    assert stopped.value.facts == {"why": "none"}
    assert said(frame) == []


# Something in the page that comes over the frame the moment the pointer
# moves onto the control, after every read before the press has passed.
LATE_IN_PAGE = ('<div id="late" style="position: fixed; left: 0; top: 0; width: 100vw; '
                'height: 100vh; z-index: 9; background: #06c; visibility: hidden" '
                'onmousedown="said(\'late-down\')" onclick="said(\'late-click\')"></div>')
SHOW_LATE = ('<script>let once = false; document.addEventListener("mousemove", () => {'
             ' if (once) return; once = true;'
             ' %s.getElementById("late").style.visibility = "visible"; });</script>')
LATE_FRAME = ('<iframe id="late" style="position: fixed; left: 0; top: 0; width: 100vw; '
              'height: 100vh; border: 0; z-index: 9; visibility: hidden" '
              'srcdoc="<body style=&quot;margin: 0&quot;><button style=&quot;width: 100vw; '
              'height: 100vh&quot; onmousedown=&quot;parent.said(\'frame-down\')&quot;>Chat'
              '</button></body>"></iframe>')


def test_something_in_the_page_that_comes_over_the_frame_as_it_is_pressed_stops_the_run(
        browser, site):
    """Playwright watches for its press only inside the control's frame,
    and takes a press that never came there for one that went through. So
    the point is read again in the page right after the press, and what
    came over the frame there stops the run."""
    main, frames = framed(site, main_extra=LATE_IN_PAGE,
                          inner_extra=SHOW_LATE % "parent.document")
    page = opened(browser, site, main, **frames)
    frame = page.frame(name="f")
    with pytest.raises(pressing.Covered) as stopped:
        press(page, frame)
    stop = stopped.value
    assert stop.reason == "something on the page came over the control"
    assert stop.facts["after_the_press"] is True and stop.facts["over_the_frame"] is True
    assert stop.after_a_press is True
    assert stop.lines[0].startswith("Something came over the heading of the year 2024 as it "
                                    "was pressed")
    assert said(frame) == []
    assert "late-down" in said(page.main_frame)


def test_a_frame_that_comes_over_the_control_inside_its_frame_as_it_is_pressed_stops_the_run(
        browser, site):
    """The same read as for a control in the page's main frame, made in the
    control's own frame."""
    main, frames = framed(site, inner_extra=LATE_FRAME + SHOW_LATE % "document")
    page = opened(browser, site, main, **frames)
    frame = page.frame(name="f")
    with pytest.raises(pressing.Covered) as stopped:
        press(page, frame)
    stop = stopped.value
    assert stop.facts["after_the_press"] is True and "over_the_frame" not in stop.facts
    assert stop.facts["over_it"]["tag"] == "iframe"
    assert "go" not in said(frame)


def test_something_under_the_frame_before_the_press_is_not_taken_for_a_cover(browser, site):
    """Pressing the control moves its frame away from the point. What the
    page shows there now was under the frame before the press, so nothing
    came over the frame and nothing stops."""
    main, frames = framed(site, onclick="; parent.document.getElementById('f').style.marginLeft"
                                        " = '600px'")
    page = opened(browser, site, main, **frames)
    frame = page.frame(name="f")
    press(page, frame)
    assert said(frame) == ["go"]
    # Not vacuous. The frame did leave the point.
    assert frame.frame_element().bounding_box()["x"] >= 600


def test_something_raised_over_a_frame_still_there_stops_the_run(browser, site):
    """A box of the page sits under the frame, and pressing the control
    raises the box over the frame. The box was at the point before the
    press, but the frame is still there under it, so the box came over the
    frame and the run stops."""
    under = ('<div id="under" style="position: absolute; left: 0; top: 1400px; width: 800px; '
             'height: 600px; z-index: 0; background: #ccc" onmousedown="said(\'under-down\')">'
             '</div>')
    main, frames = framed(site, main_extra=under, style="; position: relative; z-index: 1",
                          onclick="; parent.document.getElementById('under').style.zIndex = 9")
    page = opened(browser, site, main, **frames)
    frame = page.frame(name="f")
    with pytest.raises(pressing.Covered) as stopped:
        press(page, frame)
    assert stopped.value.facts["after_the_press"] is True
    assert stopped.value.facts["over_the_frame"] is True
    assert said(frame) == ["go"]


def test_the_page_s_own_frame_is_read_as_the_page(browser, site):
    """A control in the page's main frame, handed over with that frame, is
    read the way it always was."""
    page = opened(browser, site, SPACE + CONTROL % "" + SPACE)
    press(page, page.main_frame)
    assert said(page.main_frame) == ["go"]
