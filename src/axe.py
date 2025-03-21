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
    'wcag2a': 'WCAG 2.0 A',
    'wcag2aa': 'WCAG 2.0 AA',
    'wcag2aaa': 'WCAG 2.0 AAA',
    'wcag21a': 'WCAG 2.1 A',
    'wcag21aa': 'WCAG 2.1 AA',
    'wcag22a': 'WCAG 2.2 A',
    'wcag22aa': 'WCAG 2.2 AA',
    'best-practice': 'Best Practice'
    }

WCAG_22AA_RULESET = ['wcag2a', 'wcag21a', 'wcag2aa', 'wcag21aa', 'wcag22a', 'wcag22aa', 'best-practice']
OPTIONS_WCAG_22AA = "{runOnly: {type: 'tag', values: " + str(WCAG_22AA_RULESET) + "}}"


class Axe:
    """
    This utility allows for interaction with axe-core, to allow for accessibility scanning of pages
    under test to identify any accessibility concerns.
    """

    @staticmethod
    def run(page: Page,
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

        page.evaluate(AXE_PATH.read_text(encoding="UTF-8"))

        response = page.evaluate("axe.run(" + Axe._build_run_command(context, options) + ").then(results => {return results;})")

        logger.info(f"""Axe scan summary of [{response["url"]}]: Passes = {len(response["passes"])},
                    Violations = {len(response["violations"])}, Inapplicable = {len(response["inapplicable"])},
                    Incomplete = {len(response["incomplete"])}""")

        violations_detected = len(response["violations"]) > 0
        if not report_on_violation_only or (report_on_violation_only and violations_detected):
            if html_report_generated:
                Axe._create_html_report(response, filename)
            if json_report_generated:
                Axe._create_json_report(response, filename)

        if violations_detected and strict_mode:
            raise AxeAccessibilityException(f"Axe Accessibility Violation detected on page: {response["url"]}")

        return response

    @staticmethod
    def run_list(page: Page,
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
            filename = Axe._modify_filename_for_report(selected_page) if use_list_for_filename else ""
            results[selected_page] = Axe.run(
                page,
                filename=filename,
                context=context,
                options=options,
                # ruleset=ruleset,
                report_on_violation_only=report_on_violation_only,
                strict_mode=strict_mode,
                html_report_generated=html_report_generated,
                json_report_generated=json_report_generated
                )
        return results


    # @staticmethod
    # def _build_run_command(ruleset: list[str], ) -> str:
    #     return "run({runOnly: { type: 'tag', values: " + str(ruleset) + " }})"
    #     return "run({runOnly: { type: 'tag', values: " + str(ruleset) + " }})"

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
    def _create_path_for_report(filename: str) -> Path:
        if not os.path.exists(PATH_FOR_REPORT):
            os.mkdir(PATH_FOR_REPORT)

        return PATH_FOR_REPORT / filename

    @staticmethod
    def _create_json_report(data: dict, filename_override: str = "") -> None:
        filename = f"{Axe._modify_filename_for_report(data["url"])}.json" if filename_override == "" else f"{filename_override}.json"
        full_path = Axe._create_path_for_report(filename)

        with open(full_path, 'w') as file:
            file.writelines(json.dumps(data))

        logger.info(f"JSON report generated: {full_path}")

    @staticmethod
    def _create_html_report(data: dict, filename_override: str = "") -> None:
        filename = f"{Axe._modify_filename_for_report(data["url"])}.html" if filename_override == "" else f"{filename_override}.html"
        full_path = Axe._create_path_for_report(filename)

        with open(full_path, 'w') as file:
            # file.writelines(Axe._generate_html(data))
            file.writelines(Axe._generate_html_new(data))

        logger.info(f"HTML report generated: {full_path}")

    @staticmethod
    def _generate_html(data: dict) -> str:
        def styling() -> str:
            style = '''body { font-family: Arial, Helvetica, sans-serif; }
                    table, th, td { border: 1px solid; border-collapse: collapse; padding: 5px; }
                    th { background-color: #E8EDEE; }
                    .center { text-align: center; }
                    .details-section { width: 100% }
                    .details-header { column-width: 10% }'''
            return style

        def details_section(header: str) -> str:
            section = f'<h2 name="{header}">{header.title()}</h2>'

            if len(data[header]) > 0:
                for check in data[header]:
                    section += f'''<table class="details-section"><tr><th>ID</th><td>{check["id"]}</td></tr>
                                <tr><th class "details-header">Impact</th><td>{check["impact"]}</td></tr>
                                <tr><th class "details-header">Tags</th><td>{check["tags"]}</td></tr>
                                <tr><th class "details-header">Description</th><td>{str(check["description"]).replace("<", "&lt;").replace(">", "&rt;")}</td></tr>
                                <tr><th class "details-header">Help</th><td>{str(check["help"]).replace("<", "&lt;").replace(">", "&rt;")}</td></tr>
                                <tr><th class "details-header">Help URL</th><td><a href="{check["helpUrl"]}" target="_blank">{check["helpUrl"]}</a></td></tr>'''

                    if 'nodes' in check:
                        for node in check['nodes']:
                            section += f'''<tr><th class "details-header">Affected Node</th><td><code>{str(node).replace("<", "&lt;").replace(">", "&rt;")}</code></td></tr>'''

                    section += '</table><br />'
            else:
                section += f'<p>No {header} results returned.</p>'

            return section


        html = f'''<!doctype html><html><head>
                <style>{styling()}</style>
                <title>Axe Accessibility Report</title></head>
                <body><h1>Axe Accessibility Report</h1>
                <p>This is an axe-core accessibility summary for: <strong>{data["url"]}</strong></p>'''

        # Metadata
        html += f'''<h2>Metadata</h2>
                <table><tr><th>Key</th><th>Description</th></tr>
                <tr><td>Date/Time Executed</td><td>{datetime.strptime(data["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%d/%m/%Y %H:%M")}</td></tr>
                <tr><td>Engine Version</td><td>{data["testEngine"]["name"]} {data["testEngine"]["version"]}</td></tr>
                <tr><td>User Agent</td><td>{data["testEnvironment"]["userAgent"]}</td></tr>
                </table><br />'''

        # Summary
        html += '''<h2>Summary</h2>
                <table><tr><th>Outcome</th><th>Total Count</th></tr>'''
        for outcome in ["violations", "incomplete", "passes", "inapplicable"]:
            html += f'<tr><td>{outcome.title()}</td><td class="center">{len(data[outcome])}</td></tr>'
        html += '</table><br />'

        for section in ["violations", "incomplete", "passes", "inapplicable"]:
            html += details_section(section)

        # Close tags
        html += '</body></html>'

        return html
    
    @staticmethod
    def _generate_html_new(data: dict) -> str:
        # Example: https://lpelypenko.github.io/axe-html-reporter/

        # HTML header
        html = "<!DOCTYPE html><html><head><title>Axe Accessibility Report</title></head><body>"

        # HTML body
        # Title and URL
        html += f"<h1>Axe Accessibility Report</h1>"
        html += f"""<p>This is an axe-core accessibility summary generated on 
                    {datetime.strptime(data["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%d/%m/%Y %H:%M")} 
                    for: <strong>{data['url']}</strong></p>"""

        # Violations
        # Summary
        html += "<h2>Violations Found</h2>"
        html += f"<p>{len(data['violations'])} violations found.</p>"

        html += "<table><tr>"
        for header in [("#", "5"), ("Description", "45"), ("Axe Rule ID", "15"), ("WCAG", "23"), ("Impact", "7"), ("Count", "5")]:
            html += f'<th style="width: {header[1]}%">{header[0]}</th>'

        violation_count = 1
        violation_section = ""
        for violation in data['violations']:
            violations_table = ""

            html += "<tr>"
            html += f"<td>{violation_count}</td>"
            html += f"<td>{escape(violation['description'])}</td>"
            html += f"<td>{violation['id']}</td>"
            tags = []
            for tag in violation['tags']:
                if tag in WCAG_KEYS:
                    tags.append(WCAG_KEYS[tag])
            html += f"<td>{", ".join(tags)}</td>"
            html += f"<td>{violation['impact']}</td>"
            html += f"<td>{len(violation['nodes'])}</td>"
            html += "</tr>"

            violation_count += 1

            violations_table += "<table><tr>"
            node_count = 1
            for header in [("#", "2"), ("Description", "49"), ("Fix Information", "49")]:
                violations_table += f'<th style="width: {header[1]}%">{header[0]}</th>'

            for node in violation['nodes']:
                violations_table += f"<tr><td>{node_count}</td>"
                violations_table += f"<td><p>Element Location:</p>"
                violations_table += f"<pre><code>{escape("<br>".join(node['target']))}</code></pre>"
                violations_table += f"<p>HTML:</p><pre><code>{escape(node['html'])}</td>"
                violations_table += f"<td>{str(escape(node['failureSummary'])).replace("\n", "<br />")}</td></tr>"
                node_count += 1
            violations_table += "</table>"

            violation_section += f"<h3>{escape(violation['description'])}</h3>"
            violation_section += f"<p><strong>Axe Rule ID:</strong> {violation['id']}</p>"
            violation_section += f"<p><strong>WCAG:</strong> {', '.join(tags)}</p>"
            violation_section += f"<p><strong>Impact:</strong> {violation['impact']}</p>"
            violation_section += f"<p><strong>Tags:</strong> {", ".join(violation['tags'])}</p>"
            violation_section += violations_table
        
        html += "</table>"
        html += violation_section

        # Passed Checks (Collapsible)
        html += "<h2>Passed Checks</h2>"
        html += "<table><tr>"
        for header in [("#", "5"), ("Description", "50"), ("Axe Rule ID", "15"), ("Tags", "25"), ("Nodes Passed Count", "5")]:
            html += f'<th style="width: {header[1]}%">{header[0]}</th>'

        pass_count = 1
        for passed in data['passes']:
            violations_table = ""

            html += "<tr>"
            html += f"<td>{pass_count}</td>"
            html += f"<td>{escape(passed['description'])}</td>"
            html += f"<td>{passed['id']}</td>"
            tags = []
            for tag in passed['tags']:
                if tag in WCAG_KEYS:
                    tags.append(WCAG_KEYS[tag])
            html += f"<td>{", ".join(tags)}</td>"
            html += f"<td>{len(passed['nodes'])}</td>"
            html += "</tr>"

            pass_count += 1
        
        html += "</table>"

        # Incomplete Checks (Collapsible)
        html += "<h2>Incomplete Checks</h2>"

        # Inapplicable Checks (Collapsible)
        html += "<h2>Inapplicable Checks</h2>"

        # Rules Applied (Collapsible)
        html += "<h2>Rules Applied Checks</h2>"

        # Close tags
        html += "</body></html>"

        return html


class AxeAccessibilityException(Exception):
    pass
