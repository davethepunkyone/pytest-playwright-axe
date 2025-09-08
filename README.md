# Pytest Playwright Axe

`pytest-playwright-axe` is a package for Playwright Python that allows for the execution of [axe-core](https://github.com/dequelabs/axe-core), a JavaScript
library used for scanning for accessibility issues and providing guidance on how to resolve these issues.

## Table of Contents

- [Pytest Playwright Axe](#pytest-playwright-axe)
  - [Table of Contents](#table-of-contents)
  - [Instantiating the Axe class](#instantiating-the-axe-class)
    - [Optional arguments](#optional-arguments)
  - [.run(): Single page scan](#run-single-page-scan)
    - [Required arguments](#required-arguments)
    - [Optional arguments](#optional-arguments-1)
    - [Returns](#returns)
    - [Example usage](#example-usage)
  - [.run\_list(): Multiple page scan](#run_list-multiple-page-scan)
    - [Required arguments](#required-arguments-1)
    - [Optional arguments](#optional-arguments-2)
    - [Returns](#returns-1)
    - [Example usage](#example-usage-1)
  - [.get\_rules(): Return rules](#get_rules-return-rules)
    - [Required Arguments](#required-arguments-2)
    - [Optional Arguments](#optional-arguments-3)
    - [Returns](#returns-2)
    - [Example usage](#example-usage-2)
  - [Rulesets](#rulesets)
  - [Example Reports](#example-reports)
  - [Versioning](#versioning)
  - [Breaking Changes](#breaking-changes)
    - [4.10.3 -\> Onwards](#4103---onwards)
  - [Licence](#licence)
  - [Acknowledgements](#acknowledgements)

## Instantiating the Axe class

You can initialise the Axe class by using the following code in your test file:

    from pytest_playwright_axe import Axe

You can run the Axe instance either as a standalone instance or instantiate it as follows:

    # Standalone execution
    Axe().run(page)

    # Instantiated execution
    axe = Axe()
    axe.run(page)

### Optional arguments

The `Axe()` class has the following optional arguments that can be passed in:

| Argument            | Format                  | Supported Values                                                  | Default Value | Description                                                                                                                                   |
| ------------------- | ----------------------- | ----------------------------------------------------------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `output_directory`  | `pathlib.Path` or `str` | A valid directory path to save results to (e.g. `C:/axe_reports`) |               | If provided, sets the directory to save HTML and JSON results into. If not provided (default), the default path is `os.getcwd()/axe-reports`. |
| `css_override`      | `str`                   | A string with valid CSS.                                          |               | If provided, this will override the default CSS used in the HTML report with the CSS styling provided.                                        |
| `use_minified_file` | `bool`                  | `True`, `False`                                                   | `False`       | If True, use the minified version of axe-core (axe.min.js). If not provided (default), use the full version of axe-core (axe.js).             |


## .run(): Single page scan

To conduct a scan, you can just use the following once the page you want to check is at the right location:

    Axe().run(page)

This will inject the axe-core code into the page and then execute the axe.run() command, generating an accessibility report for the page being tested.

By default, the `Axe().run(page)` command will do the following:

- Scan the page passed in with the default axe-core configuration
- Generate a HTML and JSON report with the findings in the `axe-reports` directory, regardless of if any violations are found
- Any steps after the `Axe().run()` command will continue to execute, and it will not cause the test in progress to fail (it runs a passive scan of the page)
- Will return the full response from axe-core as a dict object if the call is set to a variable, e.g. `axe_results = Axe().run(page)` will populate `axe_results` to interact with as required

This uses the [axe-core run method outlined in the axe-core documentation](https://www.deque.com/axe/core-documentation/api-documentation/#api-name-axerun).

### Required arguments

The following are required for `Axe().run()`:

| Argument | Format                   | Description                                  |
| -------- | ------------------------ | -------------------------------------------- |
| page     | playwright.sync_api.Page | A Playwright Page on the page to be checked. |

### Optional arguments

The `Axe().run(page)` has the following optional arguments that can be passed in:

| Argument                   | Format | Supported Values                                                                                                  | Default Value | Description                                                                                                                                                                                                                                                             |
| -------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `filename`                 | `str`  | A string valid for a filename (e.g. `test_report`)                                                                |               | If provided, HTML and JSON reports will save with the filename provided. If not provided (default), the URL of the page under test will be used as the filename.                                                                                                        |
| `context`                  | `str`  | A JavaScript object, represented as a string (e.g. `{ exclude: '.ad-banner' }`)                                   |               | If provided, adds the [context that axe-core should use](https://www.deque.com/axe/core-documentation/api-documentation/?_gl=1*nt1pxm*_up*MQ..*_ga*Mjc3MzY4NDQ5LjE3NDMxMDMyMDc.*_ga_C9H6VN9QY1*MTc0MzEwMzIwNi4xLjAuMTc0MzEwMzIwNi4wLjAuODE0MjQyMzA2#context-parameter). |
| `options`                  | `str`  | A JavaScript object, represented as a string (e.g. `{ runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] } }`) |               | If provided, adds the [options that axe-core should use](https://www.deque.com/axe/core-documentation/api-documentation/?_gl=1*nt1pxm*_up*MQ..*_ga*Mjc3MzY4NDQ5LjE3NDMxMDMyMDc.*_ga_C9H6VN9QY1*MTc0MzEwMzIwNi4xLjAuMTc0MzEwMzIwNi4wLjAuODE0MjQyMzA2#options-parameter). |
| `report_on_violation_only` | `bool` | `True`, `False`                                                                                                   | `False`       | If True, HTML and JSON reports will only be generated if at least one violation is found.                                                                                                                                                                               |
| `strict_mode`              | `bool` | `True`, `False`                                                                                                   | `False`       | If True, when a violation is found an AxeAccessibilityException is raised, causing a test failure.                                                                                                                                                                      |
| `html_report_generated`    | `bool` | `True`, `False`                                                                                                   | `True`        | If True, a HTML report will be generated summarising the axe-core findings.                                                                                                                                                                                             |
| `json_report_generated`    | `bool` | `True`, `False`                                                                                                   | `True`        | If True, a JSON report will be generated with the full axe-core findings.                                                                                                                                                                                               |

### Returns

This function can be used independently, but when set to a variable returns a `dict` with the axe-core results.

### Example usage

A default execution with no arguments:

    from pytest_playwright_axe import Axe
    from playwright.sync_api import Page

    def test_axe_example(page: Page) -> None:
        page.goto("https://github.com/davethepunkyone/pytest-playwright-axe")
        Axe().run(page)

A WCAG 2.2 (AA) execution, with a custom filename, strict mode enabled and only HTML output provided:

    from pytest_playwright_axe import Axe
    from playwright.sync_api import Page

    def test_axe_example(page: Page) -> None:
        page.goto("https://github.com/davethepunkyone/pytest-playwright-axe")
        Axe().run(page, 
                  filename="test_report",
                  options="{runOnly: {type: 'tag', values: ['wcag2a', 'wcag21a', 'wcag2aa', 'wcag21aa', 'wcag22a', 'wcag22aa', 'best-practice']}}",
                  strict_mode=True,
                  json_report_generated=False)

## .run_list(): Multiple page scan

To scan multiple URLs within your application, you can use the following method:

    Axe().run_list(page, page_list)

This runs the `Axe().run(page)` function noted above against each URL provided in the `page_list` argument, and will generate reports as required. This navigates by using the Playwright Page's `.goto()` method, so this only works for pages that can be directly accessed.

### Required arguments

The following are required for `Axe().run_list()`:

| Argument  | Format                     | Description                                                                    |
| --------- | -------------------------- | ------------------------------------------------------------------------------ |
| page      | `playwright.sync_api.Page` | A Playwright Page object to drive navigation to each page to test.             |
| page_list | `list[str]`                | A list of URLs to execute against (e.g. `["home", "profile", "product/test"]`) |

> NOTE: It is heavily recommended that when using the `run_list` command, that you set a `--base-url` either via the pytest.ini file or by passing in the value when using the `pytest` command in the command line. By doing this, the list you pass in will not need to contain the base URL value and therefore make any scanning transferrable between environments.

### Optional arguments

The `Axe().run_list(page, page_list)` function has the following optional arguments that can be passed in:

| Argument                   | Format | Supported Values                                                                                                  | Default Value | Description                                                                                                                                                                                                                                                             |
| -------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `use_list_for_filename`    | `bool` | `True`, `False`                                                                                                   | `True`        | If True, the filename will be derived from the value provided in the list. If False, the full URL will be used.                                                                                                                                                         |
| `context`                  | `str`  | A JavaScript object, represented as a string (e.g. `{ exclude: '.ad-banner' }`)                                   |               | If provided, adds the [context that axe-core should use](https://www.deque.com/axe/core-documentation/api-documentation/?_gl=1*nt1pxm*_up*MQ..*_ga*Mjc3MzY4NDQ5LjE3NDMxMDMyMDc.*_ga_C9H6VN9QY1*MTc0MzEwMzIwNi4xLjAuMTc0MzEwMzIwNi4wLjAuODE0MjQyMzA2#context-parameter). |
| `options`                  | `str`  | A JavaScript object, represented as a string (e.g. `{ runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] } }`) |               | If provided, adds the [options that axe-core should use](https://www.deque.com/axe/core-documentation/api-documentation/?_gl=1*nt1pxm*_up*MQ..*_ga*Mjc3MzY4NDQ5LjE3NDMxMDMyMDc.*_ga_C9H6VN9QY1*MTc0MzEwMzIwNi4xLjAuMTc0MzEwMzIwNi4wLjAuODE0MjQyMzA2#options-parameter). |
| `report_on_violation_only` | `bool` | `True`, `False`                                                                                                   | `False`       | If True, HTML and JSON reports will only be generated if at least one violation is found.                                                                                                                                                                               |
| `strict_mode`              | `bool` | `True`, `False`                                                                                                   | `False`       | If True, when a violation is found an AxeAccessibilityException is raised, causing a test failure.                                                                                                                                                                      |
| `html_report_generated`    | `bool` | `True`, `False`                                                                                                   | `True`        | If True, a HTML report will be generated summarising the axe-core findings.                                                                                                                                                                                             |
| `json_report_generated`    | `bool` | `True`, `False`                                                                                                   | `True`        | If True, a JSON report will be generated with the full axe-core findings.                                                                                                                                                                                               |

### Returns

This function can be used independently, but when set to a variable returns a `dict` with the axe-core results for all pages scanned (using the URL value in the list provided as the key).

### Example usage

When using the following command: `pytest --base-url https://www.github.com`:

    from pytest_playwright_axe import Axe
    from playwright.sync_api import Page

    def test_accessibility(page: Page) -> None:
        # A list of URLs to loop through
        urls_to_check = [
            "davethepunkyone/pytest-playwright-axe",
            "davethepunkyone/pytest-playwright-axe/issues"
            ]

        Axe().run_list(page, urls_to_check)

## .get_rules(): Return rules

You can get the rules used for specific tags by using this method, or all rules if no ruleset is provided.

This uses the [axe-core getRules method outlined in the axe-core documentation](https://www.deque.com/axe/core-documentation/api-documentation/#api-name-axegetrules).

### Required Arguments

The following are required for `Axe().get_rules()`:

| Argument | Format                     | Description                                              |
| -------- | -------------------------- | -------------------------------------------------------- |
| page     | `playwright.sync_api.Page` | A Playwright Page object.. This page can be empty/blank. |

### Optional Arguments

The `Axe().get_rules(page, page_list)` function has the following optional arguments that can be passed in:

| Argument | Format      | Supported Values                                                                                                                    | Default Value | Description                                                                                               |
| -------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------- | --------------------------------------------------------------------------------------------------------- |
| `rules`  | `list[str]` | A Python list with strings representing [valid tags](https://www.deque.com/axe/core-documentation/api-documentation/#axecore-tags). | `None`        | If provided, the list of rules to provide information on.  If not provided, return details for all rules. |

### Returns

A Python `list[dict]` object with all matching rules and their descriptors.

### Example usage

    import logging
    from pytest_playwright_axe import Axe
    from playwright.sync_api import Page

    def test_get_rules(page: Page) -> None:

        rules = Axe().get_rules(page, ['wcag21aa'])
        for rule in rules:
            logging.info(rule)

## Rulesets

The following rulesets can also be imported via the `pytest_playwright_axe` module:

| Ruleset     | Import              | Rules Applied                                                                          |
| ----------- | ------------------- | -------------------------------------------------------------------------------------- |
| WCAG 2.2 AA | `OPTIONS_WCAG_22AA` | `['wcag2a', 'wcag21a', 'wcag2aa', 'wcag21aa', 'wcag22a', 'wcag22aa', 'best-practice']` |

Example:

    from pytest_playwright_axe import Axe, OPTIONS_WCAG_22AA
    from playwright.sync_api import Page

    def test_axe_example(page: Page) -> None:
        page.goto("https://github.com/davethepunkyone/pytest-playwright-axe")
        Axe().run(page, options=OPTIONS_WCAG_22AA)

## Example Reports

The following are examples of the reports generated using this package:

- HTML Format (Use download file to see report): [Example File](https://github.com/davethepunkyone/pytest-playwright-axe/tree/main/examples/example_result_report.html)
- JSON Format: [Example File](https://github.com/davethepunkyone/pytest-playwright-axe/tree/main/examples/example_result_report.json)

## Versioning

The versioning for this project is designed to be directly linked to the releases from 
the [axe-core](https://github.com/dequelabs/axe-core) project, to accurately reflect the
version of axe-core that is being executed.

## Breaking Changes

The following section outlines important breaking changes between version, due to the
versioning of this project being aligned with axe-core.

### 4.10.3 -> Onwards

The following significant changes have been applied for releases after 4.10.3 which
would require amending existing logic:

- The `Axe()` module logic is no longer static, so using `Axe.run()` will no longer work.
- `output_directory` has now been moved into the `__init__` method for `Axe`, and is no longer defined in the `.run()` and `run_list()` functions.

## Licence

Unless stated otherwise, the codebase is released under the [MIT License](LICENCE.md).
This covers both the codebase and any sample code in the documentation.

## Acknowledgements

This package was created based on work initially designed for the 
[NHS England Playwright Python Blueprint](https://github.com/nhs-england-tools/playwright-python-blueprint).
