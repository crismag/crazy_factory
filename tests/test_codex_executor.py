"""Read-only Codex CLI adapter: argv contract, JSONL parse, live probe."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_executor import (
    ExecutorRequest,
    ExecutorResult,
    apply_executor_result,
    default_executor,
)
from codex_executor import (
    CODEX_SANDBOX,
    FORBIDDEN_CODEX_FLAGS,
    CodexCodingExecutor,
    build_codex_exec_argv,
    codex_is_logged_in,
    extract_json_object,
    is_factory_engine_root,
    parse_codex_jsonl,
    resolve_codex_bin,
    select_codex_work_root,
)
from crazy_admin import (
    load_registry,
    resolve_project,
    startproject,
)


def _request(app_path: str, assignment: str = "") -> ExecutorRequest:
    return ExecutorRequest(
        objective_id="obj-codex",
        objective_kind="code_birth",
        objective_title="Propose hello module",
        gap="no source",
        why="adapter probe",
        focus="src/hello.py",
        seed_text="tiny hello module",
        app_path=app_path,
        assignment_text=assignment,
    )


def _jsonl(*events: dict) -> str:
    return "".join(json.dumps(event) + "\n" for event in events)


def _codex_ready() -> bool:
    binary = resolve_codex_bin()
    return bool(binary and codex_is_logged_in(binary))


class ArgvContractTests(unittest.TestCase):
    def test_read_only_json_exec_without_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            last = work / "last.txt"
            argv = build_codex_exec_argv(
                "/tmp/fake-codex",
                work_root=work,
                last_message_path=last,
                prompt="propose files",
            )
        self.assertEqual(argv[1], "exec")
        self.assertEqual(argv[argv.index("--sandbox") + 1], CODEX_SANDBOX)
        self.assertIn("--json", argv)
        self.assertIn("--ephemeral", argv)
        self.assertIn("--ignore-user-config", argv)
        for flag in FORBIDDEN_CODEX_FLAGS:
            self.assertNotIn(flag, argv)
        self.assertNotIn("workspace-write", argv)
        self.assertNotIn("danger-full-access", argv)

    def test_refuses_factory_engine_as_work_root(self) -> None:
        with self.assertRaises(ValueError):
            build_codex_exec_argv(
                "/tmp/fake-codex",
                work_root=ROOT,
                last_message_path=ROOT / "last.txt",
                prompt="nope",
            )
        self.assertTrue(is_factory_engine_root(ROOT))
        self.assertIsNone(select_codex_work_root(str(ROOT)))


class JsonlParseTests(unittest.TestCase):
    def test_last_message_and_command_exits(self) -> None:
        stdout = _jsonl(
            {"type": "thread.started", "thread_id": "t"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {
                    "id": "item_0",
                    "type": "agent_message",
                    "text": "working\n",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "item_1",
                    "type": "command_execution",
                    "command": "cat SENTINEL.txt",
                    "exit_code": 0,
                    "status": "completed",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "item_2",
                    "type": "agent_message",
                    "text": '{"files": {"src/hello.py": "HELLO = 1\\n"}}',
                },
            },
            {"type": "turn.completed", "usage": {}},
        )
        parsed = parse_codex_jsonl(stdout)
        self.assertEqual(parsed.command_exit_codes, (0,))
        data = extract_json_object(parsed.last_message)
        self.assertEqual(data, {"files": {"src/hello.py": "HELLO = 1\n"}})

    def test_extracts_fenced_json(self) -> None:
        text = '```json\n{"files": {"src/a.py": "A = 1\\n"}}\n```'
        self.assertEqual(
            extract_json_object(text),
            {"files": {"src/a.py": "A = 1\n"}},
        )


class CodexExecutorMockTests(unittest.TestCase):
    def test_skips_when_missing_binary(self) -> None:
        out = CodexCodingExecutor(binary="", logged_in=True).execute(
            _request("/tmp")
        )
        self.assertFalse(out.ok)
        self.assertEqual(out.reason, "codex_not_installed")

    def test_skips_when_not_logged_in(self) -> None:
        out = CodexCodingExecutor(
            binary="/tmp/fake-codex",
            logged_in=False,
        ).execute(_request("/tmp"))
        self.assertFalse(out.ok)
        self.assertEqual(out.reason, "codex_not_authenticated")

    def test_file_map_is_confined_and_not_written_by_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "SENTINEL.txt").write_text("keep\n", encoding="utf-8")

            def run_exec(argv, **_kwargs):  # type: ignore[no-untyped-def]
                self.assertEqual(
                    argv[argv.index("--sandbox") + 1], "read-only"
                )
                self.assertNotIn(
                    "--dangerously-bypass-approvals-and-sandbox", argv
                )
                self.assertEqual(argv[argv.index("-C") + 1], str(work))
                last = Path(argv[argv.index("-o") + 1])
                payload = {
                    "files": {
                        "src/hello.py": "HELLO = 1\n",
                        "scripts/pwn.py": "print(1)\n",
                    }
                }
                last.write_text(json.dumps(payload), encoding="utf-8")
                stdout = _jsonl(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_1",
                            "type": "command_execution",
                            "exit_code": 0,
                            "status": "completed",
                        },
                    },
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_2",
                            "type": "agent_message",
                            "text": json.dumps(payload),
                        },
                    },
                )
                return subprocess.CompletedProcess(argv, 0, stdout, "")

            out = CodexCodingExecutor(
                binary="/tmp/fake-codex",
                logged_in=True,
                run_exec=run_exec,
            ).execute(_request(str(work)))
            self.assertTrue(out.ok)
            self.assertEqual(out.provider, "codex")
            self.assertEqual(out.files, {"src/hello.py": "HELLO = 1\n"})
            self.assertNotIn("scripts/pwn.py", out.files)
            self.assertIn("session_exit=0", out.summary)
            self.assertFalse((work / "src" / "hello.py").exists())
            self.assertEqual(
                (work / "SENTINEL.txt").read_text(encoding="utf-8"), "keep\n"
            )

    def test_session_exit_nonzero_without_files_is_failure(self) -> None:
        def run_exec(argv, **_kwargs):  # type: ignore[no-untyped-def]
            return subprocess.CompletedProcess(argv, 2, "", "fail")

        out = CodexCodingExecutor(
            binary="/tmp/fake-codex",
            logged_in=True,
            run_exec=run_exec,
        ).execute(_request("/tmp"))
        self.assertFalse(out.ok)
        self.assertEqual(out.reason, "codex_session_exit_2")

    def test_env_forces_codex_executor(self) -> None:
        with patch.dict(os.environ, {"CRAZY_FACTORY_EXECUTOR": "codex"}):
            executor = default_executor()
        self.assertIsInstance(executor, CodexCodingExecutor)
        self.assertEqual(executor.name, "codex")


class CodexLiveProbeTests(unittest.TestCase):
    @unittest.skipUnless(_codex_ready(), "codex CLI is not authenticated")
    def test_live_read_only_exec_proposes_file_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            sentinel = work / "SENTINEL.txt"
            sentinel.write_text("live-keep\n", encoding="utf-8")
            digest = hashlib.sha256(sentinel.read_bytes()).hexdigest()
            assignment = (
                "Implement a one-line Python module. The JSON files map "
                "must include src/hello.py whose content is exactly "
                "HELLO = 1 followed by a newline. Returning an empty "
                "files object is incorrect. Do not write the tree; the "
                "factory will apply the JSON."
            )
            out = CodexCodingExecutor().execute(
                _request(str(work), assignment=assignment)
            )
            self.assertTrue(out.ok, f"{out.reason}: {out.summary}")
            self.assertEqual(out.provider, "codex")
            self.assertIn("src/hello.py", out.files)
            self.assertIn("HELLO", out.files["src/hello.py"])
            self.assertNotIn("scripts/pwn.py", out.files)
            names = sorted(path.name for path in work.iterdir())
            self.assertEqual(names, ["SENTINEL.txt"])
            self.assertEqual(
                hashlib.sha256(sentinel.read_bytes()).hexdigest(), digest
            )
            self.assertIn("session_exit=", out.summary)


class CodexApplyStillConfinedTests(unittest.TestCase):
    def test_apply_writes_only_through_factory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "apps").mkdir()
            (root / "config/projects.yaml").write_text(
                "projects:\n", encoding="utf-8"
            )
            (root / "config/factory.yaml").write_text(
                "factory:\n"
                '  mode: "dry_run"\n'
                '  state_dir: "state"\n'
                "  max_lines_per_file: 200\n"
                "  max_files_per_run: 5\n"
                "proposal_application:\n  allow_apply: false\n"
                "validation:\n  allow_run: false\n"
                "git:\n  allow_auto_commit: false\n",
                encoding="utf-8",
            )
            (root / "config/models.yaml").write_text(
                "models:\n  planner: x\n  architect: x\n"
                "  coder: x\n  test_builder: x\n",
                encoding="utf-8",
            )
            startproject("probe", "apps/probe", root=root)
            project = resolve_project(load_registry(root), "probe")
            result = CodexCodingExecutor(
                binary="",
                logged_in=True,
            ).execute(_request(str(root / "apps/probe")))
            self.assertFalse(result.ok)
            written, err = apply_executor_result(
                ExecutorResult(
                    ok=True,
                    provider="codex",
                    summary="fixture",
                    files={"src/hello.py": "HELLO = 1\n"},
                ),
                project,
                root,
            )
            self.assertIsNone(err)
            self.assertEqual(written, ["src/hello.py"])
            self.assertEqual(
                (root / "apps/probe/src/hello.py").read_text(encoding="utf-8"),
                "HELLO = 1\n",
            )


if __name__ == "__main__":
    unittest.main()
