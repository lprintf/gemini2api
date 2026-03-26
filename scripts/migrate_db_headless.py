"""
Database Migration Script: Remove obsolete 'headless' parameters.

To run this in local environment:
    python3 scripts/migrate_db_headless.py

To run this in docker container:
    docker compose exec -T gemini2api python3 scripts/migrate_db_headless.py
"""

import sqlite3
import os

def migrate_database():
    # 兼容相对于项目根目录的路径
    db_path = "data/gemini.db"

    if not os.path.exists(db_path):
        print(f"[{os.uname().nodename}] 数据库未找到: {db_path}，跳过清理")
        return

    conn = sqlite3.connect(db_path)

    try:
        conn.execute("ALTER TABLE browsers DROP COLUMN headless;")
        print(f"[{os.uname().nodename}] 成功删除 browsers.headless")
    except sqlite3.OperationalError:
        print(f"[{os.uname().nodename}] browsers.headless 已清理或不存在，跳过")

    try:
        conn.execute("ALTER TABLE global_config DROP COLUMN default_headless;")
        print(f"[{os.uname().nodename}] 成功删除 global_config.default_headless")
    except sqlite3.OperationalError:
        print(f"[{os.uname().nodename}] global_config.default_headless 已清理或不存在，跳过")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate_database()
