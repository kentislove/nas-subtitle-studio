from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import pymssql


ROOT = Path(__file__).resolve().parents[1]


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


def split_go_batches(sql: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?im)^\s*GO\s*$", sql) if part.strip()]


def safe_database_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise SystemExit("資料庫名稱僅支援英數字與底線")
    return name


def execute_batches(conn: pymssql.Connection, sql_path: Path) -> None:
    cursor = conn.cursor()
    for statement in split_go_batches(sql_path.read_text(encoding="utf-8")):
        cursor.execute(statement)
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create NAS Subtitle Studio MSSQL database and tables.")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    parser.add_argument("--database", default=None, help="Database name override")
    args = parser.parse_args()

    file_values = load_env(Path(args.env))
    host = os.getenv("MSSQL_HOST") or file_values.get("MSSQL_HOST")
    port = int(os.getenv("MSSQL_PORT") or file_values.get("MSSQL_PORT", "1433"))
    user = os.getenv("MSSQL_USER") or file_values.get("MSSQL_USER")
    password = os.getenv("MSSQL_PASSWORD") or file_values.get("MSSQL_PASSWORD")
    database = (
        args.database
        or os.getenv("MSSQL_DATABASE")
        or file_values.get("MSSQL_DATABASE")
        or file_values.get("MSSQL_DB")
        or "NASSubtitleStudio"
    )
    database = safe_database_name(database)

    if not host or not user or not password:
        raise SystemExit("MSSQL_HOST / MSSQL_USER / MSSQL_PASSWORD 不完整")

    create_db_sql = f"""
    IF DB_ID(N'{database}') IS NULL
    BEGIN
        CREATE DATABASE [{database}];
    END
    """
    master = pymssql.connect(
        server=host,
        port=port,
        user=user,
        password=password,
        database="master",
        login_timeout=8,
        timeout=30,
        charset="UTF-8",
        autocommit=True,
    )
    try:
        cursor = master.cursor()
        cursor.execute(create_db_sql)
    finally:
        master.close()

    target = pymssql.connect(
        server=host,
        port=port,
        user=user,
        password=password,
        database=database,
        login_timeout=8,
        timeout=30,
        charset="UTF-8",
        autocommit=False,
    )
    try:
        execute_batches(target, ROOT / "database" / "mssql_schema.sql")
        print(f"MSSQL database ready: {database}")
    finally:
        target.close()


if __name__ == "__main__":
    main()
