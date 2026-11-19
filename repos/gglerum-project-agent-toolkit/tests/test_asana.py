import importlib.util
import pathlib
import argparse
import contextlib
import io
import urllib.error
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("asana", pathlib.Path(__file__).parents[1] / "tools" / "service-readers" / "asana.py")
asana = importlib.util.module_from_spec(spec)
spec.loader.exec_module(asana)
asana.DEFAULT_PROJECT = "1"
asana.OURS = asana.re.compile(r"(?:^\s*|\b)sample[\s-]*tool\b", asana.re.IGNORECASE)


class OursTest(unittest.TestCase):
    def test_name_prefix(self):
        self.assertTrue(asana.is_ours({"name": "Sample-tool: bug"}))
        self.assertTrue(asana.is_ours({"name": "Sample tool bug"}))

    def test_custom_field(self):
        task = {"name": "x", "custom_fields": [{"name": "Epic", "display_value": "Sample-tool"}]}
        self.assertTrue(asana.is_ours(task))

    def test_other_project(self):
        task = {"name": "OtherApp thing", "custom_fields": [{"name": "Epic", "display_value": "Webscan"}, {"name": "Featured", "display_value": None}]}
        self.assertFalse(asana.is_ours(task))

    def test_skipped(self):
        self.assertTrue(asana.is_skipped({"name": "Proposal: x"}))
        self.assertTrue(asana.is_skipped({"name": "On hold: x"}))
        self.assertFalse(asana.is_skipped({"name": "Sample-tool: x"}))

    def test_name_variants(self):
        for name in (" Sample-tool: x", "Sample  tool: x", "SampleTool: x"):
            self.assertTrue(asana.is_ours({"name": name}), name)
        self.assertFalse(asana.is_ours({"name": "Sample-toolX"}))


class OpenCommandTest(unittest.TestCase):
    ROWS = [
        {"gid": "1", "name": "Sample-tool: a", "memberships": [{"project": {"gid": "P"}, "section": {"name": "Product Backlog"}}]},
        {"gid": "2", "name": "OtherApp: b", "memberships": [{"project": {"gid": "P"}, "section": {"name": "Product Backlog"}}]},
        {"gid": "3", "name": "Login broken", "memberships": [{"project": {"gid": "P"}, "section": {"name": "Bugs"}}]},
        {"gid": "4", "name": "Proposal: Sample-tool: c", "memberships": [{"project": {"gid": "P"}, "section": {"name": "Product Backlog"}}]},
    ]

    def run_open(self, ours: bool):
        out, err = io.StringIO(), io.StringIO()
        args = argparse.Namespace(project="P", section=None, ours=ours)
        with mock.patch.object(asana, "task_rows", return_value=self.ROWS) as rows, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            asana.cmd_open(args)
        rows.assert_called_once_with("P", False, ours)
        return out.getvalue(), err.getvalue()

    def test_ours_filters_and_counts_unmarked_bugs(self):
        out, err = self.run_open(True)
        self.assertEqual(["1"], [line.split(" | ")[0] for line in out.splitlines()])
        self.assertIn("1 of 4", err)
        self.assertIn("1 unmarked", err)

    def test_without_ours_lists_everything(self):
        out, err = self.run_open(False)
        self.assertEqual(4, len(out.splitlines()))
        self.assertNotIn("unmarked", err)


