import argparse
import json

from brain_infra.alpha import Alpha, init_db
from brain_infra.alpha_list import AlphaList
from brain_infra.worker import FakeWorker, Worker, load_dotenv


def build_default_payload(expression: str) -> dict:
    load_dotenv()
    return {
        "type": "REGULAR",
        "settings": {
            "instrumentType": "EQUITY",
            "region": "USA",
            "universe": "TOP3000",
            "delay": 1,
            "decay": 0,
            "neutralization": "INDUSTRY",
            "truncation": 0.08,
            "pasteurization": "ON",
            "unitHandling": "VERIFY",
            "nanHandling": "OFF",
            "language": "FASTEXPR",
            "visualization": False,
        },
        "regular": expression,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run brain_infra worker or submit a simulation.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    worker_parser = subparsers.add_parser("worker", help="Run the simulation worker loop.")
    worker_parser.add_argument("--fake", action="store_true", help="Use fake simulation results.")

    submit_parser = subparsers.add_parser("submit", help="Queue one alpha into the pending folder.")
    submit_parser.add_argument("--name", required=True, help="Alpha name.")
    submit_parser.add_argument("--expression", required=True, help="FastExpr expression.")
    submit_parser.add_argument(
        "--payload-file",
        help="Optional absolute or relative JSON file containing the full payload.",
    )
    submit_parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for completion after queueing. Requires a worker to be running.",
    )
    return parser.parse_args()


def run_worker(use_fake: bool) -> None:
    init_db()
    worker = FakeWorker() if use_fake else Worker()
    worker.run()


def submit_alpha(name: str, expression: str, payload_file: str | None, wait: bool) -> None:
    init_db()
    if payload_file:
        with open(payload_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = build_default_payload(expression)

    alpha = Alpha(name=name, payload=payload)
    alpha_list = AlphaList([alpha], [name])

    if wait:
        alpha_list.sim_and_wait()
        print(json.dumps(alpha_list.get_alphas()[alpha.filename].result, ensure_ascii=False, indent=2))
        return

    alpha.dump()
    print(alpha.filepath)


def main() -> None:
    args = parse_args()
    if args.command == "worker":
        run_worker(use_fake=args.fake)
        return
    if args.command == "submit":
        submit_alpha(
            name=args.name,
            expression=args.expression,
            payload_file=args.payload_file,
            wait=args.wait,
        )


if __name__ == "__main__":
    main()
