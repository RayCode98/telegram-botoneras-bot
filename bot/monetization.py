from __future__ import annotations

import html
import logging
import math
import secrets
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden, TelegramError

from .config import Settings
from .db import Database

log = logging.getLogger(__name__)


INSIDE_STATUSES = {
    ChatMemberStatus.OWNER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
}


def milli_xtr_text(value: int | None) -> str:
    """Muestra contabilidad interna en equivalentes de XTR.

    No implica que el bot pueda transferir Stars directamente a un usuario.
    """
    value = int(value or 0)
    sign = "-" if value < 0 else ""
    value = abs(value)
    whole, frac = divmod(value, 1000)
    if frac:
        return f"{sign}{whole:,}.{frac:03d} ⭐-eq"
    return f"{sign}{whole:,} ⭐-eq"


def campaign_status_label(status: str | None) -> str:
    return {
        "awaiting_payment": "🧾 Esperando pago",
        "paid_review": "🟡 Pago recibido · revisión",
        "recruiting": "📣 Reclutando participantes",
        "active": "🟢 Activa",
        "settling": "⏳ Validando retención",
        "completed": "✅ Completada",
        "rejected": "❌ Rechazada",
        "refunded": "↩️ Reembolsada",
        "cancelled": "⚪️ Cancelada",
    }.get(status or "", status or "—")


