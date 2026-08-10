from __future__ import annotations

import asyncio
import html
import logging
import random
from datetime import datetime, timedelta

from telegram import InlineKeyboardMarkup, InputMediaPhoto
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from .config import CATEGORIES, Settings, category_from_members
from .db import Database
from .keyboards import rows_one, url_button

log = logging.getLogger(__name__)


MISSING_MESSAGE_PATTERNS = (
    "message to edit not found",
    "message not found",
    "message_id_invalid",
    "message identifier is not specified",
)

STATS_REMOVAL_REASONS = {"expired", "manual_admin_delete"}


def is_missing_message_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(pattern in text for pattern in MISSING_MESSAGE_PATTERNS)


class Publisher:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        # Se inyecta desde app.py para evitar acoplar el publicador al servicio
        # de mantenimiento. Debe devolver (ok, issues).
        self.permission_validator = None

    async def _notify_owner(self, bot, channel: dict | None, pref_key: str, text: str) -> bool:
        if not channel or not channel.get("owner_user_id"):
            return False
        owner_id = int(channel["owner_user_id"])
        prefs = self.db.get_user_preferences(owner_id)
        if not bool(prefs.get(pref_key, 1)):
            return False
        user = self.db.get_user(owner_id)
        if not user:
            return False
        try:
            await bot.send_message(chat_id=user["private_chat_id"], text=text, parse_mode="HTML")
            return True
        except (Forbidden, BadRequest, TelegramError):
            return False

    async def _notify_category_changes(self, bot, changes: list[dict]):
        for change in changes:
            channel = self.db.get_channel(change["chat_id"])
            if not channel:
                continue
            old = change.get("old_category") or "—"
            new = change.get("new_category") or "—"
            title = html.escape(channel.get("telegram_title") or str(channel["chat_id"]))
            if new == "BELOW_5K":
                body = (f"📉 <b>Cambio de categoría</b>\n\nCanal: <b>{title}</b>\n"
                        f"{html.escape(str(old))} ➜ <b>Por debajo del mínimo</b>\n\n"
                        "El canal quedará fuera de nuevas botoneras hasta volver a cumplir el mínimo.")
            else:
                body = (f"🎉 <b>¡Tu canal cambió de categoría!</b>\n\nCanal: <b>{title}</b>\n"
                        f"{html.escape(str(old))} ➜ <b>{html.escape(str(new))}</b> 🚀\n\n"
                        "La nueva categoría se utilizará en la próxima publicación.")
            await self._notify_owner(bot, channel, "notify_category_change", body)

    async def _send_started_notice(self, bot, channel: dict, category: str, start_count: int | None, expires_at: str):
        schedule = self.db.get_schedule(category) or {}
        shuffle = bool(schedule.get("shuffle_enabled"))
        interval = int(schedule.get("shuffle_interval_minutes") or 10)
        try:
            end_dt = datetime.fromisoformat(expires_at).astimezone(self.settings.timezone)
            end_text = end_dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            end_text = expires_at
        text = (
            f"🚀 <b>¡Botonera iniciada!</b>\n\n"
            f"Canal: <b>{html.escape(channel.get('telegram_title') or str(channel['chat_id']))}</b>\n"
            f"Categoría: <b>{html.escape(category)}</b>\n"
            f"Suscriptores iniciales: <b>{int(start_count or 0):,}</b>\n"
            f"Finaliza: <b>{html.escape(end_text)}</b>\n"
            + (f"🔀 Mezcla de canales: cada <b>{interval} min</b>\n" if shuffle else "🔀 Mezcla: <b>desactivada</b>\n")
            + "\nAl finalizar recibirás tus resultados si tienes activadas las estadísticas."
        )
        await self._notify_owner(bot, channel, "notify_board_started", text)

    async def _send_finished_notice(self, bot, channel: dict, row: dict):
        end = row.get("end_member_count")
        text = (
            f"🏁 <b>Botonera finalizada</b>\n\n"
            f"Canal: <b>{html.escape(channel.get('telegram_title') or str(channel['chat_id']))}</b>\n"
            f"Categoría: <b>{html.escape(row.get('category') or '—')}</b>\n"
            + (f"Suscriptores al cierre: <b>{int(end):,}</b>\n" if end is not None else "")
            + "La publicación ya fue retirada de los canales."
        )
        await self._notify_owner(bot, channel, "notify_board_finished", text)

    # ------------------------------------------------------------------
    # Markup / shuffle
    # ------------------------------------------------------------------
    def _channel_buttons(self, category: str) -> list:
        buttons = []
        for ch in self.db.approved_channels(category):
            if ch.get("invite_url"):
                buttons.append(
                    url_button(
                        ch.get("button_title") or ch["telegram_title"],
                        ch["invite_url"],
                        ch.get("button_style") or "default",
                    )
                )
        return buttons

    def _manual_buttons(self, category: str) -> list:
        # Los botones manuales mantienen siempre el orden definido por el admin.
        return [
            url_button(button["title"], button["url"], button.get("style") or "default")
            for button in self.db.manual_buttons(category)
        ]

    def build_markup(
        self,
        category: str,
        *,
        shuffle_channels: bool = False,
        shuffle_seed: int | None = None,
    ) -> InlineKeyboardMarkup:
        channel_buttons = self._channel_buttons(category)

        if shuffle_seed is not None:
            random.Random(int(shuffle_seed)).shuffle(channel_buttons)
        elif shuffle_channels:
            random.shuffle(channel_buttons)

        # Los botones de admin se agregan DESPUÉS del bloque de canales y nunca
        # participan en random.shuffle(). Además se les reserva espacio dentro del
        # límite para que una mezcla no haga desaparecer botones manuales.
        manual_buttons = self._manual_buttons(category)
        if self.settings.max_buttons_per_board > 0:
            limit = self.settings.max_buttons_per_board
            manual_buttons = manual_buttons[:limit]
            channel_limit = max(0, limit - len(manual_buttons))
            channel_buttons = channel_buttons[:channel_limit]
        buttons = channel_buttons + manual_buttons
        return rows_one(buttons) if buttons else InlineKeyboardMarkup([])

    def markup_for_row(self, row: dict) -> InlineKeyboardMarkup:
        return self.build_markup(
            row["category"],
            shuffle_seed=row.get("shuffle_seed"),
        )

    def shuffle_enabled(self, category: str) -> bool:
        schedule = self.db.get_schedule(category) or {}
        return bool(schedule.get("shuffle_enabled"))

    def new_shuffle_seed(self) -> int:
        return random.SystemRandom().randrange(1, 2_147_483_647)

    async def shuffle_category(self, bot, category: str) -> dict:
        """Mezcla solo botones de canales en cada copia activa."""
        if not self.shuffle_enabled(category):
            return {"edited": 0, "failed": 0, "missing": 0}

        edited = failed = missing = 0
        for row in list(self.db.live_board_messages(category)):
            seed = self.new_shuffle_seed()
            try:
                await bot.edit_message_reply_markup(
                    chat_id=row["destination_chat_id"],
                    message_id=row["message_id"],
                    reply_markup=self.build_markup(category, shuffle_seed=seed),
                )
                self.db.set_board_shuffle_seed(row["id"], seed)
                self.db.mark_board_checked(row["id"])
                edited += 1
            except BadRequest as exc:
                if "not modified" in str(exc).lower():
                    # La permutación puede coincidir si hay pocos botones.
                    self.db.set_board_shuffle_seed(row["id"], seed)
                    self.db.mark_board_checked(row["id"])
                    edited += 1
                elif is_missing_message_error(exc):
                    missing += 1
                else:
                    failed += 1
                    log.warning("No se pudo mezclar publicación %s: %s", row["id"], exc)
            except TelegramError as exc:
                failed += 1
                log.warning("No se pudo mezclar publicación %s: %s", row["id"], exc)
        return {"edited": edited, "failed": failed, "missing": missing}

    # ------------------------------------------------------------------
    # Destinations / lifetime
    # ------------------------------------------------------------------
    def destinations(self, category: str) -> list[dict]:
        return self.db.approved_channels() if self.settings.distribute_mode == "all" else self.db.approved_channels(category)

    def publication_candidates(self, category: str) -> list[dict]:
        # Incluye permission_suspended para poder revalidar y reactivar justo
        # antes de una publicación si el propietario ya corrigió los permisos.
        return self.db.publication_candidates() if self.settings.distribute_mode == "all" else self.db.publication_candidates(category)

    def lifetime_hours(self, category: str) -> float:
        schedule = self.db.get_schedule(category) or {}
        return float(schedule.get("lifetime_hours") or self.settings.default_lifetime_hours)

    # ------------------------------------------------------------------
    # Member counts, stats and automatic category changes
    # ------------------------------------------------------------------
    async def _member_count(self, bot, chat_id: int, fallback: int | None = None) -> int | None:
        try:
            return int(await bot.get_chat_member_count(chat_id))
        except RetryAfter as exc:
            retry_after = getattr(exc, "retry_after", 1)
            try:
                seconds = float(retry_after.total_seconds())
            except AttributeError:
                seconds = float(retry_after)
            await asyncio.sleep(max(0.1, seconds) + 0.25)
            try:
                return int(await bot.get_chat_member_count(chat_id))
            except TelegramError:
                return fallback
        except TelegramError:
            return fallback

    def _queue_category_change(self, channel: dict, member_count: int | None) -> str | None:
        if member_count is None:
            return channel.get("pending_category")

        target = category_from_members(member_count, self.settings.min_members)
        current = channel.get("category")
        self.db.set_channel_fields(channel["chat_id"], member_count=member_count)

        if target == current:
            if channel.get("pending_category"):
                self.db.set_pending_category(channel["chat_id"], None)
            return current

        # Se difiere el cambio hasta que no haya una botonera activa ni en la
        # categoría de origen ni en la de destino. Así una campaña no cambia a mitad.
        self.db.set_pending_category(channel["chat_id"], target)
        return target

    def apply_pending_categories_if_safe(self) -> list[dict]:
        changes: list[dict] = []
        for channel in self.db.channels_with_pending_category():
            old = channel.get("category")
            new = channel.get("pending_category")
            if not new:
                continue

            old_active = bool(old in CATEGORIES and self.db.live_board_messages(old))
            new_active = bool(new in CATEGORIES and self.db.live_board_messages(new))
            if old_active or new_active:
                continue

            old_cat, new_cat = self.db.apply_pending_category(channel["chat_id"])
            if new_cat:
                if new_cat == "BELOW_5K":
                    self.db.set_channel_fields(channel["chat_id"], status="below_minimum")
                elif channel.get("status") == "below_minimum":
                    self.db.set_channel_fields(channel["chat_id"], status="approved")
                changes.append({
                    "chat_id": channel["chat_id"],
                    "title": channel.get("telegram_title"),
                    "old_category": old_cat,
                    "new_category": new_cat,
                })
        return changes

    async def audit_channel_categories(self, bot) -> dict:
        checked = changed = failed = 0
        for channel in list(self.db.participant_channels_for_audit()):
            current_count = int(channel.get("member_count") or 0)
            count = await self._member_count(bot, channel["chat_id"], current_count)
            if count is None:
                failed += 1
                continue
            checked += 1
            target = category_from_members(count, self.settings.min_members)
            if target != channel.get("category"):
                changed += 1
            self._queue_category_change(channel, count)

        applied = self.apply_pending_categories_if_safe()
        await self._notify_category_changes(bot, applied)
        return {
            "checked": checked,
            "detected_changes": changed,
            "applied": len(applied),
            "changes": applied,
            "failed": failed,
        }

    async def _send_stats_message(self, bot, row: dict) -> bool:
        channel = self.db.get_channel(row["destination_chat_id"])
        if not channel or not channel.get("owner_user_id"):
            self.db.note_stats_attempt(row["id"], "Canal sin responsable registrado")
            return False

        user = self.db.get_user(channel["owner_user_id"])
        if not user:
            self.db.note_stats_attempt(row["id"], "El propietario todavía no inició /start")
            return False
        prefs = self.db.get_user_preferences(int(channel["owner_user_id"]))
        if not bool(prefs.get("notify_stats", 1)):
            self.db.mark_stats_sent(row["id"])
            return True

        start = row.get("start_member_count")
        end = row.get("end_member_count")
        delta = row.get("member_delta")
        if start is None or end is None or delta is None:
            return False

        if delta > 0:
            result_text = f"📈 Ganaste <b>+{delta:,}</b> suscriptores"
            delta_text = f"+{delta:,}"
        elif delta < 0:
            result_text = f"📉 Perdiste <b>{abs(delta):,}</b> suscriptores"
            delta_text = f"{delta:,}"
        else:
            result_text = "➖ No hubo cambio neto de suscriptores"
            delta_text = "0"

        current_category = channel.get("category") or "—"
        pending = channel.get("pending_category")
        category_line = f"Categoría actual: <b>{html.escape(str(current_category))}</b>"
        if pending and pending != current_category:
            category_line += f"\nPróxima categoría: <b>{html.escape(str(pending))}</b> 🔄"

        text = (
            f"📊 <b>Resultados de tu botonera {html.escape(row['category'])}</b>\n\n"
            f"Canal: <b>{html.escape(channel.get('telegram_title') or str(channel['chat_id']))}</b>\n"
            f"Suscriptores al publicar: <b>{int(start):,}</b>\n"
            f"Suscriptores al finalizar: <b>{int(end):,}</b>\n"
            f"Diferencia: <b>{delta_text}</b>\n\n"
            f"{result_text}\n\n"
            f"{category_line}\n\n"
            "ℹ️ La diferencia compara el total del canal al inicio y al final de la publicación."
        )

        self.db.note_stats_attempt(row["id"], None)
        try:
            await bot.send_message(
                chat_id=user["private_chat_id"],
                text=text,
                parse_mode="HTML",
            )
        except (Forbidden, BadRequest, TelegramError) as exc:
            self.db.save_board_stats(row["id"], end, delta, str(exc)[:300])
            return False

        self.db.mark_stats_sent(row["id"])
        return True

    async def retry_pending_stats(self, bot, limit: int = 100) -> dict:
        sent = failed = 0
        for row in self.db.pending_stats_messages(limit=limit):
            if await self._send_stats_message(bot, row):
                sent += 1
            else:
                failed += 1
        return {"sent": sent, "failed": failed}

    async def _finalize_board_completion(self, bot, row: dict):
        if row.get("removal_reason") not in STATS_REMOVAL_REASONS:
            return

        channel = self.db.get_channel(row["destination_chat_id"])
        if not channel:
            return

        fallback = int(channel.get("member_count") or 0)
        end_count = await self._member_count(bot, channel["chat_id"], fallback)
        start_count = row.get("start_member_count")
        delta = None
        if end_count is not None and start_count is not None:
            delta = int(end_count) - int(start_count)

        self.db.save_board_stats(row["id"], end_count, delta)
        if end_count is not None:
            self._queue_category_change(channel, end_count)

        fresh = self.db.get_board_message(row["id"]) or row
        await self._send_finished_notice(bot, channel, fresh)
        await self._send_stats_message(bot, fresh)

    # ------------------------------------------------------------------
    # Delete / publish / refresh
    # ------------------------------------------------------------------
    async def _delete_row(self, bot, row: dict, reason: str) -> bool:
        """
        Borra un post y solo lo marca inactivo cuando Telegram confirma el borrado
        o cuando confirma que el mensaje ya no existe. Un error real queda activo
        para poder reintentarlo posteriormente.
        """
        try:
            await bot.delete_message(chat_id=row["destination_chat_id"], message_id=row["message_id"])
        except RetryAfter as exc:
            retry_after = getattr(exc, "retry_after", 1)
            try:
                seconds = float(retry_after.total_seconds())
            except AttributeError:
                seconds = float(retry_after)
            log.info("Telegram pidió esperar %.2fs antes de continuar borrando", seconds)
            await asyncio.sleep(max(0.1, seconds) + 0.25)
            return False
        except BadRequest as exc:
            if is_missing_message_error(exc):
                self.db.mark_board_removed(row["id"], reason)
                completed = self.db.get_board_message(row["id"]) or row
                if reason in STATS_REMOVAL_REASONS:
                    await self._finalize_board_completion(bot, completed)
                return True
            log.warning("No se pudo borrar publicación %s: %s", row["id"], exc)
            return False
        except TelegramError as exc:
            log.warning("No se pudo borrar publicación %s: %s", row["id"], exc)
            return False

        self.db.mark_board_removed(row["id"], reason)
        completed = self.db.get_board_message(row["id"]) or row
        if reason in STATS_REMOVAL_REASONS:
            await self._finalize_board_completion(bot, completed)
        return True

    async def delete_category_everywhere(
        self,
        bot,
        category: str,
        reason: str = "manual_admin_delete",
        attempts: int = 3,
    ) -> dict:
        initial = list(self.db.live_board_messages(category))
        if not initial:
            return {"total": 0, "deleted": 0, "failed": 0, "remaining": [], "category_changes": []}

        successful_ids: set[int] = set()
        max_attempts = max(1, int(attempts))

        for round_no in range(max_attempts):
            pending = list(self.db.live_board_messages(category))
            if not pending:
                break
            for row in pending:
                if await self._delete_row(bot, row, reason):
                    successful_ids.add(row["id"])
            if self.db.live_board_messages(category) and round_no < max_attempts - 1:
                await asyncio.sleep(0.75)

        remaining = list(self.db.live_board_messages(category))
        changes = self.apply_pending_categories_if_safe()
        await self._notify_category_changes(bot, changes)
        return {
            "total": len(initial),
            "deleted": len(successful_ids),
            "failed": len(remaining),
            "remaining": remaining,
            "category_changes": changes,
        }

    async def delete_active_for_category_destination(self, bot, category: str, chat_id: int, reason: str):
        for row in self.db.active_for_category_destination(category, chat_id):
            await self._delete_row(bot, row, reason)

    async def delete_active_posts_for_chat(self, bot, chat_id: int, reason: str, skip_board_id: int | None = None):
        for row in self.db.active_board_messages_for_chat(chat_id):
            if skip_board_id and row["id"] == skip_board_id:
                continue
            await self._delete_row(bot, row, reason)

    async def publish_category(self, bot, category: str) -> dict:
        template = self.db.get_template(category)
        if not template or not template.get("photo_file_id"):
            return {"sent": 0, "failed": 0, "reason": "La plantilla no tiene imagen."}

        # Aplica cambios de categoría pendientes solo si no alteran campañas activas.
        pre_changes = self.apply_pending_categories_if_safe()
        await self._notify_category_changes(bot, pre_changes)

        now = datetime.now(self.settings.timezone)
        today = now.date().isoformat()
        expires_at = (now + timedelta(hours=self.lifetime_hours(category))).isoformat(timespec="seconds")
        sent = failed = 0

        for channel in self.publication_candidates(category):
            chat_id = channel["chat_id"]
            try:
                if self.permission_validator is not None:
                    ok, _issues = await self.permission_validator(bot, channel)
                    if not ok:
                        failed += 1
                        continue
                    # El validador puede haber reactivado el canal.
                    channel = self.db.get_channel(chat_id) or channel

                await self.delete_active_for_category_destination(bot, category, chat_id, "replaced")

                start_count = await self._member_count(bot, chat_id, int(channel.get("member_count") or 0))
                if start_count is not None:
                    self.db.set_channel_fields(chat_id, member_count=start_count)

                seed = self.new_shuffle_seed() if self.shuffle_enabled(category) else None
                msg = await bot.send_photo(
                    chat_id=chat_id,
                    photo=template["photo_file_id"],
                    caption=template.get("text") or None,
                    reply_markup=self.build_markup(category, shuffle_seed=seed),
                    parse_mode="HTML",
                )
                self.db.add_board_message(
                    category,
                    chat_id,
                    msg.message_id,
                    today,
                    expires_at,
                    start_member_count=start_count,
                    channel_category_start=channel.get("category"),
                    shuffle_seed=seed,
                )
                await self._send_started_notice(bot, channel, category, start_count, expires_at)
                sent += 1
            except TelegramError as exc:
                failed += 1
                log.warning("No se pudo publicar %s en %s: %s", category, chat_id, exc)

        return {"sent": sent, "failed": failed, "reason": None, "expires_at": expires_at}

    async def refresh_category(self, bot, category: str) -> dict:
        edited = failed = missing = 0
        for row in self.db.live_board_messages(category):
            try:
                await bot.edit_message_reply_markup(
                    chat_id=row["destination_chat_id"],
                    message_id=row["message_id"],
                    reply_markup=self.markup_for_row(row),
                )
                self.db.mark_board_checked(row["id"])
                edited += 1
            except BadRequest as exc:
                if "not modified" in str(exc).lower():
                    self.db.mark_board_checked(row["id"])
                    edited += 1
                elif is_missing_message_error(exc):
                    missing += 1
                else:
                    failed += 1
                    log.warning("No se pudo refrescar publicación %s: %s", row["id"], exc)
            except TelegramError as exc:
                failed += 1
                log.warning("No se pudo refrescar publicación %s: %s", row["id"], exc)
        return {"edited": edited, "failed": failed, "missing": missing}

    async def refresh_content(self, bot, category: str) -> dict:
        template = self.db.get_template(category)
        if not template or not template.get("photo_file_id"):
            return {"edited": 0, "failed": 0, "missing": 0}
        edited = failed = missing = 0
        media = InputMediaPhoto(
            media=template["photo_file_id"],
            caption=template.get("text") or None,
            parse_mode="HTML",
        )
        for row in self.db.live_board_messages(category):
            try:
                await bot.edit_message_media(
                    chat_id=row["destination_chat_id"],
                    message_id=row["message_id"],
                    media=media,
                    reply_markup=self.markup_for_row(row),
                )
                self.db.mark_board_checked(row["id"])
                edited += 1
            except BadRequest as exc:
                if "not modified" in str(exc).lower():
                    self.db.mark_board_checked(row["id"])
                    edited += 1
                elif is_missing_message_error(exc):
                    missing += 1
                else:
                    failed += 1
                    log.warning("No se pudo editar contenido %s: %s", row["id"], exc)
            except TelegramError as exc:
                failed += 1
                log.warning("No se pudo editar contenido %s: %s", row["id"], exc)
        return {"edited": edited, "failed": failed, "missing": missing}

    async def publish_to_newly_approved_if_live(self, bot, category: str, chat_id: int):
        live_rows = self.db.live_board_messages(category)
        if not live_rows:
            return
        if self.settings.distribute_mode == "category":
            channel = self.db.get_channel(chat_id)
            if not channel or channel.get("category") != category:
                return

        template = self.db.get_template(category)
        if not template or not template.get("photo_file_id"):
            return

        channel = self.db.get_channel(chat_id)
        if not channel:
            return
        if self.permission_validator is not None:
            ok, _issues = await self.permission_validator(bot, channel)
            if not ok:
                return
            channel = self.db.get_channel(chat_id) or channel

        now = datetime.now(self.settings.timezone)
        valid_expiries = [row.get("expires_at") for row in live_rows if row.get("expires_at")]
        expires_at = min(valid_expiries) if valid_expiries else (
            now + timedelta(hours=self.lifetime_hours(category))
        ).isoformat(timespec="seconds")
        try:
            await self.delete_active_for_category_destination(bot, category, chat_id, "replaced")
            start_count = await self._member_count(bot, chat_id, int(channel.get("member_count") or 0))
            if start_count is not None:
                self.db.set_channel_fields(chat_id, member_count=start_count)
            seed = self.new_shuffle_seed() if self.shuffle_enabled(category) else None
            msg = await bot.send_photo(
                chat_id=chat_id,
                photo=template["photo_file_id"],
                caption=template.get("text") or None,
                reply_markup=self.build_markup(category, shuffle_seed=seed),
                parse_mode="HTML",
            )
            self.db.add_board_message(
                category,
                chat_id,
                msg.message_id,
                now.date().isoformat(),
                expires_at,
                start_member_count=start_count,
                channel_category_start=channel.get("category"),
                shuffle_seed=seed,
            )
            await self._send_started_notice(bot, channel, category, start_count, expires_at)
        except TelegramError as exc:
            log.warning("No se pudo enviar la botonera vigente a %s: %s", chat_id, exc)

    async def cleanup_expired(self, bot) -> dict:
        now = datetime.now(self.settings.timezone)
        deleted = failed = 0
        for row in list(self.db.active_board_messages()):
            raw = row.get("expires_at")
            if not raw:
                continue
            try:
                expires = datetime.fromisoformat(raw)
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=self.settings.timezone)
            except ValueError:
                continue
            if expires <= now:
                if await self._delete_row(bot, row, "expired"):
                    deleted += 1
                else:
                    failed += 1

        changes = self.apply_pending_categories_if_safe()
        await self._notify_category_changes(bot, changes)
        return {
            "deleted": deleted,
            "failed": failed,
            "category_changes": changes,
        }
