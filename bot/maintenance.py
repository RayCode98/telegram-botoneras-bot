from __future__ import annotations

import asyncio
import html
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError

from .config import CATEGORIES, Settings
from .db import Database

log = logging.getLogger(__name__)

REQUIRED_CHANNEL_RIGHTS = (
    ("can_post_messages", "publicar mensajes"),
    ("can_edit_messages", "editar mensajes"),
    ("can_delete_messages", "eliminar mensajes"),
    ("can_invite_users", "invitar usuarios / crear enlaces"),
)


class MaintenanceService:
    def __init__(self, db: Database, settings: Settings, safe_dm_func):
        self.db = db
        self.settings = settings
        self.safe_dm = safe_dm_func
        self.started_at = datetime.now(settings.timezone)
        self.last_permission_audit: dict | None = None
        self.last_backup: dict | None = None

    # ------------------------------------------------------------------
    # Backups
    # ------------------------------------------------------------------
    def _backup_dir(self) -> Path:
        path = self.settings.backup_dir
        if not path.is_absolute():
            path = self.settings.database_path.parent / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _backup_sync(self) -> Path:
        directory = self._backup_dir()
        now = datetime.now(self.settings.timezone)
        destination = directory / f"botoneras_{now.strftime('%Y%m%d_%H%M%S')}.sqlite3"

        source = sqlite3.connect(self.settings.database_path)
        target = sqlite3.connect(destination)
        try:
            # SQLite Online Backup API: obtiene una instantánea consistente aun
            # cuando la base está siendo utilizada por el bot.
            source.backup(target)
            row = target.execute("PRAGMA quick_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                raise RuntimeError(f"quick_check del backup devolvió: {row}")
        finally:
            target.close()
            source.close()

        self._prune_backups_sync()
        return destination

    def _prune_backups_sync(self) -> int:
        directory = self._backup_dir()
        cutoff = datetime.now().timestamp() - (self.settings.backup_retention_days * 86400)
        removed = 0
        for path in directory.glob("botoneras_*.sqlite3"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                log.warning("No se pudo rotar backup %s", path)
        return removed

    async def create_backup(self, reason: str = "automatic") -> dict:
        try:
            path = await asyncio.to_thread(self._backup_sync)
            size = path.stat().st_size
            result = {"ok": True, "path": str(path), "size": size, "reason": reason, "created_at": datetime.now(self.settings.timezone).isoformat()}
            self.last_backup = result
            self.db.log_system_event("backup", f"Backup {reason} creado: {path} ({size} bytes)")
            return result
        except Exception as exc:
            result = {"ok": False, "error": str(exc), "reason": reason, "created_at": datetime.now(self.settings.timezone).isoformat()}
            self.last_backup = result
            self.db.log_system_event("backup_error", str(exc), "error")
            log.exception("Falló el backup")
            return result

    def latest_backup_info(self) -> dict | None:
        try:
            files = sorted(self._backup_dir().glob("botoneras_*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return None
        if not files:
            return None
        path = files[0]
        return {
            "path": str(path),
            "size": path.stat().st_size,
            "mtime": datetime.fromtimestamp(path.stat().st_mtime, self.settings.timezone),
        }

    # ------------------------------------------------------------------
    # Channel permissions
    # ------------------------------------------------------------------
    async def inspect_channel_permissions(self, bot, channel: dict) -> tuple[bool, list[str]]:
        try:
            member = await bot.get_chat_member(channel["chat_id"], bot.id)
        except TelegramError as exc:
            return False, [f"no se pudo verificar al bot: {exc}"]

        if member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}:
            return False, ["el bot ya no es administrador"]

        missing: list[str] = []
        if member.status != ChatMemberStatus.OWNER:
            for attr, label in REQUIRED_CHANNEL_RIGHTS:
                if not bool(getattr(member, attr, False)):
                    missing.append(label)
        return not missing, missing

    async def audit_permissions(self, bot, publisher, *, notify: bool = True) -> dict:
        checked = suspended = restored = failed = 0
        changed_categories: set[str] = set()
        details: list[dict] = []

        for channel in list(self.db.channels_for_permission_audit()):
            ok, issues = await self.inspect_channel_permissions(bot, channel)
            checked += 1
            old_status = channel.get("status")
            issue_text = "; ".join(issues) if issues else None
            self.db.set_channel_permission_state(channel["chat_id"], ok, issue_text)

            if ok:
                if old_status == "permission_suspended":
                    self.db.set_channel_fields(channel["chat_id"], status="approved")
                    restored += 1
                    if channel.get("category") in CATEGORIES:
                        changed_categories.add(channel["category"])
                    if notify:
                        await self.safe_dm(
                            bot,
                            channel.get("owner_user_id"),
                            "✅ <b>Permisos restaurados.</b>\n\n"
                            f"El canal <b>{html.escape(channel.get('telegram_title') or str(channel['chat_id']))}</b> vuelve a estar habilitado para las botoneras.",
                            parse_mode="HTML",
                        )
            else:
                # Si Telegram no permite ni verificar, lo tratamos como suspensión
                # preventiva, nunca como falta. my_chat_member seguirá atendiendo una
                # expulsión explícita y su sistema de sanciones por separado.
                if old_status == "approved":
                    self.db.set_channel_fields(channel["chat_id"], status="permission_suspended")
                    suspended += 1
                    if channel.get("category") in CATEGORIES:
                        changed_categories.add(channel["category"])
                    if notify:
                        await self.safe_dm(
                            bot,
                            channel.get("owner_user_id"),
                            "⚠️ <b>Canal suspendido preventivamente.</b>\n\n"
                            f"Canal: <b>{html.escape(channel.get('telegram_title') or str(channel['chat_id']))}</b>\n"
                            f"Problema: <b>{html.escape(issue_text or 'permisos incompletos')}</b>\n\n"
                            "No participará en nuevas publicaciones hasta que restaures los permisos. El sistema lo reactivará automáticamente cuando estén correctos.",
                            parse_mode="HTML",
                        )
                details.append({"chat_id": channel["chat_id"], "issues": issues})

        for category in changed_categories:
            try:
                await publisher.refresh_category(bot, category)
            except Exception as exc:
                failed += 1
                log.warning("No se pudo refrescar %s tras auditoría de permisos: %s", category, exc)

        result = {
            "checked": checked,
            "suspended": suspended,
            "restored": restored,
            "failed": failed,
            "issues": details,
            "at": datetime.now(self.settings.timezone).isoformat(),
        }
        self.last_permission_audit = result
        self.db.log_system_event(
            "permission_audit",
            f"checked={checked}; suspended={suspended}; restored={restored}; failed={failed}",
            "warning" if suspended or failed else "info",
        )
        return result

    async def validate_publish_destination(self, bot, channel: dict) -> tuple[bool, list[str]]:
        """Comprobación inmediata justo antes de publicar en un canal."""
        ok, issues = await self.inspect_channel_permissions(bot, channel)
        self.db.set_channel_permission_state(channel["chat_id"], ok, "; ".join(issues) if issues else None)
        if not ok and channel.get("status") == "approved":
            self.db.set_channel_fields(channel["chat_id"], status="permission_suspended")
            await self.safe_dm(
                bot,
                channel.get("owner_user_id"),
                "⚠️ <b>Tu canal no recibió esta botonera.</b>\n\n"
                f"Faltan permisos: <b>{html.escape(', '.join(issues) or 'permisos de administrador')}</b>.\n"
                "Fue suspendido preventivamente y se reactivará automáticamente cuando los permisos vuelvan a ser correctos.",
                parse_mode="HTML",
            )
        elif ok and channel.get("status") == "permission_suspended":
            self.db.set_channel_fields(channel["chat_id"], status="approved")
        return ok, issues

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    async def health_report(self, application) -> dict:
        bot_ok = True
        bot_name = "—"
        bot_error = None
        try:
            me = await application.bot.get_me()
            bot_name = f"@{me.username}" if me.username else me.full_name
        except Exception as exc:
            bot_ok = False
            bot_error = str(exc)

        try:
            db_check = self.db.database_quick_check()
        except Exception as exc:
            db_check = f"ERROR: {exc}"

        try:
            jobs = list(application.job_queue.jobs())
            job_names = [job.name for job in jobs]
        except Exception:
            try:
                jobs = list(application.job_queue.scheduler.get_jobs())
                job_names = [getattr(job, "name", str(job)) for job in jobs]
            except Exception:
                job_names = []

        latest = self.latest_backup_info()
        permission_suspended = len(self.db.channels_by_status("permission_suspended"))
        conflicts = self.db.recent_ownership_conflicts(limit=5)
        recent_errors = [e for e in self.db.recent_system_events(20) if e.get("severity") == "error"][:5]
        uptime = datetime.now(self.settings.timezone) - self.started_at

        return {
            "bot_ok": bot_ok,
            "bot_name": bot_name,
            "bot_error": bot_error,
            "db_check": db_check,
            "jobs": job_names,
            "latest_backup": latest,
            "permission_suspended": permission_suspended,
            "conflicts": conflicts,
            "recent_errors": recent_errors,
            "active_posts": len(self.db.active_board_messages()),
            "approved_channels": len(self.db.approved_channels()),
            "pending_channels": len(self.db.pending_channels()),
            "uptime": uptime,
        }