class ReaderContractTest(unittest.TestCase):
    def run_cli(self, args, getter):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(asana, "get", side_effect=getter), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = asana.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_second_page_is_used_and_display_clipping_is_complete(self):
        pages = [{"data": [{"gid": "1", "name": "x" * 200}], "next_page": {"offset": "next"}},
                 {"data": [{"gid": "2", "name": "Sample-tool: second"}], "next_page": None}]
        code, out, err = self.run_cli(["open"], pages)
        self.assertEqual(0, code)
        self.assertIn("2 |", out)
        self.assertIn("chars]", out)
        self.assertIn("COMPLETE:", err)

    def test_repeated_and_cyclic_offsets_never_publish_partial_rows(self):
        for offsets in (("x", "x"), ("x", "y", "x")):
            pages = [{"data": [{"gid": "1", "name": "Sample-tool: x"}],
                      "next_page": {"offset": offset}} for offset in offsets]
            code, out, err = self.run_cli(["open"], pages)
            self.assertEqual(5, code)
            self.assertEqual("", out)
            self.assertIn("INCOMPLETE:", err)
            self.assertIn("repeated", err)

    def test_malformed_pages_are_incomplete_not_empty_success(self):
        for page in ({}, {"data": {}}, {"data": [None]}, {"data": [{"gid": "1", "name": 7}]},
                     {"data": [], "next_page": {}}, {"data": [], "next_page": "url"}):
            code, out, err = self.run_cli(["open"], [page])
            self.assertEqual(5, code, page)
            self.assertEqual("", out)
            self.assertIn("INCOMPLETE:", err)

    def test_page_limit_is_bounded(self):
        with mock.patch.object(asana, "MAX_PAGES", 1):
            code, out, err = self.run_cli(["open"], [{"data": [], "next_page": {"offset": "x"}}])
        self.assertEqual(5, code)
        self.assertEqual("", out)
        self.assertIn("page limit", err)

    def test_task_and_comments_share_deadline_and_output_is_atomic(self):
        now = [0]
        task = {"gid": "1", "name": "test", "completed": False}

        def getter(*args):
            now[0] += 2
            return {"data": task} if args[0] == "/tasks/1" else {"data": []}

        with mock.patch.object(asana.time, "monotonic", side_effect=lambda: now[0]):
            code, out, err = self.run_cli(["--timeout", "3", "task", "1", "--comments", "1"], getter)
        self.assertEqual(5, code)
        self.assertEqual("", out)
        self.assertIn("deadline", err)
        self.assertIsNone(asana.DEADLINE.get())

    def test_zero_comments_does_not_fetch_stories(self):
        with mock.patch.object(asana, "paged") as paged:
            self.assertEqual([], asana.comments("1", 0))
        paged.assert_not_called()

    def test_http_auth_is_reported_once_without_remote_body(self):
        error = urllib.error.HTTPError("https://app.asana.com", 401, "SECRET", {}, None)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(asana.os.environ, {"ASANA_TOKEN": "SECRET"}), \
                mock.patch.object(asana, "open_request", side_effect=error) as request, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(6, asana.main(["open"]))
        self.assertEqual(1, request.call_count)
        self.assertEqual("", out.getvalue())
        self.assertIn("ERROR: Asana HTTP 401", err.getvalue())
        self.assertNotIn("SECRET", err.getvalue())

    def test_request_timeout_is_capped_by_remaining_budget(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read1.side_effect = [b'{"data": []}', b'']
        token = asana.DEADLINE.set(105)
        try:
            with mock.patch.dict(asana.os.environ, {"ASANA_TOKEN": "x"}), \
                    mock.patch.object(asana.time, "monotonic", return_value=100), \
                    mock.patch.object(asana, "open_request", return_value=response) as request:
                asana.get("/tasks")
            self.assertEqual(5, request.call_args.kwargs["timeout"])
        finally:
            asana.DEADLINE.reset(token)

    def test_timeout_or_truncated_response_is_incomplete(self):
        for failure in (TimeoutError(), asana.http.client.BadStatusLine("SECRET")):
            with mock.patch.dict(asana.os.environ, {"ASANA_TOKEN": "x"}), \
                    mock.patch.object(asana, "open_request", side_effect=failure):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(5, asana.main(["open"]))
            self.assertIn("INCOMPLETE:", err.getvalue())
            self.assertNotIn("SECRET", err.getvalue())

    def test_response_byte_limit_blocks_oversized_data(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read1.return_value = b"12345"
        with mock.patch.dict(asana.os.environ, {"ASANA_TOKEN": "x"}), \
                mock.patch.object(asana, "MAX_RESPONSE_BYTES", 4), \
                mock.patch.object(asana, "open_request", return_value=response):
            with self.assertRaisesRegex(asana.ReaderError, "byte limit"):
                asana.get("/tasks")

    def test_slow_response_cannot_extend_pagination_budget(self):
        now = [0]
        response = mock.MagicMock()

        def chunk(*args):
            now[0] += 2
            return b" "

        response.__enter__.return_value.read1.side_effect = chunk
        with mock.patch.dict(asana.os.environ, {"ASANA_TOKEN": "x"}), \
                mock.patch.object(asana.time, "monotonic", side_effect=lambda: now[0]), \
                mock.patch.object(asana, "open_request", return_value=response), \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(5, asana.main(["--timeout", "3", "open"]))
        self.assertEqual("", out.getvalue())
        self.assertIn("deadline", err.getvalue())
        self.assertEqual(2, response.__enter__.return_value.read1.call_count)

    def test_invalid_timeouts_rejected(self):
        for value in ("nan", "inf", "0", "-1"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                asana.main(["--timeout", value, "open"])
            self.assertEqual(2, error.exception.code)


if __name__ == "__main__":
    unittest.main()
