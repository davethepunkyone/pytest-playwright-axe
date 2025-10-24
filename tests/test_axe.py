import json
import pytest
import os
from pathlib import Path
from src.pytest_playwright_axe import Axe, AxeAccessibilityException
from playwright.sync_api import Locator


DEFAULT_CSS_PATH = Path(__file__).parent.parent / "src" / "pytest_playwright_axe" / "resources" / "default.css"

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

@pytest.fixture
def patch_locator(monkeypatch):
    monkeypatch.setattr(Locator, "text_content", lambda self: "mocked text")


def test_axe_init_around_minified_file() -> None:
    axe = Axe()
    assert axe.axe_path.is_file()
    assert axe.axe_path.name == "axe.js"

    axe = Axe(use_minified_file=True)
    assert axe.axe_path.is_file()
    assert axe.axe_path.name == "axe.min.js"


def test_build_run_command() -> None:
    assert Axe()._build_run_command('context', 'options') == "context, options"
    assert Axe()._build_run_command(context='context') == "context"
    assert Axe()._build_run_command(options='options') == "options"


def test_modify_filename_for_report() -> None:
    assert Axe()._modify_filename_for_report(
        'https://www.test.com/1/2\\3/') == "www_test_com_1_2_3"


def test_empty_filename_for_report() -> None:
    with pytest.raises(AxeAccessibilityException):
        Axe()._modify_filename_for_report('')


def test_create_path_for_report() -> None:
    assert Axe(output_directory=AXE_REPORTS_DIR)._create_path_for_report('test123.html') == Path(
        __file__).parent.parent / "axe-reports" / "test123.html"


def test_create_json_report() -> None:
    test_data = {"url": "https://www.test.com/1"}

    # Default generation
    Axe(output_directory=AXE_REPORTS_DIR)._create_json_report(test_data)
    with open(AXE_REPORTS_DIR / TEST_JSON_DEFAULT_FILENAME, 'r') as file:
        assert file.read() == '''{\n    "url": "https://www.test.com/1"\n}'''

    # With custom filename
    Axe(output_directory=AXE_REPORTS_DIR)._create_json_report(test_data,
                            TEST_JSON_CUSTOM_FILENAME.replace(".json", ""))
    with open(AXE_REPORTS_DIR / TEST_JSON_CUSTOM_FILENAME, 'r') as file:
        assert file.read() == '''{\n    "url": "https://www.test.com/1"\n}'''


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
    expected_file_data = Axe()._generate_html(test_data, TEST_HTML_DEFAULT_FILENAME)

    # Default generation
    Axe(output_directory=AXE_REPORTS_DIR)._create_html_report(test_data)
    with open(AXE_REPORTS_DIR / TEST_HTML_DEFAULT_FILENAME, 'r') as file:
        assert file.read() == expected_file_data

    # With custom filename
    Axe(output_directory=AXE_REPORTS_DIR)._create_html_report(test_data,
                            TEST_HTML_CUSTOM_FILENAME.replace(".html", ""))
    with open(AXE_REPORTS_DIR / TEST_HTML_CUSTOM_FILENAME, 'r') as file:
        assert file.read() == expected_file_data


def test_wcag_tagging() -> None:
    result = Axe()._wcag_tagging(['wcag22a', "best-practice", "x"])
    assert result == "WCAG 2.2 (A), Best Practice"


def test_css_styling() -> None:
    default_css = DEFAULT_CSS_PATH.read_text(encoding="UTF-8")
    result = Axe()._css_styling()
    assert result == f"<style>{default_css}</style>"
    
    custom_css_result = Axe(css_override="body { background-color: red; }")._css_styling()
    assert custom_css_result == "<style>body { background-color: red; }</style>"


def test_generate_violations_section_no_data() -> None:
    test_data = []
    results = Axe()._generate_violations_section(test_data)
    assert results == "<h2>Violations Found</h2><p>No violations found.</p>"


