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


if __name__ == "__main__":
    unittest.main()
