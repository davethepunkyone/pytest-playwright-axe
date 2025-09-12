from pathlib import Path
from playwright.sync_api import Page
import pytest
from src.pytest_playwright_axe import Axe, OPTIONS_WCAG_22AA


def test_basic_example(page: Page) -> None:
    page.goto("https://github.com/davethepunkyone/pytest-playwright-axe")

    # Assert repo text is present
    Axe().run(page, options=OPTIONS_WCAG_22AA)


def test_minified_example(page: Page) -> None:
    page.goto("https://github.com/davethepunkyone/pytest-playwright-axe")

    # Assert repo text is present
    Axe(use_minified_file=True).run(page, options=OPTIONS_WCAG_22AA)


def test_get_rules(page: Page) -> None:
    rules = Axe().get_rules(page, ["wcag2a"])
    print(rules[0])


def test_run_list_with_actions(page: Page) -> None:
    actions = [
        "https://github.com/davethepunkyone/pytest-playwright-axe",
        {
            "url": "https://github.com/davethepunkyone/pytest-playwright-axe",
            "action": "click", 
            "locator": page.get_by_test_id("anchor-button"), 
            "assert_type": "to_contain_text", 
            "assert_locator": page.get_by_test_id("overlay-content"),
            "assert_value": "rework-axe-to-include-init",
            "wait_time": 1000
        }
    ]

    Axe().run_list(page, actions)

@pytest.mark.skip(reason="Test is for local execution only")
def test_get_report_of_report(page: Page) -> None:
    EXAMPLES_DIR = Path(__file__).parent.parent / "examples" / "example_result_report.html"
    page.goto(str(EXAMPLES_DIR))
    Axe().run(page)
