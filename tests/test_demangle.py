"""demangle renames real files, so every safety property gets a test.

Each case builds the exact on-disk shape the mangling leaves behind: the real
file under a '-2' name, and an empty directory squatting on the name it wants.
"""

import json
import os
import subprocess
import sys

import pytest

TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "demangle.py")

sys.path.insert(0, os.path.dirname(TOOL))
from demangle import build_plan, target_of  # noqa: E402


@pytest.fixture
def archive(tmp_path):
    """The tree under test, kept one level below the working directory.

    demangle writes its plan and journal to the current directory, so tests run
    from tmp_path and point at tmp_path/archive. That is the same shape as
    running the tool from the repo against a drive somewhere else, and it keeps
    those outputs from showing up as changes to the tree being checked.
    """
    d = tmp_path / "archive"
    d.mkdir()
    return d


def mangle(root, name, body="audio"):
    """Write `name` as the archive would have: file suffixed, name held by a dir."""
    stem, dot, ext = name.partition(".")
    (root / f"{stem}-2{dot}{ext}").write_text(body)
    (root / name).mkdir()


def run(*args, cwd):
    return subprocess.run([sys.executable, TOOL, *args], cwd=str(cwd),
                          capture_output=True, text=True)


def snapshot(root):
    """Every file as (relative path, size, inode) — the inode survives renaming."""
    out = set()
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            p = os.path.join(dirpath, f)
            st = os.stat(p)
            out.add((os.path.relpath(p, root), st.st_size, st.st_ino))
    return out


def subdirs(root):
    return sorted(d for d in os.listdir(root) if (root / d).is_dir())


def journals(workdir):
    return [f for f in os.listdir(workdir) if f.startswith("demangle-journal-")]


def test_target_of_reads_the_marker():
    assert target_of("01 Song-2.mp3") == "01 Song.mp3"
    assert target_of("-2.DS_Store") == ".DS_Store"          # stem is empty
    assert target_of("Library 2010-06-23-2") == "Library 2010-06-23"
    assert target_of("plain.mp3") is None


def test_target_of_handles_a_marker_before_an_interior_dot():
    # real case: "Oysters Vs. Flipping Channel.mp3" mangles to "Oysters Vs-2. ..."
    assert target_of("Oysters Vs-2. Flipping Channel.mp3") \
        == "Oysters Vs. Flipping Channel.mp3"


def test_dry_run_changes_nothing(archive):
    mangle(archive, "song.mp3")
    before = snapshot(archive)

    assert run(str(archive), cwd=archive.parent).returncode == 0

    assert snapshot(archive) == before
    assert (archive / "song.mp3").is_dir()
    assert not journals(archive.parent)


def test_apply_restores_names_keeping_the_same_files(archive):
    for n in ("a.mp3", "b.mp3", "c.m4a"):
        mangle(archive, n, body=n * 3)
    before = {(size, ino) for _, size, ino in snapshot(archive)}

    assert run(str(archive), "--apply", cwd=archive.parent).returncode == 0

    after = snapshot(archive)
    assert {(size, ino) for _, size, ino in after} == before, "a file was lost or rewritten"
    assert {p for p, _, _ in after} == {"a.mp3", "b.mp3", "c.m4a"}
    assert subdirs(archive) == []


def test_second_run_is_a_no_op(archive):
    mangle(archive, "song.mp3")
    run(str(archive), "--apply", cwd=archive.parent)
    after_first = snapshot(archive)

    run(str(archive), "--apply", cwd=archive.parent)

    assert snapshot(archive) == after_first


def test_a_file_genuinely_named_with_the_marker_is_left_alone(archive):
    # no empty-directory twin, so '-2' really is part of its name
    (archive / "Track-2.mp3").write_text("keep me")

    run(str(archive), "--apply", cwd=archive.parent)

    assert (archive / "Track-2.mp3").is_file()
    assert not (archive / "Track.mp3").exists()


