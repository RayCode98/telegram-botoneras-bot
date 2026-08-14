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
    def _channel_buttons(self, category: str, campaign_id: int | None = None) -> list:
        buttons = []
        if campaign_id is not None:
            rows = self.db.campaign_button_channels(int(campaign_id))
            for ch in rows:
                if ch.get("invite_link"):
                    buttons.append(
                        url_button(
                            ch.get("button_title") or ch.get("telegram_title") or str(ch["chat_id"]),
                            ch["invite_link"],
                            ch.get("button_style") or "default",
                        )
                    )
            return buttons

        # Vista previa / compatibilidad: fuera de una campaña se usa el enlace
        # configurado del canal. Las publicaciones reales v6.2 usan campaign_id.
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
        campaign_id: int | None = None,
        shuffle_channels: bool = False,
        shuffle_seed: int | None = None,
    ) -> InlineKeyboardMarkup:
        channel_buttons = self._channel_buttons(category, campaign_id=campaign_id)

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
            campaign_id=row.get("campaign_id"),
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
                    reply_markup=self.build_markup(category, campaign_id=row.get("campaign_id"), shuffle_seed=seed),
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

    async def _send_campaign_stats_message(self, bot, row: dict) -> bool:
        owner_id = row.get("owner_user_id")
        if not owner_id:
            self.db.note_campaign_stats_attempt(row["id"], "Canal sin responsable registrado")
            return False
        user = self.db.get_user(int(owner_id))
        if not user:
            self.db.note_campaign_stats_attempt(row["id"], "El propietario todavía no inició /start")
            return False
        prefs = self.db.get_user_preferences(int(owner_id))
        if not bool(prefs.get("notify_stats", 1)):
            self.db.mark_campaign_stats_sent(row["id"])
            return True

        start = row.get("start_member_count")
        end_count = row.get("end_member_count")
        delta = row.get("member_delta")
        if start is None or end_count is None or delta is None:
            return False

        requests = int(row.get("requests_count") or 0)
        request_events = int(row.get("request_events") or 0)
        joined = int(row.get("joined_count") or 0)
        left = int(row.get("left_count") or 0)
        mode = row.get("entry_mode") or "direct"
        campaign_id = int(row.get("campaign_id") or 0)

        if delta > 0:
            net_text = f"📈 <b>+{int(delta):,}</b>"
        elif delta < 0:
            net_text = f"📉 <b>{int(delta):,}</b>"
        else:
            net_text = "➖ <b>0</b>"

        lines = [
            f"📊 <b>Resultados · Campaña #{campaign_id}</b>",
            "",
            f"Canal: <b>{html.escape(row.get('telegram_title') or str(row['chat_id']))}</b>",
            f"Categoría: <b>{html.escape(row.get('category') or '—')}</b>",
            "",
        ]
        if mode == "approval":
            unconfirmed = max(0, requests - joined)
            conversion = (joined / requests * 100.0) if requests else 0.0
            lines.extend([
                "🛂 <b>Solicitudes de ingreso</b>",
                f"Solicitudes únicas atribuidas: <b>{requests:,}</b>",
                f"Ingresos confirmados: <b>{joined:,}</b>",
                f"Sin ingreso confirmado: <b>{unconfirmed:,}</b>",
                f"Conversión solicitud → ingreso: <b>{conversion:.1f}%</b>",
            ])
            if request_events > requests:
                lines.append(f"Intentos totales de solicitud: <b>{request_events:,}</b>")
        else:
            lines.extend([
                "🚪 <b>Ingreso directo</b>",
                f"Ingresos atribuidos al enlace de campaña: <b>{joined:,}</b>",
            ])

        if left:
            lines.append(f"Salidas detectadas entre los ingresos atribuidos: <b>{left:,}</b>")

        lines.extend([
            "",
            "👥 <b>Crecimiento neto del canal</b>",
            f"Al iniciar: <b>{int(start):,}</b>",
            f"Al finalizar: <b>{int(end_count):,}</b>",
            f"Diferencia neta: {net_text}",
        ])

        current_category = row.get("channel_category_current") or "—"
        pending = row.get("pending_category")
        lines.append("")
        lines.append(f"Categoría actual: <b>{html.escape(str(current_category))}</b>")
        if pending and pending != current_category:
            lines.append(f"Próxima categoría: <b>{html.escape(str(pending))}</b> 🔄")

        lines.extend([
            "",
            "ℹ️ Las solicitudes/ingresos se atribuyen al enlace exclusivo de esta campaña. "
            "El crecimiento neto puede diferir porque también existen bajas y otras fuentes de tráfico.",
        ])

        self.db.note_campaign_stats_attempt(row["id"], None)
        try:
            await bot.send_message(chat_id=user["private_chat_id"], text="\n".join(lines), parse_mode="HTML")
        except (Forbidden, BadRequest, TelegramError) as exc:
            self.db.note_campaign_stats_attempt(row["id"], str(exc)[:300])
            return False
        self.db.mark_campaign_stats_sent(row["id"])
        return True

    async def retry_pending_stats(self, bot, limit: int = 100) -> dict:
        sent = failed = 0
        # Estadísticas v6.2 por campaña.
        for row in self.db.pending_campaign_stats(limit=limit):
            if await self._send_campaign_stats_message(bot, row):
                sent += 1
            else:
                failed += 1
        # Historial heredado v6.1 sin campaign_id.
        for row in self.db.pending_stats_messages(limit=max(0, limit - sent - failed)):
            if row.get("campaign_id") is not None:
                continue
            if await self._send_stats_message(bot, row):
                sent += 1
            else:
                failed += 1
        return {"sent": sent, "failed": failed}

    async def _finalize_board_completion(self, bot, row: dict):
        # Desde v6.2 las publicaciones que pertenecen a una campaña se reportan
        # una sola vez desde campaign_channels, no una vez por copia distribuida.
        if row.get("campaign_id") is not None:
            return
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
    # Campaign links & attribution (v6.2)
    # ------------------------------------------------------------------
    async def _create_campaign_link(self, bot, campaign_id: int, channel: dict, expires_dt: datetime) -> dict | None:
        chat_id = int(channel["chat_id"])
        if self.permission_validator is not None:
            ok, _issues = await self.permission_validator(bot, channel)
            if not ok:
                return None
            channel = self.db.get_channel(chat_id) or channel
        if channel.get("status") != "approved":
            return None

        start_count = await self._member_count(bot, chat_id, int(channel.get("member_count") or 0))
        if start_count is not None:
            self.db.set_channel_fields(chat_id, member_count=start_count)
        mode = "approval" if channel.get("invite_type") == "approval" else "direct"
        short = abs(chat_id) % 1000000
        name = f"B{campaign_id}-{channel.get('category') or 'CAT'}-{short}"[:32]
        try:
            link = await bot.create_chat_invite_link(
                chat_id=chat_id,
                name=name,
                expire_date=expires_dt,
                creates_join_request=(mode == "approval"),
            )
            self.db.add_campaign_channel(
                campaign_id, chat_id, mode, link.invite_link, name, start_count, None,
            )
            return self.db.campaign_channel(campaign_id, chat_id)
        except TelegramError as exc:
            self.db.add_campaign_channel(
                campaign_id, chat_id, mode, None, name, start_count, str(exc)[:300],
            )
            log.warning("No se pudo crear enlace de campaña #%s para %s: %s", campaign_id, chat_id, exc)
            return None

    async def _prepare_campaign(self, bot, category: str, now: datetime, expires_dt: datetime) -> int:
        campaign_id = self.db.create_campaign(
            category,
            now.isoformat(timespec="seconds"),
            expires_dt.isoformat(timespec="seconds"),
        )
        # Los enlaces pertenecen solo a los canales que forman los botones de esta categoría.
        for channel in list(self.db.publication_candidates(category)):
            await self._create_campaign_link(bot, campaign_id, channel, expires_dt)
        return campaign_id

    async def _revoke_campaign_links(self, bot, campaign_id: int):
        for row in self.db.campaign_channels(campaign_id):
            link = row.get("invite_link")
            if not link or row.get("link_revoked_at"):
                continue
            try:
                await bot.revoke_chat_invite_link(chat_id=row["chat_id"], invite_link=link)
                self.db.mark_campaign_link_revoked(campaign_id, row["chat_id"])
            except TelegramError as exc:
                # El expire_date sigue siendo la segunda barrera. Guardamos el error
                # para diagnóstico (p.ej. si el bot fue eliminado del canal).
                self.db.mark_campaign_link_revoked(campaign_id, row["chat_id"], str(exc)[:300])
                log.warning("No se pudo revocar enlace campaña #%s chat %s: %s", campaign_id, row["chat_id"], exc)

    async def _close_campaign(self, bot, campaign_id: int, reason: str) -> dict:
        campaign = self.db.get_campaign(campaign_id)
        if not campaign or campaign.get("status") != "active":
            return {"closed": False, "channels": 0}

        # Primero revocamos. Para solicitudes, esto corta la atribución de la campaña
        # aunque alguna copia del post tarde en borrarse.
        await self._revoke_campaign_links(bot, campaign_id)

        finalized = 0
        for row in self.db.campaign_channels(campaign_id):
            if not row.get("invite_link"):
                continue
            channel = self.db.get_channel(row["chat_id"])
            fallback = row.get("start_member_count")
            if channel:
                fallback = int(channel.get("member_count") or fallback or 0)
            end_count = await self._member_count(bot, row["chat_id"], fallback)
            start_count = row.get("start_member_count")
            delta = None
            if end_count is not None and start_count is not None:
                delta = int(end_count) - int(start_count)
            self.db.finalize_campaign_channel(campaign_id, row["chat_id"], end_count, delta)
            if channel and end_count is not None:
                self._queue_category_change(channel, end_count)
            finalized += 1

        self.db.close_campaign(campaign_id, reason)

        # Aviso de cierre y estadísticas, una vez por canal/botón de la campaña.
        # Si nunca se publicó ninguna copia, cerramos silenciosamente.
        if reason == "publish_failed":
            return {"closed": True, "channels": finalized}

        for row in self.db.campaign_channels(campaign_id):
            if not row.get("invite_link"):
                continue
            channel = self.db.get_channel(row["chat_id"])
            if channel:
                end_count = row.get("end_member_count")
                text = (
                    f"🏁 <b>Botonera finalizada · Campaña #{campaign_id}</b>\n\n"
                    f"Canal: <b>{html.escape(channel.get('telegram_title') or str(channel['chat_id']))}</b>\n"
                    f"Categoría: <b>{html.escape(campaign.get('category') or '—')}</b>\n"
                    + (f"Suscriptores al cierre: <b>{int(end_count):,}</b>\n" if end_count is not None else "")
                    + "El enlace de esta campaña ya fue revocado/expirado."
                )
                await self._notify_owner(bot, channel, "notify_board_finished", text)
            fresh = self.db.campaign_stats_row(row["id"])
            if fresh:
                await self._send_campaign_stats_message(bot, fresh)
        return {"closed": True, "channels": finalized}

    async def _close_active_campaigns_for_category(self, bot, category: str, reason: str):
        for campaign in list(self.db.active_campaigns(category)):
            await self._close_campaign(bot, int(campaign["id"]), reason)

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
        campaigns = list(self.db.active_campaigns(category))
        if not initial and not campaigns:
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
        # La intención de cierre manda: revocamos los enlaces y consolidamos las
        # estadísticas aunque alguna copia no haya podido borrarse todavía.
        for campaign in campaigns:
            await self._close_campaign(bot, int(campaign["id"]), reason)
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

        # Si había una campaña de la misma categoría, terminarla antes de crear
        # nuevos enlaces; así nunca conviven dos juegos de enlaces atribuidos.
        if self.db.live_board_messages(category):
            await self.delete_category_everywhere(bot, category, reason="replaced", attempts=3)
        await self._close_active_campaigns_for_category(bot, category, "replaced")

        pre_changes = self.apply_pending_categories_if_safe()
        await self._notify_category_changes(bot, pre_changes)

        now = datetime.now(self.settings.timezone)
        today = now.date().isoformat()
        expires_dt = now + timedelta(hours=self.lifetime_hours(category))
        expires_at = expires_dt.isoformat(timespec="seconds")
        campaign_id = await self._prepare_campaign(bot, category, now, expires_dt)

        # Si no se pudo crear ningún enlace de canal, los botones manuales aún pueden
        # publicarse, pero lo dejamos registrado en el resultado.
        campaign_buttons = self.db.campaign_button_channels(campaign_id)
        sent = failed = 0

        for channel in self.publication_candidates(category):
            chat_id = channel["chat_id"]
            try:
                if self.permission_validator is not None:
                    ok, _issues = await self.permission_validator(bot, channel)
                    if not ok:
                        failed += 1
                        continue
                    channel = self.db.get_channel(chat_id) or channel

                seed = self.new_shuffle_seed() if self.shuffle_enabled(category) else None
                msg = await bot.send_photo(
                    chat_id=chat_id,
                    photo=template["photo_file_id"],
                    caption=template.get("text") or None,
                    reply_markup=self.build_markup(category, campaign_id=campaign_id, shuffle_seed=seed),
                    parse_mode="HTML",
                )
                self.db.add_board_message(
                    category,
                    chat_id,
                    msg.message_id,
                    today,
                    expires_at,
                    start_member_count=None,
                    channel_category_start=channel.get("category"),
                    shuffle_seed=seed,
                    campaign_id=campaign_id,
                )
                sent += 1
            except TelegramError as exc:
                failed += 1
                log.warning("No se pudo publicar %s en %s: %s", category, chat_id, exc)

        if sent == 0:
            # Sin publicaciones no existe campaña útil; cerramos y revocamos.
            await self._close_campaign(bot, campaign_id, "publish_failed")
            return {
                "sent": 0, "failed": failed, "reason": "No se pudo publicar en ningún canal.",
                "expires_at": expires_at, "campaign_id": campaign_id,
            }

        # Aviso de inicio una sola vez por canal promocionado.
        for cc in self.db.campaign_channels(campaign_id):
            channel = self.db.get_channel(cc["chat_id"])
            if channel and cc.get("invite_link"):
                await self._send_started_notice(
                    bot, channel, category, cc.get("start_member_count"), expires_at,
                )

        return {
            "sent": sent, "failed": failed, "reason": None, "expires_at": expires_at,
            "campaign_id": campaign_id, "tracked_channels": len(campaign_buttons),
        }

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
        campaigns = self.db.active_campaigns(category)
        if not live_rows or not campaigns:
            return
        campaign = campaigns[-1]
        campaign_id = int(campaign["id"])
        channel = self.db.get_channel(chat_id)
        if not channel:
            return
        if self.settings.distribute_mode == "category" and channel.get("category") != category:
            return

        template = self.db.get_template(category)
        if not template or not template.get("photo_file_id"):
            return
        if self.permission_validator is not None:
            ok, _issues = await self.permission_validator(bot, channel)
            if not ok:
                return
            channel = self.db.get_channel(chat_id) or channel

        try:
            expires_dt = datetime.fromisoformat(campaign["expires_at"])
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=self.settings.timezone)
        except Exception:
            expires_dt = datetime.now(self.settings.timezone) + timedelta(hours=self.lifetime_hours(category))

        # Si el canal pertenece a la categoría promovida, crea su enlace exclusivo
        # y refresca todos los posts antes de enviarle su propia copia.
        cc = self.db.campaign_channel(campaign_id, chat_id)
        desired_mode = "approval" if channel.get("invite_type") == "approval" else "direct"
        needs_new_link = (
            not cc or not cc.get("invite_link") or cc.get("entry_mode") != desired_mode
        )
        if channel.get("category") == category and needs_new_link:
            if cc and cc.get("invite_link"):
                try:
                    await bot.revoke_chat_invite_link(chat_id=chat_id, invite_link=cc["invite_link"])
                except TelegramError:
                    pass
            await self._create_campaign_link(bot, campaign_id, channel, expires_dt)
            await self.refresh_category(bot, category)

        try:
            await self.delete_active_for_category_destination(bot, category, chat_id, "replaced")
            seed = self.new_shuffle_seed() if self.shuffle_enabled(category) else None
            msg = await bot.send_photo(
                chat_id=chat_id,
                photo=template["photo_file_id"],
                caption=template.get("text") or None,
                reply_markup=self.build_markup(category, campaign_id=campaign_id, shuffle_seed=seed),
                parse_mode="HTML",
            )
            self.db.add_board_message(
                category,
                chat_id,
                msg.message_id,
                datetime.now(self.settings.timezone).date().isoformat(),
                campaign["expires_at"],
                channel_category_start=channel.get("category"),
                shuffle_seed=seed,
                campaign_id=campaign_id,
            )
            cc = self.db.campaign_channel(campaign_id, chat_id)
            if cc and cc.get("invite_link"):
                await self._send_started_notice(
                    bot, channel, category, cc.get("start_member_count"), campaign["expires_at"],
                )
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

        for campaign in list(self.db.active_campaigns()):
            try:
                exp = datetime.fromisoformat(campaign["expires_at"])
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=self.settings.timezone)
            except Exception:
                continue
            if exp <= now:
                await self._close_campaign(bot, int(campaign["id"]), "expired")

        changes = self.apply_pending_categories_if_safe()
        await self._notify_category_changes(bot, changes)
        return {
            "deleted": deleted,
            "failed": failed,
            "category_changes": changes,
        }
