import pytest
from playwright.sync_api import Page, expect
from src.axe import Axe, OPTIONS_WCAG_22AA


def test_basic_example(page: Page) -> None:
    page.goto("https://github.com/nhs-england-tools/playwright-python-blueprint")

    # Assert repo text is present
    Axe.run(page, options=OPTIONS_WCAG_22AA)
