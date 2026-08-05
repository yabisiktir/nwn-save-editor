"""The CI workflow, checked against the build script it drives.

These cannot run the workflow — that needs GitHub — but they can catch the way
it rots: a path renamed in build_app.py while the workflow still names the old
one, which shows up as a green build uploading nothing, or a red one on a runner
nobody looks at for a week.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "build.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_exists_and_parses(workflow):
    assert set(workflow["jobs"]) == {"test", "build", "release"}


def test_it_builds_on_every_os_it_ships_for(workflow):
    """No cross-building: each artifact is made on the OS it targets."""
    labels = [m["label"] for m in workflow["jobs"]["build"]["strategy"]["matrix"]["include"]]
    assert any("Windows" in label for label in labels)
    assert any("Linux" in label for label in labels)
    assert any("macOS" in label for label in labels)


def test_macos_is_built_for_both_cpus(workflow):
    """PySide6 wheels are per-arch, so one macOS build serves only one CPU."""
    runners = [m["os"] for m in workflow["jobs"]["build"]["strategy"]["matrix"]["include"]]
    assert "macos-14" in runners, "Apple Silicon"
    assert "macos-13" in runners, "Intel"


def test_it_runs_the_same_build_script_a_developer_runs(workflow):
    steps = workflow["jobs"]["build"]["steps"]
    assert any("scripts/build_app.py" in str(step.get("run", "")) for step in steps)


def test_the_uploaded_paths_match_what_the_build_script_produces(workflow):
    """The quiet failure: a renamed artifact and a workflow still globbing the
    old name. `if-no-files-found: error` turns that red, but only if the globs
    are right in the first place."""
    upload = next(
        step for step in workflow["jobs"]["build"]["steps"]
        if "upload-artifact" in str(step.get("uses", ""))
    )
    globs = upload["with"]["path"]
    driver = (_ROOT / "scripts" / "build_app.py").read_text(encoding="utf-8")
    for suffix, produced_by in ((".dmg", "package_macos"), (".zip", "package_windows"),
                                (".tar.gz", "package_linux")):
        assert suffix in globs, f"{suffix} is produced but never uploaded"
        assert produced_by in driver
    assert upload["with"]["if-no-files-found"] == "error"


def test_a_frozen_binary_that_cannot_start_fails_the_build(workflow):
    """The failure mode a build alone never catches."""
    steps = workflow["jobs"]["build"]["steps"]
    assert sum("Smoke test" in str(step.get("name", "")) for step in steps) >= 3


def test_the_smoke_tests_name_the_paths_pyinstaller_actually_writes(workflow):
    """EXE(name=...) and COLLECT(name=...) in the spec decide these."""
    spec = (_ROOT / "packaging" / "nwn-save-editor.spec").read_text(encoding="utf-8")
    assert 'name="nwn-save-editor"' in spec       # the executable and the folder
    assert 'name="NWN Save Editor.app"' in spec   # the macOS bundle

    steps = str(workflow["jobs"]["build"]["steps"])
    assert "NWN Save Editor.app/Contents/MacOS/nwn-save-editor" in steps
    assert "dist/nwn-save-editor/nwn-save-editor" in steps


def test_tests_run_before_anything_is_built(workflow):
    assert workflow["jobs"]["build"]["needs"] == "test"


def test_a_release_is_only_cut_from_a_tag_and_starts_as_a_draft(workflow):
    release = workflow["jobs"]["release"]
    assert "refs/tags/v" in release["if"]
    publish = next(s for s in release["steps"] if "gh-release" in str(s.get("uses", "")))
    assert publish["with"]["draft"] is True, "a human should see the artifacts first"


def test_linux_gets_the_libraries_qt_needs(workflow):
    """Qt will not start on a bare ubuntu runner; this is the usual first red."""
    steps = str(workflow["jobs"]["build"]["steps"])
    for library in ("libegl1", "libxkbcommon-x11-0", "libxcb-cursor0"):
        assert library in steps


def test_the_suite_does_not_depend_on_how_pytest_was_invoked():
    """`python -m pytest` puts the working directory on sys.path; `pytest` does not.

    Several test modules share fixtures through `from tests.test_save_editor
    import ...`, so under the bare console script — which is what CI runs — they
    failed to import and the whole collection was interrupted. The suite passed
    locally the whole time because it was being run the other way.
    """
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text())["tool"]["pytest"]["ini_options"]
    assert "." in config["pythonpath"], (
        "the repo root must be importable, or `pytest` and `python -m pytest` "
        "disagree about whether the suite even collects"
    )


def test_the_workflow_tests_can_actually_run_in_ci():
    """This module needs PyYAML. Undeclared, it skipped exactly where it matters."""
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    dev = tomllib.loads(pyproject.read_text())["project"]["optional-dependencies"]["dev"]
    assert any(name.lower().startswith("pyyaml") for name in dev), dev


def test_no_test_module_calls_a_posix_only_function_while_importing():
    """One such call takes down the entire job, not just its own test.

    `os.geteuid()` sat in a `@pytest.mark.skipif(...)` decorator — evaluated at
    import time — and does not exist on Windows. Collection died there, so every
    other test in the suite went unrun and the failure looked nothing like its
    cause. Guard the call, do not merely skip the test.
    """
    import ast
    from pathlib import Path

    posix_only = {
        "geteuid", "getuid", "getgid", "getegid", "getgroups",
        "fork", "chown", "symlink", "mkfifo", "setuid", "setgid",
    }
    offenders = []
    for path in sorted(Path(__file__).resolve().parent.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # module level only — that is what import runs
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name in posix_only and not _is_guarded(node):
                    offenders.append(f"{path.name}:{call.lineno} {name}()")
    assert not offenders, (
        "called at import time, so Windows dies collecting: " + ", ".join(offenders)
    )


def _is_guarded(node) -> bool:
    """Whether the statement checks availability before calling."""
    import ast

    return any(
        isinstance(inner, ast.Call)
        and getattr(inner.func, "id", None) == "hasattr"
        for inner in ast.walk(node)
    )
