import importlib.util

import io

import json

import pathlib

import subprocess

import unittest

from contextlib import redirect_stderr, redirect_stdout

from unittest import mock

spec = importlib.util.spec_from_file_location("pr_review", pathlib.Path(__file__).parents[1] / "tools" / "service-readers" / "pr_review.py")

pr_review = importlib.util.module_from_spec(spec)

spec.loader.exec_module(pr_review)

HEAD = "a" * 40

OLD = "b" * 40

EARLIER = "2026-11-07T15:27:00Z"

LATER = "2026-11-07T16:00:00Z"

LATEST = "2026-11-07T16:05:00Z"

PR = {"number": 5, "state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE",
      "baseRefName": "staging", "headRefOid": HEAD, "headRefName": "x", "author": {"login": "me"}}

URL = "https://ci.example.test/jenkins/job/example-pr/job/PR-5/12/"

STATUS = {"sha": HEAD, "state": "success", "statuses": [
    {"context": pr_review.CONTEXT, "state": "success", "target_url": URL}]}

EVIDENCE = {"sha": HEAD, "success": True, "url": URL}

STAGES = ("Check Changes", "Setup", "PHP Dependencies", "JS Dependencies", "Configuration",
          "Code Quality", "Security Static", "DefectDojo Publisher", "Quality Gate",
          "Unit Tests", "Infection (Mutation)", "Dynamic Scans", "SonarQube Scanner")

def review(body="approved", when=LATER, state="COMMENTED", user="me", commit=HEAD, id=1):
    return {"id": id, "user": {"login": user}, "state": state, "body": body,
            "submitted_at": when, "commit_id": commit}

def comment(body, when=LATER, user="me", id=2, **extra):
    return {"id": id, "user": {"login": user}, "body": body, "created_at": when, **extra}

def snapshot(reviews=None, comments=None, inline=None, **pr):
    return ({**PR, **pr}, STATUS, reviews if reviews is not None else [review()],
            comments or [], inline or [])

def build():
    return {"number": 12, "result": "SUCCESS", "building": False,
            "actions": [{"lastBuiltRevision": {"SHA1": HEAD}}]}

def flow():
    return {"id": "12", "status": "SUCCESS",
            "stages": [{"name": s, "status": "SUCCESS"} for s in STAGES]}

LOG = "Run PHP steps: true\nRun JS steps: true\nRun Infrastructure steps: false\n"

class ApprovalTest(unittest.TestCase):
    def test_full_body_only(self):
        for body in ("approved", "Approved.", "merge", "approved, merge", " APPROVED \n"):
            self.assertTrue(pr_review.is_approval(body))
        for body in ("not approved", "approved but fix typo", "", None, "please merge later"):
            self.assertFalse(pr_review.is_approval(body))

    def test_generated_body_never_approval(self):
        for body in ("approved\nGenerated with Claude Code", "approved\nGenerated with [Claude Code](url)"):
            self.assertFalse(pr_review.is_approval(body, HEAD))

    def test_sha_is_exact_and_full(self):
        self.assertTrue(pr_review.is_approval("approved " + HEAD, HEAD))
        self.assertFalse(pr_review.is_approval("approved " + OLD, HEAD))
        self.assertFalse(pr_review.is_approval("approved " + HEAD[:8], HEAD))

