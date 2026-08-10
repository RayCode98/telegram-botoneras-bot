from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

CATEGORIES = ("5K", "10K", "20K", "30K", "+50K")
BUTTON_STYLES = ("default", "primary", "success", "danger")


@dataclass(frozen=True)
class Settings:
    token: str
    admin_ids: frozenset[int]
    timezone_name: str
    database_path: Path
    distribute_mode: str
    max_buttons_per_board: int
    min_members: int
    default_lifetime_hours: float
    violation_limit: int
    integrity_check_seconds: int
    cleanup_check_seconds: int
    category_check_seconds: int
    leave_channels_on_ban: bool
    upcoming_notice_minutes: int
    # v6: mantenimiento/robustez
    backup_enabled: bool
    backup_dir: Path
    backup_hour: int
    backup_minute: int
    backup_retention_days: int
    permission_check_seconds: int

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


def _parse_admin_ids(value: str) -> frozenset[int]:
    result: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if part:
            result.add(int(part))
    return frozenset(result)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Falta BOT_TOKEN en el archivo .env")

    mode = os.getenv("DISTRIBUTE_MODE", "category").strip().lower()
    if mode not in {"category", "all"}:
        raise RuntimeError("DISTRIBUTE_MODE debe ser 'category' o 'all'.")

    lifetime = float(os.getenv("DEFAULT_POST_LIFETIME_HOURS", "6"))
    if not 0.25 <= lifetime <= 47:
        raise RuntimeError("DEFAULT_POST_LIFETIME_HOURS debe estar entre 0.25 y 47 horas.")

    backup_hour = int(os.getenv("BACKUP_HOUR", "3"))
    backup_minute = int(os.getenv("BACKUP_MINUTE", "30"))
    if not 0 <= backup_hour <= 23 or not 0 <= backup_minute <= 59:
        raise RuntimeError("BACKUP_HOUR/BACKUP_MINUTE contienen una hora inválida.")

    return Settings(
        token=token,
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        timezone_name=os.getenv("TIMEZONE", "America/Mexico_City"),
        database_path=Path(os.getenv("DATABASE_PATH", "botoneras.sqlite3")),
        distribute_mode=mode,
        max_buttons_per_board=int(os.getenv("MAX_BUTTONS_PER_BOARD", "100")),
        min_members=int(os.getenv("MIN_MEMBERS", "5000")),
        default_lifetime_hours=lifetime,
        violation_limit=max(1, int(os.getenv("VIOLATION_LIMIT", "3"))),
        integrity_check_seconds=max(60, int(os.getenv("INTEGRITY_CHECK_SECONDS", "300"))),
        cleanup_check_seconds=max(30, int(os.getenv("CLEANUP_CHECK_SECONDS", "60"))),
        category_check_seconds=max(300, int(os.getenv("CATEGORY_CHECK_SECONDS", "900"))),
        leave_channels_on_ban=_bool_env("LEAVE_CHANNELS_ON_BAN", True),
        upcoming_notice_minutes=max(5, int(os.getenv("UPCOMING_NOTICE_MINUTES", "30"))),
        backup_enabled=_bool_env("BACKUP_ENABLED", True),
        backup_dir=Path(os.getenv("BACKUP_DIR", "backups")),
        backup_hour=backup_hour,
        backup_minute=backup_minute,
        backup_retention_days=max(1, int(os.getenv("BACKUP_RETENTION_DAYS", "14"))),
        permission_check_seconds=max(300, int(os.getenv("PERMISSION_CHECK_SECONDS", "900"))),
    )


def category_from_members(member_count: int, min_members: int = 5000) -> str:
    if member_count < min_members:
        return "BELOW_5K"
    if member_count < 10_000:
        return "5K"
    if member_count < 20_000:
        return "10K"
    if member_count < 30_000:
        return "20K"
    if member_count < 50_000:
        return "30K"
    return "+50K"
