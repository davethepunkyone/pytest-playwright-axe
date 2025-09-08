import logging
import os
import json
from html import escape
import re
from datetime import datetime
from playwright.sync_api import Page
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
        output_directory (str): [Optional] The directory to output the reports to. If not provided, defaults to os.getcwd()/axe-reports directory.
        css_override (str): [Optional] If provided, overrides the default CSS used within the HTML report generated.
        use_minified_file (bool): [Optional] If true, use the minified axe-core file. If false (default), use the full axe-core file.
    """

    def __init__(self, 
                 output_directory: str | Path = DEFAULT_REPORT_PATH,
                 css_override: str = "", 
                 use_minified_file: bool = False) -> None:
        self.output_directory = output_directory
        self.css_override = css_override
        self.axe_path = MIN_AXE_PATH if use_minified_file else AXE_PATH

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
                 page_list: list[str],
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
            page_list (list[playwright.sync_api.Page): A list of URLs to execute against.
            use_list_for_filename (bool): If true, based filenames off the list provided. If false, use the full URL under test for the filename.
            context (str): [Optional] If provided, a stringified JavaScript object to denote the context axe-core should use.
            options (str): [Optional] If provided, a stringified JavaScript object to denote the options axe-core should use.
            report_on_violation_only (bool): [Optional] If true, only generates an Axe report if a violation is detected. If false (default), always generate a report.
            strict_mode (bool): [Optional] If true, raise an exception if a violation is detected. If false (default), proceed with test execution.
            html_report_generated (bool): [Optional] If true (default), generates a html report for the page scanned. If false, no html report is generated.
            json_report_generated (bool): [Optional] If true (default), generates a json report for the page scanned. If false, no json report is generated.

        Returns:
            dict: A Python dictionary with the axe-core output of all the pages scanned, with the page list used as the key for each report.
        """
        results = {}
        for selected_page in page_list:
            page.goto(selected_page)
            filename = self._modify_filename_for_report(
                selected_page) if use_list_for_filename else ""
            results[selected_page] = self.run(
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
            file.write(self._generate_html(data))

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

        html += f"<table><tr>{self._generate_table_header([
            ("#", "2", True), ("Description", "53", False),
            ("Axe Rule ID", "15", False), ("WCAG", "15", False),
            ("Impact", "10", False), ("Count", "5", True)
        ])}"

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

    def _generate_html(self, data: dict) -> str:
        """This generates the full HTML report based on the data provided."""

        # HTML header
        html = f'<!DOCTYPE html><html lang="en"><head>{self._css_styling()}<title>Axe Accessibility Report</title></head><body>'

        # HTML body
        # Title and URL
        html += '<header role="banner"><h1>Axe Accessibility Report</h1>'
        html += f"""<p>This is an axe-core accessibility summary generated on
                    {datetime.strptime(data["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%d %H:%M")}
                    for: <strong>{data['url']}</strong></p></header><main role="main">"""

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
