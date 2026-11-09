"""Run the real terminal API with temporary, constructed data for browser tests."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from terminal.continuous import build
from terminal.tests.test_continuous_terminal import make_inputs


def main():
    with TemporaryDirectory(prefix="nq-terminal-fixture-") as directory:
        root = Path(directory)
        release, cleaned = make_inputs(root, missing=True, extended=True)
        continuous = root / "continuous"
        build(release, cleaned, continuous)
        os.environ.update(
            NQ_DATA_ROOT=str(release), NQ_CONTINUOUS_ROOT=str(continuous),
            NQ_RESEARCH_DEMO="1", NQ_EXPERIMENT_STORE=str(root / "experiments"),
        )
        uvicorn.run("terminal.api:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