class EvaluateTest(unittest.TestCase):
    def ev(self, reviews=None, comments=(), inline=(), status=STATUS, evidence=EVIDENCE, **pr):
        return pr_review.evaluate({**PR, **pr}, status,
                                  [review()] if reviews is None else list(reviews),
                                  list(comments), list(inline), evidence)

    def test_review_on_head_ready(self):
        self.assertTrue(self.ev()[0])

    def test_missing_expected_context_despite_combined_success(self):
        status = {**STATUS, "statuses": [{"context": "unrelated", "state": "success"}]}
        self.assertFalse(self.ev(status=status)[0])

    def test_expected_context_pending_despite_combined_success(self):
        self.assertFalse(self.ev(status={**STATUS, "statuses": [
            {"context": pr_review.CONTEXT, "state": "pending"}]})[0])

    def test_unknown_null_missing_mergeability(self):
        for state in ("UNKNOWN", None, "CONFLICTING"):
            with self.subTest(state=state):
                self.assertFalse(self.ev(mergeable=state)[0])
        pr = {k: v for k, v in PR.items() if k != "mergeable"}
        self.assertFalse(pr_review.evaluate(pr, STATUS, [review()], [], [], EVIDENCE)[0])

    def test_standard_blockers(self):
        for change in ({"state": "MERGED"}, {"isDraft": True}, {"baseRefName": "main"}):
            self.assertFalse(self.ev(**change)[0])
        self.assertFalse(self.ev(status={**STATUS, "state": "failure"})[0])

    def test_missing_wrong_or_failed_build_evidence(self):
        for evidence in (None, {}, {**EVIDENCE, "sha": OLD}, {**EVIDENCE, "success": False}):
            self.assertFalse(self.ev(evidence=evidence)[0])

    def test_stale_review(self):
        self.assertFalse(self.ev([review(commit=OLD)])[0])

    def test_unbound_conversation_never_uses_push_proxy(self):
        for when in (EARLIER, LATER):
            self.assertFalse(self.ev([], [comment("approved", when)])[0])

    def test_conversation_exact_head_binding(self):
        self.assertTrue(self.ev([], [comment("approved " + HEAD)])[0])
        for suffix in (OLD, HEAD[:8]):
            self.assertFalse(self.ev([], [comment("approved " + suffix)])[0])

    def test_other_login_comment_not_authorization(self):
        self.assertFalse(self.ev([], [comment("approved " + HEAD, user="bot")])[0])
        self.assertFalse(self.ev([review(user="bot")])[0])

    def test_formal_external_approval(self):
        self.assertTrue(self.ev([review(body="Looks good", state="APPROVED", user="colleague")])[0])

    def test_generated_formal_approval_rejected(self):
        self.assertFalse(self.ev([review(body="Generated with Claude Code", state="APPROVED", user="colleague")])[0])

    def test_dismissed_and_pending_ignored(self):
        for state in ("DISMISSED", "PENDING"):
            self.assertFalse(self.ev([review(state=state)])[0])

    def test_later_author_withdrawal(self):
        self.assertFalse(self.ev(comments=[comment("wait, do not merge", LATEST)])[0])

    def test_later_reviewer_concern_and_benign_ambiguity(self):
        for body in ("Please wait: scoring incorrect", "Thanks", "Is this fixed?"):
            self.assertFalse(self.ev(comments=[comment(body, LATEST, "colleague")])[0])
        self.assertFalse(self.ev([review(), review("concern", LATEST, user="colleague", id=3)])[0])

    def test_edited_old_comment_becomes_later_concern(self):
        c = comment("wait", EARLIER, "colleague", updated_at=LATEST)
        self.assertFalse(self.ev(comments=[c])[0])

    def test_edited_sha_approval_uses_full_body_binding(self):
        c = comment("approved " + HEAD, EARLIER, updated_at=LATEST)
        self.assertTrue(self.ev([], [c])[0])
        c["body"] = "approved " + OLD
        self.assertFalse(self.ev([], [c])[0])

    def test_malformed_update_timestamp_errors(self):
        for updated in ("bad", "", None, "2026-11-07T14:00:00Z"):
            with self.assertRaises(ValueError):
                self.ev(comments=[comment("wait", updated_at=updated)])

    def test_unknown_login_cannot_supply_formal_approval_or_inline_reply(self):
        r = {**review("", state="APPROVED"), "user": None}
        self.assertFalse(self.ev([r])[0])
        root = comment("fix", EARLIER, "colleague", id=10, path="a.py")
        reply = {**comment("fixed", LATER, id=11, in_reply_to_id=10), "user": None}
        self.assertFalse(self.ev(inline=[root, reply])[0])

    def test_equal_timestamp_ambiguous(self):
        self.assertFalse(self.ev(comments=[comment("wait", LATER, "colleague")])[0])

    def test_human_resolution_requires_fresh_sha_approval(self):
        concern = comment("wait", LATER, "colleague")
        self.assertTrue(self.ev([review(when=LATEST)], [concern])[0])

    def test_changes_requested_until_reviewer_approves(self):
        cr = review("fix", EARLIER, "CHANGES_REQUESTED", "colleague", id=3)
        self.assertFalse(self.ev([review(), cr])[0])
        approved = review("", LATEST, "APPROVED", "colleague", id=4)
        self.assertTrue(self.ev([review(), cr, approved])[0])

    def test_change_request_not_cleared_by_dismissal_stale_or_generated_approval(self):
        cr = review("fix", EARLIER, "CHANGES_REQUESTED", "colleague", id=3)
        for state, body, commit in (("DISMISSED", "", HEAD), ("APPROVED", "", OLD),
                                    ("APPROVED", "Generated with Claude Code", HEAD)):
            later = review(body, LATER, state, "colleague", commit, id=4)
            self.assertFalse(self.ev([review(when=LATEST), cr, later])[0])

    def test_old_external_approval_does_not_survive_dismissal(self):
        approved = review("", EARLIER, "APPROVED", "colleague")
        dismissed = review("", LATER, "DISMISSED", "colleague", id=3)
        self.assertFalse(self.ev([approved, dismissed])[0])

    def test_inline_thread_reply_from_other_login(self):
        root = comment("fix", EARLIER, "colleague", id=10, path="a.py")
        self.assertFalse(self.ev(inline=[root])[0])
        own = comment("follow up", LATER, "colleague", id=11, in_reply_to_id=10)
        self.assertFalse(self.ev(inline=[root, own])[0])
        reply = comment("fixed", LATER, id=12, in_reply_to_id=10)
        self.assertTrue(self.ev(inline=[root, own, reply])[0])

    def test_author_inline_does_not_block(self):
        self.assertTrue(self.ev(inline=[comment("note", EARLIER)])[0])

    def test_unknown_user_later_concern_blocks(self):
        c = {**comment("wait", LATEST), "user": None}
        self.assertFalse(self.ev(comments=[c])[0])

    def test_missing_review_body_or_user_errors(self):
        for key in ("body", "user"):
            r = {k: v for k, v in review().items() if k != key}
            with self.assertRaises(ValueError):
                self.ev([r])

    def test_malformed_decision_fields_raise(self):
        for changed in ({"isDraft": None}, {"headRefOid": "short"}, {"author": None}):
            with self.assertRaises(ValueError):
                self.ev(**changed)
        for changed in ({"submitted_at": "bad"}, {"body": {}}, {"state": "ALIEN"}, {"commit_id": None}):
            with self.assertRaises(ValueError):
                self.ev([{**review(), **changed}])

