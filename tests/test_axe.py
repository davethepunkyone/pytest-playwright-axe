import pytest
import os
from pathlib import Path
from src.pytest_playwright_axe import Axe


AXE_REPORTS_DIR = Path(__file__).parent.parent / "axe-reports"
TEST_JSON_DEFAULT_FILENAME = "www_test_com_1.json"
TEST_JSON_CUSTOM_FILENAME = "test_json_file.json"
TEST_HTML_DEFAULT_FILENAME = "www_test_com_1.html"
TEST_HTML_CUSTOM_FILENAME = "test_html_file.html"


@pytest.fixture(scope="session", autouse=True)
def remove_files_before_test() -> None:
    for file in [TEST_JSON_DEFAULT_FILENAME, TEST_JSON_CUSTOM_FILENAME, TEST_HTML_DEFAULT_FILENAME, TEST_HTML_CUSTOM_FILENAME]:
        if os.path.isfile(AXE_REPORTS_DIR / file):
            os.remove(AXE_REPORTS_DIR / file)


def test_build_run_command() -> None:
    assert Axe._build_run_command('context', 'options') == "context, options"
    assert Axe._build_run_command(context='context') == "context"
    assert Axe._build_run_command(options='options') == "options"


def test_modify_filename_for_report() -> None:
    assert Axe._modify_filename_for_report(
        'https://www.test.com/1/2\\3/') == "www_test_com_1_2_3"


def test_create_path_for_report() -> None:
    assert Axe._create_path_for_report(AXE_REPORTS_DIR, 'test123.html') == Path(
        __file__).parent.parent / "axe-reports" / "test123.html"


def test_create_json_report() -> None:
    test_data = {"url": "https://www.test.com/1"}

    # Default generation
    Axe._create_json_report(test_data, AXE_REPORTS_DIR)
    with open(AXE_REPORTS_DIR / TEST_JSON_DEFAULT_FILENAME, 'r') as file:
        assert file.read() == '{"url": "https://www.test.com/1"}'

    # With custom filename
    Axe._create_json_report(test_data, AXE_REPORTS_DIR,
                            TEST_JSON_CUSTOM_FILENAME.replace(".json", ""))
    with open(AXE_REPORTS_DIR / TEST_JSON_CUSTOM_FILENAME, 'r') as file:
        assert file.read() == '{"url": "https://www.test.com/1"}'


def test_create_html_report() -> None:
    test_data = {"testEngine":
                 {"name": "axe-core", "version": "4.10.2"},
                 "testRunner": {"name": "axe"},
                 "testEnvironment": {"userAgent": "test browser"},
                 "timestamp": "2024-11-04T16:14:57.934Z",
                 "url": "https://www.test.com/1",
                 "toolOptions": {"runOnly": {"type": "tag", "values": ["wcag2a", "wcag21a", "wcag2aa", "wcag21aa", "best-practice"]}, "reporter": "v1"},
                 "inapplicable": [{"id": "test", "impact": None, "tags": ["cat.keyboard", "best-practice"], "description": "test", "help": "test", "helpUrl": "test", "nodes": []}],
                 "passes": [{"id": "test", "impact": None, "tags": ["cat.keyboard", "best-practice"], "description": "test", "help": "test", "helpUrl": "test", "nodes": []}],
                 "incomplete": [],
                 "violations": [{"id": "test", "impact": None, "tags": ["cat.keyboard", "best-practice"], "description": "test", "help": "test", "helpUrl": "test", "nodes": []}]
                 }
    expected_file_data = Axe._generate_html(test_data)

    # Default generation
    Axe._create_html_report(test_data, AXE_REPORTS_DIR)
    with open(AXE_REPORTS_DIR / TEST_HTML_DEFAULT_FILENAME, 'r') as file:
        assert file.read() == expected_file_data

    # With custom filename
    Axe._create_html_report(test_data, AXE_REPORTS_DIR,
                            TEST_HTML_CUSTOM_FILENAME.replace(".html", ""))
    with open(AXE_REPORTS_DIR / TEST_HTML_CUSTOM_FILENAME, 'r') as file:
        assert file.read() == expected_file_data


def test_wcag_tagging() -> None:
    result = Axe._wcag_tagging(['wcag22a', "best-practice", "x"])
    assert result == "WCAG 2.2 (A), Best Practice"


