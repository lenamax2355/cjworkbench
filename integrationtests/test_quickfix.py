from integrationtests.utils import LoggedInIntegrationTest


class TestQuickFix(LoggedInIntegrationTest):
    def _blur(self):
        self.browser.click_whatever(".module-name", text="Paste data")

    def _create_simple_workflow(self, *, csv_data, expected_colnames_and_types):
        b = self.browser

        b.click_button("Create your first workflow")
        b.assert_element(
            'input[name="name"][value="Untitled Workflow"]', wait=True
        )  # Wait for page to load

        b.fill_in("name", "Example Workflow")

        self.import_module("pastecsv")
        self.add_data_step("Paste data")
        b.fill_in("csv", csv_data, wait=True)
        self.submit_step()

        # Wait for table to load
        for expected_colname_and_type in expected_colnames_and_types:
            b.assert_element(".column-key", text=expected_colname_and_type, wait=True)

    def test_quick_fix_convert_to_date(self):
        """
        Tests that a module's `column_types` gets users to click "Convert".
        """
        # https://www.pivotaltracker.com/story/show/160700316
        self._create_simple_workflow(
            csv_data="A,B\n2012-01-01,1\n2012-02-03,3\n2012-01-01,2",
            expected_colnames_and_types=["A text"],
        )

        self.import_module("convert-date")
        self.import_module("countbydate")

        self.add_step("Group by date")
        self.select_column("Group by date", "column", "A")
        self.submit_step()

        # Wait for error to occur
        b = self.browser
        b.assert_element(
            ".step-error-msg",
            text="The column “A” must be converted from Text to Timestamps.",
            wait=True,
        )
        b.click_button("Convert Text to Timestamps")

        # Wait for module to appear
        b.assert_element(".module-name", text="Convert to timestamp", wait=True)

        # Click back to "Group by date" to see its output
        b.click_whatever(".module-name", text="Group by date")
        # Wait for render
        b.assert_no_element(".step-error-msg", wait=True)
        # Wait for table render
        b.assert_element(".column-key", text="count number", wait=True)

    def test_quick_fix_convert_to_numbers(self):
        """
        Tests that a module's `column_types` gets users to click "Convert".
        """
        b = self.browser

        # "Accidentally" create a column, 'Num' of type Text.
        self._create_simple_workflow(
            csv_data="T,Num\nX,$1\nY,$2\nZ,$3", expected_colnames_and_types=["T text"]
        )

        self.import_module("formatnumbers")
        self.import_module("converttexttonumber")

        # Try to format numbers. (It won't work because the input is text.)
        self.add_step("Format numbers")
        self.select_column("Format numbers", "colnames", "Num")
        b.select("format", "Currency")
        self.submit_step()
        # Wait for error
        b.assert_element(
            ".step-error-msg",
            text="The column “Num” must be converted from Text to Numbers.",
            wait=True,
        )

        # Fix the error by clicking the "Quick Fix" button.
        b.click_button("Convert Text to Numbers")
        # Wait for module to appear
        b.assert_element(".module-name", text="Convert to number", wait=True)
        # The conversion won't work until we check an option.
        b.check("Ignore non-numeric characters")
        self.submit_step()

        # Now, the "Format numbers" module will have the correct output.
        b.click_whatever(".module-name", text="Format numbers")
        b.assert_element(".cell-number", text="$2.00", wait=True)

    def test_multiple_errors_with_quick_fix(self):
        b = self.browser

        # "Accidentally" create two column, 'Num' and 'Num2', of type Text.
        self._create_simple_workflow(
            csv_data="T,Num1,Num2\nX,$1,$3\nY,$2,$5\nZ,$3,$7",
            expected_colnames_and_types=["Num1 text", "Num2 text"],
        )

        # 'Accidentally' convert 'Num2' to Timestamp
        self.import_module("convert-date")
        self.add_step("Convert to timestamp")
        self.select_column("Convert to timestamp", "colnames", "Num2")
        self.submit_step()

        # Try to format numbers. (It won't work because the inputs are text and timestamp.)
        self.import_module("formatnumbers")
        self.add_step("Format numbers")
        self.select_column("Format numbers", "colnames", "Num1")
        self.select_column("Format numbers", "colnames", "Num2")
        b.select("format", "Currency")
        self.submit_step()

        # Wait for errors
        b.assert_element(
            ".step-error-msg",
            text="The column “Num1” must be converted from Text to Numbers.",
            wait=True,
        )
        b.assert_element("button", text="Convert Text to Numbers")
        b.assert_element(
            ".step-error-msg",
            text="The column “Num2” must be converted from Timestamps to Numbers.",
            wait=True,
        )
        b.assert_element("button", "Convert Timestamps to Numbers")
