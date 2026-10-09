import logging
import os
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from html import escape
import re
from datetime import datetime
from typing import Any, Iterator
from playwright.sync_api import Page, Frame, Locator, ElementHandle, Error as PlaywrightError, expect
from pathlib import Path

logger = logging.getLogger(__name__)

RESOURCES_DIR = Path(__file__).parent.joinpath("resources")
AXE_PATH = RESOURCES_DIR.joinpath("axe.js")
MIN_AXE_PATH = RESOURCES_DIR.joinpath("axe.min.js")
DEFAULT_CSS_PATH = RESOURCES_DIR.joinpath("default.css")

DEFAULT_REPORT_PATH = Path(os.getcwd()).joinpath("axe-reports")

WCAG_KEYS = {
    'wcag2a': 'WCAG 2.0 (A)',
    'wcag2aa': 'WCAG 2.0 (AA)',
    'wcag2aaa': 'WCAG 2.0 (AAA)',
    'wcag21a': 'WCAG 2.1 (A)',
    'wcag21aa': 'WCAG 2.1 (AA)',
    'wcag22a': 'WCAG 2.2 (A)',
    'wcag22aa': 'WCAG 2.2 (AA)',
    'best-practice': 'Best Practice'
}

KEY_MAPPING = {
    "testEngine": "Test Engine",
    "testRunner": "Test Runner",
    "testEnvironment": "Test Environment",
    "toolOptions": "Tool Options",
    "timestamp": "Timestamp",
    "url": "URL",
}

WCAG_22AA_RULESET = ['wcag2a', 'wcag21a', 'wcag2aa',
                     'wcag21aa', 'wcag22a', 'wcag22aa', 'best-practice']
OPTIONS_WCAG_22AA = "{runOnly: {type: 'tag', values: " + \
    str(WCAG_22AA_RULESET) + "}}"

# The context and options accepted by Axe.run(). A string is treated as JavaScript (so can use anything
# available within the page), whereas anything else is sent to the page as JSON (or as the elements
# matched by a Locator).
ContextType = str | dict | list | Locator | Frame
OptionsType = str | dict

# axe-core is run in every frame separately (axe.runPartial) and the results are then combined
# (axe.finishRun), so frames are scanned regardless of their origin. The placeholders are replaced
# with the statement providing the context and options (see below), and with the statement applying
# any configuration provided using Axe.configure().
RUN_PARTIAL_SCRIPT = """async (args) => {
    %CONFIGURE%
    %ARGUMENTS%
    const frameContexts = axe.utils.getFrameContexts(context, options);
    const partial = await axe.runPartial(context, options);
    return { frameContexts, partial: JSON.stringify(partial), options };
}"""
ARGUMENTS_STATEMENT = """const context = (%CONTEXT%
    );
    const options = (%OPTIONS%
    );"""
# axe.run() accepts either the context or the options as its only argument, and works out which it has been
# given. A single JavaScript string passed to Axe.run() used to be handed over as is, so this keeps working.
SINGLE_ARGUMENT_STATEMENT = """const single = (%SINGLE%
    );
    const isContext = axe.utils.isContextSpec(single);
    const context = isContext ? single : document;
    const options = isContext ? {} : single;"""
FINISH_RUN_SCRIPT = """([partialResults, options]) => {
    %CONFIGURE%
    return axe.finishRun(partialResults.map(result => result === null ? null : JSON.parse(result)), options);
}"""
GET_RULES_SCRIPT = """(() => {
    %CONFIGURE%
    return axe.getRules(%TAGS%);
})()"""
FRAME_ELEMENT_SCRIPT = "(selector) => axe.utils.shadowSelect(selector)"

# How long to wait for a frame to be ready to run axe-core in. A frame whose navigation never completes (for
# example a stalled third-party iframe) cannot be scripted, and waiting on it would otherwise never end.
FRAME_READY_TIMEOUT_MS = 5000


def _fill_template(template: str, **values: str) -> str:
    """Replaces each %NAME% placeholder in a single pass, so any text being inserted is never re-processed."""
    return re.sub(r"%([A-Z]+)%", lambda match: values[match.group(1).lower()], template)


@dataclass
class _RunInputs:
    """What is needed to run axe-core, once the context and options provided have been resolved."""
    root_frame: Frame
    context_expression: str = "document"
    options_expression: str = "{}"
    single_expression: str | None = None
    script_args: dict | None = None
    handles: list[ElementHandle] = field(default_factory=list)