def test_generate_violations_section_with_data() -> None:
    test_data = [{"id": "test3", "impact": "high", "tags": ["cat.keyboard", "best-test"], "description": "test", "help": "test", "helpUrl": "test url", "nodes": []}]
    results = Axe()._generate_violations_section(test_data)
    assert results == '<h2>Violations Found</h2><p>1 violations found.</p><table><tr><th style="text-align: center; width: 2%">#</th><th style="width: 53%">Description</th><th style="width: 15%">Axe Rule ID</th><th style="width: 15%">WCAG</th><th style="width: 10%">Impact</th><th style="text-align: center; width: 5%">Count</th><tr>\n                    <td style="text-align: center;">1</td>\n                    <td>test</td>\n                    <td><a href="test url" target="_blank">test3</a></td>\n                    <td></td>\n                    <td>high</td>\n                    <td style="text-align: center;">0</td>\n                    </tr></table><table><tr><td style="width: 100%"><h3>test</h3>\n                                <p><strong>Axe Rule ID:</strong> <a href="test url" target="_blank">test3</a><br />\n                                <strong>WCAG:</strong> <br />\n                                <strong>Impact:</strong> high<br />\n                                <strong>Tags:</strong> cat.keyboard, best-test</p>\n                                <table><tr><th style="text-align: center; width: 2%">#</th><th style="width: 49%">Description</th><th style="width: 49%">Fix Information</th></table>\n                                </td></tr></table>'


def test_generate_passed_section_no_data() -> None:
    test_data = []
    results = Axe()._generate_passed_section(test_data)
    assert results == "<h2>Passed Checks</h2><p>No passed checks found.</p>"


def test_generate_passed_section_with_data() -> None:
    test_data = [{"id": "test2", "impact": None, "tags": ["cat.keyboard", "best-practice"], "description": "test", "help": "test", "helpUrl": "test", "nodes": []}]
    results = Axe()._generate_passed_section(test_data)
    assert results == '<h2>Passed Checks</h2><table><tr><th style="text-align: center; width: 2%">#</th><th style="width: 50%">Description</th><th style="width: 15%">Axe Rule ID</th><th style="width: 18%">WCAG</th><th style="text-align: center; width: 15%">Nodes Passed Count</th><tr>\n                    <td style="text-align: center;">1</td>\n                    <td>test</td>\n                    <td><a href="test" target="_blank">test2</a></td>\n                    <td>Best Practice</td>\n                    <td style="text-align: center;">0</td>\n                    </tr></table>'


def test_generate_inapplicable_section_no_data() -> None:
    test_data = []
    results = Axe()._generate_inapplicable_section(test_data)
    assert results == "<h2>Inapplicable Checks</h2><p>No inapplicable checks found.</p>"


def test_generate_inapplicable_section_with_data() -> None:
    test_data = [{"id": "test1", "impact": None, "tags": ["cat.keyboard", "best-practice"], "description": "test", "help": "test", "helpUrl": "test", "nodes": []}]
    results = Axe()._generate_inapplicable_section(test_data)
    assert results == '<h2>Inapplicable Checks</h2><table><tr><th style="text-align: center; width: 2%">#</th><th style="width: 60%">Description</th><th style="width: 20%">Axe Rule ID</th><th style="width: 18%">WCAG</th><tr>\n                    <td style="text-align: center;">1</td>\n                    <td>test</td>\n                    <td><a href="test" target="_blank">test1</a></td>\n                    <td>Best Practice</td>\n                    </tr></table>'


def test_generate_incomplete_section_no_data() -> None:
    test_data = []
    results = Axe()._generate_incomplete_section(test_data)
    assert results == "<h2>Incomplete Checks</h2><p>No incomplete checks found.</p>"


def test_generate_incomplete_section_with_data() -> None:
    test_data = [{"id": "test1", "impact": None, "tags": ["cat.keyboard", "best-practice"], "description": "test", "help": "test", "helpUrl": "test", "nodes": []}]
    results = Axe()._generate_incomplete_section(test_data)
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
    results = Axe()._generate_execution_details_section(test_data)
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
    results = Axe()._generate_html(test_data, TEST_HTML_DEFAULT_FILENAME)

    for text_to_assert in ["axe", "test browser", "https://www.test.com/2", "test1", "test2", "test3", "high", "best-test", "test url"]:
        assert text_to_assert in results

def test_check_pre_scan_actions(patch_locator: Locator) -> None:
    def return_default_data() -> dict:
        return {
            "url": "https://github.com/davethepunkyone/pytest-playwright-axe",
            "action": "click", 
            "locator": Locator.__new__(Locator), 
            "assert_type": "to_contain_text", 
            "assert_locator": Locator.__new__(Locator),
            "assert_value": "rework-axe-to-include-init",
            "wait_time": 1000
        }

    # Valid
    data = return_default_data()
    assert Axe()._check_pre_scan_actions(data) == None

    # No Action
    del data["action"]
    with pytest.raises(AxeAccessibilityException):
        Axe()._check_pre_scan_actions(data)
    
    # No Locator
    data = return_default_data()
    del data["locator"]
    with pytest.raises(AxeAccessibilityException):
        Axe()._check_pre_scan_actions(data)
    
    # No Value when required
    data = return_default_data()
    data["action"] = "fill"
    with pytest.raises(AxeAccessibilityException):
        Axe()._check_pre_scan_actions(data)
    
    # Locator not Locator instance type
    data = return_default_data()
    data["locator"] = "fake string"
    with pytest.raises(AxeAccessibilityException):
        Axe()._check_pre_scan_actions(data)
    
    # Wait time not int
    data = return_default_data()
    data["wait_time"] = "fake string"
    with pytest.raises(AxeAccessibilityException):
        Axe()._check_pre_scan_actions(data)

