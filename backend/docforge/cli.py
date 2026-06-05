"""DocForge command-line interface.

Commands:
  docforge initdb   Create the database + data directories.
  docforge seed     Build the three demo template packages.
  docforge serve    Run the API server (uvicorn).
"""

from __future__ import annotations

import argparse

from .logging_setup import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docforge", description="DocForge CLI")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("initdb", help="create database tables and data directories")
    sub.add_parser("seed", help="generate and publish the demo templates")

    serve = sub.add_parser("serve", help="run the API server")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    args = parser.parse_args(argv)
    configure_logging()

    if args.cmd == "initdb":
        from .db.session import init_db

        init_db()
        print("Database and data directories ready.")
        return 0

    if args.cmd == "seed":
        from .db.session import SessionLocal, init_db
        from .services import seed_demo_templates

        init_db()
        db = SessionLocal()
        try:
            templates = seed_demo_templates(db)
            # Read attributes while the session is still open.
            summary = [(t.name, t.id) for t in templates]
        finally:
            db.close()
        print(f"Seeded {len(summary)} demo template(s):")
        for tname, tid in summary:
            print(f"  - {tname} ({tid})")
        return 0

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run(
            "docforge.api.app:app", host=args.host, port=args.port, reload=args.reload
        )
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
