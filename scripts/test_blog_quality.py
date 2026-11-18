"""Tests for the generated-blog article quality gate."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from blog_quality import (BlogPostValidationError, content_fingerprint,
                           should_retry_rejected_post, validate_blog_post)


def article(words=760):
    prose = " ".join(f"research finding number {i} explains the technology clearly." for i in range(words // 7))
    return (
        '---\ntitle: "How New AI Agents Change Software Workflows"\n'
        'description: "A concise factual summary of the reported changes in AI agent workflows."\n'
        'pubDate: 2026-11-18\ntags: [ai, ai-agents, coding]\nauthor: "Astro Tobby"\n---\n\n'
        + "Opening paragraph. " + prose + "\n\n"
        "## Key takeaways\n- First point\n- Second point\n\n"
        "## What changed\nMore explanation.\n\n"
        "## What the evidence shows\nMore evidence.\n\n"
        "## Why it matters\nThe implications.\n\n"
        "## Watch the original video\n<iframe src=\"https://example.test\"></iframe>\n"
    )


class BlogQualityTests(unittest.TestCase):
    def write(self, root, name, content):
        path = Path(root) / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_accepts_article_matching_gemini_contract(self):
        with TemporaryDirectory() as tmp:
            result = validate_blog_post(self.write(tmp, "new-ai-agent-workflows.md", article()))
        self.assertGreaterEqual(result["word_count"], 600)
        self.assertLessEqual(result["word_count"], 1200)
        self.assertEqual(result["h2_count"], 4)

    def test_rejects_short_body(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(BlogPostValidationError) as ctx:
                validate_blog_post(self.write(tmp, "new-ai-agent-workflows.md", article(120)))
        self.assertTrue(any("article body" in item for item in ctx.exception.errors))

    def test_rejects_bad_yaml_frontmatter(self):
        with TemporaryDirectory() as tmp:
            path = self.write(tmp, "new-ai-agent-workflows.md", '---\ntitle: "broken\n---\nbody')
            with self.assertRaises(BlogPostValidationError):
                validate_blog_post(path)

    def test_rejects_invalid_tags_and_title(self):
        content = article().replace(
            'title: "How New AI Agents Change Software Workflows"',
            'title: "A Very Long Headline That Has Far Too Many Words To Meet The Editorial Rule"',
        ).replace("tags: [ai, ai-agents, coding]", "tags: [spam, random, coding]")
        with TemporaryDirectory() as tmp:
            with self.assertRaises(BlogPostValidationError) as ctx:
                validate_blog_post(self.write(tmp, "new-ai-agent-workflows.md", content))
        self.assertTrue(any("title exceeds" in item for item in ctx.exception.errors))
        self.assertTrue(any("unsupported tags" in item for item in ctx.exception.errors))

    def test_unchanged_rejected_post_is_not_retried_but_edits_are(self):
        with TemporaryDirectory() as tmp:
            path = self.write(tmp, "new-ai-agent-workflows.md", article(120))
            entry = {"quality_rejected_sha": content_fingerprint(path)}
            self.assertFalse(should_retry_rejected_post(path, entry))
            path.write_text(article(760), encoding="utf-8")
            self.assertTrue(should_retry_rejected_post(path, entry))

    def test_rejects_missing_why_it_matters(self):
        content = article().replace("## Why it matters", "## Conclusion")
        with TemporaryDirectory() as tmp:
            with self.assertRaises(BlogPostValidationError) as ctx:
                validate_blog_post(self.write(tmp, "new-ai-agent-workflows.md", content))
        self.assertIn("article must include a Why it matters section", ctx.exception.errors)


if __name__ == "__main__":
    unittest.main()
