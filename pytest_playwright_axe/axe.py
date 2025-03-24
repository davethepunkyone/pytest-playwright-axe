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
PATH_FOR_REPORT = Path(__file__).parent.parent / "axe-reports"

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

        page.evaluate(AXE_PATH.read_text(encoding="UTF-8"))

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
                json_report_generated=json_report_generated
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

        return path_for_report / filename

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
    def _generate_html(data: dict) -> str:
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

        def wcag_tagging(tags: list[str]) -> str:
            wcag_tags = []
            for tag in tags:
                if tag in WCAG_KEYS:
                    wcag_tags.append(WCAG_KEYS[tag])
            return ", ".join(wcag_tags)

        # --- HTML Generation ---

        # HTML header
        html = f"<!DOCTYPE html><html><head>{css_styling()}<title>Axe Accessibility Report</title></head><body>"

        # HTML body
        # Title and URL
        html += "<h1>Axe Accessibility Report</h1>"
        html += f"""<p>This is an axe-core accessibility summary generated on
                    {datetime.strptime(data["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%d/%m/%Y %H:%M")}
                    for: <strong>{data['url']}</strong></p>"""

        # Violations
        # Summary
        html += "<h2>Violations Found</h2>"
        if len(data['violations']) > 0:
            html += f"<p>{len(data['violations'])} violations found.</p>"

            html += "<table><tr>"
            for header in [("#", "2", "text-align: center; "), ("Description", "53", ""), ("Axe Rule ID", "15", ""), ("WCAG", "15", ""), ("Impact", "10", ""), ("Count", "5", "text-align: center; ")]:
                html += f'<th style="{header[2]}width: {header[1]}%">{header[0]}</th>'

            violation_count = 1
            violation_section = ""
            for violation in data['violations']:
                violations_table = ""

                html += "<tr>"
                html += f'<td style="text-align: center;">{violation_count}</td>'
                html += f"<td>{escape(violation['description'])}</td>"
                html += f'<td><a href="{violation['helpUrl']}" target="_blank">{violation['id']}</a></td>'
                html += f"<td>{wcag_tagging(violation['tags'])}</td>"
                html += f"<td>{violation['impact']}</td>"
                html += f'<td style="text-align: center;">{len(violation['nodes'])}</td>'
                html += "</tr>"

                violation_count += 1

                violations_table += "<table><tr>"
                node_count = 1
                for header in [("#", "2", "text-align: center; "), ("Description", "49", ""), ("Fix Information", "49", "")]:
                    violations_table += f'<th style="{header[2]}width: {header[1]}%">{header[0]}</th>'

                for node in violation['nodes']:
                    violations_table += f'<tr><td style="text-align: center;">{node_count}</td>'
                    violations_table += '<td><p>Element Location:</p>'
                    violations_table += f"<pre><code>{escape("<br>".join(node['target']))}</code></pre>"
                    violations_table += f'<p>HTML:</p><pre><code>{escape(node['html'])}</code></pre></td>'
                    violations_table += f"<td>{str(escape(node['failureSummary'])).replace("Fix any of the following:", "<strong>Fix any of the following:</strong><br />").replace("\n ", "<br /> &bullet;")}</td></tr>"
                    node_count += 1
                violations_table += "</table>"

                violation_section += f'<table><tr><td style="width: 100%"><h3>{escape(violation['description'])}</h3>'
                violation_section += f'<p><strong>Axe Rule ID:</strong> <a href="{violation['helpUrl']}" target="_blank">{violation['id']}</a><br />'
                violation_section += f"<strong>WCAG:</strong> {wcag_tagging(violation['tags'])}<br />"
                violation_section += f"<strong>Impact:</strong> {violation['impact']}<br />"
                violation_section += f"<strong>Tags:</strong> {", ".join(violation['tags'])}</p>"
                violation_section += violations_table
                violation_section += "</td></tr></table>"

            html += "</table>"
            html += violation_section
        else:
            html += "<p>No violations found.</p>"

        # Passed Checks (Collapsible)
        html += "<h2>Passed Checks</h2>"
        if len(data['passes']) > 0:
            html += "<table><tr>"
            for header in [("#", "2", "text-align: center; "), ("Description", "50", ""), ("Axe Rule ID", "15", ""), ("WCAG", "18", ""), ("Nodes Passed Count", "15", "text-align: center; ")]:
                html += f'<th style="{header[2]}width: {header[1]}%">{header[0]}</th>'

            pass_count = 1
            for passed in data['passes']:
                violations_table = ""

                html += "<tr>"
                html += f'<td style="text-align: center;">{pass_count}</td>'
                html += f"<td>{escape(passed['description'])}</td>"
                html += f'<td><a href="{passed['helpUrl']}" target="_blank">{passed['id']}</a></td>'
                html += f"<td>{wcag_tagging(passed['tags'])}</td>"
                html += f'<td style="text-align: center;">{len(passed['nodes'])}</td>'
                html += "</tr>"

                pass_count += 1

            html += "</table>"
        else:
            html += "<p>No passed checks found.</p>"

        # Incomplete Checks (Collapsible)
        html += "<h2>Incomplete Checks</h2>"
        if len(data['incomplete']) > 0:
            html += "<table><tr>"
            for header in [("#", "2", "text-align: center; "), ("Description", "50", ""), ("Axe Rule ID", "15", ""), ("WCAG", "18", ""), ("Nodes Incomplete Count", "15", "text-align: center; ")]:
                html += f'<th style="{header[2]}width: {header[1]}%">{header[0]}</th>'

            incomplete_count = 1
            for incomplete in data['incomplete']:
                violations_table = ""

                html += "<tr>"
                html += f'<td style="text-align: center;">{incomplete_count}</td>'
                html += f"<td>{escape(incomplete['description'])}</td>"
                html += f'<td><a href="{incomplete['helpUrl']}" target="_blank">{incomplete['id']}</a></td>'
                html += f"<td>{wcag_tagging(incomplete['tags'])}</td>"
                html += f'<td style="text-align: center;">{len(incomplete['nodes'])}</td>'
                html += "</tr>"

                incomplete_count += 1

            html += "</table>"
        else:
            html += "<p>No incomplete checks found.</p>"

        # Inapplicable Checks (Collapsible)
        html += "<h2>Inapplicable Checks</h2>"
        if len(data['inapplicable']) > 0:
            html += "<table><tr>"
            for header in [("#", "2", "text-align: center; "), ("Description", "60", ""), ("Axe Rule ID", "20", ""), ("WCAG", "18", "")]:
                html += f'<th style="{header[2]}width: {header[1]}%">{header[0]}</th>'

            inapplicable_count = 1
            for inapplicable in data['inapplicable']:

                html += "<tr>"
                html += f'<td style="text-align: center;">{inapplicable_count}</td>'
                html += f"<td>{escape(inapplicable['description'])}</td>"
                html += f'<td><a href="{inapplicable['helpUrl']}" target="_blank">{inapplicable['id']}</a></td>'
                html += f"<td>{wcag_tagging(inapplicable['tags'])}</td>"
                html += "</tr>"

                inapplicable_count += 1

            html += "</table>"
        else:
            html += "<p>No inapplicable checks found.</p>"

        # Execution Details (Collapsible)
        html += "<h2>Execution Details</h2>"

        html += "<table><tr>"
        for header in [("Data", "20"), ("Details", "80")]:
            html += f'<th style="width: {header[1]}%">{header[0]}</th>'

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

        html += "</table>"

        # Close tags
        html += "</body></html>"

        return html


class AxeAccessibilityException(Exception):
    pass
