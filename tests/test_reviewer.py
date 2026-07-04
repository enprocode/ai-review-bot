import json
import unittest
from types import SimpleNamespace

from src import reviewer


class DedupExistingTests(unittest.TestCase):
    def test_fallback_body_is_deduped_when_full_header_matches(self):
        fallback_body = "### 🤖 AIレビューBot（行特定不可の指摘）\n\n- test"

        class FakeReview:
            def __init__(self, body):
                self.body = body

        class FakePR:
            def get_review_comments(self):
                return []

            def get_reviews(self):
                return [FakeReview(body=fallback_body)]

        _, fallback = reviewer.dedup_existing(FakePR(), [], [fallback_body])
        self.assertEqual(fallback, [])

    def test_inline_comment_is_filtered_when_position_and_body_match(self):
        inline_candidate = {"path": "foo.py", "position": 10, "body": "comment"}

        class FakeReviewComment:
            def __init__(self, path, position, body):
                self.path = path
                self.position = position
                self.line = None
                self.body = body

        class FakePR:
            def get_review_comments(self):
                return [
                    FakeReviewComment(
                        path="foo.py",
                        position=10,
                        body="comment",
                    )
                ]

            def get_reviews(self):
                return []

        inline, _ = reviewer.dedup_existing(FakePR(), [inline_candidate], [])
        self.assertEqual(inline, [])


class ReviewedMarkerTests(unittest.TestCase):
    def test_finds_latest_marker(self):
        sha1, sha2 = "a" * 40, "b" * 40

        class FakeReview:
            def __init__(self, body):
                self.body = body

        class FakePR:
            def get_reviews(self):
                return [
                    FakeReview(f"LGTM\n\n{reviewer.reviewed_marker(sha1)}"),
                    FakeReview("普通のコメント"),
                    FakeReview(reviewer.reviewed_marker(sha2)),
                ]

        self.assertEqual(reviewer.find_last_reviewed_sha(FakePR()), sha2)

    def test_returns_none_without_marker(self):
        class FakePR:
            def get_reviews(self):
                return []

        self.assertIsNone(reviewer.find_last_reviewed_sha(FakePR()))


class BuildPromptTests(unittest.TestCase):
    def test_style_directive_is_included_when_style_is_provided(self):
        file_stub = SimpleNamespace(filename="foo.py", patch="+print('hello')")
        prompt = reviewer.build_prompt(
            [file_stub],
            user_prompt="",
            max_diff_chars=1000,
            style="concise",
        )
        self.assertIn("レビューは「concise」なトーンでお願いします。", prompt)

    def test_style_directive_is_omitted_when_style_is_none(self):
        file_stub = SimpleNamespace(filename="foo.py", patch="+print('hello')")
        prompt = reviewer.build_prompt(
            [file_stub],
            user_prompt="",
            max_diff_chars=1000,
            style=None,
        )
        self.assertNotIn("トーンでお願いします。", prompt)

    def test_language_defaults_to_japanese(self):
        file_stub = SimpleNamespace(filename="foo.py", patch="+print('hello')")
        prompt = reviewer.build_prompt([file_stub], user_prompt="", max_diff_chars=1000)
        self.assertIn("必ず日本語で記述してください", prompt)

    def test_language_can_be_overridden(self):
        file_stub = SimpleNamespace(filename="foo.py", patch="+print('hello')")
        prompt = reviewer.build_prompt([file_stub], user_prompt="", max_diff_chars=1000,
                                       language="English")
        self.assertIn("必ずEnglishで記述してください", prompt)

    def test_diff_is_truncated_when_overflow(self):
        long_patch = "+line\n" * 100
        file_stub = SimpleNamespace(filename="foo.py", patch=long_patch)
        prompt = reviewer.build_prompt(
            [file_stub],
            user_prompt="",
            max_diff_chars=50,
            style=None,
        )
        self.assertIn("=== foo.py ===", prompt)
        self.assertLess(prompt.count("+line"), 100)


