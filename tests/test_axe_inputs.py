import pytest
from playwright.sync_api import ElementHandle, Page
from src.pytest_playwright_axe import Axe, AxeAccessibilityException, OPTIONS_WCAG_22AA
from src.pytest_playwright_axe.axe import _fill_template

NO_REPORTS = {"html_report_generated": False, "json_report_generated": False}

# An image with no alternative text, which results in an image-alt violation
IMAGE = '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">'


def _html(body: str) -> str:
    return f'<!DOCTYPE html><html lang="en"><head><title>Test</title></head><body>{body}</body></html>'


# Each hostname is treated by the browser as a separate origin
PAGES = {
    "http://top.test/": _html(
        f'<header id="header">{IMAGE}</header>'
        f'<main id="content"><h1>Top</h1>{IMAGE}<div id="ads">{IMAGE}</div></main>'
        '<iframe title="same" src="http://top.test/frame"></iframe>'
        '<iframe title="cross" src="http://other.test/frame"></iframe>'),
    "http://top.test/frame": _html(
        f'<main id="inner"><h1>Frame</h1>{IMAGE}<section id="only">{IMAGE}</section></main>'),
}

IMAGE_ALT_IN_FRAMES = [
    ["iframe[title=\"cross\"]", "#inner > img"],
    ["iframe[title=\"cross\"]", "#only > img"],
    ["iframe[title=\"same\"]", "#inner > img"],
    ["iframe[title=\"same\"]", "#only > img"],
]
ALL_IMAGE_ALT = sorted([["#ads > img"], ["#content > img"], ["#header > img"]] + IMAGE_ALT_IN_FRAMES)

DISABLE_IMAGE_ALT = {"rules": [{"id": "image-alt", "enabled": False}]}

# A custom check can only be defined using JavaScript, as it has to contain a function
CUSTOM_RULE_JS = """{
    checks: [{
        id: 'has-data-test',
        evaluate: function (node) { return node.hasAttribute('data-test'); },
        metadata: {impact: 'minor', messages: {pass: 'Has data-test', fail: 'Missing data-test'}}
    }],
    rules: [{
        id: 'h1-data-test', selector: 'h1', any: ['has-data-test'],
        metadata: {description: 'h1 needs data-test', help: 'h1 needs data-test'}
    }]
}"""
ONLY_CUSTOM_RULE = {"runOnly": {"type": "rule", "values": ["h1-data-test"]}}


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
    page.goto("http://top.test/")
    return page


def _targets(results: dict, rule_id: str = "image-alt") -> list[list[str]]:
    """The targets for every node reported against the rule provided, across violations only."""
    return sorted(
        node["target"]
        for violation in results["violations"] if violation["id"] == rule_id
        for node in violation["nodes"]
    )


def test_fill_template_does_not_reprocess_inserted_text() -> None:
    assert _fill_template("%CONTEXT% | %OPTIONS%", context="%OPTIONS%", options="{}") == "%OPTIONS% | {}"


# Options and context as dicts and lists

def test_run_with_dict_options(routed_page: Page) -> None:
    results = Axe().run(routed_page, options={"rules": {"image-alt": {"enabled": False}}}, **NO_REPORTS)

    assert _targets(results) == []


def test_run_with_dict_options_for_rules_to_run(routed_page: Page) -> None:
    results = Axe().run(
        routed_page, options={"runOnly": {"type": "rule", "values": ["image-alt"]}}, **NO_REPORTS)

    assert _targets(results) == ALL_IMAGE_ALT
    assert [violation["id"] for violation in results["violations"]] == ["image-alt"]


def test_run_with_dict_context_include(routed_page: Page) -> None:
    results = Axe().run(routed_page, context={"include": ["#content"]}, **NO_REPORTS)

    assert _targets(results) == [["#ads > img"], ["#content > img"]]


def test_run_with_dict_context_exclude(routed_page: Page) -> None:
    results = Axe().run(routed_page, context={"exclude": ["#ads"]}, **NO_REPORTS)

    assert _targets(results) == sorted(
        [["#content > img"], ["#header > img"]] + IMAGE_ALT_IN_FRAMES)


def test_run_with_list_context(routed_page: Page) -> None:
    results = Axe().run(routed_page, context=["#header", "#ads"], **NO_REPORTS)

    assert _targets(results) == [["#ads > img"], ["#header > img"]]


