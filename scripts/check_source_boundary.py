"""Check every reachable Git blob against the source-only publication boundary.

This checks paths, file types, empty trust registries, and common credential
formats. Human review is still required for values embedded in source code.
"""
import json
from pathlib import PurePosixPath
import re
import subprocess
import sys


def git(*args):
    return subprocess.check_output(["git", *args])


JSON_PATHS = {
    "config/research.example.json",
    "config/approved_evidence.json",
    "backtester/vendor/lightweight-charts-source.json",
}
SOURCE_SUFFIXES = {".py", ".js", ".html", ".md", ".txt", ".lock", ".toml", ".ini", ".yml"}
DOTFILES = {".gitignore", ".gitattributes", ".env.example"}
FORBIDDEN_ROOTS = {"data", "results", "reports", "calendars", "api", "frontend"}
SECRET = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|sk-[A-Za-z0-9]{35,})")


def main():
    commits = git("rev-list", "--all").decode().splitlines()
    entries = set()
    for commit in commits:
        for row in git("ls-tree", "-rz", commit).split(b"\0"):
            if row:
                header, name = row.split(b"\t", 1)
                mode, kind, sha = header.split()
                entries.add((kind.decode(), sha.decode(), name.decode()))
    problems = []
    checked = 0
    for kind, sha, name in sorted(entries):
        if kind != "blob":
            problems.append(f"Nested repository is not allowed: {name}")
            continue
        checked += 1
        path = PurePosixPath(name)
        if (path.parts[0] in FORBIDDEN_ROOTS
                or name.startswith(("backtester/nq_", "backtester/spy_", "tests/test_nq_", "tests/test_spy_"))
                or (name not in JSON_PATHS and name not in DOTFILES and path.suffix not in SOURCE_SUFFIXES)):
            problems.append(f"Disallowed historical path or file type: {name}")
        content = git("cat-file", "blob", sha)
        if b"\0" in content or SECRET.search(content):
            problems.append(f"Binary contents or credential pattern: {name}")
        if name == "config/approved_evidence.json":
            document = json.loads(content)
            if document != {"version": 1, "capture_manifests": [], "certification_ledgers": []}:
                problems.append("The published evidence registry must be empty")
        if name == ".env.example" and content.splitlines()[-1:] != [b"DATABENTO_API_KEY="]:
            problems.append("Credential template must contain an empty key")
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"Source boundary passed: {checked} blobs across all reachable history.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
