"""Create the database and the demo user.

Run from target_app/: python -m database.seed [db_path]
Without an argument it uses LOGIN_DB_PATH, else database/app.db.
"""

import os
import sys
from pathlib import Path

from database.db import DEMO_EMAIL, init_db

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "app.db"


def main(argv):
    db_path = argv[1] if len(argv) > 1 else os.environ.get("LOGIN_DB_PATH", str(DEFAULT_DB_PATH))
    init_db(db_path)
    print(f"Database ready at {db_path} with demo user {DEMO_EMAIL}")


if __name__ == "__main__":
    main(sys.argv)