class NoFindingsBodyTests(unittest.TestCase):
    def test_success_path_returns_lgtm_only(self):
        body = reviewer.build_no_findings_body("", True)
        self.assertIn("LGTM! 🎉 特に指摘はありません。", body)
        self.assertNotIn("レビュー内容を生成できませんでした。", body)

    def test_failure_path_preserves_message(self):
        body = reviewer.build_no_findings_body("エラーが発生しました", False)
        self.assertIn("エラーが発生しました", body)
        self.assertNotIn("LGTM! 🎉 特に指摘はありません。", body)

    def test_failure_path_handles_empty_message(self):
        body = reviewer.build_no_findings_body("", False)
        self.assertIn("モデルから有効な応答が得られませんでした", body)


class ExtractOutputTextTests(unittest.TestCase):
    def test_extracts_chat_completion_content(self):
        resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))]
        )
        self.assertEqual(reviewer.extract_output_text(resp), "hello")

    def test_extracts_from_dict_response(self):
        resp = {"choices": [{"message": {"content": "hello"}}]}
        self.assertEqual(reviewer.extract_output_text(resp), "hello")

    def test_returns_empty_string_when_no_text(self):
        resp = {"choices": [{"message": {"content": None}}]}
        self.assertEqual(reviewer.extract_output_text(resp), "")


class SkipReasonTests(unittest.TestCase):
    class FakeErr(Exception):
        def __init__(self, msg, status_code=None):
            super().__init__(msg)
            self.status_code = status_code

    def test_detects_openrouter_credit_exhaustion(self):
        self.assertIsNotNone(reviewer.skip_reason(self.FakeErr("Insufficient credits", 402)))

    def test_detects_openai_quota_exhaustion(self):
        self.assertIsNotNone(reviewer.skip_reason(self.FakeErr("insufficient_quota", 429)))

    def test_detects_auth_error(self):
        self.assertIn("認証エラー", reviewer.skip_reason(self.FakeErr("invalid key", 401)))

    def test_returns_none_for_other_errors(self):
        self.assertIsNone(reviewer.skip_reason(self.FakeErr("server error", 500)))


class ExtractRetryAfterTests(unittest.TestCase):
    def test_reads_header_from_response(self):
        class FakeResp:
            headers = {"Retry-After": "12"}

        class FakeErr(Exception):
            response = FakeResp()

        self.assertEqual(reviewer.extract_retry_after(FakeErr("x")), 12.0)

    def test_reads_retry_after_seconds_from_message(self):
        err = Exception("... 'retry_after_seconds': 45.2 ...")
        self.assertEqual(reviewer.extract_retry_after(err), 45.2)

    def test_falls_back_to_default_when_no_info(self):
        self.assertEqual(reviewer.extract_retry_after(Exception("no info")), 30.0)

    def test_caps_excessive_wait(self):
        self.assertEqual(reviewer.extract_retry_after(Exception("'retry_after_seconds': 999")), 60.0)


class ParseFindingsTests(unittest.TestCase):
    def test_unwraps_dict_with_findings_list(self):
        raw = json.dumps({"findings": [{"severity": "major", "file": "a.py", "line": 1, "title": "x"}]})
        findings, parsed = reviewer.parse_findings_from_text(raw, max_findings=5)
        self.assertTrue(parsed)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["file"], "a.py")


    def test_parses_plain_json_string(self):
        raw = json.dumps([{
            "severity": "major",
            "file": "foo.py",
            "line": 10,
            "title": "Issue",
            "detail": "Fix it",
        }])
        findings, parsed = reviewer.parse_findings_from_text(raw, max_findings=5)
        self.assertTrue(parsed)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "MAJOR")

    def test_salvages_truncated_json(self):
        raw = ('{"findings":[{"severity":"MAJOR","file":"a.py","line":1,"title":"x","detail":"d"},'
               '{"severity":"MINOR","file":"b.py","li')  # 2件目の途中で切断
        findings, parsed = reviewer.parse_findings_from_text(raw, max_findings=5)
        self.assertTrue(parsed)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["file"], "a.py")

    def test_returns_false_when_no_json(self):
        findings, parsed = reviewer.parse_findings_from_text("plain text", max_findings=5)
        self.assertFalse(parsed)
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
