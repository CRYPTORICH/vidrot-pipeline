import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "daily-pipeline.yml"
COMMIT = ROOT / "scripts" / "commit_batch.sh"


def git(repo, *args, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


class GitignoreTests(unittest.TestCase):
    def ignored(self, path):
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", path],
            cwd=ROOT,
            check=False,
        )
        return result.returncode == 0

    def test_prompt_text_is_tracked_and_video_is_not(self):
        self.assertFalse(self.ignored("prompts/batch_test.json"))
        self.assertFalse(self.ignored("output/captions_batch.json"))
        self.assertFalse(self.ignored("output/generate_instructions.txt"))
        self.assertFalse(self.ignored("config/trending_cache.json"))
        self.assertTrue(self.ignored("output/000_channel.mp4"))
        self.assertTrue(self.ignored(".env"))
        self.assertTrue(self.ignored("config/session.json"))


class HistoricalFailureTests(unittest.TestCase):
    def test_git_add_of_ignored_prompts_exits_nonzero(self):
        """The daily job died on this from the first run on 2026-06-17."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q")
            git(repo, "config", "user.email", "test@example.com")
            git(repo, "config", "user.name", "test")
            (repo / ".gitignore").write_text("prompts/\noutput/\n")
            (repo / "prompts").mkdir()
            (repo / "output").mkdir()
            (repo / "config").mkdir()
            (repo / "prompts" / "batch.json").write_text("{}\n")
            (repo / "output" / "captions.json").write_text("{}\n")
            (repo / "config" / "trending_cache.json").write_text("{}\n")
            result = git(
                repo,
                "add",
                "prompts/",
                "output/",
                "config/trending_cache.json",
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("ignored", result.stderr.lower())


class CommitScriptTests(unittest.TestCase):
    def test_commit_script_keeps_text_and_drops_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.email", "test@example.com")
            git(repo, "config", "user.name", "test")
            (repo / ".gitignore").write_text((ROOT / ".gitignore").read_text())
            (repo / "prompts").mkdir()
            (repo / "output").mkdir()
            (repo / "config").mkdir()
            (repo / "prompts" / "batch_test.json").write_text('[{"channel": "X"}]\n')
            (repo / "output" / "captions_batch_test.json").write_text("{}\n")
            (repo / "output" / "generate_instructions.txt").write_text("make clips\n")
            (repo / "output" / "000_channel.mp4").write_bytes(b"video")
            (repo / "config" / "trending_cache.json").write_text('{"trending": ["x"]}\n')
            (repo / "config" / "session.json").write_text('{"secret": true}\n')

            env = os.environ.copy()
            env["PUSH"] = "0"
            result = subprocess.run(
                ["bash", str(COMMIT)],
                cwd=repo,
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            tracked = git(repo, "ls-tree", "-r", "HEAD", "--name-only").stdout.split()

        self.assertIn("prompts/batch_test.json", tracked)
        self.assertIn("output/captions_batch_test.json", tracked)
        self.assertIn("output/generate_instructions.txt", tracked)
        self.assertIn("config/trending_cache.json", tracked)
        self.assertNotIn("output/000_channel.mp4", tracked)
        self.assertNotIn("config/session.json", tracked)

    def test_second_run_with_no_changes_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q", "-b", "main")
            (repo / "prompts").mkdir()
            (repo / "config").mkdir()
            (repo / "prompts" / "batch.json").write_text("{}\n")
            (repo / "config" / "trending_cache.json").write_text("{}\n")
            env = os.environ.copy()
            env["PUSH"] = "0"
            first = subprocess.run(["bash", str(COMMIT)], cwd=repo, check=False, env=env, capture_output=True, text=True)
            second = subprocess.run(["bash", str(COMMIT)], cwd=repo, check=False, env=env, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("No changes", second.stdout)


class WorkflowFileTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()

    def test_schedule_moved_off_github(self):
        self.assertNotIn("cron:", self.text)
        self.assertIn("local console", self.text)
        self.assertNotIn("if: false", self.text)

    def test_tests_run_in_actions(self):
        self.assertIn("python -m unittest discover -s tests -v", self.text)

    def test_commit_script_still_skips_ci(self):
        self.assertIn("[skip ci]", COMMIT.read_text())


if __name__ == "__main__":
    unittest.main()