class Axe:
    """
    This utility allows for interaction with axe-core, to allow for accessibility scanning of pages
    under test to identify any accessibility concerns.

    Args:
        output_directory (str | pathlib.Path): [Optional] The directory to output the reports to. If not provided, defaults to os.getcwd()/axe-reports directory.
        css_override (str): [Optional] If provided, overrides the default CSS used within the HTML report generated.
        use_minified_file (bool): [Optional] If true, use the minified axe-core file. If false (default), use the full axe-core file.
        snapshot_directory (str | pathlib.Path): [Optional] The directory to check for JSON snapshots from previous runs to compare against.

    Example:
        ```
        # Default usage
        axe = Axe()
        # Custom output directory using minified file
        axe = Axe(output_directory="accessibility-results", use_minified_file=True)
        # Snapshot directory specified and custom CSS
        axe = Axe(
            snapshot_directory=Path(__file__).parent.joinpath("snapshots"), 
            css_override=Path(__file__).parent.joinpath("style.css")
        )
        ```
    """

    def __init__(self, 
                 output_directory: str | Path = DEFAULT_REPORT_PATH,
                 css_override: str = "", 
                 use_minified_file: bool = False,
                 snapshot_directory: str | Path = None) -> None:
        self.output_directory = Path(output_directory)
        self.css_override = css_override
        self.axe_path = MIN_AXE_PATH if use_minified_file else AXE_PATH
        self.snapshot_directory = Path(snapshot_directory) if snapshot_directory else None
        self._configurations: list[str] = []

    def configure(self, config: str | dict) -> "Axe":
        """
        This configures axe-core, using the same configuration as axe.configure() (e.g. to add custom rules and
        checks, change the rules and checks that are applied, or provide a locale).

        axe-core is injected into the page (and each of its frames) every time a scan is run, so the configuration
        is stored and then applied each time. It is cumulative: each call adds to any configuration already
        provided, in the order the calls were made, and applies to every scan completed by this Axe instance
        until reset() is used.

        Args:
            config (str | dict): The configuration to apply. A dict is sent as JSON, whereas a str is treated
                as JavaScript, which is needed if the configuration has to contain a function (e.g. to define
                a custom check).

        Returns:
            Axe: This Axe instance, so calls can be chained.

        Example:
            ```
            # Disable a rule for every scan
            axe = Axe()
            axe.configure({"rules": [{"id": "image-alt", "enabled": False}]})
            axe.run(page)

            # Chained, with a custom check that has to be written in JavaScript
            Axe().configure(
                "{checks: [{id: 'has-data-test', evaluate: function (node) { return node.hasAttribute('data-test'); }, "
                "metadata: {impact: 'minor', messages: {pass: 'Has it', fail: 'Missing data-test'}}}], "
                "rules: [{id: 'h1-data-test', selector: 'h1', any: ['has-data-test'], "
                "metadata: {description: 'h1 needs data-test', help: 'h1 needs data-test'}}]}"
            ).run(page)
            ```
        """
        if isinstance(config, str) and config.strip():
            self._configurations.append(config.strip())
        elif isinstance(config, dict):
            self._configurations.append(self._to_javascript(config, "config"))
        else:
            raise AxeAccessibilityException("config must be a dict, or a str containing a JavaScript object.")

        return self

    def reset(self) -> "Axe":
        """
        This removes all the configuration provided using configure(), so the default axe-core configuration is used.

        Returns:
            Axe: This Axe instance, so calls can be chained.
        """
        self._configurations.clear()
        return self

    def run(self,
            page: Page,
            filename: str = "",
            context: ContextType | None = None,
            options: OptionsType | None = None,
            report_on_violation_only: bool = False,
            strict_mode: bool = False,
            html_report_generated: bool = True,
            json_report_generated: bool = True) -> dict:
        """
        This runs axe-core against the page provided, including any iframes within the page (unless
        the axe-core `iframes` option is set to false).

        Frames are scanned by running axe-core in each frame separately and combining the results, so this
        also covers frames from a different origin. To do this, a temporary blank page is opened (in a separate
        browser context where possible) to combine the results, and is closed again afterwards.

        Args:
            page (playwright.sync_api.Page): The page object to execute axe-core against.
            filename (str): [Optional] The filename to use for the outputted reports. If not provided, defaults to the URL under test.
            context (str | dict | list | playwright.sync_api.Locator | playwright.sync_api.Frame): [Optional] If provided, the context axe-core should use. See below for the formats accepted.
            options (str | dict): [Optional] If provided, the options axe-core should use. A dict is sent as JSON, whereas a str is treated as JavaScript. A str is evaluated once in the page and the result sent to each frame, so any functions within it (e.g. a custom reporter) are not carried across: use configure() for those.
            report_on_violation_only (bool): [Optional] If true, only generates an Axe report if a violation is detected. If false (default), always generate a report.
            strict_mode (bool): [Optional] If true, raise an exception if a violation is detected. If false (default), proceed with test execution.
            html_report_generated (bool): [Optional] If true (default), generates a html report for the page scanned. If false, no html report is generated.
            json_report_generated (bool): [Optional] If true (default), generates a json report for the page scanned. If false, no json report is generated.

        For context, the following can be provided:

        - **dict / list**: A context in the same format as axe-core uses (e.g. {"include": ["main"], "exclude": [".ads"]}), sent as JSON.
          Playwright Locators can be used in "include" and "exclude" (or as the items in a list), and are replaced with the elements they match.
        - **playwright.sync_api.Locator**: Only the elements matched by the locator are scanned. An exception is raised if it matches nothing.
        - **playwright.sync_api.Frame**: Only that frame (and any frames within it) is scanned.
        - **str**: A JavaScript expression for the context (e.g. "{exclude: '.ad-banner'}", or "document.getElementById('content')").

        If Locators are used in "include" (or the context is a Locator), the frame containing them is the one scanned, and the
        locators must all be in the same frame. The same applies to a Frame: the results are for the frame scanned, so the
        selectors for any elements are relative to that frame. Any Locators in "exclude" must be in the frame being scanned.

        Returns:
            dict: A Python dictionary with the axe-core output of the page scanned. This is whatever the axe-core
                reporter used returns, so is a dict with the standard results (violations, passes, incomplete and
                inapplicable) unless a different reporter is used in the options (e.g. "no-passes" only
                returns the violations, and "raw" returns a list).

        The reporter used affects what else is done:

        - **"v1" (default), "v2" or "na"**: The summary, reports and strict_mode all work.
        - **"no-passes"**: These all work too, with the HTML report stating that the passes, incomplete and inapplicable checks are not included.
        - **"raw" or "rawEnv"**: The results are returned and strict_mode works, but there is no HTML report (a warning is logged) as it needs the standard results. The JSON report contains the raw results.
        - **A custom reporter**: If the results are not in one of the formats above, they are returned and the JSON report is generated, but strict_mode raises an exception as it cannot tell if there are any violations.
        
        Example:
            ```
            # Default usage
            def test_example(page: Page) -> None:
                axe = Axe()
                axe.run(page)

                # With no HTML or JSON reports, capture results in variable
                results = axe.run(
                    page, 
                    html_report_generated=False, 
                    json_report_generated=False
                )

                # Using dicts for the context and options
                axe.run(
                    page,
                    context={"include": ["main"], "exclude": [".ad-banner"]},
                    options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa"]}}
                )

                # Using Playwright Locators, to scan the main content but not the cookie banner
                axe.run(
                    page,
                    context={"include": [page.locator("main")], "exclude": [page.locator("#cookie-banner")]}
                )

                # Only scan the form within the #payment iframe
                axe.run(page, context={"fromFrames": ["iframe#payment", "form"]})

                # Skip scanning any iframes
                axe.run(page, options={"iframes": False})

                # JavaScript can still be used (as a str) where required
                axe.run(page, context="document.getElementById('content')")
            ```        
        """

        response = self._run_axe(
            page, self.axe_path.read_text(encoding="UTF-8"), context, options)

        url = self._get_url(response, page)
        self._log_summary(response, url)

        # If the results do not show whether there were any violations, reports are still generated
        violations_detected = self._has_violations(response)
        if not report_on_violation_only or violations_detected is not False:
            if html_report_generated:
                if self._is_standard_results(response):
                    self._create_html_report(response, filename)
                else:
                    logger.warning(
                        "An HTML report cannot be generated, as the results from the axe-core reporter used are not "
                        "in the standard format. Set html_report_generated=False to avoid this warning.")
            if json_report_generated:
                self._create_json_report(response, filename, url)

        if strict_mode:
            if violations_detected:
                raise AxeAccessibilityException(
                    f"Axe Accessibility Violation detected on page: {url}")
            if violations_detected is None:
                raise AxeAccessibilityException(
                    "strict_mode cannot be used with the axe-core reporter provided, as its results do not show "
                    "whether there are any violations.")

        return response

    def run_list(self,
                 page: Page,
                 page_list: list[str | dict],
                 use_list_for_filename: bool = True,
                 context: ContextType | None = None,
                 options: OptionsType | None = None,
                 report_on_violation_only: bool = False,
                 strict_mode: bool = False,
                 html_report_generated: bool = True,
                 json_report_generated: bool = True) -> dict:
        """
        This runs axe-core against a list of pages provided.

        NOTE: It is recommended to set a --base-url value when running Playwright using this functionality, so you only need to pass in a partial URL within the page_list.

        Args:
            page (playwright.sync_api.Page): The page object to execute axe-core against.
            page_list (list[str | dict]): A list of URLs to execute against. If a dict is provided, it can include actions and assertions to complete prior to scanning (see below for key/values to provide).
            use_list_for_filename (bool): If true, based filenames off the list provided. If false, use the full URL under test for the filename.
            context (str | dict | list | playwright.sync_api.Locator): [Optional] If provided, the context axe-core should use for every page (see run() for the formats accepted). A Frame is not suitable here, as it will no longer be valid once the page navigates.
            options (str | dict): [Optional] If provided, the options axe-core should use for every page. A dict is sent as JSON, whereas a str is treated as JavaScript.
            report_on_violation_only (bool): [Optional] If true, only generates an Axe report if a violation is detected. If false (default), always generate a report.
            strict_mode (bool): [Optional] If true, raise an exception if a violation is detected. If false (default), proceed with test execution.
            html_report_generated (bool): [Optional] If true (default), generates a html report for the page scanned. If false, no html report is generated.
            json_report_generated (bool): [Optional] If true (default), generates a json report for the page scanned. If false, no json report is generated.

        For page_list, the following key/value pairs can be provided if using a dict:

        - **url (str)**: The url to initially navigate to.
        - **action (str)**: The action to undertake. Can be one of the following: "click", "dblclick", "hover", "fill", "type" or "select_option".
        - **locator (playwright.sync_api.Locator)**: The locator for the element to interact with.
        - **value (str)**: The value to use (if the action is "fill", "type" or "select_option").
        - **assert_locator (playwright.sync_api.Locator)**: [Optional] The locator to do an assertion on.
        - **assert_type (str)**: [Optional] The type of assertion to do against the locator. Can be one of the following: "to_be_visible", "to_be_hidden", "to_be_enabled", "to_contain_text" or "to_not_contain_text".
        - **assert_value (str)**: [Optional] The value to assert (if the action is "to_contain_text" or "to_not_contain_text")
        - **wait_time (int)**: [Optional] If specified, the amount of time to wait after completing the action in milliseconds.

        Returns:
            dict: A Python dictionary with the axe-core output of all the pages scanned, with the page_list value used as the key for each report.
 
        Example:
            ```
            # --base-url set to: https://example.com
            def test_example(page: Page) -> None:
                # Default usage
                Axe().run_list(
                    page, 
                    ["/home", "/search"]
                )
                
                # Usage with page_list including str and dict
                page_list = [
                    "/home",
                    {
                        "url": "/search",
                        "action": "fill",
                        "locator": page.locator("#search-bar"),
                        "value": "test item",
                        "assert_locator": page.locator("#search-results-summary"),
                        "assert_type": "to_contain_text",
                        "assert_value": "1 of 1 results"
                    }
                ]
                axe = Axe()
                axe.run_list(page, page_list)
            ``` 
        """

        results = {}
        for selected_page in page_list:
            if isinstance(selected_page, dict):
                page.goto(selected_page["url"])
                self._complete_pre_scan_actions(page, selected_page)
                results_key = f"{selected_page["url"]}_{selected_page["action"]}"
                filename = self._modify_filename_for_report(
                    f"{selected_page["url"]}_{selected_page["action"]}") if use_list_for_filename else ""
            else:
                page.goto(selected_page)
                filename = self._modify_filename_for_report(
                    selected_page) if use_list_for_filename else ""
                results_key = selected_page
            
            results[results_key] = self.run(
                page,
                filename=filename,
                context=context,
                options=options,
                report_on_violation_only=report_on_violation_only,
                strict_mode=strict_mode,
                html_report_generated=html_report_generated,
                json_report_generated=json_report_generated
            )
        return results


    def get_rules(self, page: Page, rules: list[str] = None) -> list[dict]:
        """
        This runs axe.getRules(), returning the rules matching the tags specified (or all if no tags provided).
        Any configuration provided using configure() is applied first, so the rules returned reflect it.

        Args:
            page (playwright.sync_api.Page): The page object to execute axe-core against.
            rules (list[str]): [Optional] A list of axe-core tags (e.g. "wcag2a") to return the rules for. If not provided, all rules are returned.
        
        Returns:
            list[dict]: A list of dictionaries containing the axe-core rules returned.
        
        Example:
            ```
            # Standard usage
            axe = Axe()
            rules = axe.get_rules(page)
            # Get only the rules with specific tags
            rules = axe.get_rules(page, rules=["wcag2a", "wcag2aa"])
            ```
        """
        page.evaluate(self.axe_path.read_text(encoding="UTF-8"))

        return page.evaluate(_fill_template(
            GET_RULES_SCRIPT,
            configure=self._configure_statement(),
            tags="" if rules is None else json.dumps(rules)))

    def _check_pre_scan_actions(self, actions: dict) -> None:
        """This checks the pre-scan actions provided are valid and excepts if not."""

        if "action" not in actions or "locator" not in actions:
            raise AxeAccessibilityException("action and locator are required within each action dictionary provided.")

        if "value" in actions and not isinstance(actions["value"], str):
            raise AxeAccessibilityException("value must be a string.")

        if "value" not in actions and actions["action"] in ["fill", "type", "select_option"]:
            raise AxeAccessibilityException("value is required for this action type.")

        if not isinstance(actions["locator"], Locator):
            raise AxeAccessibilityException("locator must be a Playwright Locator object.")
        
        self._check_pre_scan_assertions(actions)

        if "wait_time" in actions and not isinstance(actions["wait_time"], int):
            raise AxeAccessibilityException("wait_time must be an integer representing milliseconds.")
        
    def _check_pre_scan_assertions(self, action: dict) -> None:
        """This checks the pre-scan assertions provided are valid and excepts if not."""
        if "assert_locator" in action and "assert_type" in action:

            if not isinstance(action["assert_locator"], Locator):
                raise AxeAccessibilityException("assert_locator must be a Playwright Locator object.")

            if "assert_value" not in action and action["assert_type"] in ["to_contain_text", "to_not_contain_text"]:
                raise AxeAccessibilityException("assert_value is required for this assert_type.")

    def _complete_pre_scan_actions(self, page: Page, actions: dict) -> None:
        """This completes any pre-scan actions provided.
        
        Action format: dict
        {
            "action": [action],
            "locator": [locator],
            "value": [value (if applicable)],
            "assert_locator": [assert_locator (if applicable)],
            "assert_type": [assert_type (if applicable)],
            "assert_value": [assert_value (if applicable)],
            "wait_time": [wait_time (if applicable)]
        }
        """
        self._check_pre_scan_actions(actions)

        locator: Locator = actions["locator"]

        match actions["action"]:
            case "click":
                locator.click()
            case "dblclick":
                locator.dblclick()
            case "hover":
                locator.hover()
            case "fill":
                locator.fill(actions["value"])
            case "type":
                locator.type(actions["value"])
            case "select_option":
                locator.select_option(actions["value"])
            case _:
                raise AxeAccessibilityException(f"Action type provided [{actions['action']}] is not supported.")

        if "assert_locator" in actions and "assert_type" in actions:
            
            assert_locator: Locator = actions["assert_locator"]

            match actions["assert_type"]:
                case "to_be_visible":
                    expect(assert_locator).to_be_visible()
                case "to_be_hidden":
                    expect(assert_locator).to_be_hidden()
                case "to_be_enabled":
                    expect(assert_locator).to_be_enabled()
                case "to_contain_text":
                    expect(assert_locator).to_contain_text(actions["assert_value"])
                case "to_not_contain_text":
                    expect(assert_locator).not_to_contain_text(actions["assert_value"])
                case _:
                    raise AxeAccessibilityException(f"Assert type provided [{actions['assert_type']}] is not supported.")

        if "wait_time" in actions and isinstance(actions["wait_time"], int):
            page.wait_for_timeout(actions["wait_time"])

    def _to_javascript(self, value: Any, name: str) -> str:
        """This converts a value to a JavaScript expression, as JSON is also valid JavaScript."""
        try:
            return json.dumps(value)
        except (TypeError, ValueError) as error:
            raise AxeAccessibilityException(f"{name} must be JSON serialisable: {error}") from error

    def _configure_statement(self) -> str:
        """This provides the JavaScript to apply any configuration provided using configure()."""
        if not self._configurations:
            return ""

        configurations = ",\n".join(f"({configuration}\n)" for configuration in self._configurations)
        return f"[{configurations}].forEach(configuration => axe.configure(configuration));"

    def _options_expression(self, options: OptionsType | None) -> str:
        """This provides the JavaScript expression to use for the options of an axe-core run."""
        if options is None:
            return "{}"
        if isinstance(options, str):
            return options.strip() or "{}"
        if isinstance(options, dict):
            return self._to_javascript(options, "options")

        raise AxeAccessibilityException(
            f"options must be a dict, or a str containing JavaScript, not {type(options).__name__}.")

    def _single_expression(self, context: ContextType | None, options: OptionsType | None) -> str | None:
        """
        This provides the JavaScript to use if only one of the context and options was provided, and as a str.

        axe-core works out whether it has been given the context or the options in this case, which is how a
        single str has always been handled, so it is still left to axe-core to decide.
        """
        def is_empty(value: Any) -> bool:
            return value is None or (isinstance(value, str) and not value.strip())

        if isinstance(context, str) and not is_empty(context) and is_empty(options):
            return context.strip()
        if isinstance(options, str) and not is_empty(options) and is_empty(context):
            return options.strip()

        return None

    def _prepare_run(self, page: Page, context: ContextType | None, options: OptionsType | None) -> _RunInputs:
        """This resolves the context and options provided into what is needed to run axe-core."""
        single_expression = self._single_expression(context, options)
        if single_expression:
            return _RunInputs(root_frame=page.main_frame, single_expression=single_expression)

        inputs = _RunInputs(root_frame=page.main_frame, options_expression=self._options_expression(options))

        try:
            self._resolve_context(inputs, context)
        except BaseException:
            self._dispose_handles(inputs.handles)
            raise

        return inputs

    def _resolve_context(self, inputs: _RunInputs, context: ContextType | None) -> None:
        """This updates the inputs for an axe-core run based on the context provided."""
        if isinstance(context, str):
            context = context.strip()

        if context is None or (isinstance(context, (str, dict, list)) and not context):
            return

        if isinstance(context, str):
            inputs.context_expression = context
        elif isinstance(context, Frame):
            inputs.root_frame = context
        elif isinstance(context, (Locator, dict, list)):
            include_frames: list[Frame] = []
            exclude_frames: list[Frame] = []
            resolved = self._replace_locators(context, inputs.handles, include_frames, exclude_frames)

            if include_frames:
                if any(frame != include_frames[0] for frame in include_frames):
                    raise AxeAccessibilityException("All Locators provided for the context must be in the same frame.")
                inputs.root_frame = include_frames[0]

            if any(frame != inputs.root_frame for frame in exclude_frames):
                raise AxeAccessibilityException(
                    "Any Locators provided to exclude must be in the frame being scanned.")

            if inputs.handles:
                inputs.context_expression = "args.context"
                inputs.script_args = {"context": resolved}
            else:
                inputs.context_expression = self._to_javascript(resolved, "context")
        else:
            raise AxeAccessibilityException(
                f"context must be a str, dict, list, Locator or Frame, not {type(context).__name__}.")

    def _replace_locators(self, context: Locator | dict | list, handles: list[ElementHandle],
                          include_frames: list[Frame], exclude_frames: list[Frame]) -> Any:
        """
        This replaces any Locators in the context with the elements they match.

        The elements found are added to handles (so they can be disposed of afterwards), and the frame they are in
        to include_frames or exclude_frames. A Locator to include must match at least one element, as otherwise a
        scan could pass simply because what was meant to be scanned could not be found.
        """
        def elements(locator: Locator, frames: list[Frame], required: bool) -> list[ElementHandle]:
            matched = locator.element_handles()
            handles.extend(matched)

            if not matched:
                if required:
                    raise AxeAccessibilityException("A Locator provided for the context did not match any elements.")
                return []

            frame = matched[0].owner_frame()
            if frame is None:
                raise AxeAccessibilityException("A Locator provided for the context is not attached to a frame.")
            frames.append(frame)
            return matched

        def replace(items: list, frames: list[Frame], required: bool) -> list:
            replaced = []
            for item in items:
                if isinstance(item, Locator):
                    replaced.extend(elements(item, frames, required))
                else:
                    replaced.append(item)
            return replaced

        if isinstance(context, Locator):
            return {"include": elements(context, include_frames, True)}
        if isinstance(context, list):
            return replace(context, include_frames, True)

        replaced_context = dict(context)
        for key, frames, required in (("include", include_frames, True), ("exclude", exclude_frames, False)):
            value = replaced_context.get(key)
            if isinstance(value, Locator):
                value = [value]
            if isinstance(value, list):
                replaced_context[key] = replace(value, frames, required)

        return replaced_context

    def _dispose_handles(self, handles: list[ElementHandle]) -> None:
        """This disposes of the element handles created for a run, ignoring any that are no longer available."""
        for handle in handles:
            try:
                handle.dispose()
            except PlaywrightError:
                pass

    def _build_partial_script(self, context_expression: str = "document", options_expression: str = "{}",
                              single_expression: str | None = None) -> str:
        """This builds the script that runs axe-core in a single frame."""
        if single_expression:
            arguments = _fill_template(SINGLE_ARGUMENT_STATEMENT, single=single_expression)
        else:
            arguments = _fill_template(
                ARGUMENTS_STATEMENT, context=context_expression, options=options_expression)

        return _fill_template(
            RUN_PARTIAL_SCRIPT, configure=self._configure_statement(), arguments=arguments)

    def _run_axe(self, page: Page, axe_source: str, context: ContextType | None,
                 options: OptionsType | None) -> dict:
        """This runs axe-core in the page and all of its frames, returning the combined results."""
        inputs = self._prepare_run(page, context, options)

        try:
            partial_results, evaluated_options = self._run_partial_in_frame(
                inputs.root_frame, axe_source,
                self._build_partial_script(
                    inputs.context_expression, inputs.options_expression, inputs.single_expression),
                inputs.script_args)

            # The results are combined in a blank page, so scripts within the page under test (or its frames)
            # cannot interfere with the data being passed between frames.
            with self._blank_page(page) as results_page:
                results_page.evaluate(axe_source)
                return results_page.evaluate(
                    _fill_template(FINISH_RUN_SCRIPT, configure=self._configure_statement()),
                    [partial_results, evaluated_options])
        finally:
            self._dispose_handles(inputs.handles)

    @contextmanager
    def _blank_page(self, page: Page) -> Iterator[Page]:
        """
        This provides a blank page to combine the results in, which is closed again afterwards.

        A separate browser context is used where possible, so nothing is added to the context under test (and
        as pages created using browser.new_page() cannot open another page in their context). If that is not
        possible (e.g. the context has no browser, which Playwright documents for persistent contexts, or the
        browser does not allow another context to be created) the blank page is opened within the existing
        context instead. As a last resort the page being scanned is used, so a scan can always complete.
        """
        browser = page.context.browser
        isolated_context = None
        blank_page = None

        if browser:
            try:
                isolated_context = browser.new_context()
                blank_page = isolated_context.new_page()
            except PlaywrightError as error:
                logger.debug(f"A separate browser context could not be used to combine the results: {error}")
                if isolated_context:
                    isolated_context.close()
                    isolated_context = None

        if blank_page is None:
            try:
                blank_page = page.context.new_page()
            except PlaywrightError as error:
                logger.debug(f"A blank page could not be opened to combine the results, so the page scanned is used: {error}")

        try:
            yield blank_page or page
        finally:
            if isolated_context:
                isolated_context.close()
            elif blank_page:
                blank_page.close()

    def _run_partial_in_frame(self, frame: Frame, axe_source: str, script: str,
                              script_args: dict | None = None) -> tuple[list[str | None], Any]:
        """
        This runs axe-core in a frame and then in each of the frames within it.

        Returns:
            tuple: The partial results (in the order axe.finishRun expects, with None for any frame that
                could not be scanned) and the options axe-core was run with.
        """
        # Evaluating within a frame that cannot be scripted (e.g. its navigation never completes) would
        # wait forever, so this fails after a timeout instead, which is then handled like any other
        # frame that cannot be scanned.
        frame.wait_for_function("() => true", polling=100, timeout=FRAME_READY_TIMEOUT_MS)
        frame.evaluate(axe_source)
        outcome = frame.evaluate(script, script_args)

        partial_results = [outcome["partial"]]
        for frame_details in outcome["frameContexts"]:
            partial_results.extend(self._run_partial_in_child_frame(
                frame, frame_details, axe_source, outcome["options"]))

        return partial_results, outcome["options"]

    def _run_partial_in_child_frame(self, parent_frame: Frame, frame_details: dict,
                                    axe_source: str, options: Any) -> list[str | None]:
        """
        This runs axe-core in a frame within the parent frame provided.

        If the frame cannot be scanned, a warning is logged and None is returned in place of its results
        (and the results of any frames within it), as axe.finishRun requires.
        """
        frame_selector = frame_details["frameSelector"]
        frame_handle = None

        try:
            frame_handle = parent_frame.evaluate_handle(FRAME_ELEMENT_SCRIPT, frame_selector)
            frame_element = frame_handle.as_element()
            child_frame = frame_element.content_frame() if frame_element else None

            if child_frame is not None:
                child_results, _ = self._run_partial_in_frame(
                    child_frame, axe_source, self._build_partial_script("args.context", "args.options"),
                    {"context": frame_details["frameContext"], "options": options})
                return child_results

            logger.warning(f"Frame [{frame_selector}] has no content available, so it has not been scanned.")
        except PlaywrightError as error:
            logger.warning(f"Frame [{frame_selector}] could not be scanned: {error}")
        finally:
            if frame_handle:
                frame_handle.dispose()

        return [None]

    def _get_url(self, response: Any, page: Page) -> str:
        """This provides the URL the results are for, which the standard results (and the environment details of rawEnv) contain."""
        if isinstance(response, dict):
            if isinstance(response.get("url"), str):
                return response["url"]
            environment = response.get("env")
            if isinstance(environment, dict) and isinstance(environment.get("url"), str):
                return environment["url"]

        return page.url

    def _is_standard_results(self, response: Any) -> bool:
        """
        This checks if the results have what the HTML report needs (the url, timestamp and violations), as the
        standard results do. The results for passes, incomplete and inapplicable checks are optional, as the
        "no-passes" reporter does not return them.
        """
        return (isinstance(response, dict)
                and isinstance(response.get("url"), str)
                and isinstance(response.get("timestamp"), str)
                and isinstance(response.get("violations"), list))

    def _has_violations(self, response: Any) -> bool | None:
        """
        This provides whether the results contain any violations, or None if their format is not recognised.

        This works for the standard results, and also for the raw results (as returned by the "raw" and "rawEnv"
        reporters), where each rule returned has its own list of violations.
        """
        if isinstance(response, dict):
            if isinstance(response.get("violations"), list):
                return len(response["violations"]) > 0
            response = response.get("raw")

        if isinstance(response, list) and all(
                isinstance(rule, dict) and isinstance(rule.get("violations"), list) for rule in response):
            return any(rule["violations"] for rule in response)

        return None

    def _log_summary(self, response: Any, url: str) -> None:
        """This logs a summary of the results, including the number of each type of result available."""
        groups = [("Passes", "passes"), ("Violations", "violations"),
                  ("Inapplicable", "inapplicable"), ("Incomplete", "incomplete")]
        counts = [f"- {label} = {len(response[key])}" for label, key in groups
                  if isinstance(response, dict) and isinstance(response.get(key), list)]

        if counts:
            logger.info(f"Axe scan summary of [{url}]:\n" + "\n".join(counts))
        else:
            logger.info(f"Axe scan of [{url}] complete, but its results are not in the standard format so cannot be summarised.")

    def _modify_filename_for_report(self, filename_to_modify: str) -> str:
        """This determines the filename to use for generated files."""
        if not filename_to_modify:
            raise AxeAccessibilityException("Filename to modify cannot be empty")
        
        filename_to_modify = filename_to_modify.rstrip("/")
        for item_to_remove in ["http://", "https://"]:
            filename_to_modify = filename_to_modify.replace(item_to_remove, "")
        filename_to_modify = re.sub(r'[^a-zA-Z0-9-_]', '_', filename_to_modify)

        return filename_to_modify

    def _create_path_for_report(self, filename: str) -> Path:
        """This creates the report path (if it doesn't exist) and returns the full path."""
        self.output_directory.mkdir(parents=True, exist_ok=True)
        return self.output_directory.joinpath(filename)

    def _create_json_report(self, data: Any, filename_override: str = "", url: str | None = None) -> None:
        """
        This creates a JSON report for the generated report data.

        The URL is used for the filename if no override is provided, and defaults to the one in the data (which
        is not available in every format of results).
        """
        try:
            content = json.dumps(data, indent=4)
        except (TypeError, ValueError) as error:
            logger.warning(f"A JSON report cannot be generated, as the results are not JSON serialisable: {error}")
            return

        filename = f"{self._modify_filename_for_report(url or data["url"])}.json" if filename_override == "" else f"{filename_override}.json"
        full_path = self._create_path_for_report(filename)

        with open(full_path, 'w', encoding='utf-8') as file:
            file.write(content)

        logger.info(f"JSON report generated: {full_path}")

    def _create_html_report(self, data: dict, filename_override: str = "") -> None:
        """This creates an HTML report for the generated report data."""
        filename = f"{self._modify_filename_for_report(data["url"])}.html" if filename_override == "" else f"{filename_override}.html"
        full_path = self._create_path_for_report(filename)
        content = self._generate_html(data, filename.replace(".html", ""))

        with open(full_path, 'w', encoding='utf-8') as file:
            file.write(content)

        logger.info(f"HTML report generated: {full_path}")

    def _css_styling(self) -> str:
        """This provides the CSS styling for the HTML report, or overrides if CSS provided."""
        if self.css_override:
            return f"<style>{self.css_override}</style>"

        return f"<style>{DEFAULT_CSS_PATH.read_text(encoding='UTF-8')}</style>"


    def _wcag_tagging(self, tags: list[str]) -> str:
        """Convert axe-core tags to human-readable WCAG tags."""
        wcag_tags = []
        for tag in tags:
            if tag in WCAG_KEYS:
                wcag_tags.append(WCAG_KEYS[tag])
        return ", ".join(wcag_tags)


    def _generate_table_header(self, headers: list[tuple[str, str, bool]]) -> str:
        """Generate the header row for tables in the standard format."""
        html = ""
        for header in headers:
            html += f'<th style="{"text-align: center; " if header[2] else ""}width: {header[1]}%">{header[0]}</th>'

        return html


    def _failure_summary(self, node: dict) -> str:
        """
        This provides the summary of how to fix an element, which only the "v1" reporter includes. If it is
        not provided, it is built from the checks for the element in the same way axe-core does.
        """
        if "failureSummary" in node:
            return node["failureSummary"]

        def summarise(title: str, checks: list[dict]) -> str:
            messages = (str(check.get("message") or "").replace("\n", "\n  ") for check in checks)
            return title + "".join(f"\n  {message}" for message in messages)

        sections = []
        checks_to_fix_all = list(node.get("none", [])) + list(node.get("all", []))
        if checks_to_fix_all:
            sections.append(summarise("Fix all of the following:", checks_to_fix_all))
        if node.get("any"):
            sections.append(summarise("Fix any of the following:", node["any"]))

        return "\n\n".join(sections)

    def _generate_violations_section(self, violations_data: list) -> str:
        """Generate the violations section of the HTML report."""

        html = "<h2>Violations Found</h2>"

        if len(violations_data) == 0:
            return f"{html}<p>No violations found.</p>"

        html += f"<p>{len(violations_data)} violations found.</p>"

        list_of_headers = [
            ("#", "2", True), ("Description", "53", False),
            ("Axe Rule ID", "15", False), ("WCAG", "15", False),
            ("Impact", "10", False), ("Count", "5", True)
        ]

        html += f"<table><tr>{self._generate_table_header(list_of_headers)}"

        violation_count = 1
        violation_section = ""
        for violation in violations_data:
            violations_table = ""

            html += f'''<tr>
                    <td style="text-align: center;">{violation_count}</td>
                    <td>{escape(violation['description'])}</td>
                    <td><a href="{violation['helpUrl']}" target="_blank">{violation['id']}</a></td>
                    <td>{self._wcag_tagging(violation['tags'])}</td>
                    <td>{violation['impact']}</td>
                    <td style="text-align: center;">{len(violation['nodes'])}</td>
                    </tr>'''

            violation_count += 1

            node_count = 1
            violations_table += f"<table><tr>{self._generate_table_header([
                ("#", "2", True), ("Description", "49", False), 
                ("Fix Information", "49", False)
            ])}"

            for node in violation['nodes']:
                violations_table += f'''<tr><td style="text-align: center;">{node_count}</td>
                                    <td><p>Element Location:</p>
                                    <pre><code>{escape("<br>".join(node['target']))}</code></pre>
                                    <p>HTML:</p><pre><code>{escape(node['html'])}</code></pre></td>
                                    <td>{escape(self._failure_summary(node)).replace("Fix any of the following:", "<strong>Fix any of the following:</strong><br />").replace("\n ", "<br /> &bullet;")}</td></tr>'''
                node_count += 1
            violations_table += "</table>"

            violation_section += f'''<table><tr><td style="width: 100%"><h3>{escape(violation['description'])}</h3>
                                <p><strong>Axe Rule ID:</strong> <a href="{violation['helpUrl']}" target="_blank">{violation['id']}</a><br />
                                <strong>WCAG:</strong> {self._wcag_tagging(violation['tags'])}<br />
                                <strong>Impact:</strong> {violation['impact']}<br />
                                <strong>Tags:</strong> {", ".join(violation['tags'])}</p>
                                {violations_table}
                                </td></tr></table>'''

        return f"{html}</table>{violation_section}"

    def _generate_passed_section(self, passed_data: list) -> str:
        """Generate the passed section of the HTML report."""

        html = "<h2>Passed Checks</h2>"

        if len(passed_data) == 0:
            return f"{html}<p>No passed checks found.</p>"

        html += f"<table><tr>{self._generate_table_header([
            ("#", "2", True), ("Description", "50", False),
            ("Axe Rule ID", "15", False), ("WCAG", "18", False),
            ("Nodes Passed Count", "15", True)
        ])}"

        pass_count = 1
        for passed in passed_data:

            html += f'''<tr>
                    <td style="text-align: center;">{pass_count}</td>
                    <td>{escape(passed['description'])}</td>
                    <td><a href="{passed['helpUrl']}" target="_blank">{passed['id']}</a></td>
                    <td>{self._wcag_tagging(passed['tags'])}</td>
                    <td style="text-align: center;">{len(passed['nodes'])}</td>
                    </tr>'''

            pass_count += 1

        return f"{html}</table>"

    def _generate_incomplete_section(self, incomplete_data: list) -> str:
        """Generate the incomplete section of the HTML report."""

        html = "<h2>Incomplete Checks</h2>"

        if len(incomplete_data) == 0:
            return f"{html}<p>No incomplete checks found.</p>"

        html += f"<table><tr>{self._generate_table_header([
            ("#", "2", True), ("Description", "50", False),
            ("Axe Rule ID", "15", False), ("WCAG", "18", False),
            ("Nodes Incomplete Count", "15", True)
        ])}"

        incomplete_count = 1
        for incomplete in incomplete_data:

            html += f'''<tr>
                    <td style="text-align: center;">{incomplete_count}</td>
                    <td>{escape(incomplete['description'])}</td>
                    <td><a href="{incomplete['helpUrl']}" target="_blank">{incomplete['id']}</a></td>
                    <td>{self._wcag_tagging(incomplete['tags'])}</td>
                    <td style="text-align: center;">{len(incomplete['nodes'])}</td>
                    </tr>'''

            incomplete_count += 1

        return f"{html}</table>"

    def _generate_inapplicable_section(self, inapplicable_data: list) -> str:
        """This method generates the inapplicable section of the HTML report."""

        html = "<h2>Inapplicable Checks</h2>"

        if len(inapplicable_data) == 0:
            return f"{html}<p>No inapplicable checks found.</p>"

        html += f"<table><tr>{self._generate_table_header([
            ("#", "2", True), ("Description", "60", False),
            ("Axe Rule ID", "20", False), ("WCAG", "18", False)
        ])}"

        inapplicable_count = 1
        for inapplicable in inapplicable_data:

            html += f'''<tr>
                    <td style="text-align: center;">{inapplicable_count}</td>
                    <td>{escape(inapplicable['description'])}</td>
                    <td><a href="{inapplicable['helpUrl']}" target="_blank">{inapplicable['id']}</a></td>
                    <td>{self._wcag_tagging(inapplicable['tags'])}</td>
                    </tr>'''

            inapplicable_count += 1

        return f"{html}</table>"

    def _generate_not_included_section(self, title: str) -> str:
        """This generates a section of the HTML report for results that the axe-core reporter used does not return."""
        return f"<h2>{title}</h2><p>Not included, as the axe-core reporter used does not return these results.</p>"

    def _generate_execution_details_section(self, data: dict) -> str:
        """Generate the execution details section of the HTML report."""

        html = "<h2>Execution Details</h2>"

        html += f"<table><tr>{self._generate_table_header([
            ("Data", "20", False), ("Details", "80", False)
        ])}"

        for key in ["testEngine", "testRunner", "testEnvironment", "toolOptions", "timestamp", "url"]:
            if key in data:
                html += f"<tr><td>{KEY_MAPPING[key]}</td>"
                if isinstance(data[key], dict):
                    sub_data = ""
                    for sub_key in data[key]:
                        sub_data += f"{sub_key}: <i>{escape(str(data[key][sub_key]))}</i><br />"
                    html += f"<td>{sub_data}</td></tr>"
                else:
                    html += f"<td>{escape(str(data[key]))}</td></tr>"

        return f"{html}</table>"
    
    def _get_snapshot_data(self, filename: str) -> dict | None:
        """This retrieves the data from a previous snapshot ready for comparison."""
        if not self.snapshot_directory:
            return None
        
        snapshot_path = self.snapshot_directory.joinpath(f"{filename}.json")
        if not snapshot_path.exists():
            return None

        try:
            with open(snapshot_path, encoding='utf-8') as file:
                snapshot_data = json.loads(file.read())
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse snapshot file {snapshot_path}: {e}")
            return None

        # Snapshots are compared using their violations, which the results from the "raw" reporters do not have
        if not isinstance(snapshot_data, dict) or not isinstance(snapshot_data.get("violations"), list):
            logger.warning(
                f"Snapshot file {snapshot_path} does not contain the violations needed for a comparison (it needs "
                "to be the standard results, or those from the \"no-passes\" reporter), so has not been used.")
            return None

        return snapshot_data

    def _generate_changes_section(self, data: dict, snapshot_data: dict | None) -> str:
        """Generate the changes section of the HTML report comparing current data with snapshot."""
        
        if not snapshot_data:
            return ""
        
        snapshot_timestamp = datetime.strptime(snapshot_data["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%d %H:%M")
        
        html = f"""<section class="changes-section">
        <h2>Changes Since Last Scan</h2>
        <p><strong>Comparison:</strong> This report has been compared against a snapshot taken on <strong>{snapshot_timestamp}</strong>.</p>"""
        
        changes = self._collect_all_changes(data, snapshot_data)
        
        if not changes:
            return html + "<p><strong>No changes detected</strong> - All violations remain the same as the previous scan.</p></section>"
        
        html += f"<p><strong>{len(changes)} change(s) detected:</strong></p>"
        html += self._generate_changes_table(changes)
        html += "</section>"
        
        return html

    def _collect_all_changes(self, data: dict, snapshot_data: dict) -> list[dict]:
        """Collect all changes between current and snapshot data."""
        current_violations = {v['id']: v for v in data['violations']}
        snapshot_violations = {v['id']: v for v in snapshot_data['violations']}
        
        changes = []
        changes.extend(self._find_new_violations(current_violations, snapshot_violations))
        changes.extend(self._find_resolved_violations(current_violations, snapshot_violations))
        changes.extend(self._find_count_changes(current_violations, snapshot_violations))
        
        return changes

    def _find_new_violations(self, current_violations: dict, snapshot_violations: dict) -> list[dict]:
        """Find violations that are new in the current scan."""
        new_violations = []
        
        for violation_id, violation in current_violations.items():
            if violation_id not in snapshot_violations:
                new_violations.append({
                    'type': 'New Violation',
                    'rule_id': violation_id,
                    'description': violation['description'],
                    'impact': violation['impact'],
                    'current_count': len(violation['nodes']),
                    'previous_count': 0,
                    'change': len(violation['nodes']),
                    'wcag': self._wcag_tagging(violation['tags']),
                    'status_class': 'new-violation'
                })
        
        return new_violations

    def _find_resolved_violations(self, current_violations: dict, snapshot_violations: dict) -> list[dict]:
        """Find violations that have been resolved since the snapshot."""
        resolved_violations = []
        
        for violation_id, violation in snapshot_violations.items():
            if violation_id not in current_violations:
                resolved_violations.append({
                    'type': 'Resolved Violation',
                    'rule_id': violation_id,
                    'description': violation['description'],
                    'impact': violation['impact'],
                    'current_count': 0,
                    'previous_count': len(violation['nodes']),
                    'change': -len(violation['nodes']),
                    'wcag': self._wcag_tagging(violation['tags']),
                    'status_class': 'resolved-violation'
                })
        
        return resolved_violations

    def _find_count_changes(self, current_violations: dict, snapshot_violations: dict) -> list[dict]:
        """Find violations where the count has changed."""
        count_changes = []
        
        for violation_id, current_violation in current_violations.items():
            if violation_id in snapshot_violations:
                current_count = len(current_violation['nodes'])
                previous_count = len(snapshot_violations[violation_id]['nodes'])
                
                if current_count != previous_count:
                    change_type = 'Increased Count' if current_count > previous_count else 'Decreased Count'
                    status_class = 'increased-count' if current_count > previous_count else 'decreased-count'
                    
                    count_changes.append({
                        'type': change_type,
                        'rule_id': violation_id,
                        'description': current_violation['description'],
                        'impact': current_violation['impact'],
                        'current_count': current_count,
                        'previous_count': previous_count,
                        'change': current_count - previous_count,
                        'wcag': self._wcag_tagging(current_violation['tags']),
                        'status_class': status_class
                    })
        
        return count_changes

    def _generate_changes_table(self, changes: list[dict]) -> str:
        """Generate the HTML table for displaying changes."""
        html = f"""<table class="changes-table">
        <tr>{self._generate_table_header([
            ("Change Type", "15", False),
            ("Rule ID", "15", False), 
            ("Description", "35", False),
            ("WCAG", "15", False),
            ("Impact", "8", False),
            ("Previous", "4", True),
            ("Current", "4", True),
            ("Δ", "4", True)
        ])}</tr>"""
        
        # Sort changes by priority
        type_priority = {'New Violation': 1, 'Increased Count': 2, 'Decreased Count': 3, 'Resolved Violation': 4}
        changes.sort(key=lambda x: type_priority.get(x['type'], 5))
        
        for change in changes:
            html += self._generate_change_row(change)
        
        return html + "</table>"

    def _generate_change_row(self, change: dict) -> str:
        """Generate a single row for the changes table."""
        change_indicator = f"+{change['change']}" if change['change'] > 0 else str(change['change'])
        row_class = f"class=\"{change['status_class']}\""
        
        return f"""<tr {row_class}>
        <td><strong>{change['type']}</strong></td>
        <td><a href="#violation-{change['rule_id']}" title="Jump to violation details">{change['rule_id']}</a></td>
        <td>{escape(change['description'])}</td>
        <td>{change['wcag']}</td>
        <td>{change['impact']}</td>
        <td style="text-align: center;">{change['previous_count']}</td>
        <td style="text-align: center;">{change['current_count']}</td>
        <td style="text-align: center;"><strong>{change_indicator}</strong></td>
        </tr>"""

    def _generate_html(self, data: dict, filename: str) -> str:
        """This generates the full HTML report based on the data provided."""

        snapshot_data = self._get_snapshot_data(filename)

        # HTML header
        html = f'<!DOCTYPE html><html lang="en"><head>{self._css_styling()}<title>Axe Accessibility Report</title></head><body>'

        # HTML body
        # Title and URL
        html += '<header role="banner"><h1>Axe Accessibility Report</h1>'
        html += f"""<p>This is an axe-core accessibility summary generated on
                    {datetime.strptime(data["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%d %H:%M")}
                    for: <strong>{data['url']}</strong></p></header><main role="main">"""

        # Changes
        html += self._generate_changes_section(data, snapshot_data)

        # Violations
        # Summary
        html += self._generate_violations_section(data['violations'])

        # Passed Checks (Collapsible)
        html += self._generate_passed_section(data['passes']) if 'passes' in data \
            else self._generate_not_included_section("Passed Checks")

        # Incomplete Checks (Collapsible)
        html += self._generate_incomplete_section(data['incomplete']) if 'incomplete' in data \
            else self._generate_not_included_section("Incomplete Checks")

        # Inapplicable Checks (Collapsible)
        html += self._generate_inapplicable_section(data['inapplicable']) if 'inapplicable' in data \
            else self._generate_not_included_section("Inapplicable Checks")

        # Execution Details (Collapsible)
        html += self._generate_execution_details_section(data)

        # Close tags
        html += "</main></body></html>"

        return html


class AxeAccessibilityException(Exception):
    pass
