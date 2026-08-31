import unittest
from pathlib import Path


class NotionPublishWorkflowSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow_path = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "notion-work-publish.yml"
        )
        cls.publish = workflow_path.read_text(encoding="utf-8").split(
            "\n  publish:", 1
        )[1]

    def test_exact_review_is_rechecked_before_ready(self):
        review_check = self.publish.index(
            'repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100'
        )
        ready = self.publish.index('gh pr ready "$PR_NUMBER"')

        self.assertLess(review_check, ready)
        self.assertIn('.commit_id == $sha', self.publish)
        self.assertIn('contains($marker)', self.publish)

    def test_stale_auto_merge_is_disabled_before_ready(self):
        disable_auto = self.publish.index("--disable-auto")
        ready = self.publish.index('gh pr ready "$PR_NUMBER"')

        self.assertLess(disable_auto, ready)

    def test_merge_is_bound_to_reviewed_head(self):
        self.assertIn('--match-head-commit "$EXPECTED_HEAD"', self.publish)
        self.assertIn('La tête a changé pendant la sortie du brouillon.', self.publish)


if __name__ == "__main__":
    unittest.main()
