from __future__ import annotations

import argparse
import os
from pathlib import Path

import pymssql


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description="Check MSSQL connectivity for NAS Subtitle Studio.")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    args = parser.parse_args()

    file_values = load_env(Path(args.env))
    host = os.getenv("MSSQL_HOST") or file_values.get("MSSQL_HOST")
    port = int(os.getenv("MSSQL_PORT") or file_values.get("MSSQL_PORT", "1433"))
    user = os.getenv("MSSQL_USER") or file_values.get("MSSQL_USER")
    password = os.getenv("MSSQL_PASSWORD") or file_values.get("MSSQL_PASSWORD")
    database = os.getenv("MSSQL_DATABASE") or file_values.get("MSSQL_DATABASE") or file_values.get("MSSQL_DB") or "master"

    if not host or not user or not password:
        raise SystemExit("MSSQL_HOST / MSSQL_USER / MSSQL_PASSWORD 不完整")

    conn = pymssql.connect(
        server=host,
        port=port,
        user=user,
        password=password,
        database=database,
        login_timeout=8,
        timeout=8,
        charset="UTF-8",
    )
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT @@SERVERNAME, DB_NAME()")
        server_name, db_name = cursor.fetchone()
        print(f"MSSQL connection ok: server={server_name}, database={db_name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