def test_check_pre_scan_assertions(patch_locator: Locator) -> None:
    def return_default_data() -> dict:
        return {
            "url": "https://github.com/davethepunkyone/pytest-playwright-axe",
            "action": "click", 
            "locator": Locator.__new__(Locator), 
            "assert_type": "to_contain_text", 
            "assert_locator": Locator.__new__(Locator),
            "assert_value": "rework-axe-to-include-init",
            "wait_time": 1000
        }

    data = return_default_data()
    assert Axe()._check_pre_scan_assertions(data) == None

    # Assert Locator not Locator instance type
    data["assert_locator"] = "fake string"
    with pytest.raises(AxeAccessibilityException):
        Axe()._check_pre_scan_assertions(data)
    
    # No Assert Value when required
    data = return_default_data()
    data["assert_type"] = "to_contain_text"
    del data["assert_value"]
    with pytest.raises(AxeAccessibilityException):
        Axe()._check_pre_scan_actions(data)

def test_get_snapshot_data_no_directory() -> None:
    """Test when no snapshot directory is configured"""
    result = Axe()._get_snapshot_data("test")
    assert result is None

def test_get_snapshot_data_file_not_exists() -> None:
    """Test when snapshot file doesn't exist"""
    result = Axe(snapshot_directory=AXE_REPORTS_DIR)._get_snapshot_data("nonexistent")
    assert result is None

def test_get_snapshot_data_success() -> None:
    """Test successful snapshot data retrieval"""
    # Create a test snapshot file
    test_snapshot = {"url": "test", "violations": []}
    snapshot_path = AXE_REPORTS_DIR / "test_snapshot.json"
    with open(snapshot_path, 'w') as f:
        json.dump(test_snapshot, f)
    
    result = Axe(snapshot_directory=AXE_REPORTS_DIR)._get_snapshot_data("test_snapshot")
    assert result == test_snapshot
    
    # Cleanup
    os.remove(snapshot_path)

def test_find_new_violations() -> None:
    """Test finding new violations"""
    current = {"rule1": {"id": "rule1", "description": "test", "impact": "high", "tags": [], "nodes": [1, 2]}}
    snapshot = {}
    
    result = Axe()._find_new_violations(current, snapshot)
    assert len(result) == 1
    assert result[0]['type'] == 'New Violation'
    assert result[0]['current_count'] == 2

def test_find_resolved_violations() -> None:
    """Test finding resolved violations"""
    current = {}
    snapshot = {"rule1": {"id": "rule1", "description": "test", "impact": "high", "tags": [], "nodes": [1]}}
    
    result = Axe()._find_resolved_violations(current, snapshot)
    assert len(result) == 1
    assert result[0]['type'] == 'Resolved Violation'
    assert result[0]['previous_count'] == 1

def test_find_count_changes() -> None:
    """Test finding count changes"""
    current = {"rule1": {"id": "rule1", "description": "test", "impact": "high", "tags": [], "nodes": [1, 2, 3]}}
    snapshot = {"rule1": {"id": "rule1", "description": "test", "impact": "high", "tags": [], "nodes": [1]}}
    
    result = Axe()._find_count_changes(current, snapshot)
    assert len(result) == 1
    assert result[0]['type'] == 'Increased Count'
    assert result[0]['change'] == 2

def test_generate_changes_section_no_snapshot() -> None:
    """Test changes section when no snapshot provided"""
    result = Axe()._generate_changes_section({}, None)
    assert result == ""

def test_generate_changes_section_no_changes() -> None:
    """Test changes section when no changes detected"""
    data = {"violations": [], "timestamp": "2024-11-04T16:14:57.934Z"}
    snapshot = {"violations": [], "timestamp": "2024-11-03T16:14:57.934Z"}
    
    result = Axe()._generate_changes_section(data, snapshot)
    assert "No changes detected" in result

def test_complete_pre_scan_actions_invalid_action(page, patch_locator) -> None:
    """Test invalid action raises exception"""
    actions = {
        "action": "invalid_action",
        "locator": Locator.__new__(Locator)
    }
    with pytest.raises(AxeAccessibilityException):
        Axe()._complete_pre_scan_actions(page, actions)