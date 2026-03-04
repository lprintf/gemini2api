"""
SQLite Database Manager for Gemini2API

Handles all database operations including:
- Table creation and migrations
- Browser configuration CRUD
- Task history recording
- Global configuration management
- Event logging
"""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from .models import BrowserConfig, EventLog, GlobalConfig, TaskRecord, TaskStats

# 数据库文件路径
DB_PATH = Path(__file__).parent.parent.parent / "data" / "gemini.db"


class Database:
    """SQLite 数据库管理类"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """连接数据库"""
        # 确保目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(str(self.db_path))
        self._connection.row_factory = aiosqlite.Row
        # 启用外键约束
        await self._connection.execute("PRAGMA foreign_keys = ON")

    async def disconnect(self):
        """关闭数据库连接"""
        if self._connection:
            await self._connection.close()
            self._connection = None

    @property
    def conn(self) -> aiosqlite.Connection:
        """获取数据库连接"""
        if not self._connection:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._connection

    async def init_tables(self):
        """初始化数据库表"""
        await self.conn.executescript(
            """
            -- 浏览器配置表
            CREATE TABLE IF NOT EXISTS browsers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                browser_id TEXT UNIQUE NOT NULL,
                account_name TEXT NOT NULL,
                proxy TEXT,
                user_data_dir TEXT NOT NULL,
                rate_limit INTEGER DEFAULT 3,
                rate_window INTEGER DEFAULT 60,
                is_enabled INTEGER DEFAULT 1,
                auto_start INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 任务历史表
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT UNIQUE NOT NULL,
                browser_id TEXT,
                prompt TEXT NOT NULL,
                model TEXT DEFAULT 'Fast',
                input_image TEXT,
                status TEXT DEFAULT 'pending',
                result_paths TEXT,
                error_message TEXT,
                duration REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );

            -- 全局配置表（单行）
            CREATE TABLE IF NOT EXISTS global_config (
                id INTEGER PRIMARY KEY DEFAULT 1,
                server_host TEXT DEFAULT '0.0.0.0',
                server_port INTEGER DEFAULT 8000,
                min_browsers INTEGER DEFAULT 1,
                max_browsers INTEGER DEFAULT 10,
                default_rate_limit INTEGER DEFAULT 3,
                rate_window_seconds INTEGER DEFAULT 60,
                lb_strategy TEXT DEFAULT 'least_loaded',
                log_level TEXT DEFAULT 'INFO',
                admin_username TEXT DEFAULT 'admin',
                admin_password TEXT DEFAULT 'changeme',
                cors_origins TEXT DEFAULT '["*"]',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 事件日志表
            CREATE TABLE IF NOT EXISTS event_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                browser_id TEXT,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 创建索引
            CREATE INDEX IF NOT EXISTS idx_browser_id ON browsers(browser_id);
            CREATE INDEX IF NOT EXISTS idx_task_id ON tasks(task_id);
            CREATE INDEX IF NOT EXISTS idx_task_browser ON tasks(browser_id);
            CREATE INDEX IF NOT EXISTS idx_task_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_task_created ON tasks(created_at);
            CREATE INDEX IF NOT EXISTS idx_log_browser ON event_logs(browser_id);
            CREATE INDEX IF NOT EXISTS idx_log_level ON event_logs(level);
            CREATE INDEX IF NOT EXISTS idx_log_time ON event_logs(created_at);
        """
        )
        await self.conn.commit()

        # 确保全局配置表有一行默认数据
        async with self.conn.execute("SELECT COUNT(*) FROM global_config") as cursor:
            row = await cursor.fetchone()
            if row[0] == 0:
                await self.conn.execute("INSERT INTO global_config (id) VALUES (1)")
                await self.conn.commit()

    # ==================== Browser CRUD ====================

    async def get_browser(self, browser_id: str) -> Optional[BrowserConfig]:
        """获取浏览器配置"""
        async with self.conn.execute(
            "SELECT * FROM browsers WHERE browser_id = ?", (browser_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_browser(row)
            return None

    async def get_all_browsers(self) -> List[BrowserConfig]:
        """获取所有浏览器配置"""
        async with self.conn.execute(
            "SELECT * FROM browsers ORDER BY browser_id"
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_browser(row) for row in rows]

    async def get_enabled_browsers(self) -> List[BrowserConfig]:
        """获取所有启用的浏览器配置"""
        async with self.conn.execute(
            "SELECT * FROM browsers WHERE is_enabled = 1 ORDER BY browser_id"
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_browser(row) for row in rows]

    async def get_auto_start_browsers(self) -> List[BrowserConfig]:
        """获取所有自动启动的浏览器配置"""
        async with self.conn.execute(
            "SELECT * FROM browsers WHERE is_enabled = 1 AND auto_start = 1 ORDER BY browser_id"
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_browser(row) for row in rows]

    async def create_browser(self, config: BrowserConfig) -> BrowserConfig:
        """创建浏览器配置"""
        now = datetime.now()
        await self.conn.execute(
            """
            INSERT INTO browsers
            (browser_id, account_name, proxy, user_data_dir,
             rate_limit, rate_window, is_enabled, auto_start, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                config.browser_id,
                config.account_name,
                config.proxy,
                config.user_data_dir,
                config.rate_limit,
                config.rate_window,
                1 if config.is_enabled else 0,
                1 if config.auto_start else 0,
                now,
                now,
            ),
        )
        await self.conn.commit()
        config.created_at = now
        config.updated_at = now
        return config

    async def update_browser(
        self, browser_id: str, updates: Dict[str, Any]
    ) -> Optional[BrowserConfig]:
        """更新浏览器配置"""
        if not updates:
            return await self.get_browser(browser_id)

        # 构建 UPDATE 语句
        set_clauses = []
        values = []
        for key, value in updates.items():
            if key in ("is_enabled", "auto_start"):
                value = 1 if value else 0
            set_clauses.append(f"{key} = ?")
            values.append(value)

        set_clauses.append("updated_at = ?")
        values.append(datetime.now())
        values.append(browser_id)

        await self.conn.execute(
            f"UPDATE browsers SET {', '.join(set_clauses)} WHERE browser_id = ?",
            values,
        )
        await self.conn.commit()
        return await self.get_browser(browser_id)

    async def delete_browser(self, browser_id: str) -> bool:
        """删除浏览器配置"""
        cursor = await self.conn.execute(
            "DELETE FROM browsers WHERE browser_id = ?", (browser_id,)
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def get_next_browser_id(self) -> int:
        """获取下一个可用的浏览器 ID"""
        async with self.conn.execute(
            "SELECT MAX(CAST(browser_id AS INTEGER)) FROM browsers"
        ) as cursor:
            row = await cursor.fetchone()
            max_id = row[0] if row[0] is not None else -1
            return max_id + 1

    def _row_to_browser(self, row: aiosqlite.Row) -> BrowserConfig:
        """将数据库行转换为 BrowserConfig"""
        return BrowserConfig(
            id=row["id"],
            browser_id=row["browser_id"],
            account_name=row["account_name"],
            proxy=row["proxy"],
            user_data_dir=row["user_data_dir"],
            rate_limit=row["rate_limit"],
            rate_window=row["rate_window"],
            is_enabled=bool(row["is_enabled"]),
            auto_start=bool(row["auto_start"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ==================== Task CRUD ====================

    async def create_task(self, task: TaskRecord) -> TaskRecord:
        """创建任务记录"""
        result_paths_json = json.dumps(task.result_paths) if task.result_paths else None
        await self.conn.execute(
            """
            INSERT INTO tasks
            (task_id, browser_id, prompt, model, input_image, status,
             result_paths, error_message, duration, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.browser_id,
                task.prompt,
                task.model,
                task.input_image,
                task.status,
                result_paths_json,
                task.error_message,
                task.duration,
                task.created_at or datetime.now(),
                task.completed_at,
            ),
        )
        await self.conn.commit()
        return task

    async def update_task(
        self, task_id: str, updates: Dict[str, Any]
    ) -> Optional[TaskRecord]:
        """更新任务记录"""
        if not updates:
            return await self.get_task(task_id)

        # 处理 result_paths
        if "result_paths" in updates and updates["result_paths"] is not None:
            updates["result_paths"] = json.dumps(updates["result_paths"])

        set_clauses = [f"{key} = ?" for key in updates.keys()]
        values = list(updates.values())
        values.append(task_id)

        await self.conn.execute(
            f"UPDATE tasks SET {', '.join(set_clauses)} WHERE task_id = ?",
            values,
        )
        await self.conn.commit()
        return await self.get_task(task_id)

    async def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """获取任务记录"""
        async with self.conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_task(row)
            return None

    async def get_tasks(
        self,
        browser_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[TaskRecord]:
        """获取任务列表"""
        conditions = []
        params = []

        if browser_id:
            conditions.append("browser_id = ?")
            params.append(browser_id)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        async with self.conn.execute(
            f"""
            SELECT * FROM tasks
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    async def get_task_stats(self) -> TaskStats:
        """获取任务统计"""
        today = date.today().isoformat()

        async with self.conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as processing,
                AVG(CASE WHEN duration IS NOT NULL THEN duration END) as avg_duration
            FROM tasks
            """
        ) as cursor:
            row = await cursor.fetchone()

        async with self.conn.execute(
            """
            SELECT
                COUNT(*) as today_total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as today_completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as today_failed
            FROM tasks
            WHERE DATE(created_at) = ?
            """,
            (today,),
        ) as cursor:
            today_row = await cursor.fetchone()

        return TaskStats(
            total_tasks=row["total"] or 0,
            completed_tasks=row["completed"] or 0,
            failed_tasks=row["failed"] or 0,
            pending_tasks=row["pending"] or 0,
            processing_tasks=row["processing"] or 0,
            avg_duration=row["avg_duration"],
            today_tasks=today_row["today_total"] or 0,
            today_completed=today_row["today_completed"] or 0,
            today_failed=today_row["today_failed"] or 0,
        )

    def _row_to_task(self, row: aiosqlite.Row) -> TaskRecord:
        """将数据库行转换为 TaskRecord"""
        result_paths = None
        if row["result_paths"]:
            try:
                result_paths = json.loads(row["result_paths"])
            except json.JSONDecodeError:
                result_paths = None

        return TaskRecord(
            id=row["id"],
            task_id=row["task_id"],
            browser_id=row["browser_id"],
            prompt=row["prompt"],
            model=row["model"],
            input_image=row["input_image"],
            status=row["status"],
            result_paths=result_paths,
            error_message=row["error_message"],
            duration=row["duration"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    # ==================== Global Config ====================

    async def get_global_config(self) -> GlobalConfig:
        """获取全局配置"""
        async with self.conn.execute(
            "SELECT * FROM global_config WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                cors_origins = ["*"]
                if row["cors_origins"]:
                    try:
                        cors_origins = json.loads(row["cors_origins"])
                    except json.JSONDecodeError:
                        pass

                return GlobalConfig(
                    server_host=row["server_host"],
                    server_port=row["server_port"],
                    min_browsers=row["min_browsers"],
                    max_browsers=row["max_browsers"],
                    default_rate_limit=row["default_rate_limit"],
                    rate_window_seconds=row["rate_window_seconds"],
                    lb_strategy=row["lb_strategy"],
                    log_level=row["log_level"],
                    admin_username=row["admin_username"],
                    admin_password=row["admin_password"],
                    cors_origins=cors_origins,
                    updated_at=row["updated_at"],
                )
            return GlobalConfig()

    async def update_global_config(self, updates: Dict[str, Any]) -> GlobalConfig:
        """更新全局配置"""
        if not updates:
            return await self.get_global_config()

        # 处理 cors_origins
        if "cors_origins" in updates and updates["cors_origins"] is not None:
            updates["cors_origins"] = json.dumps(updates["cors_origins"])

        # 处理布尔值

        updates["updated_at"] = datetime.now()

        set_clauses = [f"{key} = ?" for key in updates.keys()]
        values = list(updates.values())

        await self.conn.execute(
            f"UPDATE global_config SET {', '.join(set_clauses)} WHERE id = 1",
            values,
        )
        await self.conn.commit()
        return await self.get_global_config()

    # ==================== Event Logs ====================

    async def add_log(
        self,
        level: str,
        message: str,
        browser_id: Optional[str] = None,
    ):
        """添加事件日志"""
        await self.conn.execute(
            """
            INSERT INTO event_logs (browser_id, level, message, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (browser_id, level, message, datetime.now()),
        )
        await self.conn.commit()

    async def get_logs(
        self,
        browser_id: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[EventLog]:
        """获取事件日志"""
        conditions = []
        params = []

        if browser_id:
            conditions.append("browser_id = ?")
            params.append(browser_id)
        if level:
            conditions.append("level = ?")
            params.append(level)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        async with self.conn.execute(
            f"""
            SELECT * FROM event_logs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                EventLog(
                    id=row["id"],
                    browser_id=row["browser_id"],
                    level=row["level"],
                    message=row["message"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    async def clear_old_logs(self, days: int = 7):
        """清理旧日志"""
        await self.conn.execute(
            """
            DELETE FROM event_logs
            WHERE created_at < datetime('now', ?)
            """,
            (f"-{days} days",),
        )
        await self.conn.commit()


# 全局数据库实例
_db: Optional[Database] = None


async def init_db(db_path: Optional[Path] = None) -> Database:
    """初始化数据库"""
    global _db
    _db = Database(db_path)
    await _db.connect()
    await _db.init_tables()
    return _db


async def close_db():
    """关闭数据库连接"""
    global _db
    if _db:
        await _db.disconnect()
        _db = None


def get_db() -> Database:
    """获取数据库实例"""
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db