def test_css_styling() -> None:
    result = Axe._css_styling()
    for string_to_check in ["<style>", "</style>", "body", "h1", "h2", "h3", "table", "th", "td", "a", "p", "pre", "div"]:
        assert string_to_check in result


def test_generate_violations_section_no_data() -> None:
    test_data = []
    results = Axe._generate_violations_section(test_data)
    assert results == "<h2>Violations Found</h2><p>No violations found.</p>"


def test_generate_violations_section_with_data() -> None:
    test_data = [{"id": "test3", "impact": "high", "tags": ["cat.keyboard", "best-test"], "description": "test", "help": "test", "helpUrl": "test url", "nodes": []}]
    results = Axe._generate_violations_section(test_data)
    assert results == '<h2>Violations Found</h2><p>1 violations found.</p><table><tr><th style="text-align: center; width: 2%">#</th><th style="width: 53%">Description</th><th style="width: 15%">Axe Rule ID</th><th style="width: 15%">WCAG</th><th style="width: 10%">Impact</th><th style="text-align: center; width: 5%">Count</th><tr>\n                    <td style="text-align: center;">1</td>\n                    <td>test</td>\n                    <td><a href="test url" target="_blank">test3</a></td>\n                    <td></td>\n                    <td>high</td>\n                    <td style="text-align: center;">0</td>\n                    </tr></table><table><tr><td style="width: 100%"><h3>test</h3>\n                                <p><strong>Axe Rule ID:</strong> <a href="test url" target="_blank">test3</a><br />\n                                <strong>WCAG:</strong> <br />\n                                <strong>Impact:</strong> high<br />\n                                <strong>Tags:</strong> cat.keyboard, best-test</p>\n                                <table><tr><th style="text-align: center; width: 2%">#</th><th style="width: 49%">Description</th><th style="width: 49%">Fix Information</th></table>\n                                </td></tr></table>'


def test_generate_passed_section_no_data() -> None:
    test_data = []
    results = Axe._generate_passed_section(test_data)
    assert results == "<h2>Passed Checks</h2><p>No passed checks found.</p>"


def test_generate_passed_section_with_data() -> None:
    test_data = [{"id": "test2", "impact": None, "tags": ["cat.keyboard", "best-practice"], "description": "test", "help": "test", "helpUrl": "test", "nodes": []}]
    results = Axe._generate_passed_section(test_data)
    assert results == '<h2>Passed Checks</h2><table><tr><th style="text-align: center; width: 2%">#</th><th style="width: 50%">Description</th><th style="width: 15%">Axe Rule ID</th><th style="width: 18%">WCAG</th><th style="text-align: center; width: 15%">Nodes Passed Count</th><tr>\n                    <td style="text-align: center;">1</td>\n                    <td>test</td>\n                    <td><a href="test" target="_blank">test2</a></td>\n                    <td>Best Practice</td>\n                    <td style="text-align: center;">0</td>\n                    </tr></table>'


def test_generate_inapplicable_section_no_data() -> None:
    test_data = []
    results = Axe._generate_inapplicable_section(test_data)
    assert results == "<h2>Inapplicable Checks</h2><p>No inapplicable checks found.</p>"


def test_generate_inapplicable_section_with_data() -> None:
    test_data = [{"id": "test1", "impact": None, "tags": ["cat.keyboard", "best-practice"], "description": "test", "help": "test", "helpUrl": "test", "nodes": []}]
    results = Axe._generate_inapplicable_section(test_data)
    assert results == '<h2>Inapplicable Checks</h2><table><tr><th style="text-align: center; width: 2%">#</th><th style="width: 60%">Description</th><th style="width: 20%">Axe Rule ID</th><th style="width: 18%">WCAG</th><tr>\n                    <td style="text-align: center;">1</td>\n                    <td>test</td>\n                    <td><a href="test" target="_blank">test1</a></td>\n                    <td>Best Practice</td>\n                    </tr></table>'


def test_generate_incomplete_section_no_data() -> None:
    test_data = []
    results = Axe._generate_incomplete_section(test_data)
    assert results == "<h2>Incomplete Checks</h2><p>No incomplete checks found.</p>"


