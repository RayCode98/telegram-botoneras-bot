from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


BASE_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    private_chat_id INTEGER NOT NULL,
    username TEXT,
    first_name TEXT,
    started_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
    chat_id INTEGER PRIMARY KEY,
    telegram_title TEXT NOT NULL,
    telegram_username TEXT,
    owner_user_id INTEGER,
    button_title TEXT,
    invite_type TEXT,
    invite_url TEXT,
    button_style TEXT NOT NULL DEFAULT 'default',
    category TEXT,
    member_count INTEGER NOT NULL DEFAULT 0,
    pending_category TEXT,
    status TEXT NOT NULL DEFAULT 'configuring',
    rejection_reason TEXT,
    permissions_ok INTEGER NOT NULL DEFAULT 1,
    permission_issues TEXT,
    permission_checked_at TEXT,
    owner_bound_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_channels_status_category ON channels(status, category);
CREATE INDEX IF NOT EXISTS idx_channels_owner ON channels(owner_user_id);

CREATE TABLE IF NOT EXISTS templates (
    category TEXT PRIMARY KEY,
    text TEXT NOT NULL DEFAULT '',
    photo_file_id TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedules (
    category TEXT PRIMARY KEY,
    hour INTEGER NOT NULL DEFAULT 18,
    minute INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 0,
    lifetime_hours REAL NOT NULL DEFAULT 6,
    shuffle_enabled INTEGER NOT NULL DEFAULT 0,
    shuffle_interval_minutes INTEGER NOT NULL DEFAULT 10,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manual_buttons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    style TEXT NOT NULL DEFAULT 'default',
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS board_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    destination_chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    published_date TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    deleted_at TEXT,
    removal_reason TEXT,
    last_checked_at TEXT,
    start_member_count INTEGER,
    end_member_count INTEGER,
    member_delta INTEGER,
    stats_sent_at TEXT,
    stats_error TEXT,
    stats_attempts INTEGER NOT NULL DEFAULT 0,
    stats_last_attempt_at TEXT,
    channel_category_start TEXT,
    shuffle_seed INTEGER
);


CREATE TABLE IF NOT EXISTS sessions (
    user_id INTEGER PRIMARY KEY,
    action TEXT NOT NULL,
    chat_id INTEGER,
    category TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_sanctions (
    user_id INTEGER PRIMARY KEY,
    strikes INTEGER NOT NULL DEFAULT 0,
    banned INTEGER NOT NULL DEFAULT 0,
    banned_at TEXT,
    ban_reason TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS violations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    violation_type TEXT NOT NULL,
    chat_id INTEGER,
    board_message_id INTEGER,
    details TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_violations_user ON violations(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER PRIMARY KEY,
    notify_approved INTEGER NOT NULL DEFAULT 1,
    notify_rejected INTEGER NOT NULL DEFAULT 1,
    notify_board_started INTEGER NOT NULL DEFAULT 1,
    notify_board_finished INTEGER NOT NULL DEFAULT 1,
    notify_stats INTEGER NOT NULL DEFAULT 1,
    notify_category_change INTEGER NOT NULL DEFAULT 1,
    notify_next_board INTEGER NOT NULL DEFAULT 1,
    notify_warnings INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appeals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    admin_user_id INTEGER,
    resolution TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_appeals_status ON appeals(status, created_at);
CREATE INDEX IF NOT EXISTS idx_appeals_user ON appeals(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS notification_log (
    dedupe_key TEXT PRIMARY KEY,
    user_id INTEGER,
    notification_type TEXT NOT NULL,
    sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ownership_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    registered_owner_user_id INTEGER,
    attempted_owner_user_id INTEGER,
    actor_username TEXT,
    details TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ownership_conflicts_chat ON ownership_conflicts(chat_id, created_at DESC);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    started_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    closed_at TEXT,
    closure_reason TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_campaigns_active ON campaigns(category, status, expires_at);

CREATE TABLE IF NOT EXISTS campaign_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    entry_mode TEXT NOT NULL DEFAULT 'direct',
    invite_link TEXT,
    invite_link_name TEXT,
    start_member_count INTEGER,
    end_member_count INTEGER,
    member_delta INTEGER,
    requests_count INTEGER NOT NULL DEFAULT 0,
    request_events INTEGER NOT NULL DEFAULT 0,
    joined_count INTEGER NOT NULL DEFAULT 0,
    left_count INTEGER NOT NULL DEFAULT 0,
    stats_sent_at TEXT,
    stats_error TEXT,
    stats_attempts INTEGER NOT NULL DEFAULT 0,
    stats_last_attempt_at TEXT,
    link_revoked_at TEXT,
    link_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(campaign_id, chat_id),
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_channels_link ON campaign_channels(invite_link) WHERE invite_link IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_campaign_channels_campaign ON campaign_channels(campaign_id, chat_id);

CREATE TABLE IF NOT EXISTS campaign_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    invite_link TEXT,
    requested_at TEXT,
    request_count INTEGER NOT NULL DEFAULT 0,
    joined_at TEXT,
    left_at TEXT,
    via_join_request INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(campaign_id, chat_id, user_id),
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_campaign_users_link ON campaign_users(invite_link);
CREATE INDEX IF NOT EXISTS idx_campaign_users_lookup ON campaign_users(chat_id, user_id, campaign_id);

CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    details TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_system_events_created ON system_events(created_at DESC);

"""


class Database:
    def __init__(self, path: Path, default_lifetime_hours: float = 6.0):
        self.path = path
        self.default_lifetime_hours = default_lifetime_hours
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(BASE_SCHEMA)
        self._migrate()

    @contextmanager
    def connection(self):
        with self._lock:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _columns(self, table: str) -> set[str]:
        with self.connection() as conn:
            return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}

    def _ensure_column(self, table: str, name: str, ddl: str):
        if name not in self._columns(table):
            with self.connection() as conn:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def _migrate(self):
        # Permite actualizar una base creada por la versión anterior del proyecto.
        self._ensure_column("schedules", "lifetime_hours", f"REAL NOT NULL DEFAULT {float(self.default_lifetime_hours)}")
        self._ensure_column("board_messages", "expires_at", "TEXT")
        self._ensure_column("board_messages", "deleted_at", "TEXT")
        self._ensure_column("board_messages", "removal_reason", "TEXT")
        self._ensure_column("channels", "pending_category", "TEXT")
        self._ensure_column("schedules", "shuffle_enabled", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("schedules", "shuffle_interval_minutes", "INTEGER NOT NULL DEFAULT 10")
        self._ensure_column("board_messages", "last_checked_at", "TEXT")
        self._ensure_column("board_messages", "start_member_count", "INTEGER")
        self._ensure_column("board_messages", "end_member_count", "INTEGER")
        self._ensure_column("board_messages", "member_delta", "INTEGER")
        self._ensure_column("board_messages", "stats_sent_at", "TEXT")
        self._ensure_column("board_messages", "stats_error", "TEXT")
        self._ensure_column("board_messages", "stats_attempts", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("board_messages", "stats_last_attempt_at", "TEXT")
        self._ensure_column("board_messages", "channel_category_start", "TEXT")
        self._ensure_column("board_messages", "shuffle_seed", "INTEGER")
        self._ensure_column("channels", "permissions_ok", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("channels", "permission_issues", "TEXT")
        self._ensure_column("channels", "permission_checked_at", "TEXT")
        self._ensure_column("channels", "owner_bound_at", "TEXT")
        self._ensure_column("board_messages", "campaign_id", "INTEGER")
        with self.connection() as conn:
            # v6.1: antes la interfaz llamaba "público/privado" al tipo de enlace.
            # Ambos modos antiguos permitían ingreso directo, por lo que se migran
            # al nuevo nombre semántico. El propietario puede cambiar después a
            # "approval" desde su panel.
            conn.execute(
                "UPDATE channels SET invite_type='direct' WHERE invite_type IN ('public','private')"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_board_messages_live ON board_messages(category, active, expires_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_board_messages_chat ON board_messages(destination_chat_id, active)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_board_stats_pending ON board_messages(stats_sent_at, end_member_count)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_board_messages_campaign ON board_messages(campaign_id, active)")

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self.connection() as conn:
            cur = conn.execute(sql, tuple(params))
            return int(cur.lastrowid or 0)

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        with self.connection() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]

    # System/health ------------------------------------------------------
    def database_quick_check(self) -> str:
        with self.connection() as conn:
            row = conn.execute("PRAGMA quick_check").fetchone()
            return str(row[0] if row else "unknown")

    def log_system_event(self, event_type: str, details: str, severity: str = "info") -> int:
        return self.execute(
            "INSERT INTO system_events(event_type, severity, details, created_at) VALUES (?, ?, ?, ?)",
            (event_type, severity, details[:2000], now_iso()),
        )

    def recent_system_events(self, limit: int = 10) -> list[dict]:
        return self.all("SELECT * FROM system_events ORDER BY id DESC LIMIT ?", (limit,))

    # Users -------------------------------------------------------------
    def upsert_user(self, user_id: int, private_chat_id: int, username: str | None, first_name: str | None):
        self.execute(
            """
            INSERT INTO users(user_id, private_chat_id, username, first_name, started_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                private_chat_id=excluded.private_chat_id,
                username=excluded.username,
                first_name=excluded.first_name
            """,
            (user_id, private_chat_id, username, first_name, now_iso()),
        )

    def get_user(self, user_id: int) -> dict | None:
        return self.one("SELECT * FROM users WHERE user_id=?", (user_id,))

    def ensure_user_preferences(self, user_id: int):
        self.execute(
            "INSERT OR IGNORE INTO user_preferences(user_id, updated_at) VALUES (?, ?)",
            (user_id, now_iso()),
        )

    def get_user_preferences(self, user_id: int) -> dict:
        self.ensure_user_preferences(user_id)
        row = self.one("SELECT * FROM user_preferences WHERE user_id=?", (user_id,))
        return row or {
            "user_id": user_id, "notify_approved": 1, "notify_rejected": 1,
            "notify_board_started": 1, "notify_board_finished": 1, "notify_stats": 1,
            "notify_category_change": 1, "notify_next_board": 1, "notify_warnings": 1,
        }

    def set_user_preference(self, user_id: int, key: str, enabled: bool):
        allowed = {
            "notify_approved", "notify_rejected", "notify_board_started",
            "notify_board_finished", "notify_stats", "notify_category_change",
            "notify_next_board",
        }
        if key not in allowed:
            raise ValueError("Preferencia no editable")
        self.ensure_user_preferences(user_id)
        self.execute(
            f"UPDATE user_preferences SET {key}=?, updated_at=? WHERE user_id=?",
            (int(enabled), now_iso(), user_id),
        )

    def notification_sent(self, dedupe_key: str) -> bool:
        return self.one("SELECT dedupe_key FROM notification_log WHERE dedupe_key=?", (dedupe_key,)) is not None

    def mark_notification_sent(self, dedupe_key: str, user_id: int | None, notification_type: str):
        self.execute(
            "INSERT OR IGNORE INTO notification_log(dedupe_key, user_id, notification_type, sent_at) VALUES (?, ?, ?, ?)",
            (dedupe_key, user_id, notification_type, now_iso()),
        )

    # Sanctions ---------------------------------------------------------
    def get_sanction(self, user_id: int) -> dict:
        row = self.one("SELECT * FROM user_sanctions WHERE user_id=?", (user_id,))
        return row or {
            "user_id": user_id,
            "strikes": 0,
            "banned": 0,
            "banned_at": None,
            "ban_reason": None,
            "updated_at": None,
        }

    def is_banned(self, user_id: int | None) -> bool:
        if not user_id:
            return False
        return bool(self.get_sanction(user_id).get("banned"))

    def add_violation(
        self,
        user_id: int,
        violation_type: str,
        chat_id: int | None,
        board_message_id: int | None,
        details: str,
        violation_limit: int,
    ) -> dict:
        now = now_iso()
        current = self.get_sanction(user_id)
        strikes = int(current.get("strikes") or 0) + 1
        banned = strikes >= violation_limit
        self.execute(
            """
            INSERT INTO user_sanctions(user_id, strikes, banned, banned_at, ban_reason, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                strikes=excluded.strikes,
                banned=excluded.banned,
                banned_at=CASE WHEN excluded.banned=1 THEN COALESCE(user_sanctions.banned_at, excluded.banned_at) ELSE NULL END,
                ban_reason=CASE WHEN excluded.banned=1 THEN excluded.ban_reason ELSE user_sanctions.ban_reason END,
                updated_at=excluded.updated_at
            """,
            (user_id, strikes, int(banned), now if banned else None, details if banned else None, now),
        )
        violation_id = self.execute(
            """
            INSERT INTO violations(user_id, violation_type, chat_id, board_message_id, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, violation_type, chat_id, board_message_id, details, now),
        )
        result = self.get_sanction(user_id)
        result["violation_id"] = violation_id
        return result

    def recent_violations(self, limit: int = 30) -> list[dict]:
        return self.all(
            "SELECT * FROM violations ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    def violations_for_user(self, user_id: int, limit: int = 30) -> list[dict]:
        return self.all(
            "SELECT * FROM violations WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )

    def remove_one_strike(self, user_id: int) -> dict:
        state = self.get_sanction(user_id)
        strikes = max(0, int(state.get("strikes") or 0) - 1)
        banned = 0 if strikes < 1 else int(bool(state.get("banned")) and strikes > 0)
        self.execute(
            """
            INSERT INTO user_sanctions(user_id, strikes, banned, banned_at, ban_reason, updated_at)
            VALUES (?, ?, 0, NULL, NULL, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                strikes=excluded.strikes, banned=0, banned_at=NULL, ban_reason=NULL, updated_at=excluded.updated_at
            """,
            (user_id, strikes, now_iso()),
        )
        return self.get_sanction(user_id)

    def create_appeal(self, user_id: int, message: str) -> int:
        existing = self.one("SELECT id FROM appeals WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 1", (user_id,))
        if existing:
            return int(existing["id"])
        return self.execute(
            "INSERT INTO appeals(user_id, message, status, created_at) VALUES (?, ?, 'pending', ?)",
            (user_id, message, now_iso()),
        )

    def pending_appeals(self) -> list[dict]:
        return self.all("SELECT * FROM appeals WHERE status='pending' ORDER BY created_at ASC")

    def appeals_for_user(self, user_id: int, limit: int = 10) -> list[dict]:
        return self.all("SELECT * FROM appeals WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))

    def get_appeal(self, appeal_id: int) -> dict | None:
        return self.one("SELECT * FROM appeals WHERE id=?", (appeal_id,))

    def resolve_appeal(self, appeal_id: int, status: str, admin_user_id: int, resolution: str | None = None):
        self.execute(
            "UPDATE appeals SET status=?, admin_user_id=?, resolution=?, resolved_at=? WHERE id=?",
            (status, admin_user_id, resolution, now_iso(), appeal_id),
        )

    def banned_users(self) -> list[dict]:
        return self.all(
            "SELECT * FROM user_sanctions WHERE banned=1 ORDER BY banned_at DESC"
        )

    def reset_sanctions(self, user_id: int):
        self.execute(
            """
            INSERT INTO user_sanctions(user_id, strikes, banned, banned_at, ban_reason, updated_at)
            VALUES (?, 0, 0, NULL, NULL, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                strikes=0, banned=0, banned_at=NULL, ban_reason=NULL, updated_at=excluded.updated_at
            """,
            (user_id, now_iso()),
        )

    # Channels ----------------------------------------------------------
    def upsert_channel(
        self,
        chat_id: int,
        title: str,
        username: str | None,
        owner_user_id: int | None,
        member_count: int,
        category: str,
    ):
        now = now_iso()
        self.execute(
            """
            INSERT INTO channels(
                chat_id, telegram_title, telegram_username, owner_user_id,
                member_count, category, owner_bound_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                telegram_title=excluded.telegram_title,
                telegram_username=excluded.telegram_username,
                owner_user_id=COALESCE(channels.owner_user_id, excluded.owner_user_id),
                member_count=excluded.member_count,
                category=CASE
                    WHEN channels.status IN ('configuring','pending_review','rejected','inactive','suspended','banned')
                    THEN excluded.category ELSE channels.category END,
                updated_at=excluded.updated_at
            """,
            (chat_id, title, username, owner_user_id, member_count, category, now if owner_user_id else None, now, now),
        )

    def get_channel(self, chat_id: int) -> dict | None:
        return self.one("SELECT * FROM channels WHERE chat_id=?", (chat_id,))

    def owner_conflict(self, chat_id: int, attempted_owner_user_id: int | None) -> bool:
        ch = self.get_channel(chat_id)
        if not ch or not ch.get("owner_user_id") or not attempted_owner_user_id:
            return False
        return int(ch["owner_user_id"]) != int(attempted_owner_user_id)

    def record_ownership_conflict(
        self, chat_id: int, registered_owner_user_id: int | None,
        attempted_owner_user_id: int | None, actor_username: str | None, details: str,
    ) -> int:
        return self.execute(
            """
            INSERT INTO ownership_conflicts(
                chat_id, registered_owner_user_id, attempted_owner_user_id, actor_username, details, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chat_id, registered_owner_user_id, attempted_owner_user_id, actor_username, details, now_iso()),
        )

    def recent_ownership_conflicts(self, limit: int = 30) -> list[dict]:
        return self.all("SELECT * FROM ownership_conflicts ORDER BY id DESC LIMIT ?", (limit,))

    def transfer_channel_owner(self, chat_id: int, new_owner_user_id: int) -> None:
        self.execute(
            "UPDATE channels SET owner_user_id=?, owner_bound_at=?, status='pending_review', updated_at=? WHERE chat_id=?",
            (new_owner_user_id, now_iso(), now_iso(), chat_id),
        )

    def set_channel_permission_state(self, chat_id: int, ok: bool, issues: str | None) -> None:
        self.execute(
            "UPDATE channels SET permissions_ok=?, permission_issues=?, permission_checked_at=?, updated_at=? WHERE chat_id=?",
            (int(ok), issues, now_iso(), now_iso(), chat_id),
        )

    def channels_for_permission_audit(self) -> list[dict]:
        return self.all(
            "SELECT * FROM channels WHERE status IN ('approved','permission_suspended') ORDER BY updated_at"
        )

    def publication_candidates(self, category: str | None = None) -> list[dict]:
        if category:
            return self.all(
                """SELECT * FROM channels WHERE status IN ('approved','permission_suspended') AND category=?
                   ORDER BY COALESCE(button_title, telegram_title) COLLATE NOCASE""",
                (category,),
            )
        return self.all(
            """SELECT * FROM channels WHERE status IN ('approved','permission_suspended')
               ORDER BY category, COALESCE(button_title, telegram_title) COLLATE NOCASE"""
        )

    def channels_for_owner(self, user_id: int) -> list[dict]:
        return self.all("SELECT * FROM channels WHERE owner_user_id=? ORDER BY created_at DESC", (user_id,))

    def categories_for_owner(self, user_id: int) -> list[str]:
        rows = self.all("SELECT DISTINCT category FROM channels WHERE owner_user_id=? AND category IS NOT NULL", (user_id,))
        return [r["category"] for r in rows]

    def configuring_for_owner(self, user_id: int) -> list[dict]:
        return self.all(
            "SELECT * FROM channels WHERE owner_user_id=? AND status='configuring' ORDER BY created_at ASC",
            (user_id,),
        )

    def pending_channels(self) -> list[dict]:
        return self.all("SELECT * FROM channels WHERE status='pending_review' ORDER BY updated_at ASC")

    def approved_channels(self, category: str | None = None) -> list[dict]:
        if category:
            return self.all(
                """
                SELECT * FROM channels WHERE status='approved' AND category=?
                ORDER BY COALESCE(button_title, telegram_title) COLLATE NOCASE
                """,
                (category,),
            )
        return self.all(
            """
            SELECT * FROM channels WHERE status='approved'
            ORDER BY category, COALESCE(button_title, telegram_title) COLLATE NOCASE
            """
        )

    def all_channels(self) -> list[dict]:
        return self.all("SELECT * FROM channels ORDER BY updated_at DESC")

    def channels_with_pending_category(self) -> list[dict]:
        return self.all(
            "SELECT * FROM channels WHERE pending_category IS NOT NULL ORDER BY updated_at"
        )

    def channels_by_status(self, status: str) -> list[dict]:
        return self.all("SELECT * FROM channels WHERE status=? ORDER BY updated_at DESC", (status,))

    def set_channel_fields(self, chat_id: int, **fields):
        if not fields:
            return
        fields["updated_at"] = now_iso()
        keys = list(fields)
        values = [fields[k] for k in keys]
        self.execute(
            f"UPDATE channels SET {', '.join(f'{k}=?' for k in keys)} WHERE chat_id=?",
            (*values, chat_id),
        )

    def ban_channels_for_owner(self, user_id: int) -> list[dict]:
        channels = self.channels_for_owner(user_id)
        self.execute("UPDATE channels SET status='banned', updated_at=? WHERE owner_user_id=?", (now_iso(), user_id))
        return channels


    def participant_channels_for_audit(self) -> list[dict]:
        return self.all(
            "SELECT * FROM channels WHERE status IN ('approved','below_minimum') ORDER BY updated_at",
        )

    def channel_stats_history(self, user_id: int, chat_id: int, limit: int = 5, offset: int = 0) -> list[dict]:
        # v6.2: las campañas nuevas se miden por el enlace exclusivo del canal.
        # Se conservan también los históricos v6.1 (board_messages sin campaign_id).
        return self.all(
            """
            SELECT * FROM (
                SELECT cc.id AS id, cp.category AS category, cp.started_at AS created_at,
                       cp.closed_at AS deleted_at, cc.start_member_count, cc.end_member_count,
                       cc.member_delta, cc.requests_count, cc.request_events, cc.joined_count,
                       cc.left_count, cc.entry_mode, cc.campaign_id, 'campaign' AS stats_source
                FROM campaign_channels cc
                JOIN campaigns cp ON cp.id=cc.campaign_id
                JOIN channels c ON c.chat_id=cc.chat_id
                WHERE c.owner_user_id=? AND c.chat_id=? AND cc.invite_link IS NOT NULL AND cc.end_member_count IS NOT NULL
                UNION ALL
                SELECT bm.id AS id, bm.category, bm.created_at, bm.deleted_at,
                       bm.start_member_count, bm.end_member_count, bm.member_delta,
                       0 AS requests_count, 0 AS request_events, 0 AS joined_count, 0 AS left_count,
                       NULL AS entry_mode, NULL AS campaign_id, 'legacy' AS stats_source
                FROM board_messages bm
                JOIN channels c ON c.chat_id=bm.destination_chat_id
                WHERE c.owner_user_id=? AND c.chat_id=?
                  AND bm.campaign_id IS NULL
                  AND bm.end_member_count IS NOT NULL AND bm.member_delta IS NOT NULL
                  AND bm.removal_reason IN ('expired','manual_admin_delete')
            ) h
            ORDER BY COALESCE(h.deleted_at, h.created_at) DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, chat_id, user_id, chat_id, limit, offset),
        )

    def channel_stats_count(self, user_id: int, chat_id: int) -> int:
        row = self.one(
            """
            SELECT (
                SELECT COUNT(*) FROM campaign_channels cc
                JOIN channels c ON c.chat_id=cc.chat_id
                WHERE c.owner_user_id=? AND c.chat_id=? AND cc.invite_link IS NOT NULL AND cc.end_member_count IS NOT NULL
            ) + (
                SELECT COUNT(*) FROM board_messages bm
                JOIN channels c ON c.chat_id=bm.destination_chat_id
                WHERE c.owner_user_id=? AND c.chat_id=? AND bm.campaign_id IS NULL
                  AND bm.end_member_count IS NOT NULL AND bm.member_delta IS NOT NULL
                  AND bm.removal_reason IN ('expired','manual_admin_delete')
            ) AS n
            """,
            (user_id, chat_id, user_id, chat_id),
        )
        return int((row or {}).get("n") or 0)

    def owner_stats_summary(self, user_id: int, days: int = 30) -> dict:
        row = self.one(
            """
            SELECT COUNT(*) AS participations,
                   COALESCE(SUM(x.member_delta), 0) AS total_delta,
                   COALESCE(AVG(x.member_delta), 0) AS avg_delta,
                   COALESCE(MAX(x.member_delta), 0) AS best_delta,
                   COALESCE(MIN(x.member_delta), 0) AS worst_delta,
                   COALESCE(SUM(x.requests_count), 0) AS total_requests,
                   COALESCE(SUM(x.joined_count), 0) AS total_attributed_joins
            FROM (
                SELECT cc.member_delta, cc.requests_count, cc.joined_count, cp.closed_at AS finished_at
                FROM campaign_channels cc
                JOIN campaigns cp ON cp.id=cc.campaign_id
                JOIN channels c ON c.chat_id=cc.chat_id
                WHERE c.owner_user_id=? AND cc.invite_link IS NOT NULL AND cc.end_member_count IS NOT NULL
                UNION ALL
                SELECT bm.member_delta, 0, 0, bm.deleted_at
                FROM board_messages bm
                JOIN channels c ON c.chat_id=bm.destination_chat_id
                WHERE c.owner_user_id=? AND bm.campaign_id IS NULL
                  AND bm.end_member_count IS NOT NULL AND bm.member_delta IS NOT NULL
            ) x
            WHERE datetime(x.finished_at) >= datetime('now', ?)
            """,
            (user_id, user_id, f'-{int(days)} days'),
        )
        return row or {
            "participations": 0, "total_delta": 0, "avg_delta": 0,
            "best_delta": 0, "worst_delta": 0, "total_requests": 0,
            "total_attributed_joins": 0,
        }

    # Categories, templates, schedules ---------------------------------
    def ensure_categories(self, categories: tuple[str, ...], default_lifetime_hours: float):
        for category in categories:
            self.execute("INSERT OR IGNORE INTO templates(category, updated_at) VALUES (?, ?)", (category, now_iso()))
            self.execute(
                """
                INSERT OR IGNORE INTO schedules(category, lifetime_hours, updated_at)
                VALUES (?, ?, ?)
                """,
                (category, default_lifetime_hours, now_iso()),
            )

    def get_template(self, category: str) -> dict | None:
        return self.one("SELECT * FROM templates WHERE category=?", (category,))

    def set_template_text(self, category: str, text: str):
        self.execute("UPDATE templates SET text=?, updated_at=? WHERE category=?", (text, now_iso(), category))

    def set_template_photo(self, category: str, file_id: str):
        self.execute("UPDATE templates SET photo_file_id=?, updated_at=? WHERE category=?", (file_id, now_iso(), category))

    def get_schedule(self, category: str) -> dict | None:
        return self.one("SELECT * FROM schedules WHERE category=?", (category,))

    def get_enabled_schedules(self) -> list[dict]:
        return self.all("SELECT * FROM schedules WHERE enabled=1")

    def set_schedule(self, category: str, hour: int, minute: int, enabled: bool = True):
        self.execute(
            "UPDATE schedules SET hour=?, minute=?, enabled=?, updated_at=? WHERE category=?",
            (hour, minute, int(enabled), now_iso(), category),
        )

    def set_lifetime(self, category: str, lifetime_hours: float):
        self.execute(
            "UPDATE schedules SET lifetime_hours=?, updated_at=? WHERE category=?",
            (lifetime_hours, now_iso(), category),
        )

    def set_shuffle(self, category: str, enabled: bool, interval_minutes: int | None = None):
        current = self.get_schedule(category) or {}
        interval = int(interval_minutes if interval_minutes is not None else current.get("shuffle_interval_minutes") or 10)
        self.execute(
            "UPDATE schedules SET shuffle_enabled=?, shuffle_interval_minutes=?, updated_at=? WHERE category=?",
            (int(enabled), interval, now_iso(), category),
        )

    def get_shuffle_schedules(self) -> list[dict]:
        return self.all("SELECT * FROM schedules WHERE shuffle_enabled=1")

    # Manual buttons ----------------------------------------------------
    def add_manual_button(self, category: str, title: str, url: str, style: str) -> int:
        now = now_iso()
        return self.execute(
            """
            INSERT INTO manual_buttons(category, title, url, style, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (category, title, url, style, now, now),
        )

    def get_manual_button(self, button_id: int) -> dict | None:
        return self.one("SELECT * FROM manual_buttons WHERE id=?", (button_id,))

    def manual_buttons(self, category: str) -> list[dict]:
        return self.all(
            "SELECT * FROM manual_buttons WHERE category=? AND active=1 ORDER BY sort_order, id",
            (category,),
        )

    def update_manual_button(self, button_id: int, **fields):
        if not fields:
            return
        fields["updated_at"] = now_iso()
        keys = list(fields)
        values = [fields[k] for k in keys]
        self.execute(
            f"UPDATE manual_buttons SET {', '.join(f'{k}=?' for k in keys)} WHERE id=?",
            (*values, button_id),
        )

    def delete_manual_button(self, button_id: int):
        self.execute("DELETE FROM manual_buttons WHERE id=?", (button_id,))

    # Publications ------------------------------------------------------
    def get_board_message(self, board_id: int) -> dict | None:
        return self.one("SELECT * FROM board_messages WHERE id=?", (board_id,))

    def active_board_messages(self) -> list[dict]:
        return self.all("SELECT * FROM board_messages WHERE active=1 ORDER BY id")

    def active_board_messages_for_chat(self, chat_id: int) -> list[dict]:
        return self.all(
            "SELECT * FROM board_messages WHERE active=1 AND destination_chat_id=? ORDER BY id",
            (chat_id,),
        )

    def active_for_category_destination(self, category: str, destination_chat_id: int) -> list[dict]:
        return self.all(
            """
            SELECT * FROM board_messages
            WHERE active=1 AND category=? AND destination_chat_id=?
            ORDER BY id
            """,
            (category, destination_chat_id),
        )

    def live_board_messages(self, category: str) -> list[dict]:
        return self.all(
            "SELECT * FROM board_messages WHERE category=? AND active=1 ORDER BY id",
            (category,),
        )

    def add_board_message(
        self,
        category: str,
        destination_chat_id: int,
        message_id: int,
        published_date: str,
        expires_at: str,
        start_member_count: int | None = None,
        channel_category_start: str | None = None,
        shuffle_seed: int | None = None,
        campaign_id: int | None = None,
    ) -> int:
        return self.execute(
            """
            INSERT INTO board_messages(
                category, destination_chat_id, message_id, published_date,
                active, created_at, expires_at, start_member_count, channel_category_start, shuffle_seed, campaign_id
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
            """,
            (
                category, destination_chat_id, message_id, published_date, now_iso(),
                expires_at, start_member_count, channel_category_start, shuffle_seed, campaign_id,
            ),
        )

    def mark_board_removed(self, board_id: int, reason: str):
        self.execute(
            """
            UPDATE board_messages
            SET active=0, deleted_at=?, removal_reason=?, last_checked_at=?
            WHERE id=?
            """,
            (now_iso(), reason, now_iso(), board_id),
        )

    def mark_board_checked(self, board_id: int):
        self.execute("UPDATE board_messages SET last_checked_at=? WHERE id=?", (now_iso(), board_id))

    def set_board_shuffle_seed(self, board_id: int, shuffle_seed: int | None):
        self.execute("UPDATE board_messages SET shuffle_seed=? WHERE id=?", (shuffle_seed, board_id))

    def save_board_stats(
        self,
        board_id: int,
        end_member_count: int | None,
        member_delta: int | None,
        stats_error: str | None = None,
    ):
        self.execute(
            """
            UPDATE board_messages
            SET end_member_count=?, member_delta=?, stats_error=?
            WHERE id=?
            """,
            (end_member_count, member_delta, stats_error, board_id),
        )

    def mark_stats_sent(self, board_id: int):
        self.execute(
            "UPDATE board_messages SET stats_sent_at=?, stats_error=NULL, stats_last_attempt_at=? WHERE id=?",
            (now_iso(), now_iso(), board_id),
        )

    def note_stats_attempt(self, board_id: int, error: str | None = None):
        self.execute(
            """
            UPDATE board_messages
            SET stats_attempts=COALESCE(stats_attempts, 0)+1, stats_last_attempt_at=?, stats_error=?
            WHERE id=?
            """,
            (now_iso(), error, board_id),
        )

    def pending_stats_messages(self, limit: int = 100) -> list[dict]:
        return self.all(
            """
            SELECT bm.*, c.owner_user_id, c.telegram_title, c.category AS channel_category_current,
                   c.pending_category
            FROM board_messages bm
            LEFT JOIN channels c ON c.chat_id=bm.destination_chat_id
            WHERE bm.active=0
              AND bm.end_member_count IS NOT NULL
              AND bm.stats_sent_at IS NULL
              AND COALESCE(bm.stats_attempts, 0) < 5
              AND bm.removal_reason IN ('expired','manual_admin_delete')
            ORDER BY bm.id
            LIMIT ?
            """,
            (limit,),
        )

    def set_pending_category(self, chat_id: int, pending_category: str | None):
        self.set_channel_fields(chat_id, pending_category=pending_category)

    def apply_pending_category(self, chat_id: int) -> tuple[str | None, str | None]:
        channel = self.get_channel(chat_id)
        if not channel or not channel.get("pending_category"):
            return (channel.get("category") if channel else None, None)
        old = channel.get("category")
        new = channel.get("pending_category")
        self.set_channel_fields(chat_id, category=new, pending_category=None)
        return old, new

    # Campaign attribution (v6.2) ---------------------------------------
    def create_campaign(self, category: str, started_at: str, expires_at: str) -> int:
        return self.execute(
            """INSERT INTO campaigns(category, status, started_at, expires_at, created_at)
               VALUES (?, 'active', ?, ?, ?)""",
            (category, started_at, expires_at, now_iso()),
        )

    def get_campaign(self, campaign_id: int) -> dict | None:
        return self.one("SELECT * FROM campaigns WHERE id=?", (campaign_id,))

    def active_campaigns(self, category: str | None = None) -> list[dict]:
        if category:
            return self.all(
                "SELECT * FROM campaigns WHERE status='active' AND category=? ORDER BY id",
                (category,),
            )
        return self.all("SELECT * FROM campaigns WHERE status='active' ORDER BY id")

    def close_campaign(self, campaign_id: int, reason: str):
        self.execute(
            "UPDATE campaigns SET status='closed', closed_at=?, closure_reason=? WHERE id=? AND status='active'",
            (now_iso(), reason, campaign_id),
        )

    def add_campaign_channel(
        self, campaign_id: int, chat_id: int, entry_mode: str, invite_link: str | None,
        invite_link_name: str | None, start_member_count: int | None, link_error: str | None = None,
    ) -> int:
        now = now_iso()
        return self.execute(
            """
            INSERT INTO campaign_channels(
                campaign_id, chat_id, entry_mode, invite_link, invite_link_name,
                start_member_count, link_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(campaign_id, chat_id) DO UPDATE SET
                entry_mode=excluded.entry_mode,
                invite_link=COALESCE(excluded.invite_link, campaign_channels.invite_link),
                invite_link_name=COALESCE(excluded.invite_link_name, campaign_channels.invite_link_name),
                start_member_count=COALESCE(campaign_channels.start_member_count, excluded.start_member_count),
                link_revoked_at=NULL,
                link_error=excluded.link_error,
                updated_at=excluded.updated_at
            """,
            (campaign_id, chat_id, entry_mode, invite_link, invite_link_name,
             start_member_count, link_error, now, now),
        )

    def campaign_channels(self, campaign_id: int) -> list[dict]:
        return self.all(
            """
            SELECT cc.*, c.telegram_title, c.button_title, c.button_style, c.owner_user_id,
                   c.category AS channel_category, c.pending_category, c.status AS channel_status
            FROM campaign_channels cc
            LEFT JOIN channels c ON c.chat_id=cc.chat_id
            WHERE cc.campaign_id=? ORDER BY cc.id
            """,
            (campaign_id,),
        )

    def campaign_button_channels(self, campaign_id: int) -> list[dict]:
        return self.all(
            """
            SELECT cc.*, c.telegram_title, c.button_title, c.button_style, c.owner_user_id,
                   c.category AS channel_category, c.status AS channel_status
            FROM campaign_channels cc
            JOIN channels c ON c.chat_id=cc.chat_id
            WHERE cc.campaign_id=? AND c.status='approved'
              AND cc.invite_link IS NOT NULL AND cc.link_revoked_at IS NULL
              AND cc.link_error IS NULL
            ORDER BY COALESCE(c.button_title, c.telegram_title) COLLATE NOCASE
            """,
            (campaign_id,),
        )

    def campaign_channel(self, campaign_id: int, chat_id: int) -> dict | None:
        return self.one(
            "SELECT * FROM campaign_channels WHERE campaign_id=? AND chat_id=?",
            (campaign_id, chat_id),
        )

    def campaign_channel_by_link(self, invite_link: str) -> dict | None:
        return self.one(
            """
            SELECT cc.*, cp.status AS campaign_status, cp.category, cp.expires_at
            FROM campaign_channels cc JOIN campaigns cp ON cp.id=cc.campaign_id
            WHERE cc.invite_link=? ORDER BY cc.id DESC LIMIT 1
            """,
            (invite_link,),
        )

    def record_campaign_request(self, invite_link: str, user_id: int, requested_at: str) -> dict | None:
        target = self.campaign_channel_by_link(invite_link)
        if not target or target.get("campaign_status") != "active":
            return None
        now = now_iso()
        existing = self.one(
            "SELECT * FROM campaign_users WHERE campaign_id=? AND chat_id=? AND user_id=?",
            (target["campaign_id"], target["chat_id"], user_id),
        )
        if existing:
            first = existing.get("requested_at") or requested_at
            self.execute(
                """UPDATE campaign_users SET invite_link=?, requested_at=?, request_count=COALESCE(request_count,0)+1,
                   updated_at=? WHERE id=?""",
                (invite_link, first, now, existing["id"]),
            )
        else:
            self.execute(
                """INSERT INTO campaign_users(
                    campaign_id, chat_id, user_id, invite_link, requested_at, request_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                (target["campaign_id"], target["chat_id"], user_id, invite_link, requested_at, now, now),
            )
        self.refresh_campaign_counters(target["campaign_id"], target["chat_id"])
        return target

    def record_campaign_join(
        self, invite_link: str, user_id: int, joined_at: str, via_join_request: bool = False,
    ) -> dict | None:
        target = self.campaign_channel_by_link(invite_link)
        if not target or target.get("campaign_status") != "active":
            return None
        now = now_iso()
        existing = self.one(
            "SELECT * FROM campaign_users WHERE campaign_id=? AND chat_id=? AND user_id=?",
            (target["campaign_id"], target["chat_id"], user_id),
        )
        if existing:
            first_join = existing.get("joined_at") or joined_at
            self.execute(
                """UPDATE campaign_users SET invite_link=?, joined_at=?, left_at=NULL,
                   via_join_request=MAX(via_join_request, ?), updated_at=? WHERE id=?""",
                (invite_link, first_join, int(via_join_request), now, existing["id"]),
            )
        else:
            self.execute(
                """INSERT INTO campaign_users(
                    campaign_id, chat_id, user_id, invite_link, joined_at, via_join_request, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (target["campaign_id"], target["chat_id"], user_id, invite_link,
                 joined_at, int(via_join_request), now, now),
            )
        self.refresh_campaign_counters(target["campaign_id"], target["chat_id"])
        return target

    def record_campaign_join_from_pending(self, chat_id: int, user_id: int, joined_at: str) -> dict | None:
        row = self.one(
            """
            SELECT cu.invite_link FROM campaign_users cu
            JOIN campaigns cp ON cp.id=cu.campaign_id
            WHERE cu.chat_id=? AND cu.user_id=? AND cu.requested_at IS NOT NULL
              AND cu.joined_at IS NULL AND cp.status='active'
            ORDER BY cu.id DESC LIMIT 1
            """,
            (chat_id, user_id),
        )
        if not row or not row.get("invite_link"):
            return None
        return self.record_campaign_join(row["invite_link"], user_id, joined_at, True)

    def record_campaign_leave(self, chat_id: int, user_id: int, left_at: str):
        rows = self.all(
            """
            SELECT cu.id, cu.campaign_id, cu.chat_id FROM campaign_users cu
            JOIN campaigns cp ON cp.id=cu.campaign_id
            WHERE cu.chat_id=? AND cu.user_id=? AND cu.joined_at IS NOT NULL
              AND cu.left_at IS NULL AND cp.status='active'
            """,
            (chat_id, user_id),
        )
        for row in rows:
            self.execute("UPDATE campaign_users SET left_at=?, updated_at=? WHERE id=?", (left_at, now_iso(), row["id"]))
            self.refresh_campaign_counters(row["campaign_id"], row["chat_id"])

    def refresh_campaign_counters(self, campaign_id: int, chat_id: int):
        counts = self.one(
            """
            SELECT COUNT(CASE WHEN requested_at IS NOT NULL THEN 1 END) AS requests_count,
                   COALESCE(SUM(request_count),0) AS request_events,
                   COUNT(CASE WHEN joined_at IS NOT NULL THEN 1 END) AS joined_count,
                   COUNT(CASE WHEN joined_at IS NOT NULL AND left_at IS NOT NULL THEN 1 END) AS left_count
            FROM campaign_users WHERE campaign_id=? AND chat_id=?
            """,
            (campaign_id, chat_id),
        ) or {}
        self.execute(
            """UPDATE campaign_channels SET requests_count=?, request_events=?, joined_count=?, left_count=?, updated_at=?
               WHERE campaign_id=? AND chat_id=?""",
            (int(counts.get("requests_count") or 0), int(counts.get("request_events") or 0),
             int(counts.get("joined_count") or 0), int(counts.get("left_count") or 0),
             now_iso(), campaign_id, chat_id),
        )

    def finalize_campaign_channel(self, campaign_id: int, chat_id: int, end_count: int | None, delta: int | None):
        self.refresh_campaign_counters(campaign_id, chat_id)
        self.execute(
            """UPDATE campaign_channels SET end_member_count=?, member_delta=?, updated_at=?
               WHERE campaign_id=? AND chat_id=?""",
            (end_count, delta, now_iso(), campaign_id, chat_id),
        )

    def mark_campaign_link_revoked(self, campaign_id: int, chat_id: int, error: str | None = None):
        if error:
            self.execute(
                "UPDATE campaign_channels SET link_error=?, updated_at=? WHERE campaign_id=? AND chat_id=?",
                (error, now_iso(), campaign_id, chat_id),
            )
        else:
            self.execute(
                "UPDATE campaign_channels SET link_revoked_at=?, link_error=NULL, updated_at=? WHERE campaign_id=? AND chat_id=?",
                (now_iso(), now_iso(), campaign_id, chat_id),
            )

    def campaign_stats_row(self, campaign_channel_id: int) -> dict | None:
        return self.one(
            """
            SELECT cc.*, cp.category, cp.started_at, cp.expires_at, cp.closed_at, cp.closure_reason,
                   c.telegram_title, c.owner_user_id, c.category AS channel_category_current, c.pending_category
            FROM campaign_channels cc
            JOIN campaigns cp ON cp.id=cc.campaign_id
            LEFT JOIN channels c ON c.chat_id=cc.chat_id
            WHERE cc.id=?
            """,
            (campaign_channel_id,),
        )

    def mark_campaign_stats_sent(self, campaign_channel_id: int):
        self.execute(
            """UPDATE campaign_channels SET stats_sent_at=?, stats_error=NULL, stats_last_attempt_at=?, updated_at=?
               WHERE id=?""",
            (now_iso(), now_iso(), now_iso(), campaign_channel_id),
        )

    def note_campaign_stats_attempt(self, campaign_channel_id: int, error: str | None = None):
        self.execute(
            """UPDATE campaign_channels SET stats_attempts=COALESCE(stats_attempts,0)+1,
               stats_last_attempt_at=?, stats_error=?, updated_at=? WHERE id=?""",
            (now_iso(), error, now_iso(), campaign_channel_id),
        )

    def pending_campaign_stats(self, limit: int = 100) -> list[dict]:
        return self.all(
            """
            SELECT cc.*, cp.category, cp.started_at, cp.closed_at, cp.closure_reason,
                   c.telegram_title, c.owner_user_id, c.category AS channel_category_current, c.pending_category
            FROM campaign_channels cc
            JOIN campaigns cp ON cp.id=cc.campaign_id
            LEFT JOIN channels c ON c.chat_id=cc.chat_id
            WHERE cp.status='closed' AND cc.invite_link IS NOT NULL AND cc.end_member_count IS NOT NULL
              AND cc.stats_sent_at IS NULL AND COALESCE(cc.stats_attempts,0) < 5
            ORDER BY cc.id LIMIT ?
            """,
            (limit,),
        )

    def active_board_messages_for_campaign(self, campaign_id: int) -> list[dict]:
        return self.all(
            "SELECT * FROM board_messages WHERE campaign_id=? AND active=1 ORDER BY id",
            (campaign_id,),
        )

    # Sessions ----------------------------------------------------------
    def set_session(
        self,
        user_id: int,
        action: str,
        chat_id: int | None = None,
        category: str | None = None,
        payload: dict | None = None,
    ):
        self.execute(
            """
            INSERT INTO sessions(user_id, action, chat_id, category, payload_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                action=excluded.action,
                chat_id=excluded.chat_id,
                category=excluded.category,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (user_id, action, chat_id, category, json.dumps(payload or {}), now_iso()),
        )

    def get_session(self, user_id: int) -> dict | None:
        row = self.one("SELECT * FROM sessions WHERE user_id=?", (user_id,))
        if row:
            row["payload"] = json.loads(row.pop("payload_json") or "{}")
        return row

    def clear_session(self, user_id: int):
        self.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
