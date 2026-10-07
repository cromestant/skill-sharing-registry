#!/usr/bin/env python3
"""Create an agent identity and print its API key (shown once).

Usage: DATABASE_URL=... python scripts/seed_agent.py "Charles's household agent"
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.auth import mint_agent_identity  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402


def main() -> None:
    display_name = sys.argv[1] if len(sys.argv) > 1 else "seed agent"
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        ident, raw_key = mint_agent_identity(db, display_name)
        db.commit()
        print(f"agent id:     {ident.id}")
        print(f"display name: {ident.display_name}")
        print(f"API key (shown once — store it now):\n{raw_key}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