class MonetizationService:
    def __init__(self, db: Database, settings: Settings, publisher, safe_dm, is_admin):
        self.db = db
        self.settings = settings
        self.publisher = publisher
        self.safe_dm = safe_dm
        self.is_admin = is_admin

    # ------------------------------------------------------------------
    # General helpers
    # ------------------------------------------------------------------
    def enabled(self) -> bool:
        return bool(self.settings.monetization_enabled)

    def price_for_goal(self, goal: int) -> int:
        return max(1, math.ceil(int(goal) * self.settings.monetization_stars_per_1000 / 1000))

    def participant_share_percent(self) -> float:
        return max(0.0, (10000 - self.settings.monetization_platform_fee_bps) / 100)

    def _owner_channels_for_advertising(self, user_id: int) -> list[dict]:
        rows = []
        for ch in self.db.channels_for_owner(user_id):
            if not ch.get("permissions_ok"):
                continue
            if ch.get("status") in {"banned", "withdrawn", "inactive"}:
                continue
            rows.append(ch)
        return rows

    async def refresh_source_boards(self, bot, source_chat_id: int) -> dict:
        edited = failed = 0
        for row in self.db.active_board_messages_for_chat(source_chat_id):
            try:
                await bot.edit_message_reply_markup(
                    chat_id=row["destination_chat_id"],
                    message_id=row["message_id"],
                    reply_markup=self.publisher.markup_for_row(row),
                )
                edited += 1
            except BadRequest as exc:
                if "not modified" in str(exc).lower():
                    edited += 1
                else:
                    failed += 1
            except TelegramError:
                failed += 1
        return {"edited": edited, "failed": failed}

    # ------------------------------------------------------------------
    # Participant UI
    # ------------------------------------------------------------------
    def money_home_keyboard(self, user_id: int) -> InlineKeyboardMarkup:
        profile = self.db.get_monetization_profile(user_id)
        enabled = bool(profile.get("enabled"))
        rows = [
            [InlineKeyboardButton("💵 Mi monedero", callback_data="money:wallet", style="success")],
            [InlineKeyboardButton("📣 Oportunidades", callback_data="money:opportunities")],
            [InlineKeyboardButton("📊 Mis campañas pagadas", callback_data="money:history")],
            [InlineKeyboardButton(
                "⏸ Desactivar monetización" if enabled else "✅ Activar monetización",
                callback_data="money:toggle",
                style="danger" if enabled else "primary",
            )],
            [InlineKeyboardButton("⬅️ Mi panel", callback_data="user:home")],
        ]
        return InlineKeyboardMarkup(rows)

    async def money_callback(self, update, context):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        data = q.data
        if not self.enabled():
            await q.answer("La monetización está desactivada por el administrador.", show_alert=True)
            return

        if data == "money:home":
            profile = self.db.get_monetization_profile(uid)
            wallet = self.db.wallet_summary(uid)
            text = (
                "💰 <b>Monetización</b>\n\n"
                f"Estado: <b>{'🟢 activa' if profile.get('enabled') else '⚪️ desactivada'}</b>\n"
                f"Disponible: <b>{milli_xtr_text(wallet['available_milli'])}</b>\n"
                f"Pendiente de retención: <b>{milli_xtr_text(wallet['pending_milli'])}</b>\n\n"
                "Las ganancias son contabilidad interna equivalente a Stars. "
                "Los retiros se solicitan al administrador y se liquidan manualmente mientras no exista un método de pago externo configurado."
            )
            await q.edit_message_text(text, parse_mode="HTML", reply_markup=self.money_home_keyboard(uid))
            return

        if data == "money:toggle":
            profile = self.db.get_monetization_profile(uid)
            if bool(profile.get("enabled")):
                self.db.set_monetization_enabled(uid, False)
                await q.edit_message_text(
                    "⏸ <b>Monetización desactivada.</b>\n\nNo recibirás nuevas oportunidades. "
                    "Las participaciones ya iniciadas y tus ganancias acumuladas se conservan.",
                    parse_mode="HTML", reply_markup=self.money_home_keyboard(uid),
                )
                return
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Acepto y activar", callback_data="money:accept", style="success")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="money:home")],
            ])
            await q.edit_message_text(
                "💰 <b>Activar monetización</b>\n\n"
                "Al activarla aceptas estas reglas básicas:\n\n"
                "• participar en cada campaña es voluntario;\n"
                "• la primera fuente atribuida a un usuario es la que conserva la conversión;\n"
                f"• una conversión solo genera saldo si permanece al menos <b>{self.settings.monetization_retention_hours} horas</b>;\n"
                "• reingresos, bots, administradores del canal objetivo y actividad fraudulenta no generan saldo;\n"
                "• el monedero mostrado por el bot es <b>contabilidad interna</b>, no Stars transferibles automáticamente;\n"
                "• los retiros requieren revisión y liquidación administrativa.\n\n"
                "Puedes desactivar nuevas oportunidades cuando quieras sin perder el saldo acumulado.",
                parse_mode="HTML", reply_markup=kb,
            )
            return

        if data == "money:accept":
            self.db.set_monetization_enabled(uid, True)
            await q.edit_message_text(
                "✅ <b>Monetización activada.</b>\n\n"
                "Recibirás oportunidades antes de las campañas y elegirás en cuáles participar y con qué canales.",
                parse_mode="HTML", reply_markup=self.money_home_keyboard(uid),
            )
            return

        if data == "money:wallet":
            w = self.db.wallet_summary(uid)
            can_withdraw = w["available_milli"] >= self.settings.monetization_min_withdraw_milli
            rows = []
            if can_withdraw:
                rows.append([InlineKeyboardButton("💸 Solicitar retiro", callback_data="money:withdraw", style="success")])
            rows.append([InlineKeyboardButton("⬅️ Monetización", callback_data="money:home")])
            text = (
                "💵 <b>Mi monedero</b>\n\n"
                f"Disponible: <b>{milli_xtr_text(w['available_milli'])}</b>\n"
                f"Pendiente: <b>{milli_xtr_text(w['pending_milli'])}</b>\n"
                f"Ganancias históricas: <b>{milli_xtr_text(w['historical_milli'])}</b>\n"
                f"Retiros liquidados: <b>{milli_xtr_text(w['withdrawn_milli'])}</b>\n\n"
                f"Retiro mínimo: <b>{milli_xtr_text(self.settings.monetization_min_withdraw_milli)}</b>."
            )
            await q.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))
            return

        if data == "money:withdraw":
            w = self.db.wallet_summary(uid)
            amount = int(w["available_milli"])
            if amount < self.settings.monetization_min_withdraw_milli:
                await q.answer("Aún no alcanzas el retiro mínimo.", show_alert=True)
                return
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Solicitar todo", callback_data="money:withdrawconfirm", style="success")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="money:wallet")],
            ])
            await q.edit_message_text(
                f"💸 <b>Solicitar retiro</b>\n\nMonto disponible: <b>{milli_xtr_text(amount)}</b>\n\n"
                "El administrador recibirá la solicitud. Esta versión no transfiere Stars automáticamente a usuarios.",
                parse_mode="HTML", reply_markup=kb,
            )
            return

        if data == "money:withdrawconfirm":
            w = self.db.wallet_summary(uid)
            amount = int(w["available_milli"])
            if amount < self.settings.monetization_min_withdraw_milli:
                await q.answer("Saldo insuficiente o ya reservado.", show_alert=True)
                return
            wid = self.db.create_withdrawal_request(uid, amount)
            await q.edit_message_text(
                f"✅ <b>Retiro #{wid} solicitado.</b>\n\nMonto: <b>{milli_xtr_text(amount)}</b>\n"
                "El saldo quedó reservado hasta que un administrador lo liquide o rechace.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Monetización", callback_data="money:home")]]),
            )
            for admin_id in self.settings.admin_ids:
                await self.safe_dm(
                    context.bot, admin_id,
                    f"💸 <b>Nueva solicitud de retiro #{wid}</b>\n\nUsuario: <code>{uid}</code>\nMonto: <b>{milli_xtr_text(amount)}</b>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Marcar pagado", callback_data=f"monadm:withdrawpaid:{wid}", style="success")],
                        [InlineKeyboardButton("❌ Rechazar", callback_data=f"monadm:withdrawreject:{wid}", style="danger")],
                    ]),
                )
            return

        if data == "money:history":
            rows = []
            # campañas donde alguno de sus canales fue fuente
            with self.db.connection() as conn:
                found = conn.execute(
                    """SELECT DISTINCT sc.* FROM sponsored_campaigns sc JOIN sponsored_sources ss ON ss.campaign_id=sc.id
                       WHERE ss.source_owner_user_id=? ORDER BY sc.id DESC LIMIT 15""",
                    (uid,),
                ).fetchall()
                campaigns = [dict(r) for r in found]
            lines = ["📊 <b>Mis campañas pagadas</b>", ""]
            if not campaigns:
                lines.append("Todavía no has participado en campañas monetizadas.")
            for c in campaigns:
                srcs = self.db.selected_sponsored_sources_for_owner(c["id"], uid)
                verified = sum(int(x.get("verified_count") or 0) for x in srcs)
                earned = sum(int(x.get("earned_milli") or 0) for x in srcs)
                lines.append(f"• #{c['id']} · {html.escape(c['title'])} · ✅ {verified} · <b>{milli_xtr_text(earned)}</b>")
            await q.edit_message_text(
                "\n".join(lines), parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Monetización", callback_data="money:home")]]),
            )
            return

        if data == "money:opportunities":
            campaigns = self.db.sponsored_campaigns_by_status(("recruiting",), 20)
            rows = []
            for c in campaigns:
                eligible = self.db.eligible_monetization_channels(uid, c["target_chat_id"])
                if eligible:
                    rows.append([InlineKeyboardButton(
                        f"📢 #{c['id']} · {c['title'][:30]}", callback_data=f"monopp:open:{c['id']}"
                    )])
            if not rows:
                rows.append([InlineKeyboardButton("Sin oportunidades ahora", callback_data="money:noop")])
            rows.append([InlineKeyboardButton("⬅️ Monetización", callback_data="money:home")])
            await q.edit_message_text(
                "📣 <b>Oportunidades disponibles</b>\n\nSelecciona una campaña para elegir tus canales.",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
            )
            return

        if data == "money:noop":
            return

    # ------------------------------------------------------------------
    # Advertiser UI + Stars payments
    # ------------------------------------------------------------------
    def ads_home_keyboard(self, user_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Nueva campaña", callback_data="ads:new", style="success")],
            [InlineKeyboardButton("📊 Mis campañas", callback_data="ads:list")],
            [InlineKeyboardButton("⬅️ Mi panel", callback_data="user:home")],
        ])

    async def ads_callback(self, update, context):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        data = q.data
        if not self.enabled():
            await q.answer("La monetización está desactivada.", show_alert=True)
            return

        if data == "ads:home":
            campaigns = self.db.sponsored_campaigns_for_advertiser(uid, 100)
            active = sum(1 for c in campaigns if c.get("status") in {"recruiting", "active", "settling"})
            await q.edit_message_text(
                "📢 <b>Publicidad</b>\n\n"
                f"Campañas creadas: <b>{len(campaigns)}</b> · Activas/en proceso: <b>{active}</b>\n"
                f"Tarifa actual: <b>{self.settings.monetization_stars_per_1000:,} ⭐ por 1,000 miembros objetivo</b>.\n\n"
                "Las campañas se pagan con Telegram Stars y pasan por revisión administrativa antes de publicarse.",
                parse_mode="HTML", reply_markup=self.ads_home_keyboard(uid),
            )
            return

        if data == "ads:new":
            channels = self._owner_channels_for_advertising(uid)
            if not channels:
                await q.edit_message_text(
                    "📢 <b>Nueva campaña</b>\n\nPrimero agrega/verifica como administrador el canal que deseas promocionar.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("➕ Agregar/verificar canal", callback_data="user:add", style="success")],
                        [InlineKeyboardButton("⬅️ Publicidad", callback_data="ads:home")],
                    ]),
                )
                return
            rows = [[InlineKeyboardButton((ch.get("telegram_title") or str(ch["chat_id"]))[:50], callback_data=f"ads:target:{ch['chat_id']}")] for ch in channels[:40]]
            rows.append([InlineKeyboardButton("⬅️ Publicidad", callback_data="ads:home")])
            await q.edit_message_text(
                "📢 <b>Nueva campaña</b>\n\nSelecciona el canal que deseas promocionar:",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
            )
            return

        if data.startswith("ads:target:"):
            chat_id = int(data.split(":", 2)[2])
            ch = self.db.get_channel(chat_id)
            if not ch or int(ch.get("owner_user_id") or 0) != uid:
                await q.answer("Ese canal no te pertenece.", show_alert=True)
                return
            rows = []
            for goal in self.settings.monetization_goals:
                price = self.price_for_goal(goal)
                rows.append([InlineKeyboardButton(
                    f"🎯 {goal:,} miembros · {price:,} ⭐", callback_data=f"ads:goal:{chat_id}:{goal}", style="primary"
                )])
            rows.append([InlineKeyboardButton("⬅️ Elegir canal", callback_data="ads:new")])
            await q.edit_message_text(
                f"🎯 <b>Objetivo para {html.escape(ch.get('telegram_title') or str(chat_id))}</b>\n\n"
                "Selecciona cuántos miembros deseas adquirir mediante promoción voluntaria:",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
            )
            return

        if data.startswith("ads:goal:"):
            _, _, raw_chat, raw_goal = data.split(":", 3)
            chat_id, goal = int(raw_chat), int(raw_goal)
            if goal not in self.settings.monetization_goals:
                return
            ch = self.db.get_channel(chat_id)
            if not ch or int(ch.get("owner_user_id") or 0) != uid:
                return
            price = self.price_for_goal(goal)
            payload = f"sponsor:{uid}:{secrets.token_hex(12)}"
            entry_mode = "approval" if ch.get("invite_type") == "approval" else "direct"
            cid = self.db.create_sponsored_campaign(
                uid, chat_id, ch.get("telegram_title") or str(chat_id), goal, price,
                self.settings.monetization_platform_fee_bps, entry_mode, payload,
            )
            await context.bot.send_invoice(
                chat_id=uid,
                title=f"Campaña #{cid}",
                description=f"Promoción de {goal:,} miembros para {ch.get('telegram_title') or chat_id}. Requiere revisión administrativa.",
                payload=payload,
                currency="XTR",
                prices=[LabeledPrice("Campaña promocional", price)],
                provider_token="",
            )
            await q.edit_message_text(
                f"🧾 <b>Campaña #{cid} creada</b>\n\nObjetivo: <b>{goal:,}</b>\nPrecio: <b>{price:,} ⭐</b>\n\n"
                "Telegram te mostrará la factura de Stars. Después del pago pasará automáticamente a revisión.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📊 Mis campañas", callback_data="ads:list")]]),
            )
            return

        if data == "ads:list":
            campaigns = self.db.sponsored_campaigns_for_advertiser(uid, 20)
            rows = []
            for c in campaigns:
                rows.append([InlineKeyboardButton(
                    f"#{c['id']} · {campaign_status_label(c.get('status'))[:22]} · {c.get('title','')[:22]}",
                    callback_data=f"ads:campaign:{c['id']}",
                )])
            if not rows:
                rows.append([InlineKeyboardButton("No hay campañas", callback_data="ads:noop")])
            rows.append([InlineKeyboardButton("⬅️ Publicidad", callback_data="ads:home")])
            await q.edit_message_text("📊 <b>Mis campañas</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("ads:campaign:"):
            cid = int(data.split(":", 2)[2])
            c = self.db.get_sponsored_campaign(cid)
            if not c or int(c.get("advertiser_user_id") or 0) != uid:
                return
            verified = int(c.get("verified_count") or 0)
            goal = int(c.get("goal_members") or 1)
            pct = min(100.0, verified * 100 / goal)
            text = (
                f"📢 <b>Campaña #{cid}</b>\n\n"
                f"Canal: <b>{html.escape(c.get('title') or str(c['target_chat_id']))}</b>\n"
                f"Estado: <b>{html.escape(campaign_status_label(c.get('status')))}</b>\n"
                f"Objetivo: <b>{goal:,}</b>\n"
                f"🛂 Solicitudes únicas: <b>{int(c.get('requests_count') or 0):,}</b>\n"
                f"🔁 Intentos de solicitud: <b>{int(c.get('request_attempts_count') or 0):,}</b>\n"
                f"✅ Ingresos atribuidos: <b>{int(c.get('joined_count') or 0):,}</b>\n"
                f"🛡 Verificados {self.settings.monetization_retention_hours}h: <b>{verified:,}</b> ({pct:.1f}%)\n"
                f"Pago: <b>{int(c.get('stars_price') or 0):,} ⭐</b>"
            )
            await q.edit_message_text(
                text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Mis campañas", callback_data="ads:list")]]),
            )
            return

        if data == "ads:noop":
            return

    async def precheckout_handler(self, update, context):
        query = update.pre_checkout_query
        if not query:
            return
        c = self.db.sponsored_campaign_by_payload(query.invoice_payload)
        ok = bool(
            c
            and c.get("status") == "awaiting_payment"
            and int(c.get("advertiser_user_id") or 0) == query.from_user.id
            and query.currency == "XTR"
            and int(query.total_amount) == int(c.get("stars_price") or 0)
        )
        if ok:
            await query.answer(ok=True)
        else:
            await query.answer(ok=False, error_message="La campaña o el importe ya no son válidos. Vuelve a crear la orden.")

    async def successful_payment_handler(self, update, context):
        msg = update.effective_message
        if not msg or not msg.successful_payment:
            return
        pay = msg.successful_payment
        c = self.db.sponsored_campaign_by_payload(pay.invoice_payload)
        if not c:
            return
        if c.get("status") != "awaiting_payment":
            return
        if pay.currency != "XTR" or int(pay.total_amount) != int(c.get("stars_price") or 0):
            self.db.log_system_event("star_payment_mismatch", f"campaign={c['id']}; amount={pay.total_amount}; currency={pay.currency}", "error")
            return
        paid_at = datetime.now(self.settings.timezone).isoformat(timespec="seconds")
        self.db.mark_sponsored_paid(c["id"], pay.telegram_payment_charge_id, paid_at)
        await msg.reply_html(
            f"✅ <b>Pago recibido · Campaña #{c['id']}</b>\n\n"
            f"Importe: <b>{int(pay.total_amount):,} ⭐</b>\n"
            "La campaña pasó a revisión administrativa. Si se rechaza, el bot intentará reembolsar el pago con Telegram Stars."
        )
        fresh = self.db.get_sponsored_campaign(c["id"]) or c
        await self.notify_admins_paid(context.bot, fresh)

    async def notify_admins_paid(self, bot, campaign: dict):
        cid = int(campaign["id"])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Aprobar y reclutar", callback_data=f"monadm:approve:{cid}", style="success")],
            [InlineKeyboardButton("❌ Rechazar + reembolsar", callback_data=f"monadm:reject:{cid}", style="danger")],
        ])
        for admin_id in self.settings.admin_ids:
            await self.safe_dm(
                bot, admin_id,
                f"💳 <b>Campaña pagada #{cid}</b>\n\n"
                f"Anunciante: <code>{campaign.get('advertiser_user_id')}</code>\n"
                f"Canal: <b>{html.escape(campaign.get('title') or str(campaign.get('target_chat_id')))}</b>\n"
                f"Objetivo: <b>{int(campaign.get('goal_members') or 0):,}</b>\n"
                f"Pago: <b>{int(campaign.get('stars_price') or 0):,} ⭐</b>\n"
                f"Modo: <b>{'solicitud' if campaign.get('entry_mode') == 'approval' else 'ingreso directo'}</b>",
                parse_mode="HTML", reply_markup=kb,
            )

    # ------------------------------------------------------------------
    # Opportunity recruitment
    # ------------------------------------------------------------------
    def opportunity_keyboard(self, campaign_id: int, user_id: int) -> InlineKeyboardMarkup:
        c = self.db.get_sponsored_campaign(campaign_id)
        if not c:
            return InlineKeyboardMarkup([[InlineKeyboardButton("Cerrar", callback_data="money:home")]])
        eligible = self.db.eligible_monetization_channels(user_id, c["target_chat_id"])
        selected = {int(r["source_chat_id"]) for r in self.db.selected_sponsored_sources_for_owner(campaign_id, user_id)}
        rows = []
        for ch in eligible[:30]:
            mark = "✅" if int(ch["chat_id"]) in selected else "▫️"
            rows.append([InlineKeyboardButton(
                f"{mark} {(ch.get('telegram_title') or str(ch['chat_id']))[:45]}",
                callback_data=f"monopp:toggle:{campaign_id}:{ch['chat_id']}",
            )])
        rows.append([InlineKeyboardButton("✅ Confirmar participación", callback_data=f"monopp:confirm:{campaign_id}", style="success")])
        rows.append([InlineKeyboardButton("❌ No participar", callback_data=f"monopp:decline:{campaign_id}")])
        return InlineKeyboardMarkup(rows)

    async def send_opportunities(self, bot, campaign: dict):
        cid = int(campaign["id"])
        scheduled = campaign.get("scheduled_at") or "—"
        for profile in self.db.monetization_participants():
            uid = int(profile["user_id"])
            if uid == int(campaign["advertiser_user_id"]):
                continue
            eligible = self.db.eligible_monetization_channels(uid, int(campaign["target_chat_id"]))
            if not eligible:
                continue
            text = (
                f"💰 <b>Nueva oportunidad · Campaña #{cid}</b>\n\n"
                f"Canal promocionado: <b>{html.escape(campaign.get('title') or str(campaign['target_chat_id']))}</b>\n"
                f"Objetivo: <b>{int(campaign.get('goal_members') or 0):,} miembros</b>\n"
                f"Pool participantes: <b>{milli_xtr_text(campaign.get('participant_pool_milli'))}</b>\n"
                f"Valor por conversión verificada: <b>{milli_xtr_text(campaign.get('rate_milli_per_verified'))}</b>\n"
                f"Retención requerida: <b>{self.settings.monetization_retention_hours}h</b>\n"
                f"Comienza: <b>{html.escape(scheduled[:16].replace('T',' '))}</b>\n\n"
                "Selecciona los canales con los que deseas participar. Cuantas más conversiones válidas genere tu canal, mayor será tu saldo."
            )
            await self.safe_dm(bot, uid, text, parse_mode="HTML", reply_markup=self.opportunity_keyboard(cid, uid))

    async def opportunity_callback(self, update, context):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        parts = q.data.split(":")
        action = parts[1]
        cid = int(parts[2])
        campaign = self.db.get_sponsored_campaign(cid)
        if not campaign or campaign.get("status") != "recruiting":
            await q.answer("Esta oportunidad ya no está abierta.", show_alert=True)
            return
        if not self.db.get_monetization_profile(uid).get("enabled"):
            await q.answer("Activa monetización primero.", show_alert=True)
            return

        if action == "open":
            await q.edit_message_text(
                f"💰 <b>Campaña #{cid}</b>\n\nSelecciona los canales que participarán:",
                parse_mode="HTML", reply_markup=self.opportunity_keyboard(cid, uid),
            )
            return

        if action == "toggle":
            chat_id = int(parts[3])
            eligible_ids = {int(ch["chat_id"]) for ch in self.db.eligible_monetization_channels(uid, campaign["target_chat_id"])}
            if chat_id not in eligible_ids:
                await q.answer("Ese canal no es elegible.", show_alert=True)
                return
            existing = self.db.sponsored_source(cid, chat_id)
            selected = not bool(existing and existing.get("status") == "selected")
            self.db.upsert_sponsored_source(cid, chat_id, uid, selected)
            await q.edit_message_reply_markup(reply_markup=self.opportunity_keyboard(cid, uid))
            return

        if action == "confirm":
            selected = self.db.selected_sponsored_sources_for_owner(cid, uid)
            if not selected:
                await q.answer("Selecciona al menos un canal.", show_alert=True)
                return
            await q.edit_message_text(
                f"✅ <b>Participación confirmada</b>\n\nCampaña #{cid}\nCanales seleccionados: <b>{len(selected)}</b>\n\n"
                "Cuando comience, cada canal recibirá un enlace de atribución distinto dentro de su botonera activa.",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Monetización", callback_data="money:home")]]),
            )
            return

        if action == "decline":
            for src in self.db.selected_sponsored_sources_for_owner(cid, uid):
                self.db.upsert_sponsored_source(cid, src["source_chat_id"], uid, False)
            await q.edit_message_text(
                "👌 No participarás en esta campaña. Esto no afecta tus botoneras normales ni genera sanciones.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Monetización", callback_data="money:home")]]),
            )

    # ------------------------------------------------------------------
    # Admin UI / review / withdrawals
    # ------------------------------------------------------------------
    def admin_home_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🟡 Campañas por revisar", callback_data="monadm:campaigns", style="primary")],
            [InlineKeyboardButton("💸 Retiros pendientes", callback_data="monadm:withdrawals")],
            [InlineKeyboardButton("📊 Resumen", callback_data="monadm:summary")],
            [InlineKeyboardButton("⬅️ Panel", callback_data="panel:home")],
        ])

    async def admin_callback(self, update, context):
        q = update.callback_query
        await q.answer()
        if not self.is_admin(q.from_user.id):
            await q.answer("Solo administradores.", show_alert=True)
            return
        data = q.data
        parts = data.split(":")
        action = parts[1]

        if action == "home":
            review = self.db.sponsored_campaigns_by_status(("paid_review",), 100)
            active = self.db.sponsored_campaigns_by_status(("recruiting", "active", "settling"), 100)
            withdrawals = self.db.pending_withdrawals(100)
            await q.edit_message_text(
                "💰 <b>Administración de monetización</b>\n\n"
                f"Campañas por revisar: <b>{len(review)}</b>\n"
                f"En proceso: <b>{len(active)}</b>\n"
                f"Retiros pendientes: <b>{len(withdrawals)}</b>\n"
                f"Tarifa: <b>{self.settings.monetization_stars_per_1000} ⭐ / 1K</b>\n"
                f"Comisión plataforma: <b>{self.settings.monetization_platform_fee_bps/100:.1f}%</b>",
                parse_mode="HTML", reply_markup=self.admin_home_keyboard(),
            )
            return

        if action == "campaigns":
            campaigns = self.db.sponsored_campaigns_by_status(("paid_review", "recruiting", "active", "settling"), 30)
            rows = [[InlineKeyboardButton(
                f"#{c['id']} · {campaign_status_label(c['status'])[:20]} · {c['title'][:20]}",
                callback_data=f"monadm:campaign:{c['id']}",
            )] for c in campaigns]
            if not rows:
                rows.append([InlineKeyboardButton("Sin campañas", callback_data="monadm:noop")])
            rows.append([InlineKeyboardButton("⬅️ Monetización", callback_data="monadm:home")])
            await q.edit_message_text("📢 <b>Campañas monetizadas</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))
            return

        if action == "campaign":
            cid = int(parts[2])
            c = self.db.get_sponsored_campaign(cid)
            if not c:
                return
            rows = []
            if c.get("status") == "paid_review":
                rows.append([InlineKeyboardButton("✅ Aprobar y reclutar", callback_data=f"monadm:approve:{cid}", style="success")])
                rows.append([InlineKeyboardButton("❌ Rechazar + reembolsar", callback_data=f"monadm:reject:{cid}", style="danger")])
            rows.append([InlineKeyboardButton("⬅️ Campañas", callback_data="monadm:campaigns")])
            await q.edit_message_text(
                f"📢 <b>Campaña #{cid}</b>\n\n"
                f"Canal: <b>{html.escape(c.get('title') or '')}</b>\n"
                f"Anunciante: <code>{c.get('advertiser_user_id')}</code>\n"
                f"Estado: <b>{html.escape(campaign_status_label(c.get('status')))}</b>\n"
                f"Objetivo: <b>{int(c.get('goal_members') or 0):,}</b>\n"
                f"Pago: <b>{int(c.get('stars_price') or 0):,} ⭐</b>\n"
                f"Solicitudes: <b>{int(c.get('requests_count') or 0):,}</b> ({int(c.get('request_attempts_count') or 0):,} intentos) · "
                f"Ingresos: <b>{int(c.get('joined_count') or 0):,}</b> · Verificados: <b>{int(c.get('verified_count') or 0):,}</b>",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
            )
            return

        if action == "approve":
            cid = int(parts[2])
            c = self.db.get_sponsored_campaign(cid)
            if not c or c.get("status") != "paid_review":
                await q.answer("La campaña ya no está pendiente.", show_alert=True)
                return
            now = datetime.now(self.settings.timezone)
            scheduled = now + timedelta(hours=self.settings.monetization_opportunity_hours)
            max_end = scheduled + timedelta(hours=self.settings.monetization_max_campaign_hours)
            self.db.approve_sponsored_campaign(cid, q.from_user.id, scheduled.isoformat(timespec="seconds"), max_end.isoformat(timespec="seconds"))
            fresh = self.db.get_sponsored_campaign(cid)
            await self.send_opportunities(context.bot, fresh)
            await self.safe_dm(
                context.bot, fresh["advertiser_user_id"],
                f"✅ <b>Campaña #{cid} aprobada.</b>\n\nAhora comienza un periodo de reclutamiento de <b>{self.settings.monetization_opportunity_hours} horas</b>. "
                f"Inicio programado: <b>{scheduled.strftime('%d/%m/%Y %H:%M')}</b>.",
                parse_mode="HTML",
            )
            await q.edit_message_text(
                f"✅ Campaña #{cid} aprobada. Se enviaron oportunidades a participantes monetizados. Inicio: {scheduled.strftime('%d/%m %H:%M')}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Monetización", callback_data="monadm:home")]]),
            )
            return

        if action == "reject":
            cid = int(parts[2])
            c = self.db.get_sponsored_campaign(cid)
            if not c or c.get("status") != "paid_review":
                return
            refunded = False
            err = None
            if c.get("telegram_payment_charge_id"):
                try:
                    await context.bot.refund_star_payment(
                        user_id=int(c["advertiser_user_id"]),
                        telegram_payment_charge_id=c["telegram_payment_charge_id"],
                    )
                    refunded = True
                except TelegramError as exc:
                    err = str(exc)
            reason = "Rechazada por revisión administrativa."
            if err:
                reason += f" Reembolso pendiente por error: {err[:180]}"
            self.db.reject_sponsored_campaign(cid, q.from_user.id, reason, refunded=refunded)
            await self.safe_dm(
                context.bot, c["advertiser_user_id"],
                f"❌ <b>Campaña #{cid} rechazada.</b>\n\n" + ("El pago fue reembolsado en Telegram Stars." if refunded else "No se pudo confirmar el reembolso automáticamente; el administrador revisará la transacción."),
                parse_mode="HTML",
            )
            await q.edit_message_text(
                f"❌ Campaña #{cid} rechazada. {'Reembolso confirmado.' if refunded else 'Reembolso requiere revisión.'}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Monetización", callback_data="monadm:home")]]),
            )
            return

        if action == "withdrawals":
            withdrawals = self.db.pending_withdrawals(30)
            rows = []
            for w in withdrawals:
                rows.append([
                    InlineKeyboardButton(f"✅ #{w['id']} {milli_xtr_text(w['amount_milli'])}", callback_data=f"monadm:withdrawpaid:{w['id']}", style="success"),
                    InlineKeyboardButton("❌", callback_data=f"monadm:withdrawreject:{w['id']}", style="danger"),
                ])
            if not rows:
                rows.append([InlineKeyboardButton("Sin retiros pendientes", callback_data="monadm:noop")])
            rows.append([InlineKeyboardButton("⬅️ Monetización", callback_data="monadm:home")])
            await q.edit_message_text("💸 <b>Retiros pendientes</b>\n\nEn v7 la liquidación es manual fuera del bot; estos botones solo actualizan la contabilidad.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))
            return

        if action in {"withdrawpaid", "withdrawreject"}:
            wid = int(parts[2])
            w = self.db.get_withdrawal(wid)
            if not w or w.get("status") != "pending":
                await q.answer("Ese retiro ya fue resuelto.", show_alert=True)
                return
            status = "paid" if action == "withdrawpaid" else "rejected"
            self.db.resolve_withdrawal(wid, q.from_user.id, status, "Resuelto desde panel Telegram")
            await self.safe_dm(
                context.bot, w["user_id"],
                (f"✅ <b>Retiro #{wid} marcado como pagado.</b>" if status == "paid" else f"❌ <b>Retiro #{wid} rechazado.</b> El saldo vuelve a quedar disponible."),
                parse_mode="HTML",
            )
            await q.edit_message_text(
                f"Retiro #{wid}: {status}.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Retiros", callback_data="monadm:withdrawals")]]),
            )
            return

        if action == "summary":
            with self.db.connection() as conn:
                row = conn.execute(
                    """SELECT COUNT(*) n, COALESCE(SUM(stars_price),0) stars,
                              COALESCE(SUM(verified_count),0) verified FROM sponsored_campaigns WHERE paid_at IS NOT NULL"""
                ).fetchone()
                participants = conn.execute("SELECT COUNT(*) n FROM monetization_profiles WHERE enabled=1").fetchone()[0]
            await q.edit_message_text(
                "📊 <b>Resumen de monetización</b>\n\n"
                f"Campañas pagadas: <b>{int(row['n'] or 0)}</b>\n"
                f"Stars cobradas registradas: <b>{int(row['stars'] or 0):,} ⭐</b>\n"
                f"Conversiones verificadas: <b>{int(row['verified'] or 0):,}</b>\n"
                f"Participantes monetizados: <b>{int(participants or 0)}</b>",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Monetización", callback_data="monadm:home")]]),
            )
            return

        if action == "noop":
            return

    # ------------------------------------------------------------------
    # Campaign engine
    # ------------------------------------------------------------------
    async def _refund_and_cancel(self, bot, campaign: dict, reason: str) -> bool:
        refunded = False
        charge_id = campaign.get("telegram_payment_charge_id")
        if charge_id:
            try:
                await bot.refund_star_payment(
                    user_id=int(campaign["advertiser_user_id"]),
                    telegram_payment_charge_id=charge_id,
                )
                refunded = True
            except TelegramError as exc:
                log.warning("No se pudo reembolsar campaña %s: %s", campaign.get("id"), exc)
        self.db.reject_sponsored_campaign(int(campaign["id"]), 0, reason, refunded=refunded)
        await self.safe_dm(
            bot, campaign["advertiser_user_id"],
            f"⚪️ <b>Campaña #{campaign['id']} cancelada.</b>\n\n{html.escape(reason)}\n\n"
            + ("✅ El pago fue reembolsado en Telegram Stars." if refunded else "⚠️ El reembolso automático no pudo confirmarse; un administrador debe revisar la transacción."),
            parse_mode="HTML",
        )
        return refunded

    async def start_campaign(self, bot, campaign_id: int) -> dict:
        c = self.db.get_sponsored_campaign(campaign_id)
        if not c or c.get("status") != "recruiting":
            return {"started": False, "reason": "invalid_status"}
        sources = self.db.sponsored_sources(campaign_id, ("selected",))
        if not sources:
            await self._refund_and_cancel(bot, c, "No hubo canales participantes elegibles al iniciar la campaña.")
            return {"started": False, "reason": "no_sources"}

        # Verifica que el canal objetivo siga accesible antes de crear enlaces.
        target = self.db.get_channel(c["target_chat_id"])
        if not target or target.get("status") not in {"approved", "permission_suspended"} or not target.get("permissions_ok"):
            await self._refund_and_cancel(bot, c, "El canal promocionado ya no tiene los permisos necesarios para crear y medir enlaces de campaña.")
            return {"started": False, "reason": "target_permissions"}

        try:
            max_end = datetime.fromisoformat(c["max_end_at"])
        except Exception:
            max_end = datetime.now(self.settings.timezone) + timedelta(hours=self.settings.monetization_max_campaign_hours)
        active_sources = []
        for src in sources:
            channel = self.db.get_channel(src["source_chat_id"])
            if not channel or channel.get("status") != "approved" or not channel.get("permissions_ok"):
                self.db.upsert_sponsored_source(campaign_id, src["source_chat_id"], src["source_owner_user_id"], False)
                continue
            name = f"SP{campaign_id}-SRC{abs(int(src['source_chat_id'])) % 1000000}"[:32]
            try:
                link = await bot.create_chat_invite_link(
                    chat_id=int(c["target_chat_id"]),
                    name=name,
                    expire_date=max_end,
                    creates_join_request=(c.get("entry_mode") == "approval"),
                )
                self.db.set_sponsored_source_link(campaign_id, src["source_chat_id"], link.invite_link, name)
                active_sources.append(src["source_chat_id"])
            except TelegramError as exc:
                log.warning("No se pudo crear enlace patrocinado campaña %s fuente %s: %s", campaign_id, src["source_chat_id"], exc)

        if not active_sources:
            await self._refund_and_cancel(bot, c, "No se pudieron crear enlaces de atribución para las fuentes seleccionadas.")
            return {"started": False, "reason": "link_failure"}

        self.db.start_sponsored_campaign(campaign_id)
        for source_chat_id in active_sources:
            await self.refresh_source_boards(bot, int(source_chat_id))
            src = self.db.sponsored_source(campaign_id, int(source_chat_id))
            if src:
                await self.safe_dm(
                    bot, src["source_owner_user_id"],
                    f"🚀 <b>Campaña #{campaign_id} iniciada.</b>\n\nTu canal ya tiene el botón patrocinado cuando exista una botonera activa. "
                    f"Cada conversión que permanezca {self.settings.monetization_retention_hours}h puede generar <b>{milli_xtr_text(c.get('rate_milli_per_verified'))}</b>.",
                    parse_mode="HTML",
                )
        await self.safe_dm(
            bot, c["advertiser_user_id"],
            f"🚀 <b>Campaña #{campaign_id} iniciada.</b>\n\nFuentes activas: <b>{len(active_sources)}</b>\nObjetivo: <b>{int(c['goal_members']):,}</b> ingresos atribuidos.",
            parse_mode="HTML",
        )
        return {"started": True, "sources": len(active_sources)}

    async def disable_source_channel(self, bot, source_chat_id: int, reason: str = "source_unavailable") -> int:
        """Retira un canal fuente de campañas patrocinadas activas y revoca sus enlaces.

        Las conversiones ya registradas permanecen para validación/pago, pero el canal deja
        de poder generar nuevas atribuciones inmediatamente.
        """
        rows = self.db.active_sponsored_sources_for_chat(source_chat_id)
        closed = 0
        for src in rows:
            if src.get("invite_link"):
                try:
                    await bot.revoke_chat_invite_link(int(src["target_chat_id"]), src["invite_link"])
                except TelegramError as exc:
                    log.warning(
                        "No se pudo revocar enlace patrocinado campaña %s fuente %s: %s",
                        src["campaign_id"], source_chat_id, exc,
                    )
            self.db.mark_sponsored_source_revoked(int(src["campaign_id"]), source_chat_id)
            closed += 1
            self.db.log_system_event(
                "sponsored_source_disabled",
                f"campaign={src['campaign_id']}; source={source_chat_id}; reason={reason}",
            )
        return closed

    async def close_acquisition(self, bot, campaign_id: int, reason: str = "goal_reached"):
        c = self.db.get_sponsored_campaign(campaign_id)
        if not c or c.get("status") != "active":
            return
        self.db.close_sponsored_acquisition(campaign_id, "settling")
        for src in self.db.sponsored_sources(campaign_id, ("active",)):
            if src.get("invite_link"):
                try:
                    await bot.revoke_chat_invite_link(int(c["target_chat_id"]), src["invite_link"])
                except TelegramError:
                    pass
            self.db.mark_sponsored_source_revoked(campaign_id, src["source_chat_id"])
            await self.refresh_source_boards(bot, int(src["source_chat_id"]))
        await self.safe_dm(
            bot, c["advertiser_user_id"],
            f"🎯 <b>Adquisición cerrada · Campaña #{campaign_id}</b>\n\n"
            f"Ingresos atribuidos: <b>{int(c.get('joined_count') or 0):,}</b> / {int(c.get('goal_members') or 0):,}.\n"
            f"Ahora se validará la permanencia mínima de {self.settings.monetization_retention_hours}h antes de cerrar resultados.",
            parse_mode="HTML",
        )
        self.db.log_system_event("sponsored_acquisition_closed", f"campaign={campaign_id}; reason={reason}")

    async def on_join_request(self, bot, request) -> bool:
        if not request or not request.from_user or request.from_user.is_bot:
            return False
        link_obj = request.invite_link
        if not link_obj or not getattr(link_obj, "invite_link", None):
            return False
        source = self.db.sponsored_source_by_link(link_obj.invite_link)
        if not source:
            return False
        when = request.date.isoformat(timespec="seconds") if request.date else datetime.now(self.settings.timezone).isoformat(timespec="seconds")
        self.db.record_sponsored_request(link_obj.invite_link, request.from_user.id, when)
        return True

    async def on_chat_member(self, bot, event) -> bool:
        if not event:
            return False
        user = getattr(event.new_chat_member, "user", None)
        if not user or user.is_bot:
            return False
        old_status = getattr(event.old_chat_member, "status", None)
        new_status = getattr(event.new_chat_member, "status", None)
        was_inside = old_status in INSIDE_STATUSES or (old_status == ChatMemberStatus.RESTRICTED and bool(getattr(event.old_chat_member, "is_member", False)))
        is_inside = new_status in INSIDE_STATUSES or (new_status == ChatMemberStatus.RESTRICTED and bool(getattr(event.new_chat_member, "is_member", False)))
        when_dt = event.date.astimezone(self.settings.timezone) if event.date else datetime.now(self.settings.timezone)
        when = when_dt.isoformat(timespec="seconds")

        if not was_inside and is_inside:
            link_obj = event.invite_link
            row = None
            if link_obj and getattr(link_obj, "invite_link", None) and self.db.sponsored_source_by_link(link_obj.invite_link):
                due = (when_dt + timedelta(hours=self.settings.monetization_retention_hours)).isoformat(timespec="seconds")
                row = self.db.record_sponsored_join(link_obj.invite_link, user.id, when, due)
            elif bool(getattr(event, "via_join_request", False)):
                due = (when_dt + timedelta(hours=self.settings.monetization_retention_hours)).isoformat(timespec="seconds")
                row = self.db.record_sponsored_join_from_pending(event.chat.id, user.id, when, due)
            if row:
                campaign = self.db.get_sponsored_campaign(row["campaign_id"])
                source = self.db.sponsored_source(row["campaign_id"], row["first_source_chat_id"])
                if campaign and source:
                    self.db.ensure_pending_earning(
                        row["campaign_id"], row["first_source_chat_id"], user.id,
                        source["source_owner_user_id"], int(campaign.get("rate_milli_per_verified") or 0),
                    )
                    campaign = self.db.get_sponsored_campaign(row["campaign_id"])
                    if campaign and campaign.get("status") == "active" and int(campaign.get("joined_count") or 0) >= int(campaign.get("goal_members") or 0):
                        await self.close_acquisition(bot, int(campaign["id"]), "goal_reached")
                return True

        if was_inside and not is_inside:
            # Solo devuelve True si existe una conversión patrocinada activa/settling.
            before = self.db.one(
                """SELECT su.id FROM sponsored_users su JOIN sponsored_campaigns sc ON sc.id=su.campaign_id
                   WHERE su.target_chat_id=? AND su.user_id=? AND sc.status IN ('active','settling') ORDER BY su.id DESC LIMIT 1""",
                (event.chat.id, user.id),
            )
            if before:
                self.db.record_sponsored_leave(event.chat.id, user.id, when)
                return True
        return False

    async def validate_due(self, bot) -> dict:
        now = datetime.now(self.settings.timezone)
        verified = rejected = failed = 0
        for row in self.db.pending_sponsored_validations(now.isoformat(timespec="seconds"), 250):
            try:
                member = await bot.get_chat_member(int(row["campaign_target_chat_id"]), int(row["user_id"]))
                status = getattr(member, "status", None)
                payable_member = (
                    status == ChatMemberStatus.MEMBER
                    or (status == ChatMemberStatus.RESTRICTED and bool(getattr(member, "is_member", False)))
                )
                if payable_member:
                    self.db.mark_sponsored_verified(row["campaign_id"], row["user_id"], int(row.get("rate_milli_per_verified") or 0))
                    verified += 1
                elif status in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}:
                    self.db.mark_sponsored_rejected(row["campaign_id"], row["user_id"], "Administradores/propietarios del canal objetivo no generan conversiones pagables")
                    rejected += 1
                else:
                    self.db.mark_sponsored_rejected(row["campaign_id"], row["user_id"], "No permaneció durante el periodo mínimo")
                    rejected += 1
            except TelegramError as exc:
                failed += 1
                log.warning("No se pudo validar conversión campaña %s usuario %s: %s", row["campaign_id"], row["user_id"], exc)

        # Finaliza campañas settling cuando no queda nadie por validar.
        for c in self.db.sponsored_campaigns_by_status(("settling",), 100):
            if self.db.sponsored_campaign_pending_count(c["id"]) == 0:
                self.db.complete_sponsored_campaign(c["id"])
                fresh = self.db.get_sponsored_campaign(c["id"]) or c
                await self.send_final_reports(bot, fresh)
        return {"verified": verified, "rejected": rejected, "failed": failed}

    async def send_final_reports(self, bot, campaign: dict):
        cid = int(campaign["id"])
        participant_pool = int(campaign.get("participant_pool_milli") or 0)
        earned = 0
        for src in self.db.sponsored_sources(cid):
            earned += int(src.get("earned_milli") or 0)
        unused = max(0, participant_pool - earned)
        await self.safe_dm(
            bot, campaign["advertiser_user_id"],
            f"✅ <b>Campaña #{cid} finalizada</b>\n\n"
            f"Objetivo: <b>{int(campaign.get('goal_members') or 0):,}</b>\n"
            f"Solicitudes únicas: <b>{int(campaign.get('requests_count') or 0):,}</b>\n"
            f"Intentos de solicitud: <b>{int(campaign.get('request_attempts_count') or 0):,}</b>\n"
            f"Ingresos atribuidos: <b>{int(campaign.get('joined_count') or 0):,}</b>\n"
            f"Verificados {self.settings.monetization_retention_hours}h: <b>{int(campaign.get('verified_count') or 0):,}</b>\n"
            f"No válidos: <b>{int(campaign.get('rejected_count') or 0):,}</b>",
            parse_mode="HTML",
        )
        # Resumen por propietario, una notificación por campaña.
        owners: dict[int, list[dict]] = {}
        for src in self.db.sponsored_sources(cid):
            owners.setdefault(int(src["source_owner_user_id"]), []).append(src)
        for owner_id, srcs in owners.items():
            verified = sum(int(x.get("verified_count") or 0) for x in srcs)
            total = sum(int(x.get("earned_milli") or 0) for x in srcs)
            await self.safe_dm(
                bot, owner_id,
                f"💰 <b>Resultados pagados · Campaña #{cid}</b>\n\n"
                f"Canales fuente: <b>{len(srcs)}</b>\n"
                f"Conversiones verificadas: <b>{verified:,}</b>\n"
                f"Ganancia acreditada: <b>{milli_xtr_text(total)}</b>\n\n"
                "El saldo disponible puede solicitarse desde 💰 Monetización → Mi monedero.",
                parse_mode="HTML",
            )
        self.db.log_system_event("sponsored_campaign_completed", f"campaign={cid}; earned_milli={earned}; unused_pool_milli={unused}")

    async def job(self, context):
        if not self.enabled():
            return
        now = datetime.now(self.settings.timezone)

        # Una fuente que deja de estar aprobada/operativa deja de generar atribución
        # inmediatamente, incluso si la suspensión se detectó mediante la auditoría periódica.
        for c in self.db.sponsored_campaigns_by_status(("active",), 100):
            for src in self.db.sponsored_sources(int(c["id"]), ("active",)):
                ch = self.db.get_channel(int(src["source_chat_id"]))
                if not ch or ch.get("status") != "approved" or not ch.get("permissions_ok"):
                    await self.disable_source_channel(context.bot, int(src["source_chat_id"]), "source_not_eligible")

        # Comienzos programados.
        for c in self.db.recruiting_sponsored_due(now.isoformat(timespec="seconds")):
            await self.start_campaign(context.bot, int(c["id"]))

        # Cierre de seguridad por tiempo máximo o meta ya alcanzada.
        for c in self.db.sponsored_campaigns_by_status(("active",), 100):
            if int(c.get("joined_count") or 0) >= int(c.get("goal_members") or 0):
                await self.close_acquisition(context.bot, int(c["id"]), "goal_reached")
                continue
            try:
                max_end = datetime.fromisoformat(c["max_end_at"])
                if max_end.tzinfo is None:
                    max_end = max_end.replace(tzinfo=self.settings.timezone)
                if now >= max_end:
                    await self.close_acquisition(context.bot, int(c["id"]), "max_duration")
            except Exception:
                pass
        await self.validate_due(context.bot)
