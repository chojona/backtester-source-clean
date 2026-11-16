"""Persistent one-shot custody for the built-in synthetic holdout rehearsal."""

from dataclasses import asdict
from datetime import date
from pathlib import Path

from .artifacts import _publish, canonical_json, digest
from .evaluation import evaluate
from .inputs import make_session
from .ledger import pair_session, scenarios
from .protocol import Protocol
from .rules import detect_opening_range
from .splits import plan_forward


def _binding():
    protocol = Protocol()
    # Keep the source-visible rehearsal distinct from the original acceptance run.
    sessions = tuple(make_session(protocol, date(2030, 2, day), closes={30: 80004, 31: 80004, 32: 80004},
                                  opens={33: 80004, 63: 80000 + 2 * day})
                     for day in range(4, 8))
    sessions = tuple(session for session in sessions if session.coverage_reason() is None)
    days = tuple(session.day for session in sessions)
    plan = plan_forward(days, holdout_start=days[2], minimum_train=1, validation_size=1)
    selection = tuple(session for session in sessions if session.day in plan.holdout)
    record = {
        "schema_version": 1, "scope": "h4_acceptance_rehearsal", "stage": "synthetic",
        "plan_sha256": plan.sha256, "plan": asdict(plan), "protocol": asdict(protocol),
        "code_sha256": {
            name: digest((Path(__file__).parent / name).read_bytes())
            for name in ("custody.py", "splits.py", "protocol.py", "inputs.py", "rules.py",
                         "ledger.py", "evaluation.py", "artifacts.py", "../data.py", "../instruments.py")
        },
    }
    return canonical_json(record), selection, protocol


def prepare_rehearsal(store: Path) -> str:
    """Pin the plan in the designated custody store and return its confirmation digest."""
    binding, _, _ = _binding()
    scope = store / "h4_acceptance_rehearsal"
    scope.mkdir(parents=True, exist_ok=True)
    _publish(scope / "binding.json", binding)
    return digest(binding)


def evaluate_locked(store: Path, *, stage: str, confirmation: str) -> dict:
    """Consume the bound rehearsal once. Any post-claim failure leaves it consumed."""
    if stage != "synthetic":
        raise PermissionError("Historical holdout execution is disabled")
    scope = store / "h4_acceptance_rehearsal"
    binding, selection, protocol = _binding()
    publication = scope / "binding.json"
    if confirmation != digest(binding) or not publication.is_file() or publication.read_bytes() != binding:
        raise PermissionError("Explicit confirmation of the prepared binding is required")

    # A fixed scope prevents new digests from creating new attempts in this store.
    # mkdir is exclusive, including across concurrent processes.
    claim = scope / "consumed"
    try:
        claim.mkdir()
    except FileExistsError:
        raise PermissionError("Holdout evaluation has already been claimed") from None
    _publish(claim / "attempt.json", canonical_json({"binding_sha256": confirmation}))
    base = next(scenario for scenario in scenarios(protocol) if scenario.id == "base")
    rows = [pair_session(session, protocol, detect_opening_range(session, protocol), base,
                         coverage_reason=None)[0]
            for session in selection]
    report = evaluate(rows, protocol)
    _publish(claim / "report.json", canonical_json({"binding_sha256": confirmation, "report": report}))
    return report