def test_run_with_dict_context_from_frames(routed_page: Page) -> None:
    results = Axe().run(
        routed_page, context={"fromFrames": ["iframe[title=same]", "#only"]}, **NO_REPORTS)

    assert _targets(results) == [["iframe[title=\"same\"]", "#only > img"]]


def test_run_with_dict_context_excluding_an_element_in_a_frame(routed_page: Page) -> None:
    results = Axe().run(
        routed_page, context={"exclude": [["iframe[title=same]", "#only"]]}, **NO_REPORTS)

    assert _targets(results) == sorted(
        target for target in ALL_IMAGE_ALT if target != ["iframe[title=\"same\"]", "#only > img"])


def test_run_with_empty_context_and_options_scans_everything(routed_page: Page) -> None:
    results = Axe().run(routed_page, context={}, options={}, **NO_REPORTS)

    assert _targets(results) == ALL_IMAGE_ALT


def test_run_with_javascript_strings_is_still_supported(routed_page: Page) -> None:
    results = Axe().run(
        routed_page, context="document.getElementById('content')", options="{iframes: false}", **NO_REPORTS)

    assert _targets(results) == [["#ads > img"], ["#content > img"]]


# Where only one JavaScript string is provided, axe-core works out whether it is the context or the options,
# which is how a single string has always been handled

def test_run_with_only_a_context_string(routed_page: Page) -> None:
    results = Axe().run(routed_page, context="{include: ['#content']}", **NO_REPORTS)

    assert _targets(results) == [["#ads > img"], ["#content > img"]]


def test_run_with_only_an_options_string(routed_page: Page) -> None:
    results = Axe().run(routed_page, options=OPTIONS_WCAG_22AA, **NO_REPORTS)

    assert results["toolOptions"]["runOnly"]["type"] == "tag"
    assert _targets(results) == ALL_IMAGE_ALT


def test_run_with_options_provided_as_the_context(routed_page: Page) -> None:
    results = Axe().run(routed_page, context="{runOnly: ['image-alt']}", **NO_REPORTS)

    assert [violation["id"] for violation in results["violations"]] == ["image-alt"]
    assert sum(len(results[group]) for group in ["violations", "passes", "incomplete", "inapplicable"]) == 1


def test_run_with_context_provided_as_the_options(routed_page: Page) -> None:
    results = Axe().run(routed_page, options="{include: ['#content']}", **NO_REPORTS)

    assert _targets(results) == [["#ads > img"], ["#content > img"]]


def test_single_expression() -> None:
    assert Axe()._single_expression(" {a: 1} ", None) == "{a: 1}"
    assert Axe()._single_expression("", " {b: 2} ") == "{b: 2}"
    assert Axe()._single_expression("{a: 1}", "  ") == "{a: 1}"
    # Anything else is an explicit context and options, so is not interpreted
    assert Axe()._single_expression("{a: 1}", "{b: 2}") is None
    assert Axe()._single_expression("{a: 1}", {"b": 2}) is None
    assert Axe()._single_expression({"a": 1}, None) is None
    assert Axe()._single_expression(None, None) is None
    assert Axe()._single_expression("", "") is None


def test_run_does_not_modify_the_context_provided(routed_page: Page) -> None:
    locator = routed_page.locator("#content")
    context = {"include": [locator], "exclude": ["#ads"]}

    Axe().run(routed_page, context=context, **NO_REPORTS)

    assert context["include"][0] is locator
    assert context["exclude"] == ["#ads"]


def test_run_with_invalid_context_and_options(routed_page: Page) -> None:
    with pytest.raises(AxeAccessibilityException, match="context must be a str, dict, list, Locator or Frame"):
        Axe().run(routed_page, context=123, **NO_REPORTS)
    with pytest.raises(AxeAccessibilityException, match="context must be JSON serialisable"):
        Axe().run(routed_page, context={"include": [object()]}, **NO_REPORTS)
    with pytest.raises(AxeAccessibilityException, match="options must be a dict"):
        Axe().run(routed_page, options=["wcag2a"], **NO_REPORTS)


# Locators and frames as the context

def test_run_with_locator_context(routed_page: Page) -> None:
    results = Axe().run(routed_page, context=routed_page.locator("#content"), **NO_REPORTS)

    assert _targets(results) == [["#ads > img"], ["#content > img"]]


