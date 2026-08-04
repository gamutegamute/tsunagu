import subprocess
import sys

from app.db import get_conn


def main() -> None:
    # Serialize migration commands when two ECS tasks start during a deployment.
    with get_conn() as conn:
        conn.execute("SELECT pg_advisory_lock(hashtext('shelteros_migrations'));")
        try:
            subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtext('shelteros_migrations'));")


if __name__ == "__main__":
    main()
