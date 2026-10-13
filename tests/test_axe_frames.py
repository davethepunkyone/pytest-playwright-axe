import logging
import time
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from playwright.sync_api import (
    Browser, BrowserContext, BrowserType, Page, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError)
from src.pytest_playwright_axe import Axe
from src.pytest_playwright_axe.axe import FRAME_READY_TIMEOUT_MS

NO_REPORTS = {"html_report_generated": False, "json_report_generated": False}

# An image with no alternative text, which results in an image-alt violation
IMAGE = '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">'


def _html(body: str = "") -> str:
    return ('<!DOCTYPE html><html lang="en"><head><title>Test</title></head>'
            f'<body><main><h1>Test</h1>{body}</main></body></html>')


# Each hostname is treated by the browser as a separate origin
PAGES = {
    "http://top.test/": _html(
        f'{IMAGE}<iframe title="same" src="http://top.test/frame"></iframe>'
        '<iframe title="cross" src="http://other.test/frame"></iframe>'),
    "http://top.test/frame": _html(IMAGE),
    "http://top.test/nested": _html(
        '<iframe title="a" src="http://top.test/frame-a"></iframe>'
        '<iframe title="b" src="http://other.test/frame"></iframe>'),
    "http://top.test/frame-a": _html(
        f'{IMAGE}<iframe title="a1" src="http://other.test/frame"></iframe>'),
    "http://top.test/no-frames": _html(f'{IMAGE}<button></button>'),
    "http://top.test/stalled": _html(f'{IMAGE}<iframe title="stalled" src="http://stall.test/frame"></iframe>'),
}


@pytest.fixture
def routed_page(page: Page) -> Page:
    """A page where all the URLs in PAGES are served locally, so no network access is required."""
    def handle_route(route):
        url = route.request.url
        body = PAGES.get(url, PAGES.get(url.replace("http://other.test", "http://top.test")))
        if body is None:
            route.fulfill(status=404, body="")
        else:
            route.fulfill(status=200, content_type="text/html", body=body)

    page.context.route("**/*", handle_route)
    return page


def _targets(results: dict, rule_id: str) -> list[list[str]]:
    """The targets for every node reported against the rule provided, across violations only."""
    return sorted(
        node["target"]
        for violation in results["violations"] if violation["id"] == rule_id
        for node in violation["nodes"]
    )


def test_run_scans_same_and_cross_origin_frames(routed_page: Page) -> None:
    routed_page.goto("http://top.test/")

    results = Axe().run(routed_page, **NO_REPORTS)

    assert _targets(results, "image-alt") == [
        ["iframe[title=\"cross\"]", "img"],
        ["iframe[title=\"same\"]", "img"],
        ["img"],
    ]
    assert not any(item["id"] == "frame-tested" for item in results["incomplete"])
    assert results["url"] == "http://top.test/"


def test_run_scans_nested_frames(routed_page: Page) -> None:
    routed_page.goto("http://top.test/nested")

    results = Axe().run(routed_page, **NO_REPORTS)

    # axe uses the shortest unique selector within each document, so the only iframe inside frame "a" is just "iframe"
    assert _targets(results, "image-alt") == [
        ["iframe[title=\"a\"]", "iframe", "img"],
        ["iframe[title=\"a\"]", "img"],
        ["iframe[title=\"b\"]", "img"],
    ]


def test_run_passes_options_to_frames(routed_page: Page) -> None:
    routed_page.goto("http://top.test/")

    results = Axe().run(
        routed_page, options="{rules: {'image-alt': {enabled: false}}}", **NO_REPORTS)

    assert _targets(results, "image-alt") == []


def test_run_with_context_from_frames(routed_page: Page) -> None:
    routed_page.goto("http://top.test/")

    results = Axe().run(
        routed_page, context="{fromFrames: ['iframe[title=same]', 'img']}", **NO_REPORTS)

    assert _targets(results, "image-alt") == [["iframe[title=\"same\"]", "img"]]


def test_run_with_context_excluding_a_frame(routed_page: Page) -> None:
    routed_page.goto("http://top.test/")

    results = Axe().run(
        routed_page, context="{exclude: ['iframe[title=cross]']}", **NO_REPORTS)

    assert _targets(results, "image-alt") == [["iframe[title=\"same\"]", "img"], ["img"]]


