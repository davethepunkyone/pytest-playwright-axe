import json
import logging
from unittest.mock import MagicMock
import pytest
from playwright.sync_api import Page
from src.pytest_playwright_axe import Axe, AxeAccessibilityException

# An image with no alternative text, which results in an image-alt violation
IMAGE = '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">'

# Only one rule is run, so what is returned does not depend on anything else on the page
ONLY_IMAGE_ALT = {"runOnly": {"type": "rule", "values": ["image-alt"]}}
NO_PASSES = {**ONLY_IMAGE_ALT, "reporter": "no-passes"}
RAW = {**ONLY_IMAGE_ALT, "reporter": "raw"}
RAW_ENV = {**ONLY_IMAGE_ALT, "reporter": "rawEnv"}
UNRECOGNISED_REPORTER = "{reporter: function (raw, options, resolve) { resolve({custom: true}); }}"


def _html(body: str = "") -> str:
    return ('<!DOCTYPE html><html lang="en"><head><title>Test</title></head>'
            f'<body><main><h1>Test</h1>{body}</main></body></html>')


PAGES = {
    "http://top.test/": _html(f'{IMAGE}<iframe title="same" src="http://top.test/frame"></iframe>'),
    "http://top.test/frame": _html(IMAGE),
    "http://top.test/clean": _html(),
    "http://top.test/list": _html(f'{IMAGE}<ul><div>Not a list item</div></ul>'),
}


@pytest.fixture
def routed_page(page: Page) -> Page:
    """A page (with a violation, and a frame with one) where all the URLs in PAGES are served locally."""
    def handle_route(route):
        body = PAGES.get(route.request.url)
        if body is None:
            route.fulfill(status=404, body="")
        else:
            route.fulfill(status=200, content_type="text/html", body=body)

    page.context.route("**/*", handle_route)
    page.goto("http://top.test/")
    return page


@pytest.fixture
def axe(tmp_path) -> Axe:
    return Axe(output_directory=tmp_path / "reports")


def _files(axe: Axe) -> list[str]:
    return sorted(path.name for path in axe.output_directory.glob("*")) if axe.output_directory.exists() else []


# Working out what the results contain

STANDARD = {"url": "http://top.test/", "timestamp": "2024-11-04T16:14:57.934Z",
            "violations": [{"id": "rule"}], "passes": [], "incomplete": [], "inapplicable": []}
NO_PASSES_RESULTS = {"url": "http://top.test/", "timestamp": "2024-11-04T16:14:57.934Z", "violations": []}


def test_has_violations() -> None:
    axe = Axe()

    assert axe._has_violations(STANDARD) is True
    assert axe._has_violations({**STANDARD, "violations": []}) is False
    assert axe._has_violations(NO_PASSES_RESULTS) is False
    # The raw results have a list of violations for each rule, and rawEnv has these within "raw"
    raw = [{"id": "a", "violations": []}, {"id": "b", "violations": [{"node": 1}]}]
    assert axe._has_violations(raw) is True
    assert axe._has_violations([{"id": "a", "violations": []}]) is False
    assert axe._has_violations({"raw": raw, "env": {}}) is True
    assert axe._has_violations({"raw": [], "env": {}}) is False


@pytest.mark.parametrize("unrecognised", [{"custom": True}, "text", None, 5, [1, 2], [{"id": "a"}], {"violations": "no"}])
def test_has_violations_with_unrecognised_results(unrecognised) -> None:
    assert Axe()._has_violations(unrecognised) is None


def test_is_standard_results() -> None:
    axe = Axe()

    assert axe._is_standard_results(STANDARD) is True
    assert axe._is_standard_results(NO_PASSES_RESULTS) is True
    assert axe._is_standard_results([{"violations": []}]) is False
    assert axe._is_standard_results({"raw": [], "env": {}}) is False
    assert axe._is_standard_results({"url": "x", "violations": []}) is False


def test_get_url() -> None:
    page = MagicMock()
    page.url = "http://page.test/"

    assert Axe()._get_url(STANDARD, page) == "http://top.test/"
    assert Axe()._get_url({"raw": [], "env": {"url": "http://env.test/"}}, page) == "http://env.test/"
    assert Axe()._get_url([], page) == "http://page.test/"
    assert Axe()._get_url({"custom": True}, page) == "http://page.test/"


