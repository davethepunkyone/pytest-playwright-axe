from playwright.sync_api import Page
from src.pytest_playwright_axe import Axe, OPTIONS_WCAG_22AA


def test_basic_example(page: Page) -> None:
    page.goto("https://github.com/davethepunkyone/pytest-playwright-axe")

    # Assert repo text is present
    Axe.run(page, options=OPTIONS_WCAG_22AA)


def test_minified_example(page: Page) -> None:
    page.goto("https://github.com/davethepunkyone/pytest-playwright-axe")

    # Assert repo text is present
    Axe.run(page, options=OPTIONS_WCAG_22AA, use_minified_file=True)


def test_get_rules(page: Page) -> None:
    rules = Axe.get_rules(page, ["wcag2a"])
    print(rules[0])