def test_run_with_locators_to_include_and_exclude(routed_page: Page) -> None:
    results = Axe().run(
        routed_page,
        context={"include": [routed_page.locator("#content")], "exclude": [routed_page.locator("#ads")]},
        **NO_REPORTS)

    assert _targets(results) == [["#content > img"]]


def test_run_with_single_locators_to_include_and_exclude(routed_page: Page) -> None:
    results = Axe().run(
        routed_page,
        context={"include": routed_page.locator("#content"), "exclude": routed_page.locator("#ads")},
        **NO_REPORTS)

    assert _targets(results) == [["#content > img"]]


def test_run_with_locator_matching_multiple_elements(routed_page: Page) -> None:
    results = Axe().run(routed_page, context=routed_page.locator("#header, #ads"), **NO_REPORTS)

    assert _targets(results) == [["#ads > img"], ["#header > img"]]


def test_run_with_list_of_locators_and_selectors(routed_page: Page) -> None:
    results = Axe().run(routed_page, context=[routed_page.locator("#header"), "#ads"], **NO_REPORTS)

    assert _targets(results) == [["#ads > img"], ["#header > img"]]


def test_run_with_locator_matching_nothing(routed_page: Page) -> None:
    with pytest.raises(AxeAccessibilityException, match="did not match any elements"):
        Axe().run(routed_page, context=routed_page.locator("#missing"), **NO_REPORTS)
    with pytest.raises(AxeAccessibilityException, match="did not match any elements"):
        Axe().run(routed_page, context={"include": [routed_page.locator("#missing")]}, **NO_REPORTS)


def test_run_with_excluded_locator_matching_nothing(routed_page: Page) -> None:
    results = Axe().run(routed_page, context={"exclude": [routed_page.locator("#missing")]}, **NO_REPORTS)

    assert _targets(results) == ALL_IMAGE_ALT


def test_run_with_locator_in_a_frame(routed_page: Page) -> None:
    locator = routed_page.frame_locator("iframe[title=same]").locator("#only")

    results = Axe().run(routed_page, context=locator, **NO_REPORTS)

    # The results are for the frame containing the locator, so the selectors are relative to it
    assert _targets(results) == [["#only > img"]]
    assert results["url"] == "http://top.test/frame"


def test_run_with_frame_context(routed_page: Page) -> None:
    frame = routed_page.frame(url="http://top.test/frame")

    results = Axe().run(routed_page, context=frame, **NO_REPORTS)

    assert _targets(results) == [["#inner > img"], ["#only > img"]]
    assert results["url"] == "http://top.test/frame"


def test_run_with_locators_in_different_frames(routed_page: Page) -> None:
    context = [routed_page.locator("#header"), routed_page.frame_locator("iframe[title=same]").locator("#only")]

    with pytest.raises(AxeAccessibilityException, match="must be in the same frame"):
        Axe().run(routed_page, context=context, **NO_REPORTS)


def test_run_with_excluded_locator_in_a_different_frame(routed_page: Page) -> None:
    context = {
        "include": [routed_page.locator("#content")],
        "exclude": [routed_page.frame_locator("iframe[title=same]").locator("#only")],
    }

    with pytest.raises(AxeAccessibilityException, match="must be in the frame being scanned"):
        Axe().run(routed_page, context=context, **NO_REPORTS)


@pytest.mark.parametrize("fails", [False, True])
def test_run_disposes_of_element_handles(routed_page: Page, monkeypatch: pytest.MonkeyPatch, fails: bool) -> None:
    disposed = []
    original_dispose = ElementHandle.dispose

    def spy_on_dispose(self: ElementHandle) -> None:
        disposed.append(self)
        original_dispose(self)

    monkeypatch.setattr(ElementHandle, "dispose", spy_on_dispose)

    if fails:
        # The elements are found before the problem with the frames is identified
        context = [routed_page.locator("#header"), routed_page.frame_locator("iframe[title=same]").locator("#only")]
        with pytest.raises(AxeAccessibilityException):
            Axe().run(routed_page, context=context, **NO_REPORTS)
        assert len(disposed) == 2
    else:
        Axe().run(
            routed_page,
            context={"include": [routed_page.locator("#content")], "exclude": [routed_page.locator("#ads")]},
            **NO_REPORTS)
        assert len(disposed) == 2


def test_run_list_with_dict_context_and_options(routed_page: Page) -> None:
    results = Axe().run_list(
        routed_page, ["http://top.test/"],
        context={"include": ["#content"]}, options={"iframes": False}, **NO_REPORTS)

    assert _targets(results["http://top.test/"]) == [["#ads > img"], ["#content > img"]]


