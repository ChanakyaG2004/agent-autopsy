"""Explicit startup checks; never requests inference or mutates application data."""

import argparse
import json

from sqlalchemy.orm import Session

from app.database import engine
from app.health import database_ready


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama", action="store_true", help="Also verify installed local tool-capable model metadata")
    args = parser.parse_args(argv)
    with Session(engine) as session:
        checks = {"database_and_schema": database_ready(session)}
    if args.ollama:
        from app.ollama_provider import OllamaDriver, OllamaUnavailable, settings
        try:
            model, url = settings()
            driver = OllamaDriver(model, url)
            driver.close()
            checks["local_model_metadata"] = True
        except OllamaUnavailable:
            checks["local_model_metadata"] = False
    passed = all(checks.values())
    print(json.dumps({"ready": passed, "checks": checks, "inference_requested": False}))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