def test_double_mangled_name_stops_after_one_step(archive):
    # "01 1-2.mp3" was the original name, so it mangled to "01 1-2-2.mp3"
    (archive / "01 1-2-2.mp3").write_text("x")
    (archive / "01 1-2.mp3").mkdir()

    run(str(archive), "--apply", cwd=archive.parent)
    assert (archive / "01 1-2.mp3").is_file()

    run(str(archive), "--apply", cwd=archive.parent)   # must not strip a second time
    assert (archive / "01 1-2.mp3").is_file()
    assert not (archive / "01 1.mp3").exists()


def test_refuses_when_the_twin_directory_holds_anything(archive):
    mangle(archive, "song.mp3")
    (archive / "song.mp3" / "keepme.txt").write_text("real content")
    before = snapshot(archive)

    result = run(str(archive), "--apply", cwd=archive.parent)

    assert result.returncode == 1
    # It must decline while still planning, not blow up partway through: a
    # traceback here would mean it had already started renaming.
    assert "REFUSING TO RUN" in result.stderr
    assert "Traceback" not in result.stderr
    assert "twin directory is not empty" in result.stderr
    assert not journals(archive.parent)
    assert snapshot(archive) == before
    assert (archive / "song.mp3" / "keepme.txt").read_text() == "real content"


def test_refuses_when_the_target_name_is_already_a_file(archive):
    (archive / "song-2.mp3").write_text("mangled")
    (archive / "song.mp3").write_text("already here")
    before = snapshot(archive)

    result = run(str(archive), "--apply", cwd=archive.parent)
    assert result.returncode == 1
    assert "REFUSING TO RUN" in result.stderr
    assert "Traceback" not in result.stderr
    assert snapshot(archive) == before


def test_one_conflict_stops_the_whole_run(archive):
    """All-or-nothing: a single problem must not leave a half-renamed tree."""
    for n in ("a.mp3", "b.mp3"):
        mangle(archive, n)
    (archive / "bad-2.mp3").write_text("x")
    (archive / "bad.mp3").mkdir()
    (archive / "bad.mp3" / "occupied.txt").write_text("x")
    before = snapshot(archive)

    result = run(str(archive), "--apply", cwd=archive.parent)
    assert result.returncode == 1
    assert "REFUSING TO RUN" in result.stderr
    assert "Traceback" not in result.stderr
    assert snapshot(archive) == before, "renamed something despite refusing"
    assert not journals(archive.parent)


def test_undo_restores_the_tree_exactly(archive):
    for n in ("a.mp3", "b.mp3"):
        mangle(archive, n)
    before_files, before_dirs = snapshot(archive), subdirs(archive)

    run(str(archive), "--apply", cwd=archive.parent)
    written = journals(archive.parent)
    assert len(written) == 1

    assert run("--undo", str(archive.parent / written[0]),
               cwd=archive.parent).returncode == 0

    assert snapshot(archive) == before_files
    assert subdirs(archive) == before_dirs


def test_a_later_run_cannot_truncate_an_earlier_journal(archive):
    """The journal is the only undo; one run must never overwrite another's."""
    mangle(archive, "a.mp3")
    run(str(archive), "--apply", cwd=archive.parent)
    first = journals(archive.parent)[0]
    entries = len((archive.parent / first).read_text(encoding="utf-8").splitlines())
    assert entries == 1

    mangle(archive, "b.mp3")
    run(str(archive), "--apply", cwd=archive.parent)

    still = len((archive.parent / first).read_text(encoding="utf-8").splitlines())
    assert still == entries, "an earlier journal was overwritten"


def test_journal_records_both_ends_of_every_rename(archive):
    mangle(archive, "song.mp3")
    run(str(archive), "--apply", cwd=archive.parent)

    written = journals(archive.parent)[0]
    line = json.loads((archive.parent / written).read_text(encoding="utf-8").splitlines()[0])
    assert line["from"].endswith("song-2.mp3")
    assert line["to"].endswith("song.mp3")


def test_an_unreadable_directory_raises_rather_than_being_misread(archive):
    """Reading it as 'occupied' would look like a conflict that isn't there."""
    locked = archive / "locked"
    locked.mkdir()
    (locked / "inner.mp3").write_text("x")
    os.chmod(locked, 0o000)
    try:
        with pytest.raises(PermissionError):
            build_plan(str(archive))
    finally:
        os.chmod(locked, 0o755)
