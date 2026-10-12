"""Run worker and scheduler as separate processes, alongside the API."""
import argparse
import time

from .config import Settings
from .db import database
from .discovery import DiscoveryHandler
from .operations import process_one, schedule_tick


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["worker", "scheduler"])
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    engine, sessions = database(Settings.from_env().database_url)
    handlers = {"discovery.fetch": DiscoveryHandler(sessions)}
    try:
        while True:
            count = process_one(sessions, handlers) if args.mode == "worker" else schedule_tick(sessions)
            if count:
                print(f"{args.mode}: processed {int(count)}", flush=True)
            if args.once:
                break
            time.sleep(2 if args.mode == "worker" else 15)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
