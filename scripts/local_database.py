"""Start/stop a project-owned PostgreSQL cluster. Never touches installed services."""
import argparse
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "private-data"
DATA = PRIVATE / "postgres"
PORT = 55439


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop"])
    args = parser.parse_args()
    bindir = Path(os.environ.get("POSTGRES_BIN", r"C:\Program Files\PostgreSQL\18\bin"))

    def run(name, *arguments, check=True):
        executable = shutil.which(name) or str(bindir / (name + (".exe" if os.name == "nt" else "")))
        return subprocess.run([executable, *map(str, arguments)], check=check,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    if args.action == "stop":
        if DATA.exists():
            run("pg_ctl", "-D", DATA, "-m", "fast", "-w", "stop")
        return
    PRIVATE.mkdir(exist_ok=True)
    if DATA.exists() and run("pg_ctl", "-D", DATA, "status", check=False).returncode == 0:
        print("Project database already running.")
        return
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", PORT))
    env_path = ROOT / ".env"
    if not (DATA / "PG_VERSION").exists():
        if env_path.exists():
            raise SystemExit("Existing .env found; use its configured database or move it before local cluster setup.")
        password = secrets.token_urlsafe(32)
        password_file = PRIVATE / "init-password"
        password_file.write_text(password, encoding="utf-8")
        try:
            run("initdb", "-D", DATA, "-U", "jobpilot", "-A", "scram-sha-256", "--pwfile", password_file, "--encoding=UTF8", "--locale=C")
        finally:
            password_file.unlink(missing_ok=True)
        # The default postgres database is used by this isolated personal cluster.
        url = f"postgresql+psycopg://jobpilot:{password}@127.0.0.1:{PORT}/postgres"
        env_path.write_text(f"DATABASE_URL={url}\nTEST_DATABASE_URL={url}\nAPP_ORIGIN=http://localhost:5173\nCOOKIE_SECURE=false\n", encoding="utf-8")
    run("pg_ctl", "-D", DATA, "-l", PRIVATE / "postgres.log", "-o", f"-h 127.0.0.1 -p {PORT}", "-w", "start")
    print(f"Project database listening on 127.0.0.1:{PORT}; credentials are in ignored .env.")


if __name__ == "__main__":
    main()