def test_run_with_iframes_option_disabled(routed_page: Page) -> None:
    routed_page.goto("http://top.test/")

    results = Axe().run(routed_page, options="{iframes: false}", **NO_REPORTS)

    assert _targets(results, "image-alt") == [["img"]]


def test_run_without_frames_matches_axe_run(routed_page: Page) -> None:
    routed_page.goto("http://top.test/no-frames")
    axe = Axe()

    results = axe.run(routed_page, **NO_REPORTS)

    routed_page.evaluate(axe.axe_path.read_text(encoding="UTF-8"))
    expected = routed_page.evaluate("axe.run()")

    def summarise(data: dict) -> dict:
        return {
            group: [(rule["id"], [node["target"] for node in rule["nodes"]]) for rule in data[group]]
            for group in ["violations", "passes", "incomplete", "inapplicable"]
        }

    assert summarise(results) == summarise(expected)
    assert results["testEngine"] == expected["testEngine"]
    assert results["url"] == expected["url"]


def test_run_does_not_leave_extra_pages_open(routed_page: Page) -> None:
    routed_page.goto("http://top.test/")

    Axe().run(routed_page, **NO_REPORTS)

    assert routed_page.context.pages == [routed_page]


def test_run_with_page_from_browser_new_page(browser: Browser) -> None:
    # Pages created this way cannot open another page in their (implicit) context
    page = browser.new_page()
    try:
        page.route("**/*", lambda route: route.fulfill(
            status=200, content_type="text/html", body=_html(IMAGE)))
        page.goto("http://top.test/")

        results = Axe().run(page, **NO_REPORTS)

        assert _targets(results, "image-alt") == [["img"]]
        assert page.context.pages == [page]
    finally:
        page.close()


def test_run_with_persistent_context(browser_type: BrowserType, tmp_path: Path) -> None:
    context = browser_type.launch_persistent_context(str(tmp_path))
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.route("**/*", lambda route: route.fulfill(
            status=200, content_type="text/html", body=_html(IMAGE)))
        page.goto("http://top.test/")

        results = Axe().run(page, **NO_REPORTS)

        assert _targets(results, "image-alt") == [["img"]]
        assert context.pages == [page]
    finally:
        context.close()


def test_blank_page_uses_separate_context_when_browser_available() -> None:
    page = MagicMock()

    with Axe()._blank_page(page) as blank_page:
        assert blank_page is page.context.browser.new_context.return_value.new_page.return_value

    page.context.browser.new_context.return_value.close.assert_called_once()
    page.context.new_page.assert_not_called()


def test_blank_page_falls_back_to_same_context_if_separate_context_cannot_be_used() -> None:
    page = MagicMock()
    page.context.browser.new_context.return_value.new_page.side_effect = PlaywrightError("boom")

    with Axe()._blank_page(page) as blank_page:
        assert blank_page is page.context.new_page.return_value

    # The separate context that was opened is not left behind
    page.context.browser.new_context.return_value.close.assert_called_once()
    blank_page.close.assert_called_once()


def test_blank_page_falls_back_to_same_context_if_new_context_is_not_allowed() -> None:
    page = MagicMock()
    page.context.browser.new_context.side_effect = PlaywrightError("Not supported")

    with Axe()._blank_page(page) as blank_page:
        assert blank_page is page.context.new_page.return_value

    blank_page.close.assert_called_once()


def test_blank_page_uses_the_page_scanned_if_no_other_page_can_be_opened() -> None:
    page = MagicMock()
    page.context.browser.new_context.side_effect = PlaywrightError("Not supported")
    page.context.new_page.side_effect = PlaywrightError("Please use browser.new_context()")

    with Axe()._blank_page(page) as blank_page:
        assert blank_page is page

    page.close.assert_not_called()


def test_blank_page_uses_same_context_when_there_is_no_browser() -> None:
    page = MagicMock()
    page.context.browser = None

    with Axe()._blank_page(page) as blank_page:
        assert blank_page is page.context.new_page.return_value

    blank_page.close.assert_called_once()


