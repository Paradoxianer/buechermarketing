import argparse
import json

from mvp_marketing.storage import load_state, save_state
from mvp_marketing.workflow import run_workflow


def process_manual_approval(state_path: str, approval_id: str, decision: str) -> None:
    state = load_state(state_path)
    record = state.get("approvals", {}).get(approval_id)
    if not record:
        raise SystemExit(f"Approval-ID nicht gefunden: {approval_id}")
    record["status"] = decision
    draft_id = record["draft_id"]
    for draft in state["outreach_queue"]:
        if draft["id"] == draft_id:
            draft["approval_status"] = decision
    save_state(state_path, state)


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline-Marketing-Agentur MVP")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_cmd = sub.add_parser("run", help="Happy-Path ausführen")
    run_cmd.add_argument("--briefing", required=True)
    run_cmd.add_argument("--state", default="mvp_state.json")
    run_cmd.add_argument("--no-dry-run", action="store_true")

    approve_cmd = sub.add_parser("approve", help="Freigabe manuell setzen")
    approve_cmd.add_argument("--state", default="mvp_state.json")
    approve_cmd.add_argument("--approval-id", required=True)
    approve_cmd.add_argument("--decision", choices=["approved", "rejected"], required=True)

    args = parser.parse_args()

    if args.cmd == "run":
        result = run_workflow(args.briefing, args.state, dry_run=not args.no_dry_run)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.cmd == "approve":
        process_manual_approval(args.state, args.approval_id, args.decision)
        print(f"{args.approval_id} -> {args.decision}")


if __name__ == "__main__":
    main()