def test_log_summary(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        Axe()._log_summary(STANDARD, "http://top.test/")
        Axe()._log_summary(NO_PASSES_RESULTS, "http://top.test/")
        Axe()._log_summary([], "http://top.test/")

    messages = [record.getMessage() for record in caplog.records]
    assert messages[0] == ("Axe scan summary of [http://top.test/]:\n- Passes = 0\n- Violations = 1\n"
                           "- Inapplicable = 0\n- Incomplete = 0")
    assert messages[1] == "Axe scan summary of [http://top.test/]:\n- Violations = 0"
    assert "cannot be summarised" in messages[2]


# Reports

def test_create_json_report_with_a_url_for_the_filename(axe: Axe) -> None:
    axe._create_json_report([{"id": "a", "violations": []}], url="http://raw.test/page/")

    assert _files(axe) == ["raw_test_page.json"]
    assert json.loads((axe.output_directory / "raw_test_page.json").read_text()) == [{"id": "a", "violations": []}]


def test_create_json_report_that_cannot_be_serialised(axe: Axe, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        axe._create_json_report({"url": "http://top.test/", "bad": {1, 2}})

    assert "not JSON serialisable" in caplog.text
    assert _files(axe) == []


def test_generate_html_with_results_not_included() -> None:
    html = Axe()._generate_html(NO_PASSES_RESULTS, "report")

    assert html.count("Not included, as the axe-core reporter used does not return these results.") == 3
    for title in ["Passed Checks", "Incomplete Checks", "Inapplicable Checks"]:
        assert f"<h2>{title}</h2><p>Not included" in html
    assert "<h2>Violations Found</h2>" in html
    assert "No passed checks found" not in html


def test_failure_summary_is_used_if_provided() -> None:
    assert Axe()._failure_summary({"failureSummary": "Provided", "any": [{"message": "Ignored"}]}) == "Provided"


def test_failure_summary_built_from_checks() -> None:
    node = {
        "any": [{"message": "Any one"}, {"message": "Or another\nover two lines"}],
        "all": [{"message": "All of this"}],
        "none": [{"message": "None of this"}, {}],
    }

    # As axe-core does, the checks to fix all of come first (those for none, then all) and then those to fix any of
    assert Axe()._failure_summary(node) == (
        "Fix all of the following:\n  None of this\n  \n  All of this\n\n"
        "Fix any of the following:\n  Any one\n  Or another\n  over two lines")
    assert Axe()._failure_summary({"any": [{"message": "Only any"}], "all": [], "none": []}) == (
        "Fix any of the following:\n  Only any")
    assert Axe()._failure_summary({}) == ""


def test_failure_summary_matches_the_v1_reporter(routed_page: Page) -> None:
    routed_page.goto("http://top.test/list")
    axe = Axe()

    results = axe._run_axe(
        routed_page, axe.axe_path.read_text(encoding="UTF-8"), None,
        {"runOnly": {"type": "rule", "values": ["image-alt", "list"]}, "reporter": "v1"})

    nodes = [node for violation in results["violations"] for node in violation["nodes"]]
    summaries = [node["failureSummary"] for node in nodes]
    assert any("Fix any of the following:" in summary for summary in summaries)
    assert any("Fix all of the following:" in summary for summary in summaries)
    for node in nodes:
        without_summary = {key: value for key, value in node.items() if key != "failureSummary"}
        assert axe._failure_summary(without_summary) == node["failureSummary"]


def test_get_snapshot_data_without_violations(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
    (tmp_path / "report.json").write_text(json.dumps([{"id": "a", "violations": []}]))
    (tmp_path / "raw_env.json").write_text(json.dumps({"raw": [], "env": {}}))
    axe = Axe(snapshot_directory=tmp_path)

    with caplog.at_level(logging.WARNING):
        assert axe._get_snapshot_data("report") is None
        assert axe._get_snapshot_data("raw_env") is None

    assert caplog.text.count("does not contain the violations needed for a comparison") == 2


# Scanning using each reporter

@pytest.mark.parametrize("reporter", ["v1", "v2", "na"])
def test_run_with_standard_reporters(routed_page: Page, axe: Axe, reporter: str) -> None:
    results = axe.run(routed_page, filename="report", options={**ONLY_IMAGE_ALT, "reporter": reporter})

    assert [violation["id"] for violation in results["violations"]] == ["image-alt"]
    assert len(results["violations"][0]["nodes"]) == 2
    assert _files(axe) == ["report.html", "report.json"]
    html = (axe.output_directory / "report.html").read_text()
    assert "Not included" not in html
    # The guidance on fixing each element is in the report, whichever reporter provided the results
    assert "<strong>Fix any of the following:</strong>" in html
    assert "Element does not have an alt attribute" in html


def test_run_with_no_passes_reporter(routed_page: Page, axe: Axe, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        results = axe.run(routed_page, filename="report", options=NO_PASSES)

    # The frame is scanned too, and only the violations (and what describes the scan) are returned
    assert [(violation["id"], len(violation["nodes"])) for violation in results["violations"]] == [("image-alt", 2)]
    assert {"passes", "incomplete", "inapplicable"}.isdisjoint(results)
    assert results["url"] == "http://top.test/"

    assert _files(axe) == ["report.html", "report.json"]
    assert json.loads((axe.output_directory / "report.json").read_text()) == results
    html = (axe.output_directory / "report.html").read_text()
    assert html.count("Not included, as the axe-core reporter used") == 3
    assert "image-alt" in html
    assert "<strong>Fix any of the following:</strong>" in html
    assert "- Violations = 1" in caplog.text and "- Passes" not in caplog.text


def test_run_with_no_passes_reporter_and_strict_mode(routed_page: Page, axe: Axe) -> None:
    with pytest.raises(AxeAccessibilityException, match="Violation detected on page: http://top.test/"):
        axe.run(routed_page, filename="report", options=NO_PASSES, strict_mode=True)
    # The reports are still generated before the exception is raised
    assert _files(axe) == ["report.html", "report.json"]

    routed_page.goto("http://top.test/clean")
    results = axe.run(routed_page, options=NO_PASSES, strict_mode=True, html_report_generated=False,
                      json_report_generated=False)
    assert results["violations"] == []


def test_run_with_no_passes_reporter_set_using_configure(routed_page: Page, axe: Axe) -> None:
    results = axe.configure({"reporter": "no-passes"}).run(
        routed_page, options=ONLY_IMAGE_ALT, json_report_generated=False, html_report_generated=False)

    assert {"passes", "incomplete", "inapplicable"}.isdisjoint(results)
    assert len(results["violations"]) == 1


def test_run_with_no_passes_reporter_compared_to_a_snapshot(routed_page: Page, tmp_path) -> None:
    # A snapshot from a scan with the default reporter can be compared to one from the no-passes reporter
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    previous = Axe(output_directory=snapshots)
    previous.run(routed_page, filename="report", options=ONLY_IMAGE_ALT, html_report_generated=False)

    axe = Axe(output_directory=tmp_path / "reports", snapshot_directory=snapshots)
    axe.run(routed_page, filename="report", options=NO_PASSES)

    html = (axe.output_directory / "report.html").read_text()
    assert "Changes Since Last Scan" in html
    assert "No changes detected" in html


def test_run_with_raw_reporter(routed_page: Page, axe: Axe, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        results = axe.run(routed_page, options=RAW)

    assert isinstance(results, list)
    assert [rule["id"] for rule in results if rule["violations"]] == ["image-alt"]
    assert "not in the standard format" in caplog.text

    # There is no HTML report, and the filename comes from the page as the results do not contain the URL
    assert _files(axe) == ["top_test.json"]
    assert json.loads((axe.output_directory / "top_test.json").read_text()) == results


def test_run_with_raw_reporter_and_strict_mode(routed_page: Page, axe: Axe) -> None:
    with pytest.raises(AxeAccessibilityException, match="Violation detected on page: http://top.test/"):
        axe.run(routed_page, options=RAW, strict_mode=True, html_report_generated=False)

    routed_page.goto("http://top.test/clean")
    results = axe.run(routed_page, options=RAW, strict_mode=True, html_report_generated=False)
    assert not any(rule["violations"] for rule in results)


def test_run_with_raw_reporter_reports_only_on_violation(routed_page: Page, axe: Axe) -> None:
    routed_page.goto("http://top.test/clean")
    axe.run(routed_page, options=RAW, report_on_violation_only=True, html_report_generated=False)
    assert _files(axe) == []

    routed_page.goto("http://top.test/")
    axe.run(routed_page, options=RAW, report_on_violation_only=True, html_report_generated=False)
    assert _files(axe) == ["top_test.json"]


def test_run_with_raw_env_reporter(routed_page: Page, axe: Axe) -> None:
    results = axe.run(routed_page, options=RAW_ENV, html_report_generated=False)

    assert set(results) == {"raw", "env"}
    assert [rule["id"] for rule in results["raw"] if rule["violations"]] == ["image-alt"]
    assert _files(axe) == ["top_test.json"]

    with pytest.raises(AxeAccessibilityException, match="Violation detected on page: http://top.test/"):
        axe.run(routed_page, options=RAW_ENV, strict_mode=True, html_report_generated=False)


def test_run_with_unrecognised_results(routed_page: Page, axe: Axe, caplog: pytest.LogCaptureFixture) -> None:
    axe.configure(UNRECOGNISED_REPORTER)

    with caplog.at_level(logging.WARNING):
        results = axe.run(routed_page, options=ONLY_IMAGE_ALT)

    assert results == {"custom": True}
    assert "HTML report cannot be generated" in caplog.text
    assert _files(axe) == ["top_test.json"]
    assert json.loads((axe.output_directory / "top_test.json").read_text()) == {"custom": True}


def test_run_with_unrecognised_results_and_strict_mode(routed_page: Page, axe: Axe) -> None:
    axe.configure(UNRECOGNISED_REPORTER)

    # A scan cannot be allowed to pass when there is no way of knowing if it should have failed
    with pytest.raises(AxeAccessibilityException, match="strict_mode cannot be used"):
        axe.run(routed_page, options=ONLY_IMAGE_ALT, strict_mode=True, html_report_generated=False)

    # The reports are still generated if only reporting on violations, as it is not known if there were any
    axe.run(routed_page, options=ONLY_IMAGE_ALT, report_on_violation_only=True, html_report_generated=False)
    assert _files(axe) == ["top_test.json"]


def test_run_list_with_no_passes_reporter(routed_page: Page, axe: Axe) -> None:
    results = axe.run_list(
        routed_page, ["http://top.test/", "http://top.test/clean"], options=NO_PASSES, html_report_generated=False)

    assert len(results["http://top.test/"]["violations"]) == 1
    assert results["http://top.test/clean"]["violations"] == []
    assert _files(axe) == ["top_test.json", "top_test_clean.json"]