def test_run_still_completes_if_a_blank_page_cannot_be_opened(routed_page: Page, monkeypatch: pytest.MonkeyPatch) -> None:
    # Combining the results within the page being scanned is the last resort, and must give the same results
    routed_page.goto("http://top.test/")
    expected = _targets(Axe().run(routed_page, **NO_REPORTS), "image-alt")

    def refuse(*args, **kwargs):
        raise PlaywrightError("Not supported")

    monkeypatch.setattr(Browser, "new_context", refuse)
    monkeypatch.setattr(BrowserContext, "new_page", refuse)

    results = Axe().run(routed_page, **NO_REPORTS)

    assert _targets(results, "image-alt") == expected
    assert len(expected) == 3


def test_run_skips_a_frame_that_never_finishes_loading(
        routed_page: Page, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    stalled_requests = []
    # The request for the frame is never answered, so its navigation never completes and it cannot be scripted
    routed_page.context.route("http://stall.test/**", lambda route: stalled_requests.append(route))
    monkeypatch.setattr("src.pytest_playwright_axe.axe.FRAME_READY_TIMEOUT_MS", 1000)

    try:
        routed_page.goto("http://top.test/stalled", wait_until="domcontentloaded")
        started = time.time()

        with caplog.at_level(logging.WARNING):
            results = Axe().run(routed_page, **NO_REPORTS)

        assert time.time() - started < 30
        assert stalled_requests
        assert _targets(results, "image-alt") == [["img"]]
        assert "could not be scanned" in caplog.text
    finally:
        for route in stalled_requests:
            try:
                route.abort()
            except PlaywrightError:
                pass


def test_run_list_scans_frames(routed_page: Page) -> None:
    results = Axe().run_list(routed_page, ["http://top.test/", "http://top.test/no-frames"], **NO_REPORTS)

    assert len(_targets(results["http://top.test/"], "image-alt")) == 3
    assert _targets(results["http://top.test/no-frames"], "image-alt") == [["img"]]


def test_run_partial_in_frame_waits_for_the_frame_to_be_ready_before_scripting_it() -> None:
    frame = MagicMock()
    frame.evaluate.return_value = {"partial": "{}", "frameContexts": [], "options": {}}

    Axe()._run_partial_in_frame(frame, "axe source", "script")

    assert [call[0] for call in frame.method_calls] == ["wait_for_function", "evaluate", "evaluate"]
    assert frame.wait_for_function.call_args.kwargs["timeout"] == FRAME_READY_TIMEOUT_MS


def test_run_partial_in_child_frame_that_is_not_ready(caplog: pytest.LogCaptureFixture) -> None:
    child_frame = MagicMock()
    child_frame.wait_for_function.side_effect = PlaywrightTimeoutError("Timeout 5000ms exceeded.")
    parent_frame = MagicMock()
    parent_frame.evaluate_handle.return_value.as_element.return_value.content_frame.return_value = child_frame
    frame_details = {"frameSelector": "iframe#stalled", "frameContext": {}}

    with caplog.at_level(logging.WARNING):
        results = Axe()._run_partial_in_child_frame(parent_frame, frame_details, "", {})

    assert results == [None]
    assert "Frame [iframe#stalled] could not be scanned" in caplog.text
    child_frame.evaluate.assert_not_called()


def test_run_partial_in_child_frame_with_unavailable_frame(caplog: pytest.LogCaptureFixture) -> None:
    parent_frame = MagicMock()
    parent_frame.evaluate_handle.side_effect = PlaywrightError("Frame was detached")
    frame_details = {"frameSelector": "iframe#gone", "frameContext": {}}

    with caplog.at_level(logging.WARNING):
        results = Axe()._run_partial_in_child_frame(parent_frame, frame_details, "", {})

    assert results == [None]
    assert "Frame [iframe#gone] could not be scanned" in caplog.text


def test_run_partial_in_child_frame_with_no_content(caplog: pytest.LogCaptureFixture) -> None:
    parent_frame = MagicMock()
    parent_frame.evaluate_handle.return_value.as_element.return_value = None
    frame_details = {"frameSelector": "iframe#empty", "frameContext": {}}

    with caplog.at_level(logging.WARNING):
        results = Axe()._run_partial_in_child_frame(parent_frame, frame_details, "", {})

    assert results == [None]
    assert "Frame [iframe#empty] has no content available" in caplog.text
    parent_frame.evaluate_handle.return_value.dispose.assert_called_once()
