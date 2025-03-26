from playwright.sync_api import Page
from src.pytest_playwright_axe import Axe, OPTIONS_WCAG_22AA


def test_basic_example(page: Page) -> None:
    page.goto("https://wrestlingheadlines.com")

    # Assert repo text is present
    Axe.run(page, options=OPTIONS_WCAG_22AA)