def test_generate_incomplete_section_with_data() -> None:
    test_data = [{"id": "test1", "impact": None, "tags": ["cat.keyboard", "best-practice"], "description": "test", "help": "test", "helpUrl": "test", "nodes": []}]
    results = Axe._generate_incomplete_section(test_data)
    assert results == '<h2>Incomplete Checks</h2><table><tr><th style="text-align: center; width: 2%">#</th><th style="width: 50%">Description</th><th style="width: 15%">Axe Rule ID</th><th style="width: 18%">WCAG</th><th style="text-align: center; width: 15%">Nodes Incomplete Count</th><tr>\n                    <td style="text-align: center;">1</td>\n                    <td>test</td>\n                    <td><a href="test" target="_blank">test1</a></td>\n                    <td>Best Practice</td>\n                    <td style="text-align: center;">0</td>\n                    </tr></table>'


def test_generate_execution_details_section() -> None:
    test_data = {"testEngine":
                 {"name": "axe-core", "version": "4.10.2"},
                 "testRunner": {"name": "axe"},
                 "testEnvironment": {"userAgent": "test browser"},
                 "timestamp": "2024-11-04T16:14:57.934Z",
                 "url": "https://www.test.com/2",
                 "toolOptions": {"runOnly": {"type": "tag", "values": ["wcag2a", "wcag21a", "wcag2aa", "wcag21aa", "best-practice"]}, "reporter": "v1"},
                 "inapplicable": [{"id": "test1", "impact": None, "tags": ["cat.keyboard", "best-practice"], "description": "test", "help": "test", "helpUrl": "test", "nodes": []}],
                 "passes": [{"id": "test2", "impact": None, "tags": ["cat.keyboard", "best-practice"], "description": "test", "help": "test", "helpUrl": "test", "nodes": []}],
                 "incomplete": [],
                 "violations": [{"id": "test3", "impact": "high", "tags": ["cat.keyboard", "best-test"], "description": "test", "help": "test", "helpUrl": "test url", "nodes": []}]
                 }
    results = Axe._generate_execution_details_section(test_data)
    assert results == '<h2>Execution Details</h2><table><tr><th style="width: 20%">Data</th><th style="width: 80%">Details</th><tr><td>Test Engine</td><td>name: <i>axe-core</i><br />version: <i>4.10.2</i><br /></td></tr><tr><td>Test Runner</td><td>name: <i>axe</i><br /></td></tr><tr><td>Test Environment</td><td>userAgent: <i>test browser</i><br /></td></tr><tr><td>Tool Options</td><td>runOnly: <i>{&#x27;type&#x27;: &#x27;tag&#x27;, &#x27;values&#x27;: [&#x27;wcag2a&#x27;, &#x27;wcag21a&#x27;, &#x27;wcag2aa&#x27;, &#x27;wcag21aa&#x27;, &#x27;best-practice&#x27;]}</i><br />reporter: <i>v1</i><br /></td></tr><tr><td>Timestamp</td><td>2024-11-04T16:14:57.934Z</td></tr><tr><td>URL</td><td>https://www.test.com/2</td></tr></table>'


def test_generate_html() -> None:
    test_data = {"testEngine":
                 {"name": "axe-core", "version": "4.10.2"},
                 "testRunner": {"name": "axe"},
                 "testEnvironment": {"userAgent": "test browser"},
                 "timestamp": "2024-11-04T16:14:57.934Z",
                 "url": "https://www.test.com/2",
                 "toolOptions": {"runOnly": {"type": "tag", "values": ["wcag2a", "wcag21a", "wcag2aa", "wcag21aa", "best-practice"]}, "reporter": "v1"},
                 "inapplicable": [{"id": "test1", "impact": None, "tags": ["cat.keyboard", "best-practice"], "description": "test", "help": "test", "helpUrl": "test", "nodes": []}],
                 "passes": [{"id": "test2", "impact": None, "tags": ["cat.keyboard", "best-practice"], "description": "test", "help": "test", "helpUrl": "test", "nodes": []}],
                 "incomplete": [],
                 "violations": [{"id": "test3", "impact": "high", "tags": ["cat.keyboard", "best-test"], "description": "test", "help": "test", "helpUrl": "test url", "nodes": []}]
                 }
    results = Axe._generate_html(test_data)

    for text_to_assert in ["axe", "test browser", "https://www.test.com/2", "test1", "test2", "test3", "high", "best-test", "test url"]:
        assert text_to_assert in results