class ApiTest(unittest.TestCase):
    def test_all_review_comment_pages_retained(self):
        for endpoint in ("pulls/5/reviews", "issues/5/comments", "pulls/5/comments"):
            with mock.patch.object(pr_review, "gh", return_value=json.dumps([[{"id": 1}], [{"id": 2}]])) as gh:
                self.assertEqual([{"id": 1}, {"id": 2}], pr_review.api(endpoint))
            self.assertEqual(("api", "--paginate", "--slurp", endpoint + "?per_page=100"), gh.call_args.args)

    def test_malformed_failed_and_repeated_pages(self):
        for data in (None, {}, [], [None], [[None]], [{"message": "denied"}], [[{"id": 1}], {"message": "failed"}],
                     [[{"id": 1}], [{"id": 1}]], [[{"body": "approved"}]]):
            with self.subTest(data=data), mock.patch.object(pr_review, "gh", return_value=json.dumps(data)), self.assertRaises(ValueError):
                pr_review.api("path")
        with mock.patch.object(pr_review, "gh", return_value="not json"), self.assertRaises(ValueError):
            pr_review.api("path")

    def test_status_context_on_second_page(self):
        pages = [{**STATUS, "total_count": 2, "statuses": [{"context": "other", "state": "success"}]},
                 {**STATUS, "total_count": 2}]
        with mock.patch.object(pr_review, "gh", return_value=json.dumps(pages)) as gh:
            status = pr_review.status_for(HEAD)
        self.assertEqual(2, len(status["statuses"]))
        self.assertIn("--paginate", gh.call_args.args)

    def test_incomplete_inconsistent_malformed_status_pages(self):
        valid = {**STATUS, "total_count": 1}
        for pages in ([], [None], [STATUS], [{**valid, "total_count": 2}],
                      [{**valid, "sha": OLD}], [{**valid, "statuses": None}],
                      [valid, valid], [valid, {**valid, "state": "pending"}],
                      [{**valid, "statuses": [{"context": "x"}]}]):
            with self.subTest(pages=pages), mock.patch.object(pr_review, "gh", return_value=json.dumps(pages)), self.assertRaises(ValueError):
                pr_review.status_for(HEAD)

def setUpModule():
    pr_review.BASE = "staging"