# Configuration

def test_configure_with_dict_applies_to_every_frame(routed_page: Page) -> None:
    axe = Axe().configure(DISABLE_IMAGE_ALT)

    results = axe.run(routed_page, **NO_REPORTS)

    assert _targets(results) == []


def test_configure_applies_to_every_run_and_can_be_reset(routed_page: Page) -> None:
    axe = Axe().configure(DISABLE_IMAGE_ALT)

    # Axe is injected again for each run, which would otherwise discard the configuration
    assert _targets(axe.run(routed_page, **NO_REPORTS)) == []
    assert _targets(axe.run(routed_page, **NO_REPORTS)) == []

    assert axe.reset() is axe
    assert _targets(axe.run(routed_page, **NO_REPORTS)) == ALL_IMAGE_ALT


def test_configure_only_applies_to_that_instance(routed_page: Page) -> None:
    Axe().configure(DISABLE_IMAGE_ALT)

    assert _targets(Axe().run(routed_page, **NO_REPORTS)) == ALL_IMAGE_ALT


def test_configure_is_cumulative_and_applied_in_order(routed_page: Page) -> None:
    enable_image_alt = {"rules": [{"id": "image-alt", "enabled": True}]}

    # Whichever is applied last wins, so the order the calls were made in is what matters
    disabled_last = Axe().configure(enable_image_alt)
    assert disabled_last.configure(DISABLE_IMAGE_ALT) is disabled_last
    enabled_last = Axe().configure(DISABLE_IMAGE_ALT).configure(enable_image_alt)

    assert _targets(disabled_last.run(routed_page, **NO_REPORTS)) == []
    assert _targets(enabled_last.run(routed_page, **NO_REPORTS)) == ALL_IMAGE_ALT


def test_configure_with_javascript_string(routed_page: Page) -> None:
    # The comment checks that anything following the configuration cannot affect what is applied after it
    axe = Axe().configure("{rules: [{id: 'image-alt', enabled: false}]} // disable image-alt")

    assert _targets(axe.run(routed_page, **NO_REPORTS)) == []


def test_configure_with_a_custom_rule_using_a_function(routed_page: Page) -> None:
    axe = Axe().configure(CUSTOM_RULE_JS)

    results = axe.run(routed_page, options=ONLY_CUSTOM_RULE, **NO_REPORTS)

    # The rule has to be configured in the page and in every frame, as well as where the results are combined
    assert _targets(results, "h1-data-test") == [
        ["h1"],
        ["iframe[title=\"cross\"]", "h1"],
        ["iframe[title=\"same\"]", "h1"],
    ]
    violation = next(violation for violation in results["violations"] if violation["id"] == "h1-data-test")
    assert violation["help"] == "h1 needs data-test"
    assert violation["impact"] == "minor"


def test_configure_with_a_custom_reporter_function(routed_page: Page) -> None:
    # Functions are not carried over from the options to each frame, so configure() is how to provide one
    reporter = ("{reporter: function (raw, options, resolve) { axe.getReporter('v1')(raw, options, "
                "function (results) { results.custom = true; resolve(results); }); }}")

    results = Axe().configure(reporter).run(routed_page, **NO_REPORTS)

    assert results["custom"] is True
    assert _targets(results) == ALL_IMAGE_ALT


def test_configure_with_invalid_values() -> None:
    for invalid in [123, None, "", "   ", ["rules"]]:
        with pytest.raises(AxeAccessibilityException, match="config must be a dict"):
            Axe().configure(invalid)
    with pytest.raises(AxeAccessibilityException, match="config must be JSON serialisable"):
        Axe().configure({"rules": {1, 2}})


def test_get_rules_reflects_configuration(routed_page: Page) -> None:
    def image_alt_enabled(axe: Axe) -> bool:
        return next(rule for rule in axe.get_rules(routed_page, ["wcag2a"]) if rule["ruleId"] == "image-alt")["enabled"]

    assert image_alt_enabled(Axe()) is True
    assert image_alt_enabled(Axe().configure(DISABLE_IMAGE_ALT)) is False


def test_get_rules_with_tags(routed_page: Page) -> None:
    rules = Axe().get_rules(routed_page, ["wcag2a"])

    assert rules and all("wcag2a" in rule["tags"] for rule in rules)
    assert len(Axe().get_rules(routed_page)) > len(rules)
