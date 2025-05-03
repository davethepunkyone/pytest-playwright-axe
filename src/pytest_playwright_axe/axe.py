import logging
import os
import json
from html import escape
import re
from datetime import datetime
from playwright.sync_api import Page
from pathlib import Path

logger = logging.getLogger(__name__)
AXE_PATH = Path(__file__).parent / "resources" / "axe.js"
MIN_AXE_PATH = Path(__file__).parent / "resources" / "axe.min.js"
PATH_FOR_REPORT = Path(os.getcwd()) / "axe-reports"

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
    """

    @staticmethod
    def run(page: Page,
            filename: str = "",
            output_directory: str = PATH_FOR_REPORT,
            context: str = "",
            options: str = "",
            report_on_violation_only: bool = False,
            strict_mode: bool = False,
            html_report_generated: bool = True,
            json_report_generated: bool = True,
            use_minified_file: bool = False) -> dict:
        """
        This runs axe-core against the page provided.

        Args:
            page (playwright.sync_api.Page): The page object to execute axe-core against.
            filename (str): [Optional] The filename to use for the outputted reports. If not provided, defaults to the URL under test.
            output_directory (str): [Optional] The directory to output the reports to. If not provided, defaults to /axe-reports directory.
            context (str): [Optional] If provided, a stringified JavaScript object to denote the context axe-core should use.
            options (str): [Optional] If provided, a stringified JavaScript object to denote the options axe-core should use.
            report_on_violation_only (bool): [Optional] If true, only generates an Axe report if a violation is detected. If false (default), always generate a report.
            strict_mode (bool): [Optional] If true, raise an exception if a violation is detected. If false (default), proceed with test execution.
            html_report_generated (bool): [Optional] If true (default), generates a html report for the page scanned. If false, no html report is generated.
            json_report_generated (bool): [Optional] If true (default), generates a json report for the page scanned. If false, no json report is generated.
            use_minified_file (bool): [Optional] If true, use the minified axe-core file. If false (default), use the full axe-core file.

        Returns:
            dict: A Python dictionary with the axe-core output of the page scanned.
        """
        
        axe_path = MIN_AXE_PATH if use_minified_file else AXE_PATH
        page.evaluate(axe_path.read_text(encoding="UTF-8"))

        response = page.evaluate(
            "axe.run(" + Axe._build_run_command(context, options) + ").then(results => {return results;})")

        logger.info(f"""Axe scan summary of [{response["url"]}]: Passes = {len(response["passes"])},
                    Violations = {len(response["violations"])}, Inapplicable = {len(response["inapplicable"])},
                    Incomplete = {len(response["incomplete"])}""")

        violations_detected = len(response["violations"]) > 0
        if not report_on_violation_only or (report_on_violation_only and violations_detected):
            if html_report_generated:
                Axe._create_html_report(response, output_directory, filename)
            if json_report_generated:
                Axe._create_json_report(response, output_directory, filename)

        if violations_detected and strict_mode:
            raise AxeAccessibilityException(
                f"Axe Accessibility Violation detected on page: {response["url"]}")

        return response

    @staticmethod
    def run_list(page: Page,
                 page_list: list[str],
                 use_list_for_filename: bool = True,
                 output_directory: str = PATH_FOR_REPORT,
                 context: str = "",
                 options: str = "",
                 report_on_violation_only: bool = False,
                 strict_mode: bool = False,
                 html_report_generated: bool = True,
                 json_report_generated: bool = True,
                 use_minified_file: bool = False) -> dict:
        """
        This runs axe-core against a list of pages provided.

        NOTE: It is recommended to set a --base-url value when running Playwright using this functionality, so you only need to pass in a partial URL within the page_list.

        Args:
            page (playwright.sync_api.Page): The page object to execute axe-core against.
            page_list (list[playwright.sync_api.Page): A list of URLs to execute against.
            use_list_for_filename (bool): If true, based filenames off the list provided. If false, use the full URL under test for the filename.
            output_directory (str): [Optional] The directory to output the reports to. If not provided, defaults to /axe-reports directory.
            context (str): [Optional] If provided, a stringified JavaScript object to denote the context axe-core should use.
            options (str): [Optional] If provided, a stringified JavaScript object to denote the options axe-core should use.
            report_on_violation_only (bool): [Optional] If true, only generates an Axe report if a violation is detected. If false (default), always generate a report.
            strict_mode (bool): [Optional] If true, raise an exception if a violation is detected. If false (default), proceed with test execution.
            html_report_generated (bool): [Optional] If true (default), generates a html report for the page scanned. If false, no html report is generated.
            json_report_generated (bool): [Optional] If true (default), generates a json report for the page scanned. If false, no json report is generated.
            use_minified_file (bool): [Optional] If true, use the minified axe-core file. If false (default), use the full axe-core file.

        Returns:
            dict: A Python dictionary with the axe-core output of all the pages scanned, with the page list used as the key for each report.
        """
        results = {}
        for selected_page in page_list:
            page.goto(selected_page)
            filename = Axe._modify_filename_for_report(
                selected_page) if use_list_for_filename else ""
            results[selected_page] = Axe.run(
                page,
                filename=filename,
                output_directory=output_directory,
                context=context,
                options=options,
                report_on_violation_only=report_on_violation_only,
                strict_mode=strict_mode,
                html_report_generated=html_report_generated,
                json_report_generated=json_report_generated,
                use_minified_file=use_minified_file
            )
        return results

    @staticmethod
    def _build_run_command(context: str = "", options: str = "") -> str:
        return_str = context if len(context) > 0 else ""
        return_str += ", " if len(return_str) > 0 and len(options) > 0 else ""
        return_str += options if len(options) > 0 else ""

        return return_str

    @staticmethod
    def _modify_filename_for_report(filename_to_modify: str) -> str:
        if filename_to_modify[-1] == "/":
            filename_to_modify = filename_to_modify[:-1]
        for item_to_remove in ["http://", "https://"]:
            filename_to_modify = filename_to_modify.replace(item_to_remove, "")
        filename_to_modify = re.sub(r'[^a-zA-Z0-9-_]', '_', filename_to_modify)

        return filename_to_modify

    @staticmethod
    def _create_path_for_report(path_for_report: str, filename: str) -> Path:
        if not os.path.exists(path_for_report):
            os.mkdir(path_for_report)

        return Path(path_for_report) / filename

    @staticmethod
    def _create_json_report(data: dict, path_for_report: str, filename_override: str = "") -> None:
        filename = f"{Axe._modify_filename_for_report(data["url"])}.json" if filename_override == "" else f"{filename_override}.json"
        full_path = Axe._create_path_for_report(path_for_report, filename)

        with open(full_path, 'w') as file:
            file.writelines(json.dumps(data))

        logger.info(f"JSON report generated: {full_path}")

    @staticmethod
    def _create_html_report(data: dict, path_for_report: str, filename_override: str = "") -> None:
        filename = f"{Axe._modify_filename_for_report(data["url"])}.html" if filename_override == "" else f"{filename_override}.html"
        full_path = Axe._create_path_for_report(path_for_report, filename)

        with open(full_path, 'w') as file:
            file.writelines(Axe._generate_html(data))

        logger.info(f"HTML report generated: {full_path}")

    @staticmethod
    def css_styling() -> str:
            return """
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; }
                    h1, h2, h3 { color: #333; }
                    table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
                    th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
                    th { background-color: #f4f4f4; }
                    pre { background-color: #f9f9f9; padding: 10px; border: 1px solid #ddd; }
                    code { background-color: #f9f9f9; padding: 2px 4px; border-radius: 4px; word-wrap: break-word; word-break: break-all; white-space: pre-wrap; }
                    p { margin: 10px 0; }
                    div { padding: 10px; border: 1px solid #ddd; }
                </style>"""

    @staticmethod
    def wcag_tagging(tags: list[str]) -> str:
        wcag_tags = []
        for tag in tags:
            if tag in WCAG_KEYS:
                wcag_tags.append(WCAG_KEYS[tag])
        return ", ".join(wcag_tags)

    @staticmethod
    def _generate_table_header(headers: list[tuple[str, str, bool]]) -> str:
        """Generate the header row for tables in the standard format."""
        html = ""
        for header in headers:
            html += f'<th style="{"text-align: center; " if header[2] else ""}width: {header[1]}%">{header[0]}</th>'
        
        return html

    @staticmethod
    def _generate_violations_section(violations_data: dict) -> str:
        """Generate the violations section of the HTML report."""

        html = "<h2>Violations Found</h2>"

        if len(violations_data) == 0:
            return f"{html}<p>No violations found.</p>"
        
        html += f"<p>{len(violations_data)} violations found.</p>"

        html += f"<table><tr>{Axe._generate_table_header([
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
                    <td>{Axe.wcag_tagging(violation['tags'])}</td>
                    <td>{violation['impact']}</td>
                    <td style="text-align: center;">{len(violation['nodes'])}</td>
                    </tr>'''

            violation_count += 1

            node_count = 1
            violations_table += f"<table><tr>{Axe._generate_table_header([
                ("#", "2", True), ("Description", "49", False), ("Fix Information", "49", False)
                ])}"

            for node in violation['nodes']:
                violations_table += f'''<tr><td style="text-align: center;">{node_count}</td>
                                    <td><p>Element Location:</p>
                                    <pre><code>{escape("<br>".join(node['target']))}</code></pre>
                                    <p>HTML:</p><pre><code>{escape(node['html'])}</code></pre></td>
                                    <td>{str(escape(node['failureSummary'])).replace("Fix any of the following:", "<strong>Fix any of the following:</strong><br />").replace("\n ", "<br /> &bullet;")}</td></tr>'''
                node_count += 1
            violations_table += "</table>"

            violation_section += f'''<table><tr><td style="width: 100%"><h3>{escape(violation['description'])}</h3>
                                <p><strong>Axe Rule ID:</strong> <a href="{violation['helpUrl']}" target="_blank">{violation['id']}</a><br />
                                <strong>WCAG:</strong> {Axe.wcag_tagging(violation['tags'])}<br />
                                <strong>Impact:</strong> {violation['impact']}<br />
                                <strong>Tags:</strong> {", ".join(violation['tags'])}</p>
                                {violations_table}
                                </td></tr></table>'''
        
        return f"{html}</table>{violation_section}"
    
    @staticmethod
    def _generate_passed_section(passed_data: dict) -> str:
        """Generate the passed section of the HTML report."""

        html = "<h2>Passed Checks</h2>"

        if len(passed_data) == 0:
            return f"<p>{html}No passed checks found.</p>"
            
        html += f"<table><tr>{Axe._generate_table_header([
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
                    <td>{Axe.wcag_tagging(passed['tags'])}</td>
                    <td style="text-align: center;">{len(passed['nodes'])}</td>
                    </tr>'''

            pass_count += 1
        
        return f"{html}</table>"

    @staticmethod
    def _generate_incomplete_section(incomplete_data: dict) -> str:
        """Generate the incomplete section of the HTML report."""

        html = "<h2>Incomplete Checks</h2>"

        if len(incomplete_data) == 0:
            return f"{html}<p>No incomplete checks found.</p>"
            
        html += f"<table><tr>{Axe._generate_table_header([
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
                    <td>{Axe.wcag_tagging(incomplete['tags'])}</td>
                    <td style="text-align: center;">{len(incomplete['nodes'])}</td>
                    </tr>'''

            incomplete_count += 1
        
        return f"{html}</table>"

    @staticmethod
    def _generate_inapplicable_section(inapplicable_data: dict) -> str:
        """This method generates the inapplicable section of the HTML report."""

        html = "<h2>Inapplicable Checks</h2>"

        if len(inapplicable_data) == 0:
            return f"{html}<p>No inapplicable checks found.</p>"

        html += f"<table><tr>{Axe._generate_table_header([
            ("#", "2", True), ("Description", "60", False), 
            ("Axe Rule ID", "20", False), ("WCAG", "18", False)
            ])}"

        inapplicable_count = 1
        for inapplicable in inapplicable_data:

            html += f'''<tr>
                    <td style="text-align: center;">{inapplicable_count}</td>
                    <td>{escape(inapplicable['description'])}</td>
                    <td><a href="{inapplicable['helpUrl']}" target="_blank">{inapplicable['id']}</a></td>
                    <td>{Axe.wcag_tagging(inapplicable['tags'])}</td>
                    </tr>'''

            inapplicable_count += 1

        return f"{html}</table>"
    
    @staticmethod
    def _generate_execution_details_section(data: dict) -> str:
        """Generate the execution details section of the HTML report."""

        html = "<h2>Execution Details</h2>"
        
        html += f"<table><tr>{Axe._generate_table_header([
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

    @staticmethod
    def _generate_html(data: dict) -> str:

        # HTML header
        html = f"<!DOCTYPE html><html><head>{Axe.css_styling()}<title>Axe Accessibility Report</title></head><body>"

        # HTML body
        # Title and URL
        html += "<h1>Axe Accessibility Report</h1>"
        html += f"""<p>This is an axe-core accessibility summary generated on
                    {datetime.strptime(data["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%d %H:%M")}
                    for: <strong>{data['url']}</strong></p>"""

        # Violations
        # Summary
        html += Axe._generate_violations_section(data['violations'])

        # Passed Checks (Collapsible)
        html += Axe._generate_passed_section(data['passes'])

        # Incomplete Checks (Collapsible)
        html += Axe._generate_incomplete_section(data['incomplete'])

        # Inapplicable Checks (Collapsible)
        html += Axe._generate_inapplicable_section(data['inapplicable'])

        # Execution Details (Collapsible)
        html += Axe._generate_execution_details_section(data)

        # Close tags
        html += "</body></html>"

        return html


class AxeAccessibilityException(Exception):
    pass
