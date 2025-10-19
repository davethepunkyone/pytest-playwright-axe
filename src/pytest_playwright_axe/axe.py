import logging
import os
import json
from html import escape
import re
from datetime import datetime
from playwright.sync_api import Page, Locator, expect
from pathlib import Path

logger = logging.getLogger(__name__)

RESOURCES_DIR = Path(__file__).parent / "resources"
AXE_PATH = RESOURCES_DIR / "axe.js"
MIN_AXE_PATH = RESOURCES_DIR / "axe.min.js"
DEFAULT_CSS_PATH = RESOURCES_DIR / "default.css"

DEFAULT_REPORT_PATH = Path(os.getcwd()) / "axe-reports"

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


class Axe:
    """
    This utility allows for interaction with axe-core, to allow for accessibility scanning of pages
    under test to identify any accessibility concerns.

    Args:
        output_directory (str | pathlib.Path): [Optional] The directory to output the reports to. If not provided, defaults to os.getcwd()/axe-reports directory.
        css_override (str): [Optional] If provided, overrides the default CSS used within the HTML report generated.
        use_minified_file (bool): [Optional] If true, use the minified axe-core file. If false (default), use the full axe-core file.
        snapshot_directory (str | pathlib.Path): [Optional] The directory to check for JSON snapshots from previous runs to compare against.
    """

    def __init__(self, 
                 output_directory: str | Path = DEFAULT_REPORT_PATH,
                 css_override: str = "", 
                 use_minified_file: bool = False,
                 snapshot_directory: str | Path = None) -> None:
        self.output_directory = output_directory
        self.css_override = css_override
        self.axe_path = MIN_AXE_PATH if use_minified_file else AXE_PATH
        self.snapshot_directory = snapshot_directory

    def run(self,
            page: Page,
            filename: str = "",
            context: str = "",
            options: str = "",
            report_on_violation_only: bool = False,
            strict_mode: bool = False,
            html_report_generated: bool = True,
            json_report_generated: bool = True) -> dict:
        """
        This runs axe-core against the page provided.

        Args:
            page (playwright.sync_api.Page): The page object to execute axe-core against.
            filename (str): [Optional] The filename to use for the outputted reports. If not provided, defaults to the URL under test.
            context (str): [Optional] If provided, a stringified JavaScript object to denote the context axe-core should use.
            options (str): [Optional] If provided, a stringified JavaScript object to denote the options axe-core should use.
            report_on_violation_only (bool): [Optional] If true, only generates an Axe report if a violation is detected. If false (default), always generate a report.
            strict_mode (bool): [Optional] If true, raise an exception if a violation is detected. If false (default), proceed with test execution.
            html_report_generated (bool): [Optional] If true (default), generates a html report for the page scanned. If false, no html report is generated.
            json_report_generated (bool): [Optional] If true (default), generates a json report for the page scanned. If false, no json report is generated.

        Returns:
            dict: A Python dictionary with the axe-core output of the page scanned.
        """

        page.evaluate(self.axe_path.read_text(encoding="UTF-8"))

        response = page.evaluate(
            "axe.run(" + self._build_run_command(context, options) + ").then(results => {return results;})")

        logger.info(f"""Axe scan summary of [{response["url"]}]: Passes = {len(response["passes"])},
                    Violations = {len(response["violations"])}, Inapplicable = {len(response["inapplicable"])},
                    Incomplete = {len(response["incomplete"])}""")

        violations_detected = len(response["violations"]) > 0
        if not report_on_violation_only or (report_on_violation_only and violations_detected):
            if html_report_generated:
                self._create_html_report(response, filename)
            if json_report_generated:
                self._create_json_report(response, filename)

        if violations_detected and strict_mode:
            raise AxeAccessibilityException(
                f"Axe Accessibility Violation detected on page: {response['url']}")

        return response

    def run_list(self,
                 page: Page,
                 page_list: list[str | dict],
                 use_list_for_filename: bool = True,
                 context: str = "",
                 options: str = "",
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
            context (str): [Optional] If provided, a stringified JavaScript object to denote the context axe-core should use.
            options (str): [Optional] If provided, a stringified JavaScript object to denote the options axe-core should use.
            report_on_violation_only (bool): [Optional] If true, only generates an Axe report if a violation is detected. If false (default), always generate a report.
            strict_mode (bool): [Optional] If true, raise an exception if a violation is detected. If false (default), proceed with test execution.
            html_report_generated (bool): [Optional] If true (default), generates a html report for the page scanned. If false, no html report is generated.
            json_report_generated (bool): [Optional] If true (default), generates a json report for the page scanned. If false, no json report is generated.

        Returns:
            dict: A Python dictionary with the axe-core output of all the pages scanned, with the page list used as the key for each report.
        
        For page_list, the following key/value pairs can be provided if using a dict:
            - url (str): The url to initially navigate to.
            - action (str): The action to undertake. Can be one of the following: "click", "dblclick", "hover", "fill", "type" or "select_option".
            - locator (playwright.sync_api.Locator): The locator for the element to interact with.
            - value (str): The value to use (if the action is "fill", "type" or "select_option").
            - assert_locator (playwright.sync_api.Locator): [Optional] The locator to do an assertion on.
            - assert_type (str): [Optional] The type of assertion to do against the locator. Can be one of the following: "to_be_visible", "to_be_hidden", "to_be_enabled", "to_contain_text" or "to_not_contain_text".
            - assert_value (str): [Optional] The value to assert (if the action is "to_contain_text" or "to_not_contain_text")
            - wait_time (int): [Optional] If specified, the amount of time to wait after completing the action in milliseconds.
        """

        results = {}
        for selected_page in page_list:
            if isinstance(selected_page, dict):
                page.goto(selected_page["url"])
                self._complete_pre_scan_actions(page, selected_page)
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
        This runs axe.getRules(), returning the specified rules (or all if no ruleset provided).

        Args:
            page (playwright.sync_api.Page): The page object to execute axe-core against.
            rules (list[str]): [Optional] A list of rules to return. If not provided, all rules are returned.
        
        Returns:
            list[dict]: A list of dictionaries containing the axe-core rules returned.
        """
        page.evaluate(self.axe_path.read_text(encoding="UTF-8"))

        return page.evaluate(
            f"axe.getRules({"" if rules is None else str(rules)});")

    def _check_pre_scan_actions(self, actions: dict) -> None:
        """This checks the pre-scan actions provided are valid and excepts if not."""

        if "action" not in actions or "locator" not in actions:
            raise AxeAccessibilityException("action and locator are required within each action dictionary provided.")

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

    def _build_run_command(self, context: str = "", options: str = "") -> str:
        """This builds the run command for axe-core based on the context and options provided."""
        if context and options:
            return f"{context}, {options}"

        return context or options

    def _modify_filename_for_report(self, filename_to_modify: str) -> str:
        """This determines the filename to use for generated files."""
        if not filename_to_modify:
            raise AxeAccessibilityException("Filename to modify cannot be empty")
        
        if filename_to_modify[-1] == "/":
            filename_to_modify = filename_to_modify[:-1]
        for item_to_remove in ["http://", "https://"]:
            filename_to_modify = filename_to_modify.replace(item_to_remove, "")
        filename_to_modify = re.sub(r'[^a-zA-Z0-9-_]', '_', filename_to_modify)

        return filename_to_modify

    def _create_path_for_report(self, filename: str) -> Path:
        """This creates the report path (if it doesn't exist) and returns the full path."""
        os.makedirs(self.output_directory, exist_ok=True)
        return Path(self.output_directory).joinpath(filename)

    def _create_json_report(self, data: dict, filename_override: str = "") -> None:
        """This creates a JSON report for the generated report data."""
        filename = f"{self._modify_filename_for_report(data["url"])}.json" if filename_override == "" else f"{filename_override}.json"
        full_path = self._create_path_for_report(filename)

        with open(full_path, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4)

        logger.info(f"JSON report generated: {full_path}")

    def _create_html_report(self, data: dict, filename_override: str = "") -> None:
        """This creates an HTML report for the generated report data."""
        filename = f"{self._modify_filename_for_report(data["url"])}.html" if filename_override == "" else f"{filename_override}.html"
        full_path = self._create_path_for_report(filename)

        with open(full_path, 'w', encoding='utf-8') as file:
            file.write(self._generate_html(data, filename.replace(".html", "")))

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
                                    <td>{escape(node['failureSummary']).replace("Fix any of the following:", "<strong>Fix any of the following:</strong><br />").replace("\n ", "<br /> &bullet;")}</td></tr>'''
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
        
        snapshot_path = Path(self.snapshot_directory).joinpath(f"{filename}.json")
        if not snapshot_path.exists():
            return None

        with open(snapshot_path) as file:
            return json.loads(file.read())

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
        html += self._generate_passed_section(data['passes'])

        # Incomplete Checks (Collapsible)
        html += self._generate_incomplete_section(data['incomplete'])

        # Inapplicable Checks (Collapsible)
        html += self._generate_inapplicable_section(data['inapplicable'])

        # Execution Details (Collapsible)
        html += self._generate_execution_details_section(data)

        # Close tags
        html += "</main></body></html>"

        return html


class AxeAccessibilityException(Exception):
    pass
