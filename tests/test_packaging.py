"""The files that build and run the container work from a Windows checkout too (2026-10-28: Git for Windows
turned start.sh's line endings into CRLF and the container stopped with "exec ./start.sh: no such file")."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_checkouts_keep_unix_line_endings_except_batch_files():
    attrs = (ROOT / ".gitattributes").read_text().split("\n")
    assert "* text=auto eol=lf" in attrs and "*.bat text eol=crlf" in attrs


def test_the_image_strips_windows_line_endings_before_running_start_sh():
    lines = (ROOT / "Dockerfile").read_text().splitlines()
    strip = next(i for i, ln in enumerate(lines) if "sed -i 's/\\r$//' start.sh" in ln)
    copy = next(i for i, ln in enumerate(lines) if ln.startswith("COPY") and "start.sh" in ln)
    assert copy < strip and lines[-1].startswith("ENTRYPOINT")


def test_the_strip_command_fixes_a_crlf_script(tmp_path):
    script = tmp_path / "start.sh"
    script.write_bytes(b"#!/bin/sh\r\necho ok\r\n")
    subprocess.run(["sed", "-i", r"s/\r$//", str(script)], check=True)
    assert script.read_bytes() == b"#!/bin/sh\necho ok\n"
    assert subprocess.run(["sh", str(script)], capture_output=True, text=True).stdout == "ok\n"


def test_shell_scripts_in_the_repository_have_unix_line_endings():
    for f in [ROOT / "start.sh", *ROOT.glob("tests/*.sh")]:
        assert b"\r\n" not in f.read_bytes(), f
