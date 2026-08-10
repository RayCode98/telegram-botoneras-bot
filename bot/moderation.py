from __future__ import annotations

import html
import logging
from datetime import datetime

from telegram.error import BadRequest, TelegramError

from .config import CATEGORIES, Settings
from .db import Database
from .publisher import Publisher, is_missing_message_error

log = logging.getLogger(__name__)


class ModerationService:
    def __init__(self, db: Database, settings: Settings, publisher: Publisher, is_admin_func, safe_dm_func):
        self.db = db
        self.settings = settings
        self.publisher = publisher
        self.is_admin = is_admin_func
        self.safe_dm = safe_dm_func

    async def register_violation(
        self,
        bot,
        user_id: int | None,
        violation_type: str,
        chat_id: int | None,
        details: str,
        board_message_id: int | None = None,
    ) -> dict | None:
        if not user_id or self.is_admin(user_id):
            return None

        state = self.db.add_violation(
            user_id=user_id,
            violation_type=violation_type,
            chat_id=chat_id,
            board_message_id=board_message_id,
            details=details,
            violation_limit=self.settings.violation_limit,
        )

        strikes = int(state["strikes"])
        banned = bool(state["banned"])
        if banned:
            channels = self.db.ban_channels_for_owner(user_id)
            categories = {ch.get("category") for ch in channels if ch.get("category") in CATEGORIES}
            for category in categories:
                await self.publisher.refresh_category(bot, category)

            # Elimina publicaciones aún activas en canales del usuario y, opcionalmente,
            # hace que el bot abandone esos canales.
            for channel in channels:
                await self.publisher.delete_active_posts_for_chat(bot, channel["chat_id"], "owner_banned")
                if self.settings.leave_channels_on_ban:
                    try:
                        await bot.leave_chat(channel["chat_id"])
                    except TelegramError:
                        pass

            await self.safe_dm(
                bot,
                user_id,
                "🚫 <b>Acceso bloqueado.</b>\n\n"
                f"Alcanzaste {strikes}/{self.settings.violation_limit} faltas. "
                "Ya no podrás registrar canales hasta que un administrador retire la sanción.",
                parse_mode="HTML",
            )
        else:
            await self.safe_dm(
                bot,
                user_id,
                "⚠️ <b>Falta registrada.</b>\n\n"
                f"Llevas <b>{strikes}/{self.settings.violation_limit}</b> faltas.\n"
                f"Motivo: {html.escape(details)}",
                parse_mode="HTML",
            )
        return state

    async def handle_bot_removed(self, bot, channel: dict, actor_user_id: int | None):
        category = channel.get("category")
        owner_id = channel.get("owner_user_id")
        # Si Telegram informa quién ejecutó la acción, se sanciona a esa persona.
        # Si no hay actor útil, recae en el responsable registrado del canal.
        responsible = actor_user_id or owner_id

        self.db.set_channel_fields(channel["chat_id"], status="inactive")
        # Ya no tenemos permiso para borrar dentro de ese canal, pero sí dejamos sus
        # registros locales como inactivos para no seguir auditándolos.
        for row in self.db.active_board_messages_for_chat(channel["chat_id"]):
            self.db.mark_board_removed(row["id"], "bot_removed")

        if category in CATEGORIES:
            await self.publisher.refresh_category(bot, category)

        return await self.register_violation(
            bot,
            responsible,
            "bot_removed",
            channel["chat_id"],
            "El bot fue eliminado o perdió su rol de administrador durante la participación activa.",
        )

    async def handle_early_post_deletion(self, bot, row: dict):
        channel = self.db.get_channel(row["destination_chat_id"])
        self.db.mark_board_removed(row["id"], "deleted_early")
        if not channel:
            return None

        owner_id = channel.get("owner_user_id")
        owner_category = channel.get("category")
        self.db.set_channel_fields(channel["chat_id"], status="suspended")

        # Retiramos las demás botoneras del canal que cometió la falta para dejar de
        # distribuirle contenido hasta revisión.
        await self.publisher.delete_active_posts_for_chat(
            bot,
            channel["chat_id"],
            "channel_suspended",
            skip_board_id=row["id"],
        )

        # Su botón desaparece de su categoría inmediatamente.
        if owner_category in CATEGORIES:
            await self.publisher.refresh_category(bot, owner_category)

        return await self.register_violation(
            bot,
            owner_id,
            "post_deleted",
            channel["chat_id"],
            "Una botonera fue eliminada antes de que terminara su tiempo de publicación.",
            board_message_id=row["id"],
        )

    async def audit_active_posts(self, bot) -> dict:
        now = datetime.now(self.settings.timezone)
        checked = missing = failed = 0
        incidents: list[dict] = []
        rows = list(self.db.active_board_messages())

        for row in rows:
            current = self.db.get_board_message(row["id"])
            if not current or not current.get("active"):
                continue
            row = current
            expires_at = row.get("expires_at")
            if expires_at:
                try:
                    expires = datetime.fromisoformat(expires_at)
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=self.settings.timezone)
                    if expires <= now:
                        # La limpieza se encarga; al llegar a expiración no se sanciona.
                        continue
                except ValueError:
                    pass

            try:
                await bot.edit_message_reply_markup(
                    chat_id=row["destination_chat_id"],
                    message_id=row["message_id"],
                    reply_markup=self.publisher.markup_for_row(row),
                )
                self.db.mark_board_checked(row["id"])
                checked += 1
            except BadRequest as exc:
                if "not modified" in str(exc).lower():
                    self.db.mark_board_checked(row["id"])
                    checked += 1
                elif is_missing_message_error(exc):
                    missing += 1
                    channel = self.db.get_channel(row["destination_chat_id"])
                    state = await self.handle_early_post_deletion(bot, row)
                    incidents.append({
                        "row": row,
                        "channel": channel,
                        "user_id": channel.get("owner_user_id") if channel else None,
                        "sanction": state,
                    })
                else:
                    failed += 1
                    log.warning("Auditoría: no se pudo comprobar %s: %s", row["id"], exc)
            except TelegramError as exc:
                failed += 1
                log.warning("Auditoría: error en %s: %s", row["id"], exc)

        return {"checked": checked, "missing": missing, "failed": failed, "incidents": incidents}
