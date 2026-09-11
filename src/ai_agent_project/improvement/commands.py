"""Small explicit CLI adapter. Inspection never constructs an evaluator."""

import argparse
import json
from typing import TextIO

from ai_agent_project.improvement.service import (
    ImprovementService,
    build_improvement_service,
)


def add_parser(parent: argparse._SubParsersAction) -> None:
    parser = parent.add_parser("improvement", help="Human-governed experience guidance")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("candidates", "rules", "evaluations"):
        commands.add_parser(name)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("domain", choices=("developer", "researcher"))
    evaluate.add_argument("identity")
    for name in ("approve", "reject", "enable", "disable", "impact"):
        command = commands.add_parser(name)
        command.add_argument("identity")
        if name == "approve":
            command.add_argument(
                "--scope", choices=("global", "developer", "researcher", "project")
            )
    feedback = commands.add_parser("feedback")
    feedback.add_argument(
        "target", choices=("developer", "researcher", "candidate", "rule")
    )
    feedback.add_argument("identity")
    feedback.add_argument("rating", choices=("helpful", "not_helpful"))
    feedback.add_argument("--text", default="")


def run_command(
    args: argparse.Namespace, output: TextIO, service: ImprovementService | None = None
) -> int:
    service = service or build_improvement_service()
    match args.command:
        case "candidates":
            result = service.list_candidates()
        case "rules":
            result = service.list_rules()
        case "evaluations":
            result = service.overview().evaluations
        case "evaluate":
            result = service.evaluate(args.domain, args.identity)
        case "approve":
            result = service.approve_candidate(args.identity, args.scope)
        case "reject":
            result = service.reject_candidate(args.identity)
        case "enable" | "disable":
            result = service.set_enabled(args.identity, args.command == "enable")
        case "feedback":
            result = service.submit_feedback(
                args.target, args.identity, args.rating, args.text
            )
        case "impact":
            result = service.impact(args.identity)
        case _:
            raise ValueError("Unsupported improvement command")
    data = (
        [v.model_dump(mode="json") for v in result]
        if isinstance(result, tuple)
        else result.model_dump(mode="json")
        if result is not None
        else {"status": "completed"}
    )
    print(json.dumps(data, indent=2), file=output)
    return 0
