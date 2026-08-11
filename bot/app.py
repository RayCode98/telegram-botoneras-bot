from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, time

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import BUTTON_STYLES, CATEGORIES, category_from_members, load_settings
from .db import Database
from .keyboards import (
    admin_home_keyboard,
    approval_keyboard,
    category_keyboard,
    channel_admin_keyboard,
    color_keyboard,
    lifetime_actions_keyboard,
    link_type_keyboard,
    owner_channel_keyboard,
    publish_confirm_keyboard,
    publish_delete_confirm_keyboard,
    sanction_keyboard,
    schedule_actions_keyboard,
    shuffle_actions_keyboard,
    template_actions_keyboard,
    participant_home_keyboard,
    participant_channels_keyboard,
    participant_channel_keyboard,
    participant_stats_channels_keyboard,
    participant_stats_history_keyboard,
    participant_status_keyboard,
    participant_notifications_keyboard,
    participant_withdraw_confirm_keyboard,
    participant_add_channel_keyboard,
    manual_channel_verification_keyboard,
    appeal_admin_keyboard,
    system_admin_keyboard,
    system_back_keyboard,
)
from .moderation import ModerationService
from .maintenance import MaintenanceService
from .publisher import Publisher

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("botoneras")

settings = load_settings()
db = Database(settings.database_path, settings.default_lifetime_hours)
db.ensure_categories(CATEGORIES, settings.default_lifetime_hours)
publisher = Publisher(db, settings)


def is_admin(user_id: int | None) -> bool:
    return bool(user_id and user_id in settings.admin_ids)


def parse_category(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().upper()
    if value in {"50K", "50K+", "+50K"}:
        value = "+50K"
    return value if value in CATEGORIES else None


MANUAL_CHANNEL_REQUEST_ID = 61001


def invite_mode_label(value: str | None) -> str:
    labels = {
        "direct": "Ingreso directo",
        "approval": "Solicitud de ingreso",
        # Compatibilidad visual si se abre una base todavía no migrada.
        "public": "Ingreso directo",
        "private": "Ingreso directo",
    }
    return labels.get(value or "", value or "—")


def required_channel_permissions(member) -> list[str]:
    required = (
        ("can_post_messages", "Publicar mensajes"),
        ("can_edit_messages", "Editar mensajes"),
        ("can_delete_messages", "Eliminar mensajes"),
        ("can_invite_users", "Invitar usuarios / crear enlaces"),
    )
    return [label for attr, label in required if not bool(getattr(member, attr, False))]


def fmt_channel(ch: dict) -> str:
    owner = ch.get("owner_user_id")
    sanction = db.get_sanction(owner) if owner else {"strikes": 0, "banned": 0}
    return (
        f"<b>{html.escape(ch.get('telegram_title') or 'Sin título')}</b>\n"
        f"ID: <code>{ch['chat_id']}</code>\n"
        f"Botón: <b>{html.escape(ch.get('button_title') or '—')}</b>\n"
        f"Miembros: <b>{int(ch.get('member_count') or 0):,}</b>\n"
        f"Categoría: <b>{html.escape(ch.get('category') or '—')}</b>\n"
        + (f"Próxima categoría: <b>{html.escape(ch.get('pending_category'))}</b> 🔄\n" if ch.get("pending_category") else "")
        + f"Ingreso: <b>{html.escape(invite_mode_label(ch.get('invite_type')))}</b>\n"
        f"Color: <b>{html.escape(ch.get('button_style') or 'default')}</b>\n"
        f"Estado: <b>{html.escape(ch.get('status') or '—')}</b>\n"
        f"Permisos: <b>{'✅ OK' if ch.get('permissions_ok', 1) else '⚠️ incompletos'}</b>\n"
        + (f"Detalle permisos: <b>{html.escape(ch.get('permission_issues') or '')}</b>\n" if not ch.get('permissions_ok', 1) else "")
        + f"Responsable: <code>{owner or '—'}</code>\n"
        f"Faltas: <b>{int(sanction.get('strikes') or 0)}/{settings.violation_limit}</b>"
        + (" 🚫" if sanction.get("banned") else "")
    )


async def safe_dm(bot, user_id: int | None, text: str, **kwargs) -> bool:
    if not user_id:
        return False
    known = db.get_user(user_id)
    if not known:
        return False
    try:
        await bot.send_message(chat_id=known["private_chat_id"], text=text, **kwargs)
        return True
    except (Forbidden, BadRequest, TelegramError):
        return False


async def notify_user_pref(bot, user_id: int | None, pref_key: str, text: str, **kwargs) -> bool:
    if not user_id:
        return False
    prefs = db.get_user_preferences(int(user_id))
    if not bool(prefs.get(pref_key, 1)):
        return False
    return await safe_dm(bot, user_id, text, **kwargs)


def _next_start_for_category(category: str) -> datetime | None:
    sched = db.get_schedule(category) or {}
    if not sched.get("enabled"):
        return None
    now = datetime.now(settings.timezone)
    candidate = now.replace(
        hour=int(sched.get("hour") or 0), minute=int(sched.get("minute") or 0),
        second=0, microsecond=0,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _category_progress(member_count: int, category: str) -> tuple[int | None, str | None, float]:
    targets = {"BELOW_5K": (settings.min_members, "5K"), "5K": (10_000, "10K"), "10K": (20_000, "20K"), "20K": (30_000, "30K"), "30K": (50_000, "+50K")}
    if category not in targets:
        return None, None, 1.0
    target, next_cat = targets[category]
    if category == "BELOW_5K":
        base = 0
    elif category == "5K":
        base = settings.min_members
    elif category == "10K":
        base = 10_000
    elif category == "20K":
        base = 20_000
    else:
        base = 30_000
    denom = max(1, target - base)
    progress = max(0.0, min(1.0, (member_count - base) / denom))
    return target, next_cat, progress


maintenance = MaintenanceService(db, settings, safe_dm)
publisher.permission_validator = maintenance.validate_publish_destination
moderation = ModerationService(db, settings, publisher, is_admin, safe_dm)


async def admin_only(update: Update) -> bool:
    if not is_admin(update.effective_user.id if update.effective_user else None):
        await update.effective_message.reply_text("⛔ Comando exclusivo de administradores.")
        return False
    return True


async def deny_if_banned(user_id: int, target_message) -> bool:
    if db.is_banned(user_id) and not is_admin(user_id):
        state = db.get_sanction(user_id)
        await target_message.reply_html(
            "🚫 <b>Tu acceso está bloqueado.</b>\n\n"
            f"Faltas: <b>{state['strikes']}/{settings.violation_limit}</b>. "
            "Un administrador debe retirar la sanción antes de que puedas registrar o modificar canales."
        )
        return True
    return False


async def notify_admins_review(bot, ch: dict):
    text = "🛡 <b>Nueva solicitud para revisión</b>\n\n" + fmt_channel(ch)
    if ch.get("invite_url"):
        text += "\n\nEnlace: " + html.escape(ch["invite_url"])
    for admin_id in settings.admin_ids:
        await safe_dm(bot, admin_id, text, parse_mode="HTML", reply_markup=approval_keyboard(ch["chat_id"]))


async def notify_admins_violation(bot, user_id: int | None, chat_id: int, detail: str):
    if not user_id:
        return
    state = db.get_sanction(user_id)
    text = (
        "⚠️ <b>Incidencia automática</b>\n\n"
        f"Usuario: <code>{user_id}</code>\n"
        f"Canal: <code>{chat_id}</code>\n"
        f"Faltas: <b>{state['strikes']}/{settings.violation_limit}</b>\n"
        f"Estado: <b>{'BLOQUEADO' if state['banned'] else 'advertido'}</b>\n\n"
        f"{html.escape(detail)}"
    )
    for admin_id in settings.admin_ids:
        await safe_dm(bot, admin_id, text, parse_mode="HTML", reply_markup=sanction_keyboard(user_id, bool(state["banned"])))


async def submit_channel_review(bot, chat_id: int):
    ch = db.get_channel(chat_id)
    if not ch:
        return
    category = ch.get("category")
    db.set_channel_fields(chat_id, status="pending_review")
    if category in CATEGORIES:
        # Al modificar un canal aprobado, su botón sale temporalmente de la botonera
        # hasta que el cambio vuelva a ser aprobado.
        await publisher.refresh_category(bot, category)
    await notify_admins_review(bot, db.get_channel(chat_id))


# ---------------------------------------------------------------------
# Owner/user flow
# ---------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat or chat.type != ChatType.PRIVATE:
        return

    db.upsert_user(user.id, chat.id, user.username, user.first_name)
    db.ensure_user_preferences(user.id)
    state = db.get_sanction(user.id)
    blocked = bool(state.get("banned") and not is_admin(user.id))
    text = (
        f"👋 <b>Bienvenido, {html.escape(user.first_name or 'participante')}</b>\n\n"
        "Desde aquí puedes administrar tus canales, estadísticas, próximas botoneras, "
        "notificaciones y solicitudes."
    )
    if blocked:
        text += f"\n\n🚫 <b>Tu cuenta está bloqueada</b> · faltas {state['strikes']}/{settings.violation_limit}. Puedes consultar el estado y enviar una apelación."
    await update.message.reply_html(text, reply_markup=participant_home_keyboard(is_admin(user.id)))

    pending = db.configuring_for_owner(user.id)
    if pending and not blocked:
        ch = pending[0]
        await update.message.reply_html(
            "Encontré un canal pendiente de configurar:\n\n" + fmt_channel(ch),
            reply_markup=link_type_keyboard(ch["chat_id"]),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_html(
        "<b>Propietarios</b>\n"
        "/start — registrar chat privado\n"
        "/miscanales — ver/editar canales\n/verificarcanal — recuperar manualmente un canal ya agregado\n\n"
        "<b>Administradores</b>\n"
        "/panel — panel visual completo\n"
        "/publicar 5K — publicar ahora\n/eliminarpublicacion 5K — borrar la botonera activa de todos los canales\n"
        "/programar 5K 18:00 — horario diario\n"
        "/duracion 5K 6 — duración en horas\n"
        "/mezcla 5K 10 — mezclar botones de canales cada 10 min\n"
        "/nomezcla 5K — desactivar mezcla\n"
        "/plantilla 5K — cargar imagen + caption\n"
        "/texto 5K TEXTO — editar texto\n"
        "/preview 5K — previsualizar\n"
        "/refrescar 5K — refrescar botones\n"
        "/pendientes — revisiones\n"
        "/health — estado del sistema\n"
        "/backup — crear backup manual\n"
        "/auditarpermisos — verificar permisos de canales\n"
        "/transferircanal CHAT_ID USER_ID — transferir propiedad (admin)\n"
        "/faltas — ver sanciones\n"
        "/resetfaltas USER_ID — desbanear/resetear"
    )


async def my_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    rows = db.channels_for_owner(user.id)
    approved = sum(1 for ch in rows if ch.get("status") == "approved")
    pending = sum(1 for ch in rows if ch.get("status") in {"pending_review", "configuring"})
    await update.effective_message.reply_html(
        f"📡 <b>Mis canales</b>\n\nTotal: <b>{len(rows)}</b> · ✅ {approved} aprobados · 🟡 {pending} pendientes",
        reply_markup=participant_channels_keyboard(rows),
    )


async def send_manual_channel_verification(target_message):
    """Muestra el selector nativo de Telegram para verificar un canal ya agregado."""
    await target_message.reply_html(
        "✅ <b>Verificación manual de canal</b>\n\n"
        "Pulsa el botón inferior y selecciona el canal. Telegram solo mostrará canales "
        "compatibles con los permisos solicitados. Después comprobaré en tiempo real que:\n\n"
        "• tú seas propietario/administrador del canal;\n"
        "• el bot sea administrador;\n"
        "• tenga permisos para publicar, editar, eliminar e invitar usuarios.\n\n"
        "Esto sirve especialmente cuando el bot ya aparece como administrador pero el alta automática no llegó.",
        reply_markup=manual_channel_verification_keyboard(MANUAL_CHANNEL_REQUEST_ID),
    )


async def verify_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat or chat.type != ChatType.PRIVATE:
        return
    if await deny_if_banned(user.id, update.effective_message):
        return
    await send_manual_channel_verification(update.effective_message)


async def manual_chat_shared(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recupera un alta cuando my_chat_member no llegó o ya expiró.

    No confía únicamente en el objeto ChatShared: vuelve a consultar a Telegram
    tanto el estado del bot como el del usuario solicitante antes de vincular el
    canal a la cuenta.
    """
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    shared = getattr(msg, "chat_shared", None) if msg else None
    if not msg or not user or not chat or chat.type != ChatType.PRIVATE or not shared:
        return

    if int(getattr(shared, "request_id", -1)) != MANUAL_CHANNEL_REQUEST_ID:
        return

    # Quita inmediatamente el teclado de selección para evitar dobles envíos.
    try:
        await msg.reply_text("🔎 Verificando canal con Telegram…", reply_markup=ReplyKeyboardRemove())
    except TelegramError:
        pass

    if db.is_banned(user.id) and not is_admin(user.id):
        await msg.reply_html("🚫 Tu cuenta está bloqueada y no puede registrar nuevos canales.")
        return

    chat_id = int(shared.chat_id)
    existing = db.get_channel(chat_id)

    # Protección contra apropiación: nunca se sustituye al responsable existente.
    if (
        existing and existing.get("owner_user_id")
        and int(existing["owner_user_id"]) != int(user.id)
        and not is_admin(user.id)
    ):
        db.record_ownership_conflict(
            chat_id,
            existing.get("owner_user_id"),
            user.id,
            user.username,
            "Intento de verificación manual de un canal ya registrado por otra cuenta.",
        )
        await msg.reply_html(
            "⛔ <b>Este canal ya está registrado.</b>\n\n"
            "La verificación manual no cambia al propietario. Si hubo un cambio legítimo de responsable, "
            "un administrador del bot debe usar la transferencia de canal."
        )
        for admin_id in settings.admin_ids:
            await safe_dm(
                context.bot,
                admin_id,
                "🧩 <b>Conflicto de propiedad en verificación manual</b>\n\n"
                f"Canal: <code>{chat_id}</code>\n"
                f"Propietario registrado: <code>{existing.get('owner_user_id')}</code>\n"
                f"Intento desde: <code>{user.id}</code>",
                parse_mode="HTML",
            )
        return

    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
    except TelegramError as exc:
        await msg.reply_html(
            "❌ <b>No puedo acceder a ese canal.</b>\n\n"
            "Confirma que el bot siga dentro del canal y vuelve a intentarlo.\n\n"
            f"<code>{html.escape(str(exc))}</code>"
        )
        return

    if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
        await msg.reply_html(
            "⚠️ <b>El bot está en el canal, pero no figura como administrador.</b>\n\n"
            "Dale rol de administrador y vuelve a pulsar <b>Verificar manualmente</b>."
        )
        return

    missing = required_channel_permissions(bot_member)

    # getChatMember para otros usuarios está garantizado cuando el bot es admin.
    try:
        requester_member = await context.bot.get_chat_member(chat_id, user.id)
    except TelegramError as exc:
        await msg.reply_html(
            "❌ No pude confirmar que tu cuenta administre ese canal.\n\n"
            f"<code>{html.escape(str(exc))}</code>"
        )
        return

    if requester_member.status not in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR} and not is_admin(user.id):
        await msg.reply_html(
            "⛔ <b>No puedo vincular ese canal a tu cuenta.</b>\n\n"
            "Tu usuario debe aparecer como propietario o administrador del canal."
        )
        return

    try:
        info = await context.bot.get_chat(chat_id)
        count = await context.bot.get_chat_member_count(chat_id)
    except TelegramError as exc:
        await msg.reply_html(
            "❌ Telegram compartió el canal, pero no pude leer sus datos.\n\n"
            f"<code>{html.escape(str(exc))}</code>"
        )
        return

    category = category_from_members(count, settings.min_members)
    was_registered = bool(existing)
    old_status = existing.get("status") if existing else None

    db.upsert_channel(
        chat_id,
        info.title or getattr(shared, "title", None) or str(chat_id),
        info.username or getattr(shared, "username", None),
        existing.get("owner_user_id") if existing and existing.get("owner_user_id") else user.id,
        count,
        category,
    )
    db.set_channel_permission_state(chat_id, not missing, "; ".join(missing) if missing else None)

    if missing:
        # El canal queda registrado para no perderlo, pero no puede publicarse todavía.
        new_status = "permission_suspended" if old_status == "approved" else "configuring"
        db.set_channel_fields(chat_id, status=new_status)
        await msg.reply_html(
            "⚠️ <b>Canal encontrado, pero faltan permisos.</b>\n\n"
            f"<b>{html.escape(info.title or str(chat_id))}</b>\n"
            f"ID: <code>{chat_id}</code>\n"
            "Faltan:\n• " + "\n• ".join(map(html.escape, missing)) +
            "\n\nCorrige esos permisos y vuelve a verificar el canal."
        )
        return

    # Si ya tenía una configuración completa, la verificación no obliga a repetir
    # el onboarding. Puede incluso recuperar automáticamente una suspensión causada
    # exclusivamente por permisos faltantes.
    complete_config = bool(existing and existing.get("button_title") and existing.get("invite_url"))
    if was_registered and complete_config and old_status in {"approved", "permission_suspended"}:
        db.set_channel_fields(chat_id, status="approved")
        if existing.get("category") in CATEGORIES:
            await publisher.refresh_category(context.bot, existing["category"])
        db.log_system_event("manual_channel_verified", f"chat_id={chat_id}; user_id={user.id}; restored_approved=1")
        await msg.reply_html(
            "✅ <b>Canal verificado correctamente.</b>\n\n"
            f"{html.escape(info.title or str(chat_id))}\n"
            f"Miembros: <b>{count:,}</b>\n"
            f"Categoría: <b>{html.escape(category)}</b>\n\n"
            "La configuración existente se conservó y el canal está listo para participar.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📡 Ver mis canales", callback_data="user:channels")]]),
        )
        return

    if was_registered and complete_config and old_status == "pending_review":
        db.set_channel_fields(chat_id, status="pending_review")
        db.log_system_event("manual_channel_verified", f"chat_id={chat_id}; user_id={user.id}; pending_review=1")
        await msg.reply_html(
            "✅ <b>Canal verificado correctamente.</b>\n\n"
            "Tu configuración ya está completa y continúa <b>pendiente de revisión administrativa</b>.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📡 Ver mis canales", callback_data="user:channels")]]),
        )
        return

    db.set_channel_fields(chat_id, status="configuring")
    db.log_system_event("manual_channel_verified", f"chat_id={chat_id}; user_id={user.id}; recovered=1")
    await msg.reply_html(
        "✅ <b>Canal verificado manualmente.</b>\n\n"
        f"{html.escape(info.title or str(chat_id))}\n"
        f"Miembros: <b>{count:,}</b>\n"
        f"Categoría: <b>{html.escape(category)}</b>\n\n"
        "Ahora selecciona cómo deberá comportarse el enlace del botón:",
        reply_markup=link_type_keyboard(chat_id),
    )


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event = update.my_chat_member
    if not event or event.chat.type != ChatType.CHANNEL:
        return

    chat = event.chat
    actor = event.from_user
    new = event.new_chat_member
    old = event.old_chat_member
    existing = db.get_channel(chat.id)
    bot_id = context.bot.id

    new_is_admin = new.status == ChatMemberStatus.ADMINISTRATOR
    old_was_admin = old.status == ChatMemberStatus.ADMINISTRATOR

    if new_is_admin and old_was_admin:
        # Cambio de permisos de un bot que ya era administrador. La suspensión por
        # permisos NO suma una falta y se revierte automáticamente al restaurarlos.
        if existing:
            missing = required_channel_permissions(new)
            db.set_channel_permission_state(chat.id, not missing, "; ".join(missing) if missing else None)
            if missing and existing.get("status") == "approved":
                db.set_channel_fields(chat.id, status="permission_suspended")
                if existing.get("category") in CATEGORIES:
                    await publisher.refresh_category(context.bot, existing["category"])
                await safe_dm(
                    context.bot, existing.get("owner_user_id"),
                    "⚠️ <b>Canal suspendido preventivamente.</b>\n\n"
                    f"Faltan permisos: <b>{html.escape(', '.join(missing))}</b>. "
                    "El sistema lo reactivará automáticamente cuando los restaures.",
                    parse_mode="HTML",
                )
            elif not missing and existing.get("status") == "permission_suspended":
                db.set_channel_fields(chat.id, status="approved")
                if existing.get("category") in CATEGORIES:
                    await publisher.refresh_category(context.bot, existing["category"])
                await safe_dm(
                    context.bot, existing.get("owner_user_id"),
                    "✅ <b>Permisos restaurados.</b> Tu canal vuelve a participar automáticamente.",
                    parse_mode="HTML",
                )
            return
        # Si no existe en la base pero Telegram informa un cambio de permisos de un
        # bot que ya era admin, aprovechamos el evento para recuperar el alta en vez
        # de descartarlo. Esto cubre parte de los casos donde se perdió el evento inicial.

    if not new_is_admin:
        # Evita contabilizar como otra falta cuando el propio bot abandona un canal
        # debido a un bloqueo automático.
        if existing and existing.get("status") in {"banned", "withdrawn"}:
            reason = "owner_banned" if existing.get("status") == "banned" else "voluntary_withdrawal"
            for row in db.active_board_messages_for_chat(chat.id):
                db.mark_board_removed(row["id"], reason)
            return
        if actor and actor.id == bot_id:
            return
        if existing and old_was_admin:
            responsible = actor.id if actor and not actor.is_bot else existing.get("owner_user_id")
            state = await moderation.handle_bot_removed(context.bot, existing, responsible)
            if state:
                await notify_admins_violation(
                    context.bot,
                    responsible,
                    chat.id,
                    "El bot fue eliminado o perdió permisos de administrador.",
                )
        return

    # El bot acaba de ser agregado/promovido.
    attempted_owner = actor.id if actor and not actor.is_bot else None
    if (
        existing and existing.get("owner_user_id") and attempted_owner
        and int(existing["owner_user_id"]) != int(attempted_owner)
        and not is_admin(attempted_owner)
    ):
        # Un chat_id solo puede estar ligado a un responsable. No se reasigna por
        # volver a agregar el bot desde otra cuenta: requiere transferencia de admin.
        db.record_ownership_conflict(
            chat.id, existing.get("owner_user_id"), attempted_owner,
            getattr(actor, "username", None),
            "Otra cuenta intentó agregar el bot a un canal ya registrado.",
        )
        await safe_dm(
            context.bot, attempted_owner,
            "⛔ <b>Canal ya registrado.</b>\n\nEste canal pertenece a otro participante dentro del sistema. "
            "No puedes reclamarlo agregando nuevamente el bot. Un administrador debe transferir la propiedad si corresponde.",
            parse_mode="HTML",
        )
        await safe_dm(
            context.bot, existing.get("owner_user_id"),
            "🔐 <b>Intento de registro bloqueado.</b>\n\n"
            f"Otra cuenta (<code>{attempted_owner}</code>) intentó agregar el bot a tu canal "
            f"<b>{html.escape(existing.get('telegram_title') or str(chat.id))}</b>. La propiedad no fue modificada.",
            parse_mode="HTML",
        )
        for admin_id in settings.admin_ids:
            await safe_dm(
                context.bot, admin_id,
                "🧩 <b>Conflicto de propiedad detectado</b>\n\n"
                f"Canal: <code>{chat.id}</code>\n"
                f"Propietario registrado: <code>{existing.get('owner_user_id')}</code>\n"
                f"Intento desde: <code>{attempted_owner}</code>",
                parse_mode="HTML",
            )
        try:
            await context.bot.leave_chat(chat.id)
        except TelegramError:
            pass
        return

    candidate_owner = existing.get("owner_user_id") if existing and existing.get("owner_user_id") else attempted_owner
    banned_actor = actor.id if actor and db.is_banned(actor.id) and not is_admin(actor.id) else None
    banned_owner = candidate_owner if candidate_owner and db.is_banned(candidate_owner) and not is_admin(candidate_owner) else None
    if banned_actor or banned_owner:
        blocked_user = banned_actor or banned_owner
        db.upsert_channel(chat.id, chat.title or str(chat.id), getattr(chat, "username", None), blocked_user, 0, existing.get("category") if existing else "BELOW_5K")
        db.set_channel_fields(chat.id, status="banned")
        await safe_dm(
            context.bot,
            blocked_user,
            "🚫 No puedes registrar este canal porque tu cuenta está bloqueada.",
        )
        try:
            await context.bot.leave_chat(chat.id)
        except TelegramError:
            pass
        return

    try:
        info = await context.bot.get_chat(chat.id)
        count = await context.bot.get_chat_member_count(chat.id)
    except TelegramError as exc:
        log.warning("No se pudo consultar %s: %s", chat.id, exc)
        return

    category = category_from_members(count, settings.min_members)
    owner_id = candidate_owner or (actor.id if actor else None)
    db.upsert_channel(chat.id, info.title or str(chat.id), info.username, owner_id, count, category)
    db.set_channel_fields(chat.id, status="configuring")

    missing = required_channel_permissions(new)
    db.set_channel_permission_state(chat.id, not missing, "; ".join(missing) if missing else None)
    warning = ""
    if missing:
        warning = "\n\n⚠️ <b>Permisos faltantes:</b>\n• " + "\n• ".join(map(html.escape, missing))

    delivered = await safe_dm(
        context.bot,
        owner_id,
        "✅ Canal detectado:\n\n"
        f"<b>{html.escape(info.title or str(chat.id))}</b>\n"
        f"Miembros: <b>{count:,}</b>\n"
        f"Categoría: <b>{html.escape(category)}</b>\n\n"
        "Selecciona si el enlace permitirá ingreso directo o requerirá aprobación:" + warning,
        parse_mode="HTML",
        reply_markup=link_type_keyboard(chat.id),
    )
    if not delivered:
        log.info("El responsable %s debe ejecutar /start para configurar %s", owner_id, chat.id)


async def config_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if db.is_banned(q.from_user.id) and not is_admin(q.from_user.id):
        await q.answer("Tu cuenta está bloqueada.", show_alert=True)
        return

    _, kind, raw_id = q.data.split(":", 2)
    chat_id = int(raw_id)
    ch = db.get_channel(chat_id)
    if not ch or (ch.get("owner_user_id") != q.from_user.id and not is_admin(q.from_user.id)):
        await q.answer("No tienes permiso.", show_alert=True)
        return

    if kind not in {"direct", "approval"}:
        await q.answer("Tipo de ingreso inválido.", show_alert=True)
        return

    try:
        # Siempre generamos un enlace administrado por el bot. Así el comportamiento
        # elegido es independiente de que el canal tenga o no @username público.
        # En modo approval Telegram crea una solicitud que debe aprobar un admin.
        previous_url = ch.get("invite_url")
        if previous_url and ("t.me/+" in previous_url or "t.me/joinchat/" in previous_url):
            try:
                await context.bot.revoke_chat_invite_link(chat_id=chat_id, invite_link=previous_url)
            except TelegramError:
                # Puede ser un enlace antiguo creado por otro administrador. No impide
                # generar el enlace nuevo que usará la botonera.
                pass

        link = await context.bot.create_chat_invite_link(
            chat_id=chat_id,
            name="Botonera - Solicitud" if kind == "approval" else "Botonera - Directo",
            creates_join_request=(kind == "approval"),
        )
        invite_url = link.invite_link

        db.set_channel_fields(chat_id, invite_type=kind, invite_url=invite_url)
        ch = db.get_channel(chat_id)
        if ch.get("button_title"):
            await submit_channel_review(context.bot, chat_id)
            db.clear_session(q.from_user.id)
            await q.message.reply_html("✅ Cambio enviado nuevamente a revisión.\n\n" + fmt_channel(db.get_channel(chat_id)))
        else:
            db.set_session(q.from_user.id, "channel_title", chat_id=chat_id)
            await q.message.reply_html("🔗 Enlace configurado. Ahora envíame el <b>título</b> del botón.")
    except TelegramError as exc:
        await q.message.reply_html("❌ No pude configurar el enlace.\n\n<code>" + html.escape(str(exc)) + "</code>")


async def config_color_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if db.is_banned(q.from_user.id) and not is_admin(q.from_user.id):
        await q.answer("Tu cuenta está bloqueada.", show_alert=True)
        return

    _, style, raw_id = q.data.split(":", 2)
    chat_id = int(raw_id)
    ch = db.get_channel(chat_id)
    if style not in BUTTON_STYLES or not ch or (ch.get("owner_user_id") != q.from_user.id and not is_admin(q.from_user.id)):
        return

    db.set_channel_fields(chat_id, button_style=style)
    db.clear_session(q.from_user.id)
    await submit_channel_review(context.bot, chat_id)
    await q.message.reply_html("✅ <b>Solicitud enviada a revisión.</b>\n\n" + fmt_channel(db.get_channel(chat_id)))


async def owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if db.is_banned(q.from_user.id) and not is_admin(q.from_user.id):
        await q.answer("Tu cuenta está bloqueada.", show_alert=True)
        return

    _, action, raw_id = q.data.split(":", 2)
    chat_id = int(raw_id)
    ch = db.get_channel(chat_id)
    if not ch or (ch.get("owner_user_id") != q.from_user.id and not is_admin(q.from_user.id)):
        return

    if action == "title":
        db.set_session(q.from_user.id, "channel_title_edit", chat_id=chat_id)
        await q.message.reply_html("✏️ Envíame el nuevo título. El cambio volverá a revisión.")
    elif action == "color":
        await q.message.reply_html("🎨 Elige el color:", reply_markup=color_keyboard(chat_id))
    elif action == "link":
        await q.message.reply_html("🔗 Elige cómo será el ingreso mediante el botón:", reply_markup=link_type_keyboard(chat_id))
    elif action == "reactivate":
        try:
            member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if member.status != ChatMemberStatus.ADMINISTRATOR:
                await q.answer("Primero vuelve a agregarme como administrador.", show_alert=True)
                return
            count = await context.bot.get_chat_member_count(chat_id)
            category = category_from_members(count, settings.min_members)
            db.set_channel_fields(chat_id, member_count=count, category=category)
            ch = db.get_channel(chat_id)
            if category not in CATEGORIES:
                db.set_channel_fields(chat_id, status="below_minimum")
                await q.message.reply_html(
                    f"📉 El canal tiene <b>{count:,}</b> suscriptores y todavía no alcanza el mínimo de <b>{settings.min_members:,}</b>. Se revisará automáticamente."
                )
                return
            if not ch.get("button_title") or not ch.get("invite_url"):
                db.set_channel_fields(chat_id, status="configuring")
                await q.message.reply_html("Faltan datos. Configura de nuevo el enlace:", reply_markup=link_type_keyboard(chat_id))
                return
            await submit_channel_review(context.bot, chat_id)
            await q.message.reply_html("🔁 <b>Reactivación enviada a revisión.</b>\n\n" + fmt_channel(db.get_channel(chat_id)))
        except TelegramError as exc:
            await q.message.reply_text(f"No pude validar el canal: {exc}")

# ---------------------------------------------------------------------
# Participant visual panel
# ---------------------------------------------------------------------
def participant_home_text(user_id: int) -> str:
    channels = db.channels_for_owner(user_id)
    approved = sum(1 for ch in channels if ch.get("status") == "approved")
    pending = sum(1 for ch in channels if ch.get("status") in {"pending_review", "configuring"})
    state = db.get_sanction(user_id)
    return (
        "👤 <b>Panel del participante</b>\n\n"
        f"Canales: <b>{len(channels)}</b> · ✅ {approved} aprobados · 🟡 {pending} pendientes\n"
        f"Faltas: <b>{int(state.get('strikes') or 0)}/{settings.violation_limit}</b>"
        + (" · 🚫 <b>BLOQUEADO</b>" if state.get("banned") else " · 🟢 Activo")
        + "\n\nAdministra todo desde los botones inferiores."
    )


async def participant_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    data = q.data
    current_session = db.get_session(user_id)
    if data in {"user:home", "user:status"} and current_session and current_session.get("action") == "appeal_message":
        db.clear_session(user_id)

    if data == "user:noop":
        return
    if data == "user:home":
        await q.edit_message_text(participant_home_text(user_id), parse_mode="HTML", reply_markup=participant_home_keyboard(is_admin(user_id)))
        return
    if data == "user:channels":
        rows = db.channels_for_owner(user_id)
        approved = sum(1 for ch in rows if ch.get("status") == "approved")
        pending = sum(1 for ch in rows if ch.get("status") in {"pending_review", "configuring"})
        await q.edit_message_text(
            f"📡 <b>Mis canales</b>\n\nTotal: <b>{len(rows)}</b> · ✅ {approved} aprobados · 🟡 {pending} pendientes",
            parse_mode="HTML", reply_markup=participant_channels_keyboard(rows),
        )
        return
    if data.startswith("user:channel:"):
        chat_id = int(data.split(":", 2)[2])
        ch = db.get_channel(chat_id)
        if not ch or ch.get("owner_user_id") != user_id:
            await q.answer("Ese canal no te pertenece.", show_alert=True)
            return
        try:
            count = int(await context.bot.get_chat_member_count(chat_id))
            db.set_channel_fields(chat_id, member_count=count)
            ch = db.get_channel(chat_id) or ch
        except TelegramError:
            count = int(ch.get("member_count") or 0)
        nxt = _next_start_for_category(ch.get("category") or "") if ch.get("status") == "approved" else None
        next_text = nxt.strftime("%d/%m/%Y %H:%M") if nxt else "No programada / no elegible"
        text = (
            f"📡 <b>{html.escape(ch.get('telegram_title') or str(chat_id))}</b>\n\n"
            f"👥 Suscriptores: <b>{count:,}</b>\n"
            f"📊 Categoría: <b>{html.escape(ch.get('category') or '—')}</b>\n"
            + (f"🔄 Próxima categoría: <b>{html.escape(ch.get('pending_category'))}</b>\n" if ch.get("pending_category") else "")
            + f"Estado: <b>{html.escape(ch.get('status') or '—')}</b>\n"
            f"🔘 Botón: <b>{html.escape(ch.get('button_title') or '—')}</b>\n"
            f"🎨 Color: <b>{html.escape(ch.get('button_style') or 'default')}</b>\n"
            f"🔗 Ingreso: <b>{html.escape(invite_mode_label(ch.get('invite_type')))}</b>\n"
            f"🕐 Próxima botonera: <b>{html.escape(next_text)}</b>"
        )
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=participant_channel_keyboard(chat_id, ch.get("status") or ""))
        return
    if data == "user:stats":
        summary = db.owner_stats_summary(user_id, 30)
        channels = db.channels_for_owner(user_id)
        total = int(summary.get("total_delta") or 0)
        avg = float(summary.get("avg_delta") or 0)
        best = int(summary.get("best_delta") or 0)
        worst = int(summary.get("worst_delta") or 0)
        text = (
            "📊 <b>Mis estadísticas · últimos 30 días</b>\n\n"
            f"📣 Participaciones: <b>{int(summary.get('participations') or 0)}</b>\n"
            f"📈 Crecimiento neto registrado: <b>{total:+,}</b>\n"
            f"Promedio por botonera: <b>{avg:+.1f}</b>\n"
            f"🏆 Mejor resultado: <b>{best:+,}</b>\n"
            f"📉 Peor resultado: <b>{worst:+,}</b>\n\n"
            "Selecciona un canal para consultar el historial."
        )
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=participant_stats_channels_keyboard(channels))
        return
    if data.startswith("user:statsch:"):
        _, _, raw_chat, raw_page = data.split(":", 3)
        chat_id, page = int(raw_chat), max(0, int(raw_page))
        ch = db.get_channel(chat_id)
        if not ch or ch.get("owner_user_id") != user_id:
            return
        per_page = 5
        total = db.channel_stats_count(user_id, chat_id)
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, pages - 1)
        rows = db.channel_stats_history(user_id, chat_id, per_page, page * per_page)
        lines = [f"📊 <b>{html.escape(ch.get('telegram_title') or str(chat_id))}</b>", f"Categoría actual: <b>{html.escape(ch.get('category') or '—')}</b>", ""]
        if not rows:
            lines.append("Todavía no hay participaciones finalizadas con estadísticas.")
        for row in rows:
            date = (row.get("deleted_at") or row.get("published_date") or "")[:10]
            start, end, delta = int(row.get("start_member_count") or 0), int(row.get("end_member_count") or 0), int(row.get("member_delta") or 0)
            lines.append(f"📅 {html.escape(date)} · {start:,} → {end:,} · <b>{delta:+,}</b>")
        await q.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=participant_stats_history_keyboard(chat_id, page, pages))
        return
    if data.startswith("user:progress:"):
        chat_id = int(data.split(":", 2)[2])
        ch = db.get_channel(chat_id)
        if not ch or ch.get("owner_user_id") != user_id:
            return
        try:
            count = int(await context.bot.get_chat_member_count(chat_id))
            db.set_channel_fields(chat_id, member_count=count)
        except TelegramError:
            count = int(ch.get("member_count") or 0)
        category = ch.get("category") or "BELOW_5K"
        target, next_cat, progress = _category_progress(count, category)
        if target is None:
            body = f"📈 <b>Progreso de categoría</b>\n\n{count:,} suscriptores\n\n🏆 Ya estás en <b>+50K</b>, la categoría superior actual."
        else:
            filled = int(round(progress * 10))
            bar = "█" * filled + "░" * (10 - filled)
            missing = max(0, target - count)
            body = (
                f"📈 <b>Progreso de categoría</b>\n\nCanal: <b>{html.escape(ch.get('telegram_title') or str(chat_id))}</b>\n"
                f"Categoría actual: <b>{html.escape(category)}</b>\nSuscriptores: <b>{count:,}</b>\n"
                f"Siguiente: <b>{html.escape(next_cat)}</b> al llegar a <b>{target:,}</b>\n"
                f"Te faltan: <b>{missing:,}</b>\n\n<code>{bar}</code> {progress*100:.1f}%"
            )
        await q.edit_message_text(body, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Canal", callback_data=f"user:channel:{chat_id}")]]))
        return
    if data == "user:next":
        channels = db.channels_for_owner(user_id)
        lines = ["🕐 <b>Próximas botoneras</b>", ""]
        for ch in channels:
            title = html.escape(ch.get("telegram_title") or str(ch["chat_id"]))
            if ch.get("status") != "approved" or ch.get("category") not in CATEGORIES:
                lines.append(f"• {title}: ⚠️ no participará ({html.escape(ch.get('status') or '—')})")
                continue
            active = db.active_for_category_destination(ch["category"], ch["chat_id"])
            if active:
                exp = active[0].get("expires_at") or "—"
                try:
                    exp = datetime.fromisoformat(exp).astimezone(settings.timezone).strftime("%d/%m %H:%M")
                except Exception:
                    pass
                lines.append(f"• {title}: 🟢 activa hasta <b>{html.escape(str(exp))}</b>")
                continue
            nxt = _next_start_for_category(ch["category"])
            if nxt:
                sched = db.get_schedule(ch["category"]) or {}
                lifetime = float(sched.get("lifetime_hours") or settings.default_lifetime_hours)
                shuffle = f" · 🔀 {int(sched.get('shuffle_interval_minutes') or 10)}m" if sched.get("shuffle_enabled") else ""
                lines.append(f"• {title}: <b>{nxt.strftime('%d/%m %H:%M')}</b> · {html.escape(ch['category'])} · ⌛ {lifetime:g}h{shuffle}")
            else:
                lines.append(f"• {title}: sin horario activo")
        await q.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Inicio", callback_data="user:home")]]))
        return
    if data == "user:status":
        state = db.get_sanction(user_id)
        appeals = db.appeals_for_user(user_id, 1)
        appeal_line = ""
        if appeals and appeals[0].get("status") == "pending":
            appeal_line = "\n📨 Apelación: <b>pendiente</b>"
        body = (
            "⚠️ <b>Mi estado</b>\n\n"
            f"Cuenta: <b>{'🚫 Bloqueada' if state.get('banned') else '🟢 Activa'}</b>\n"
            f"Faltas: <b>{int(state.get('strikes') or 0)}/{settings.violation_limit}</b>"
            + appeal_line
            + "\n\nLas retiradas voluntarias hechas desde el panel no generan faltas. Las alertas de seguridad no se pueden desactivar."
        )
        await q.edit_message_text(body, parse_mode="HTML", reply_markup=participant_status_keyboard(bool(state.get("strikes") or state.get("banned"))))
        return
    if data == "user:violations":
        rows = db.violations_for_user(user_id, 20)
        lines = ["📜 <b>Historial de faltas</b>", ""]
        if not rows:
            lines.append("No tienes faltas registradas.")
        for v in rows:
            lines.append(f"• {html.escape((v.get('created_at') or '')[:16])} · <b>{html.escape(v.get('violation_type') or 'incidencia')}</b> · canal <code>{v.get('chat_id') or '—'}</code>")
        await q.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Mi estado", callback_data="user:status")]]))
        return
    if data == "user:notifications":
        prefs = db.get_user_preferences(user_id)
        await q.edit_message_text("🔔 <b>Notificaciones</b>\n\nToca una opción para activarla/desactivarla. Las alertas de seguridad son obligatorias.", parse_mode="HTML", reply_markup=participant_notifications_keyboard(prefs))
        return
    if data.startswith("user:notify:"):
        key = data.split(":", 2)[2]
        prefs = db.get_user_preferences(user_id)
        try:
            db.set_user_preference(user_id, key, not bool(prefs.get(key, 1)))
        except ValueError:
            return
        prefs = db.get_user_preferences(user_id)
        await q.edit_message_text("🔔 <b>Notificaciones</b>\n\nPreferencias guardadas automáticamente.", parse_mode="HTML", reply_markup=participant_notifications_keyboard(prefs))
        return
    if data == "user:add":
        if db.is_banned(user_id) and not is_admin(user_id):
            await q.answer("Tu cuenta está bloqueada. Primero solicita una revisión.", show_alert=True)
            return
        me = await context.bot.get_me()
        body = (
            "➕ <b>Agregar canal</b>\n\n"
            "1. Pulsa <b>Agregar bot a un canal</b>.\n"
            "2. Selecciona el canal y concede los permisos solicitados.\n"
            "3. Normalmente el alta se detectará automáticamente.\n\n"
            "Si el bot <b>ya aparece como administrador</b> pero no recibiste la confirmación, "
            "pulsa <b>Ya lo agregué · Verificar manualmente</b>. El sistema consultará el canal directamente con Telegram.\n\n"
            "Permisos requeridos: publicar, editar, eliminar mensajes e invitar usuarios."
        )
        await q.edit_message_text(body, parse_mode="HTML", reply_markup=participant_add_channel_keyboard(me.username))
        return
    if data == "user:verifychannel":
        if db.is_banned(user_id) and not is_admin(user_id):
            await q.answer("Tu cuenta está bloqueada.", show_alert=True)
            return
        await send_manual_channel_verification(q.message)
        return
    if data.startswith("user:withdrawask:"):
        chat_id = int(data.split(":", 2)[2])
        ch = db.get_channel(chat_id)
        if not ch or ch.get("owner_user_id") != user_id:
            return
        await q.edit_message_text(
            f"🚪 <b>Retirar {html.escape(ch.get('telegram_title') or str(chat_id))}</b>\n\nSe quitará de futuras botoneras y de las publicaciones activas. <b>No generará una falta.</b>",
            parse_mode="HTML", reply_markup=participant_withdraw_confirm_keyboard(chat_id),
        )
        return
    if data.startswith("user:withdraw:"):
        chat_id = int(data.split(":", 2)[2])
        ch = db.get_channel(chat_id)
        if not ch or ch.get("owner_user_id") != user_id:
            return
        old_cat = ch.get("category")
        db.set_channel_fields(chat_id, status="withdrawn")
        await publisher.delete_active_posts_for_chat(context.bot, chat_id, "voluntary_withdrawal")
        if old_cat in CATEGORIES:
            await publisher.refresh_category(context.bot, old_cat)
        await q.edit_message_text(
            "✅ <b>Canal retirado voluntariamente.</b>\n\nNo se agregó ninguna falta. Puedes solicitar reactivación después.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Mis canales", callback_data="user:channels")]]),
        )
        return
    if data == "user:appeal":
        pending = [a for a in db.appeals_for_user(user_id, 5) if a.get("status") == "pending"]
        if pending:
            await q.answer("Ya tienes una apelación pendiente.", show_alert=True)
            return
        db.set_session(user_id, "appeal_message")
        await q.edit_message_text(
            "📨 <b>Solicitar revisión</b>\n\nEscribe en un solo mensaje qué ocurrió y por qué deseas que un administrador revise tus faltas o bloqueo.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancelar", callback_data="user:status")]]),
        )
        return
    if data == "user:help":
        await q.edit_message_text(
            "ℹ️ <b>Ayuda del participante</b>\n\n"
            "• Agrega el bot como administrador desde ➕ Agregar canal.\n"
            "• Si no llega la confirmación automática, usa ✅ Verificar manualmente o /verificarcanal.\n"
            "• El enlace puede ser de ingreso directo o de solicitud para aprobación.\n"
            "• Cada alta o modificación pasa por revisión.\n"
            "• Tus estadísticas comparan suscriptores al inicio y al cierre.\n"
            "• Las categorías se actualizan automáticamente.\n"
            "• Retira un canal desde el panel para hacerlo sin penalización.\n"
            "• Con 3 faltas se bloquea el alta de canales hasta revisión.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Inicio", callback_data="user:home")]]),
        )
        return


# ---------------------------------------------------------------------
# Review flow
# ---------------------------------------------------------------------
async def review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.answer("Solo administradores.", show_alert=True)
        return

    _, action, raw_id = q.data.split(":", 2)
    chat_id = int(raw_id)
    ch = db.get_channel(chat_id)
    if not ch:
        return

    if action == "recalc":
        try:
            count = await context.bot.get_chat_member_count(chat_id)
            category = category_from_members(count, settings.min_members)
            db.set_channel_fields(chat_id, member_count=count, category=category)
            await q.edit_message_text(
                "🔄 <b>Categoría recalculada</b>\n\n" + fmt_channel(db.get_channel(chat_id)),
                parse_mode="HTML",
                reply_markup=approval_keyboard(chat_id),
            )
        except TelegramError as exc:
            await q.message.reply_text(f"No pude recalcular: {exc}")
        return

    if action == "reject":
        db.set_channel_fields(chat_id, status="rejected")
        if ch.get("category") in CATEGORIES:
            await publisher.refresh_category(context.bot, ch["category"])
        await q.edit_message_text("❌ <b>Solicitud rechazada</b>\n\n" + fmt_channel(db.get_channel(chat_id)), parse_mode="HTML")
        await notify_user_pref(context.bot, ch.get("owner_user_id"), "notify_rejected", "❌ Tu canal fue rechazado por un administrador.")
        return

    if action == "approve":
        owner_id = ch.get("owner_user_id")
        if owner_id and db.is_banned(owner_id) and not is_admin(owner_id):
            await q.answer("El responsable está bloqueado.", show_alert=True)
            return
        category = ch.get("category")
        if category not in CATEGORIES:
            await q.answer("No cumple una categoría válida.", show_alert=True)
            return
        if not ch.get("button_title") or not ch.get("invite_url"):
            await q.answer("Faltan título o enlace.", show_alert=True)
            return

        permissions_ok, issues = await maintenance.inspect_channel_permissions(context.bot, ch)
        db.set_channel_permission_state(chat_id, permissions_ok, "; ".join(issues) if issues else None)
        if not permissions_ok:
            await q.answer("No se puede aprobar: faltan permisos del bot.", show_alert=True)
            await q.message.reply_html(
                "⚠️ <b>Permisos incompletos</b>\n\n" + html.escape(", ".join(issues) or "El bot no es administrador")
            )
            return

        db.set_channel_fields(chat_id, status="approved", rejection_reason=None)
        await publisher.refresh_category(context.bot, category)
        await publisher.publish_to_newly_approved_if_live(context.bot, category, chat_id)
        await publisher.refresh_category(context.bot, category)
        ch = db.get_channel(chat_id)
        await q.edit_message_text("✅ <b>Canal aprobado</b>\n\n" + fmt_channel(ch), parse_mode="HTML")
        await notify_user_pref(
            context.bot, owner_id, "notify_approved",
            "🎉 <b>Tu canal fue aprobado.</b>\nSu botón ya está en la botonera.", parse_mode="HTML"
        )


# ---------------------------------------------------------------------
# Admin visual panel
# ---------------------------------------------------------------------
def panel_summary() -> str:
    lines = [
        "🛡 <b>Panel de Botoneras</b>",
        f"Canales aprobados: <b>{len(db.approved_channels())}</b>",
        f"Pendientes: <b>{len(db.pending_channels())}</b>",
        f"Bloqueados: <b>{len(db.banned_users())}</b>",
        f"Apelaciones: <b>{len(db.pending_appeals())}</b>",
        f"Posts activos: <b>{len(db.active_board_messages())}</b>",
        f"Suspendidos por permisos: <b>{len(db.channels_by_status('permission_suspended'))}</b>",
        f"Distribución: <b>{html.escape(settings.distribute_mode)}</b>",
        "",
    ]
    for cat in CATEGORIES:
        s = db.get_schedule(cat) or {}
        when = f"{int(s.get('hour', 0)):02d}:{int(s.get('minute', 0)):02d}"
        lifetime = float(s.get("lifetime_hours") or settings.default_lifetime_hours)
        shuffle_enabled = bool(s.get("shuffle_enabled"))
        shuffle_minutes = int(s.get("shuffle_interval_minutes") or 10)
        shuffle_text = f"🔀 {shuffle_minutes}m" if shuffle_enabled else "🔀 off"
        lines.append(
            f"• {cat}: <b>{len(db.approved_channels(cat))}</b> canales · "
            f"{'🟢' if s.get('enabled') else '⚪️'} {when} · ⌛ {lifetime:g}h · {shuffle_text}"
        )
    return "\n".join(lines)


async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    await update.effective_message.reply_html(panel_summary(), reply_markup=admin_home_keyboard())


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.answer("Solo administradores.", show_alert=True)
        return

    action = q.data.split(":", 1)[1]
    if action == "home":
        await q.edit_message_text(panel_summary(), parse_mode="HTML", reply_markup=admin_home_keyboard())
    elif action == "publish":
        await q.edit_message_text("📣 <b>Publicar botonera</b>\nSelecciona una categoría:", parse_mode="HTML", reply_markup=category_keyboard("publish"))
    elif action == "templates":
        await q.edit_message_text("🖼 <b>Plantillas</b>\nSelecciona una categoría:", parse_mode="HTML", reply_markup=category_keyboard("template"))
    elif action == "schedules":
        await q.edit_message_text("⏰ <b>Horarios diarios</b>\nSelecciona una categoría:", parse_mode="HTML", reply_markup=category_keyboard("schedule"))
    elif action == "lifetimes":
        await q.edit_message_text("⌛ <b>Duración de publicaciones</b>\nSelecciona una categoría:", parse_mode="HTML", reply_markup=category_keyboard("lifetime"))
    elif action == "shuffles":
        await q.edit_message_text(
            "🔀 <b>Mezcla periódica</b>\nSelecciona una categoría. Solo se mezclan los botones de canales; los botones manuales del administrador conservan su orden:",
            parse_mode="HTML",
            reply_markup=category_keyboard("shuffle"),
        )
    elif action == "channels":
        text = "📡 <b>Canales aprobados</b>\n\n" + "\n".join(f"• {c}: <b>{len(db.approved_channels(c))}</b>" for c in CATEGORIES)
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=category_keyboard("channels"))
    elif action == "pending":
        rows = db.pending_channels()
        await q.edit_message_text(
            f"✅ <b>Pendientes de revisión: {len(rows)}</b>\n\nLos detalles se enviaron abajo.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Panel", callback_data="panel:home")]]),
        )
        for ch in rows[:30]:
            await q.message.reply_html(fmt_channel(ch), reply_markup=approval_keyboard(ch["chat_id"]))
    elif action == "buttons":
        await q.edit_message_text("🔘 <b>Administrar botones</b>\nSelecciona una categoría:", parse_mode="HTML", reply_markup=category_keyboard("buttons"))
    elif action == "sanctions":
        await show_sanctions_panel(q)
    elif action == "appeals":
        await show_appeals_panel(q)
    elif action == "system":
        latest = maintenance.latest_backup_info()
        backup_text = "ninguno" if not latest else latest["mtime"].strftime("%d/%m/%Y %H:%M")
        await q.edit_message_text(
            "🩺 <b>Sistema y mantenimiento</b>\n\n"
            f"Backup automático: <b>{'activo' if settings.backup_enabled else 'desactivado'}</b>\n"
            f"Último backup: <b>{html.escape(backup_text)}</b>\n"
            f"Canales suspendidos por permisos: <b>{len(db.channels_by_status('permission_suspended'))}</b>\n"
            f"Conflictos de propiedad registrados: <b>{len(db.recent_ownership_conflicts(1000))}</b>",
            parse_mode="HTML", reply_markup=system_admin_keyboard(),
        )


async def system_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.answer("Solo administradores.", show_alert=True)
        return
    action = q.data.split(":", 1)[1]
    if action == "health":
        report = await maintenance.health_report(context.application)
        await q.edit_message_text(format_health_report(report), parse_mode="HTML", reply_markup=system_back_keyboard())
    elif action == "backup":
        await q.edit_message_text("💾 Creando snapshot consistente de SQLite…", reply_markup=system_back_keyboard())
        result = await maintenance.create_backup("manual_panel")
        if result.get("ok"):
            await q.edit_message_text(
                "✅ <b>Backup creado</b>\n\n"
                f"Archivo: <code>{html.escape(result['path'])}</code>\n"
                f"Tamaño: <b>{int(result['size']) / 1024:.1f} KB</b>",
                parse_mode="HTML", reply_markup=system_back_keyboard(),
            )
        else:
            await q.edit_message_text(
                f"❌ <b>Error creando backup</b>\n\n<code>{html.escape(result.get('error','desconocido'))}</code>",
                parse_mode="HTML", reply_markup=system_back_keyboard(),
            )
    elif action == "permissions":
        result = await maintenance.audit_permissions(context.bot, publisher, notify=True)
        await q.edit_message_text(
            "🔐 <b>Auditoría de permisos terminada</b>\n\n"
            f"Revisados: <b>{result['checked']}</b>\n"
            f"Suspendidos ahora: <b>{result['suspended']}</b>\n"
            f"Restaurados: <b>{result['restored']}</b>\n"
            f"Fallos de refresco: <b>{result['failed']}</b>",
            parse_mode="HTML", reply_markup=system_back_keyboard(),
        )
    elif action == "conflicts":
        rows = db.recent_ownership_conflicts(20)
        lines = ["🧩 <b>Conflictos de propiedad</b>", ""]
        if not rows:
            lines.append("No hay conflictos registrados.")
        for r in rows:
            lines.append(
                f"• Canal <code>{r['chat_id']}</code> · dueño <code>{r.get('registered_owner_user_id') or '—'}</code> "
                f"← intento <code>{r.get('attempted_owner_user_id') or '—'}</code>"
            )
        lines.append("\nPara una transferencia legítima usa:\n<code>/transferircanal CHAT_ID USER_ID</code>")
        await q.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=system_back_keyboard())


def format_health_report(report: dict) -> str:
    latest = report.get("latest_backup")
    if latest:
        backup_text = f"{latest['mtime'].strftime('%d/%m/%Y %H:%M')} · {latest['size']/1024:.1f} KB"
    else:
        backup_text = "sin backups"
    uptime = report.get("uptime")
    uptime_text = str(uptime).split(".")[0] if uptime is not None else "—"
    errors = report.get("recent_errors") or []
    error_text = "ninguno" if not errors else f"{len(errors)} recientes"
    return (
        "🩺 <b>Health check</b>\n\n"
        f"Telegram: <b>{'✅ conectado' if report.get('bot_ok') else '❌ error'}</b> {html.escape(report.get('bot_name') or '')}\n"
        f"SQLite quick_check: <b>{html.escape(str(report.get('db_check')))}</b>\n"
        f"Jobs programados: <b>{len(report.get('jobs') or [])}</b>\n"
        f"Uptime: <b>{html.escape(uptime_text)}</b>\n"
        f"Canales aprobados: <b>{report.get('approved_channels',0)}</b>\n"
        f"Suspendidos por permisos: <b>{report.get('permission_suspended',0)}</b>\n"
        f"Posts activos: <b>{report.get('active_posts',0)}</b>\n"
        f"Último backup: <b>{html.escape(backup_text)}</b>\n"
        f"Errores recientes: <b>{html.escape(error_text)}</b>\n"
        f"Conflictos recientes: <b>{len(report.get('conflicts') or [])}</b>"
    )


async def admin_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    _, action, category = q.data.split(":", 2)
    category = parse_category(category)
    if not category:
        return

    if action == "publish":
        s = db.get_schedule(category) or {}
        lifetime = float(s.get("lifetime_hours") or settings.default_lifetime_hours)
        active_count = len(db.live_board_messages(category))
        await q.edit_message_text(
            f"📣 <b>{category}</b>\n\n"
            f"Destinos actuales: <b>{len(publisher.destinations(category))}</b>\n"
            f"Botones: <b>{len(db.approved_channels(category)) + len(db.manual_buttons(category))}</b>\n"
            f"Publicaciones activas: <b>{active_count}</b>\n"
            f"Duración: <b>{lifetime:g} horas</b>\n\n"
            "Puedes publicar ahora o eliminar manualmente todas las copias activas.",
            parse_mode="HTML",
            reply_markup=publish_confirm_keyboard(category, has_active=active_count > 0),
        )
    elif action == "template":
        t = db.get_template(category) or {}
        await q.edit_message_text(
            f"🖼 <b>Plantilla {category}</b>\n\n"
            f"Imagen: <b>{'✅ configurada' if t.get('photo_file_id') else '❌ faltante'}</b>\n"
            f"Texto: <b>{'✅ configurado' if t.get('text') else '⚪️ vacío'}</b>",
            parse_mode="HTML",
            reply_markup=template_actions_keyboard(category),
        )
    elif action == "schedule":
        s = db.get_schedule(category) or {}
        enabled = bool(s.get("enabled"))
        await q.edit_message_text(
            f"⏰ <b>Horario {category}</b>\n\n"
            f"Hora: <b>{int(s.get('hour', 18)):02d}:{int(s.get('minute', 0)):02d}</b>\n"
            f"Estado: <b>{'Activo' if enabled else 'Desactivado'}</b>",
            parse_mode="HTML",
            reply_markup=schedule_actions_keyboard(category, enabled),
        )
    elif action == "lifetime":
        s = db.get_schedule(category) or {}
        lifetime = float(s.get("lifetime_hours") or settings.default_lifetime_hours)
        await q.edit_message_text(
            f"⌛ <b>Duración {category}</b>\n\n"
            f"Cada publicación permanecerá <b>{lifetime:g} horas</b> antes de ser eliminada automáticamente.",
            parse_mode="HTML",
            reply_markup=lifetime_actions_keyboard(category),
        )
    elif action == "shuffle":
        s = db.get_schedule(category) or {}
        enabled = bool(s.get("shuffle_enabled"))
        minutes = int(s.get("shuffle_interval_minutes") or 10)
        active_count = len(db.live_board_messages(category))
        await q.edit_message_text(
            f"🔀 <b>Mezcla {category}</b>\n\n"
            f"Estado: <b>{'Activa' if enabled else 'Desactivada'}</b>\n"
            f"Intervalo: <b>{minutes} minutos</b>\n"
            f"Posts activos: <b>{active_count}</b>\n\n"
            "Solo cambia el orden de los botones pertenecientes a canales. Los botones agregados manualmente por un administrador mantienen su orden.",
            parse_mode="HTML",
            reply_markup=shuffle_actions_keyboard(category, enabled),
        )
    elif action == "channels":
        channels = db.approved_channels(category)
        await q.edit_message_text(
            f"📡 <b>{category}: {len(channels)} canales</b>\n\nLos detalles se muestran abajo.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Categorías", callback_data="panel:channels")]]),
        )
        for ch in channels[:40]:
            await q.message.reply_html(fmt_channel(ch), reply_markup=channel_admin_keyboard(ch["chat_id"]))
    elif action == "buttons":
        await show_buttons_category(q, category)


async def publish_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return

    _, action, category = q.data.split(":", 2)
    category = parse_category(category)
    if not category:
        return

    if action == "confirm":
        result = await publisher.publish_category(context.bot, category)
        if result.get("reason"):
            await q.message.reply_text(result["reason"])
            return
        await q.edit_message_text(
            f"✅ <b>Botonera {category} publicada.</b>\n\n"
            f"Enviadas: <b>{result['sent']}</b>\n"
            f"Fallidas: <b>{result['failed']}</b>\n"
            f"Expira: <code>{html.escape(result['expires_at'])}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Panel", callback_data="panel:home")]]),
        )
        return

    if action == "deleteask":
        active = len(db.live_board_messages(category))
        if not active:
            await q.edit_message_text(
                f"ℹ️ No hay publicaciones activas de <b>{category}</b>.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver", callback_data=f"admin:publish:{category}")]]),
            )
            return
        await q.edit_message_text(
            f"⚠️ <b>Eliminar botonera {category}</b>\n\n"
            f"Se intentarán borrar <b>{active}</b> publicaciones activas de todos los canales.\n"
            "Esta acción no elimina la plantilla ni los botones guardados; solamente las publicaciones actualmente distribuidas.\n\n"
            "¿Confirmas?",
            parse_mode="HTML",
            reply_markup=publish_delete_confirm_keyboard(category),
        )
        return

    if action == "deleteconfirm":
        result = await publisher.delete_category_everywhere(
            context.bot,
            category,
            reason="manual_admin_delete",
            attempts=3,
        )
        if result["total"] == 0:
            text = f"ℹ️ No había publicaciones activas de <b>{category}</b>."
        elif result["failed"] == 0:
            text = (
                f"🗑 <b>Botonera {category} eliminada.</b>\n\n"
                f"Telegram confirmó la eliminación (o ausencia previa) de las <b>{result['total']}</b> copias activas.\n"
                "Los registros quedaron cerrados y ya no serán auditados ni refrescados."
            )
        else:
            failed_chats = sorted({str(r['destination_chat_id']) for r in result['remaining']})
            preview = ", ".join(failed_chats[:12])
            more = "…" if len(failed_chats) > 12 else ""
            text = (
                f"⚠️ <b>Eliminación incompleta de {category}</b>\n\n"
                f"Copias iniciales: <b>{result['total']}</b>\n"
                f"Eliminadas/ya ausentes: <b>{result['deleted']}</b>\n"
                f"Aún pendientes: <b>{result['failed']}</b>\n\n"
                f"Chats pendientes: <code>{html.escape(preview + more)}</code>\n\n"
                "Esos registros permanecen activos para que puedas reintentar; normalmente indica falta de permisos o un error temporal de Telegram."
            )
        await q.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Publicaciones", callback_data="panel:publish")]]),
        )


async def template_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    _, action, category = q.data.split(":", 2)
    category = parse_category(category)
    if not category:
        return

    if action == "photo":
        db.set_session(q.from_user.id, "template_wait_photo", category=category)
        await q.message.reply_html(
            f"🖼 Envíame la <b>foto</b> de la plantilla <b>{category}</b>.\n"
            "Puedes incluir el texto como caption; conservaré el formato compatible de Telegram."
        )
    elif action == "text":
        db.set_session(q.from_user.id, "template_wait_text", category=category)
        await q.message.reply_html(f"📝 Envíame el nuevo texto para <b>{category}</b>.")
    elif action == "preview":
        await send_preview(context.bot, q.message.chat_id, category)


async def schedule_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    _, action, category = q.data.split(":", 2)
    category = parse_category(category)
    if not category:
        return

    s = db.get_schedule(category) or {}
    if action == "set":
        db.set_session(q.from_user.id, "admin_schedule_input", category=category)
        await q.message.reply_html(f"🕐 Envíame la hora para <b>{category}</b> en formato <code>HH:MM</code>.")
    elif action == "toggle":
        enabled = not bool(s.get("enabled"))
        db.set_schedule(category, int(s.get("hour", 18)), int(s.get("minute", 0)), enabled)
        if enabled:
            install_or_replace_job(context.application, category, int(s.get("hour", 18)), int(s.get("minute", 0)))
        else:
            remove_schedule_job(context.application, category)
        s = db.get_schedule(category)
        await q.edit_message_text(
            f"⏰ <b>Horario {category}</b>\n\n"
            f"Hora: <b>{s['hour']:02d}:{s['minute']:02d}</b>\n"
            f"Estado: <b>{'Activo' if s['enabled'] else 'Desactivado'}</b>",
            parse_mode="HTML",
            reply_markup=schedule_actions_keyboard(category, bool(s["enabled"])),
        )


async def lifetime_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    _, action, category = q.data.split(":", 2)
    if action != "set" or not parse_category(category):
        return
    db.set_session(q.from_user.id, "admin_lifetime_input", category=category)
    await q.message.reply_html(
        f"⌛ Envíame cuántas horas debe permanecer publicada <b>{category}</b>.\n"
        "Rango permitido: <code>0.25</code> a <code>47</code> horas. Ejemplos: <code>2</code>, <code>6</code>, <code>12.5</code>."
    )


async def shuffle_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return

    _, action, category = q.data.split(":", 2)
    category = parse_category(category)
    if not category:
        return

    schedule = db.get_schedule(category) or {}
    enabled = bool(schedule.get("shuffle_enabled"))
    minutes = int(schedule.get("shuffle_interval_minutes") or 10)

    if action == "set":
        db.set_session(q.from_user.id, "admin_shuffle_input", category=category)
        await q.message.reply_html(
            f"⏱ Envíame cada cuántos minutos quieres mezclar <b>{category}</b>.\n"
            "Mínimo recomendado/permitido: <code>5</code> minutos. Ejemplos: <code>5</code>, <code>10</code>, <code>30</code>."
        )
        return

    if action == "toggle":
        enabled = not enabled
        db.set_shuffle(category, enabled, minutes)
        if enabled:
            install_or_replace_shuffle_job(context.application, category, minutes)
        else:
            remove_shuffle_job(context.application, category)
        schedule = db.get_schedule(category) or {}
        await q.edit_message_text(
            f"🔀 <b>Mezcla {category}</b>\n\n"
            f"Estado: <b>{'Activa' if schedule.get('shuffle_enabled') else 'Desactivada'}</b>\n"
            f"Intervalo: <b>{int(schedule.get('shuffle_interval_minutes') or 10)} minutos</b>\n\n"
            "Solo se mezclan botones de canales. Los botones manuales mantienen su orden.",
            parse_mode="HTML",
            reply_markup=shuffle_actions_keyboard(category, bool(schedule.get("shuffle_enabled"))),
        )
        return

    if action == "now":
        result = await publisher.shuffle_category(context.bot, category)
        await q.message.reply_html(
            f"🔀 <b>{category}</b>: {result['edited']} publicaciones mezcladas, "
            f"{result['failed']} fallidas, {result['missing']} ausentes."
        )


async def channel_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    _, action, raw_id = q.data.split(":", 2)
    chat_id = int(raw_id)
    ch = db.get_channel(chat_id)
    if not ch:
        return

    if action == "suspend":
        db.set_channel_fields(chat_id, status="suspended")
        await publisher.delete_active_posts_for_chat(context.bot, chat_id, "admin_suspended")
        if ch.get("category") in CATEGORIES:
            await publisher.refresh_category(context.bot, ch["category"])
        await q.edit_message_text("🚫 <b>Canal suspendido.</b>\n\n" + fmt_channel(db.get_channel(chat_id)), parse_mode="HTML")
    elif action == "recalc":
        try:
            count = await context.bot.get_chat_member_count(chat_id)
            category = category_from_members(count, settings.min_members)
            old = ch.get("category")
            db.set_channel_fields(chat_id, member_count=count, category=category)
            if old in CATEGORIES:
                await publisher.refresh_category(context.bot, old)
            if category in CATEGORIES:
                await publisher.refresh_category(context.bot, category)
            await q.edit_message_text("🔄 <b>Canal actualizado.</b>\n\n" + fmt_channel(db.get_channel(chat_id)), parse_mode="HTML", reply_markup=channel_admin_keyboard(chat_id))
        except TelegramError as exc:
            await q.message.reply_text(f"No pude recalcular: {exc}")


async def show_buttons_category(q, category: str):
    manual = db.manual_buttons(category)
    channels = db.approved_channels(category)
    rows = [[InlineKeyboardButton("➕ Agregar botón manual", callback_data=f"manual_panel:add:{category}", style="success")]]
    for b in manual[:25]:
        rows.append([
            InlineKeyboardButton(f"✏️ #{b['id']}", callback_data=f"manual_panel:edit:{b['id']}"),
            InlineKeyboardButton(f"🗑 #{b['id']}", callback_data=f"manual_panel:delete:{b['id']}", style="danger"),
        ])
    rows.append([InlineKeyboardButton("⬅️ Categorías", callback_data="panel:buttons")])
    text = (
        f"🔘 <b>Botones {category}</b>\n\n"
        f"Canales aprobados: <b>{len(channels)}</b>\n"
        f"Botones manuales: <b>{len(manual)}</b>"
    )
    if manual:
        text += "\n\n" + "\n".join(
            f"• <code>#{b['id']}</code> {html.escape(b['title'])} · {html.escape(b['style'])}" for b in manual[:25]
        )
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))


async def manual_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    _, action, value = q.data.split(":", 2)
    if action == "add":
        category = parse_category(value)
        if not category:
            return
        db.set_session(q.from_user.id, "manual_title", category=category)
        await q.message.reply_html(f"➕ Nuevo botón para <b>{category}</b>. Envíame el título.")
    elif action == "edit":
        button_id = int(value)
        b = db.get_manual_button(button_id)
        if not b:
            await q.answer("Ya no existe.", show_alert=True)
            return
        db.set_session(q.from_user.id, "manual_edit_title", category=b["category"], payload={"button_id": button_id})
        await q.message.reply_html(f"✏️ Editando <code>#{button_id}</code>. Envíame el nuevo título.")
    elif action == "delete":
        button_id = int(value)
        b = db.get_manual_button(button_id)
        if not b:
            await q.answer("Ya no existe.", show_alert=True)
            return
        category = b["category"]
        db.delete_manual_button(button_id)
        await publisher.refresh_category(context.bot, category)
        await q.message.reply_html(f"🗑 Botón <code>#{button_id}</code> eliminado y publicaciones refrescadas.")
        await show_buttons_category(q, category)


def manual_color_keyboard(category: str, mode: str) -> InlineKeyboardMarkup:
    prefix = "manual_add_color" if mode == "add" else "manual_edit_color"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Predeterminado", callback_data=f"{prefix}:default:{category}")],
        [
            InlineKeyboardButton("Azul", callback_data=f"{prefix}:primary:{category}", style="primary"),
            InlineKeyboardButton("Verde", callback_data=f"{prefix}:success:{category}", style="success"),
            InlineKeyboardButton("Rojo", callback_data=f"{prefix}:danger:{category}", style="danger"),
        ],
    ])


async def manual_color_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    prefix, style, category = q.data.split(":", 2)
    session = db.get_session(q.from_user.id)
    if not session or style not in BUTTON_STYLES:
        return
    payload = session.get("payload", {})
    if prefix == "manual_add_color" and session["action"] == "manual_color":
        button_id = db.add_manual_button(category, payload["title"], payload["url"], style)
        db.clear_session(q.from_user.id)
        await publisher.refresh_category(context.bot, category)
        await q.message.reply_html(f"✅ Botón manual <code>#{button_id}</code> agregado y publicaciones refrescadas.")
    elif prefix == "manual_edit_color" and session["action"] == "manual_edit_color":
        button_id = int(payload["button_id"])
        db.update_manual_button(button_id, title=payload["title"], url=payload["url"], style=style)
        db.clear_session(q.from_user.id)
        await publisher.refresh_category(context.bot, category)
        await q.message.reply_html(f"✅ Botón <code>#{button_id}</code> actualizado y publicaciones refrescadas.")


async def show_sanctions_panel(q):
    banned = db.banned_users()
    violations = db.recent_violations(10)
    text = [
        "🚫 <b>Sanciones</b>",
        f"Usuarios bloqueados: <b>{len(banned)}</b>",
        f"Límite automático: <b>{settings.violation_limit} faltas</b>",
        "",
    ]
    if violations:
        text.append("<b>Últimas incidencias</b>")
        for v in violations:
            state = db.get_sanction(v["user_id"])
            text.append(
                f"• <code>{v['user_id']}</code> · {html.escape(v['violation_type'])} · "
                f"{state['strikes']}/{settings.violation_limit}"
            )
    else:
        text.append("Sin incidencias registradas.")

    rows = []
    for state in banned[:20]:
        rows.append([InlineKeyboardButton(
            f"✅ Desbanear {state['user_id']}",
            callback_data=f"sanction:reset:{state['user_id']}",
            style="success",
        )])
    rows.append([InlineKeyboardButton("⬅️ Panel", callback_data="panel:home")])
    await q.edit_message_text("\n".join(text), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))


async def sanction_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    _, action, raw_id = q.data.split(":", 2)
    user_id = int(raw_id)
    if action == "reset":
        db.reset_sanctions(user_id)
        for ch in db.channels_for_owner(user_id):
            if ch.get("status") == "banned":
                db.set_channel_fields(ch["chat_id"], status="inactive")
        await q.message.reply_html(f"✅ Sanciones de <code>{user_id}</code> reiniciadas. Podrá volver a registrar canales.")
        await show_sanctions_panel(q)


async def show_appeals_panel(q):
    appeals = db.pending_appeals()
    await q.edit_message_text(
        f"📨 <b>Apelaciones pendientes: {len(appeals)}</b>\n\n"
        "Cada solicitud puede quitar una falta, reiniciar todas las sanciones o rechazarse.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Panel", callback_data="panel:home")]]),
    )
    for appeal in appeals[:30]:
        state = db.get_sanction(appeal["user_id"])
        text = (
            f"📨 <b>Apelación #{appeal['id']}</b>\n"
            f"Usuario: <code>{appeal['user_id']}</code>\n"
            f"Faltas: <b>{state['strikes']}/{settings.violation_limit}</b> · "
            f"{'🚫 bloqueado' if state.get('banned') else 'activo'}\n\n"
            f"{html.escape(appeal.get('message') or '')}"
        )
        await q.message.reply_html(text, reply_markup=appeal_admin_keyboard(int(appeal["id"])))


async def appeal_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    _, action, raw_id = q.data.split(":", 2)
    appeal_id = int(raw_id)
    appeal = db.get_appeal(appeal_id)
    if not appeal or appeal.get("status") != "pending":
        await q.answer("Esta apelación ya fue resuelta.", show_alert=True)
        return
    user_id = int(appeal["user_id"])
    if action == "one":
        state = db.remove_one_strike(user_id)
        for ch in db.channels_for_owner(user_id):
            if ch.get("status") == "banned":
                db.set_channel_fields(ch["chat_id"], status="inactive")
        db.resolve_appeal(appeal_id, "approved", q.from_user.id, "Se retiró una falta")
        await safe_dm(context.bot, user_id, f"✅ Tu apelación fue aceptada. Se retiró una falta. Ahora tienes {state['strikes']}/{settings.violation_limit}.")
        await q.edit_message_text(f"✅ Apelación #{appeal_id} aprobada: se retiró una falta.")
    elif action == "reset":
        db.reset_sanctions(user_id)
        for ch in db.channels_for_owner(user_id):
            if ch.get("status") == "banned":
                db.set_channel_fields(ch["chat_id"], status="inactive")
        db.resolve_appeal(appeal_id, "approved", q.from_user.id, "Sanciones reiniciadas")
        await safe_dm(context.bot, user_id, "🔓 Tu apelación fue aceptada. Tus faltas fueron reiniciadas y puedes solicitar la reactivación de tus canales.")
        await q.edit_message_text(f"🔓 Apelación #{appeal_id} aprobada: sanciones reiniciadas.")
    elif action == "reject":
        db.resolve_appeal(appeal_id, "rejected", q.from_user.id, "Rechazada por administrador")
        await safe_dm(context.bot, user_id, "❌ Tu solicitud de revisión fue rechazada por un administrador.")
        await q.edit_message_text(f"❌ Apelación #{appeal_id} rechazada.")


# ---------------------------------------------------------------------
# Text/photo input sessions
# ---------------------------------------------------------------------
async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg or not msg.text:
        return
    session = db.get_session(user.id)
    if not session:
        return

    action = session["action"]
    chat_id = session.get("chat_id")
    category = session.get("category")
    payload = session.get("payload", {})

    if action in {"channel_title", "channel_title_edit"}:
        if await deny_if_banned(user.id, msg):
            db.clear_session(user.id)
            return
        title = msg.text.strip()
        if not 1 <= len(title) <= 64:
            await msg.reply_text("El título debe tener entre 1 y 64 caracteres.")
            return
        ch = db.get_channel(chat_id)
        if not ch or (ch.get("owner_user_id") != user.id and not is_admin(user.id)):
            db.clear_session(user.id)
            return
        db.set_channel_fields(chat_id, button_title=title, status="configuring")
        db.clear_session(user.id)
        if action == "channel_title_edit":
            await submit_channel_review(context.bot, chat_id)
            await msg.reply_html("✅ Nuevo título enviado a revisión. Mientras se revisa, el canal queda fuera de la botonera activa.")
        else:
            await msg.reply_html("🎨 Elige el color del botón:", reply_markup=color_keyboard(chat_id))
        return

    if action == "appeal_message":
        message = msg.text.strip()
        if not 10 <= len(message) <= 1500:
            await msg.reply_text("Describe lo ocurrido con entre 10 y 1500 caracteres.")
            return
        appeal_id = db.create_appeal(user.id, message)
        db.clear_session(user.id)
        await msg.reply_html(f"📨 <b>Apelación #{appeal_id} enviada.</b>\n\nUn administrador podrá revisarla desde su panel.")
        state = db.get_sanction(user.id)
        for admin_id in settings.admin_ids:
            await safe_dm(
                context.bot, admin_id,
                f"📨 <b>Nueva apelación #{appeal_id}</b>\nUsuario: <code>{user.id}</code>\nFaltas: <b>{state['strikes']}/{settings.violation_limit}</b>\n\n{html.escape(message)}",
                parse_mode="HTML", reply_markup=appeal_admin_keyboard(appeal_id),
            )
        return

    if not is_admin(user.id):
        return

    if action == "template_wait_text":
        if category not in CATEGORIES:
            db.clear_session(user.id)
            return
        # text_html conserva negritas, enlaces y entidades admitidas por Telegram.
        db.set_template_text(category, msg.text_html)
        db.clear_session(user.id)
        result = await publisher.refresh_content(context.bot, category)
        await msg.reply_html(
            f"✅ Texto de <b>{category}</b> guardado. Posts activos actualizados: <b>{result['edited']}</b>."
        )
    elif action == "admin_schedule_input":
        try:
            hour, minute = map(int, msg.text.strip().split(":", 1))
            if category not in CATEGORIES or not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            await msg.reply_text("Hora inválida. Usa HH:MM, por ejemplo 18:30.")
            return
        db.set_schedule(category, hour, minute, True)
        install_or_replace_job(context.application, category, hour, minute)
        db.clear_session(user.id)
        await msg.reply_html(f"✅ <b>{category}</b> se publicará diariamente a las <b>{hour:02d}:{minute:02d}</b>.")
    elif action == "admin_lifetime_input":
        try:
            hours = float(msg.text.strip().replace(",", "."))
            if category not in CATEGORIES or not 0.25 <= hours <= 47:
                raise ValueError
        except ValueError:
            await msg.reply_text("Duración inválida. Debe ser entre 0.25 y 47 horas.")
            return
        db.set_lifetime(category, hours)
        db.clear_session(user.id)
        await msg.reply_html(f"✅ Las nuevas publicaciones de <b>{category}</b> durarán <b>{hours:g} horas</b>.")
    elif action == "admin_shuffle_input":
        try:
            minutes = int(msg.text.strip())
            if category not in CATEGORIES or not 5 <= minutes <= 1440:
                raise ValueError
        except ValueError:
            await msg.reply_text("Intervalo inválido. Usa un número entero entre 5 y 1440 minutos.")
            return
        db.set_shuffle(category, True, minutes)
        install_or_replace_shuffle_job(context.application, category, minutes)
        db.clear_session(user.id)
        await msg.reply_html(
            f"✅ La mezcla de <b>{category}</b> quedó activa cada <b>{minutes} minutos</b>. "
            "Solo cambiará el orden de los botones de canales."
        )
    elif action == "manual_title":
        payload["title"] = msg.text.strip()
        db.set_session(user.id, "manual_url", category=category, payload=payload)
        await msg.reply_text("Ahora envíame la URL del botón.")
    elif action == "manual_url":
        url = msg.text.strip()
        if not (url.startswith("https://") or url.startswith("http://") or url.startswith("tg://")):
            await msg.reply_text("URL inválida. Debe iniciar con https://, http:// o tg://")
            return
        payload["url"] = url
        db.set_session(user.id, "manual_color", category=category, payload=payload)
        await msg.reply_text("Elige el color:", reply_markup=manual_color_keyboard(category, "add"))
    elif action == "manual_edit_title":
        payload["title"] = msg.text.strip()
        db.set_session(user.id, "manual_edit_url", category=category, payload=payload)
        await msg.reply_text("Ahora envíame la nueva URL.")
    elif action == "manual_edit_url":
        url = msg.text.strip()
        if not (url.startswith("https://") or url.startswith("http://") or url.startswith("tg://")):
            await msg.reply_text("URL inválida.")
            return
        payload["url"] = url
        db.set_session(user.id, "manual_edit_color", category=category, payload=payload)
        await msg.reply_text("Elige el nuevo color:", reply_markup=manual_color_keyboard(category, "edit"))


async def photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg or not msg.photo or not is_admin(user.id):
        return
    session = db.get_session(user.id)
    if not session or session["action"] != "template_wait_photo":
        return
    category = session.get("category")
    if category not in CATEGORIES:
        db.clear_session(user.id)
        return

    db.set_template_photo(category, msg.photo[-1].file_id)
    if msg.caption is not None:
        db.set_template_text(category, msg.caption_html)
    db.clear_session(user.id)
    result = await publisher.refresh_content(context.bot, category)
    await msg.reply_html(
        f"✅ Plantilla <b>{category}</b> guardada. Posts activos actualizados: <b>{result['edited']}</b>."
    )


# ---------------------------------------------------------------------
# Command compatibility
# ---------------------------------------------------------------------
async def send_preview(bot, chat_id: int, category: str):
    template = db.get_template(category)
    if not template or not template.get("photo_file_id"):
        await bot.send_message(chat_id, "La plantilla todavía no tiene imagen.")
        return
    await bot.send_photo(
        chat_id=chat_id,
        photo=template["photo_file_id"],
        caption=template.get("text") or None,
        parse_mode="HTML",
        reply_markup=publisher.build_markup(category),
    )


async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    rows = db.pending_channels()
    if not rows:
        await update.effective_message.reply_text("No hay solicitudes pendientes.")
        return
    for ch in rows:
        await update.effective_message.reply_html("🛡 <b>Pendiente</b>\n\n" + fmt_channel(ch), reply_markup=approval_keyboard(ch["chat_id"]))


async def template_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    cat = parse_category(context.args[0] if context.args else None)
    if not cat:
        await update.effective_message.reply_text("Uso: /plantilla 5K")
        return
    db.set_session(update.effective_user.id, "template_wait_photo", category=cat)
    await update.effective_message.reply_html(f"📸 Envíame la foto de <b>{cat}</b>. Si agregas caption, también se guardará.")


async def text_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if len(context.args) < 2:
        await update.effective_message.reply_text("Uso: /texto 5K Texto...")
        return
    cat = parse_category(context.args[0])
    if not cat:
        return
    text = update.effective_message.text.split(maxsplit=2)[2]
    db.set_template_text(cat, html.escape(text))
    result = await publisher.refresh_content(context.bot, cat)
    await update.effective_message.reply_html(f"✅ Texto de <b>{cat}</b> actualizado. Posts activos: {result['edited']}.")


async def preview_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    cat = parse_category(context.args[0] if context.args else None)
    if not cat:
        await update.effective_message.reply_text("Uso: /preview 5K")
        return
    await send_preview(context.bot, update.effective_chat.id, cat)


async def publish_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    cat = parse_category(context.args[0] if context.args else None)
    if not cat:
        await update.effective_message.reply_text("Uso: /publicar 5K")
        return
    result = await publisher.publish_category(context.bot, cat)
    await update.effective_message.reply_text(result.get("reason") or f"{cat}: {result['sent']} enviadas, {result['failed']} fallidas. Expira {result['expires_at']}")


async def delete_publication_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    cat = parse_category(context.args[0] if context.args else None)
    if not cat:
        await update.effective_message.reply_text("Uso: /eliminarpublicacion 5K")
        return

    result = await publisher.delete_category_everywhere(
        context.bot,
        cat,
        reason="manual_admin_delete",
        attempts=3,
    )
    if result["total"] == 0:
        await update.effective_message.reply_text(f"No hay publicaciones activas de {cat}.")
    elif result["failed"] == 0:
        await update.effective_message.reply_text(
            f"🗑 {cat}: las {result['total']} publicaciones activas fueron eliminadas o ya no existían."
        )
    else:
        chats = sorted({str(r['destination_chat_id']) for r in result['remaining']})
        await update.effective_message.reply_text(
            f"⚠️ {cat}: {result['deleted']} eliminadas y {result['failed']} pendientes. "
            f"Chats pendientes: {', '.join(chats[:12])}"
        )


async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    cat = parse_category(context.args[0] if context.args else None)
    if not cat:
        await update.effective_message.reply_text("Uso: /refrescar 5K")
        return
    result = await publisher.refresh_category(context.bot, cat)
    await update.effective_message.reply_text(f"{cat}: {result['edited']} actualizadas, {result['failed']} fallidas, {result['missing']} ausentes.")


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Uso: /programar 5K 18:30")
        return
    cat = parse_category(context.args[0])
    try:
        hour, minute = map(int, context.args[1].split(":", 1))
        if not cat or not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("Categoría u hora inválida.")
        return
    db.set_schedule(cat, hour, minute, True)
    install_or_replace_job(context.application, cat, hour, minute)
    await update.effective_message.reply_text(f"⏰ {cat}: diario a las {hour:02d}:{minute:02d} ({settings.timezone_name}).")


async def unschedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    cat = parse_category(context.args[0] if context.args else None)
    if not cat:
        return
    s = db.get_schedule(cat)
    if s:
        db.set_schedule(cat, s["hour"], s["minute"], False)
    remove_schedule_job(context.application, cat)
    await update.effective_message.reply_text(f"⏹ {cat} desprogramada.")


async def duration_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Uso: /duracion 5K 6")
        return
    cat = parse_category(context.args[0])
    try:
        hours = float(context.args[1].replace(",", "."))
        if not cat or not 0.25 <= hours <= 47:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("Duración inválida: usa 0.25 a 47 horas.")
        return
    db.set_lifetime(cat, hours)
    await update.effective_message.reply_html(f"⌛ <b>{cat}</b>: las nuevas publicaciones durarán <b>{hours:g} horas</b>.")


async def shuffle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Uso: /mezcla 5K 10")
        return
    cat = parse_category(context.args[0])
    try:
        minutes = int(context.args[1])
        if not cat or not 5 <= minutes <= 1440:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("Intervalo inválido: usa 5 a 1440 minutos.")
        return
    db.set_shuffle(cat, True, minutes)
    install_or_replace_shuffle_job(context.application, cat, minutes)
    await update.effective_message.reply_html(
        f"🔀 <b>{cat}</b>: mezcla activa cada <b>{minutes} minutos</b>. "
        "Los botones manuales no se mezclan."
    )


async def no_shuffle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    cat = parse_category(context.args[0] if context.args else None)
    if not cat:
        await update.effective_message.reply_text("Uso: /nomezcla 5K")
        return
    schedule = db.get_schedule(cat) or {}
    db.set_shuffle(cat, False, int(schedule.get("shuffle_interval_minutes") or 10))
    remove_shuffle_job(context.application, cat)
    await update.effective_message.reply_html(f"⏹ Mezcla de <b>{cat}</b> desactivada.")


async def violations_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    violations = db.recent_violations(30)
    if not violations:
        await update.effective_message.reply_text("No hay faltas registradas.")
        return
    lines = ["🚫 <b>Últimas faltas</b>", ""]
    for v in violations:
        state = db.get_sanction(v["user_id"])
        lines.append(f"• <code>{v['user_id']}</code> · {html.escape(v['violation_type'])} · {state['strikes']}/{settings.violation_limit}")
    await update.effective_message.reply_html("\n".join(lines))


async def reset_violations_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    try:
        user_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Uso: /resetfaltas USER_ID")
        return
    db.reset_sanctions(user_id)
    for ch in db.channels_for_owner(user_id):
        if ch.get("status") == "banned":
            db.set_channel_fields(ch["chat_id"], status="inactive")
    await update.effective_message.reply_text(f"Sanciones de {user_id} reiniciadas.")


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    report = await maintenance.health_report(context.application)
    await update.effective_message.reply_html(format_health_report(report), reply_markup=system_back_keyboard())


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    result = await maintenance.create_backup("manual_command")
    if result.get("ok"):
        await update.effective_message.reply_html(
            f"✅ Backup creado: <code>{html.escape(result['path'])}</code> · {result['size']/1024:.1f} KB"
        )
    else:
        await update.effective_message.reply_html(
            f"❌ Error de backup: <code>{html.escape(result.get('error','desconocido'))}</code>"
        )


async def permission_audit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    result = await maintenance.audit_permissions(context.bot, publisher, notify=True)
    await update.effective_message.reply_html(
        f"🔐 Auditoría terminada: <b>{result['checked']}</b> revisados · "
        f"<b>{result['suspended']}</b> suspendidos · <b>{result['restored']}</b> restaurados."
    )


async def transfer_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Uso: /transferircanal CHAT_ID USER_ID")
        return
    try:
        chat_id = int(context.args[0]); new_owner = int(context.args[1])
    except ValueError:
        await update.effective_message.reply_text("CHAT_ID y USER_ID deben ser numéricos.")
        return
    ch = db.get_channel(chat_id)
    if not ch:
        await update.effective_message.reply_text("Ese canal no está registrado.")
        return
    if not db.get_user(new_owner):
        await update.effective_message.reply_text("El nuevo propietario debe ejecutar /start primero.")
        return
    old_owner = ch.get("owner_user_id")
    db.transfer_channel_owner(chat_id, new_owner)
    if ch.get("category") in CATEGORIES:
        await publisher.refresh_category(context.bot, ch["category"])
    db.log_system_event("ownership_transfer", f"chat={chat_id}; {old_owner} -> {new_owner}; admin={update.effective_user.id}")
    await safe_dm(context.bot, new_owner, "🔐 Un administrador te transfirió un canal. La configuración quedó pendiente de revisión.")
    if old_owner and old_owner != new_owner:
        await safe_dm(context.bot, old_owner, f"ℹ️ El canal <code>{chat_id}</code> fue transferido administrativamente a otro responsable.", parse_mode="HTML")
    await update.effective_message.reply_html(
        f"✅ Canal <code>{chat_id}</code> transferido de <code>{old_owner or '—'}</code> a <code>{new_owner}</code>. Estado: pendiente de revisión."
    )


# ---------------------------------------------------------------------
# Maintenance jobs
# ---------------------------------------------------------------------
async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    category = context.job.data["category"]
    result = await publisher.publish_category(context.bot, category)
    log.info("Publicación diaria %s: %s", category, result)


async def cleanup_job(context: ContextTypes.DEFAULT_TYPE):
    result = await publisher.cleanup_expired(context.bot)
    if result["deleted"]:
        log.info("Limpieza automática: %s publicaciones eliminadas", result["deleted"])


async def backup_job(context: ContextTypes.DEFAULT_TYPE):
    if not settings.backup_enabled:
        return
    result = await maintenance.create_backup("automatic_daily")
    if not result.get("ok"):
        log.error("Backup automático falló: %s", result.get("error"))


async def permission_audit_job(context: ContextTypes.DEFAULT_TYPE):
    result = await maintenance.audit_permissions(context.bot, publisher, notify=True)
    if result.get("suspended") or result.get("restored") or result.get("failed"):
        log.info("Auditoría de permisos: %s", result)


async def integrity_job(context: ContextTypes.DEFAULT_TYPE):
    # Detecta posts eliminados antes de expirar. Telegram no entrega un update normal
    # de borrado de post de canal, por eso se verifica activamente el mensaje.
    result = await moderation.audit_active_posts(context.bot)
    for incident in result.get("incidents", []):
        channel = incident.get("channel")
        if channel:
            await notify_admins_violation(
                context.bot,
                incident.get("user_id"),
                channel["chat_id"],
                "Se detectó que una publicación activa fue eliminada antes de su expiración.",
            )
    if result["missing"]:
        log.warning("Auditoría detectó %s publicaciones ausentes", result["missing"])


async def shuffle_job(context: ContextTypes.DEFAULT_TYPE):
    category = context.job.data["category"]
    result = await publisher.shuffle_category(context.bot, category)
    if result["edited"] or result["failed"] or result["missing"]:
        log.info("Mezcla %s: %s", category, result)


async def category_audit_job(context: ContextTypes.DEFAULT_TYPE):
    result = await publisher.audit_channel_categories(context.bot)
    stats_retry = await publisher.retry_pending_stats(context.bot, limit=100)

    if result.get("detected_changes") or result.get("failed"):
        log.info("Auditoría de categorías: %s", result)
    if stats_retry.get("sent") or stats_retry.get("failed"):
        log.info("Reintento de estadísticas: %s", stats_retry)


async def upcoming_board_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(settings.timezone)
    window = timedelta(minutes=settings.upcoming_notice_minutes)
    for channel in db.approved_channels():
        category = channel.get("category")
        if category not in CATEGORIES or not channel.get("owner_user_id"):
            continue
        prefs = db.get_user_preferences(int(channel["owner_user_id"]))
        if not bool(prefs.get("notify_next_board", 1)):
            continue
        nxt = _next_start_for_category(category)
        if not nxt:
            continue
        remaining = nxt - now
        if remaining.total_seconds() <= 0 or remaining > window:
            continue
        key = f"upcoming:{channel['chat_id']}:{category}:{nxt.isoformat()}"
        if db.notification_sent(key):
            continue
        schedule = db.get_schedule(category) or {}
        lifetime = float(schedule.get("lifetime_hours") or settings.default_lifetime_hours)
        shuffle = f"\n🔀 Mezcla: cada <b>{int(schedule.get('shuffle_interval_minutes') or 10)} minutos</b>" if schedule.get("shuffle_enabled") else "\n🔀 Mezcla: <b>desactivada</b>"
        sent = await notify_user_pref(
            context.bot, channel.get("owner_user_id"), "notify_next_board",
            f"⏰ <b>Próxima botonera</b>\n\n"
            f"Canal: <b>{html.escape(channel.get('telegram_title') or str(channel['chat_id']))}</b>\n"
            f"Categoría: <b>{html.escape(category)}</b>\n"
            f"Inicio: <b>{nxt.strftime('%d/%m/%Y %H:%M')}</b>\n"
            f"Duración: <b>{lifetime:g} horas</b>{shuffle}",
            parse_mode="HTML",
        )
        if sent:
            db.mark_notification_sent(key, channel.get("owner_user_id"), "next_board")


def install_or_replace_job(application: Application, category: str, hour: int, minute: int):
    remove_schedule_job(application, category)
    application.job_queue.run_daily(
        daily_job,
        time=time(hour=hour, minute=minute, tzinfo=settings.timezone),
        data={"category": category},
        name=f"board:{category}",
    )


def remove_schedule_job(application: Application, category: str):
    for job in application.job_queue.get_jobs_by_name(f"board:{category}"):
        job.schedule_removal()


def install_or_replace_shuffle_job(application: Application, category: str, interval_minutes: int):
    remove_shuffle_job(application, category)
    seconds = max(5, int(interval_minutes)) * 60
    application.job_queue.run_repeating(
        shuffle_job,
        interval=seconds,
        first=seconds,
        data={"category": category},
        name=f"shuffle:{category}",
    )


def remove_shuffle_job(application: Application, category: str):
    for job in application.job_queue.get_jobs_by_name(f"shuffle:{category}"):
        job.schedule_removal()


async def post_init(application: Application):
    for s in db.get_enabled_schedules():
        install_or_replace_job(application, s["category"], int(s["hour"]), int(s["minute"]))

    for s in db.get_shuffle_schedules():
        install_or_replace_shuffle_job(
            application,
            s["category"],
            int(s.get("shuffle_interval_minutes") or 10),
        )

    application.job_queue.run_repeating(
        cleanup_job,
        interval=settings.cleanup_check_seconds,
        first=5,
        name="maintenance:cleanup",
    )
    application.job_queue.run_repeating(
        integrity_job,
        interval=settings.integrity_check_seconds,
        first=30,
        name="maintenance:integrity",
    )
    application.job_queue.run_repeating(
        category_audit_job,
        interval=settings.category_check_seconds,
        first=60,
        name="maintenance:categories",
    )
    application.job_queue.run_repeating(
        upcoming_board_job,
        interval=60,
        first=15,
        name="maintenance:upcoming",
    )
    application.job_queue.run_repeating(
        permission_audit_job,
        interval=settings.permission_check_seconds,
        first=45,
        name="maintenance:permissions",
    )
    if settings.backup_enabled:
        application.job_queue.run_daily(
            backup_job,
            time=time(hour=settings.backup_hour, minute=settings.backup_minute, tzinfo=settings.timezone),
            name="maintenance:backup",
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        db.log_system_event("unhandled_error", str(context.error), "error")
    except Exception:
        pass
    log.exception("Error no controlado procesando update", exc_info=context.error)


def build_application() -> Application:
    app = Application.builder().token(settings.token).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler(["miscanales", "miscanais"], my_channels))
    app.add_handler(CommandHandler("verificarcanal", verify_channel_command))
    app.add_handler(CommandHandler(["miperfil", "inicio"], start))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("pendientes", pending_command))
    app.add_handler(CommandHandler("plantilla", template_command))
    app.add_handler(CommandHandler("texto", text_command))
    app.add_handler(CommandHandler("preview", preview_command))
    app.add_handler(CommandHandler("publicar", publish_command))
    app.add_handler(CommandHandler("eliminarpublicacion", delete_publication_command))
    app.add_handler(CommandHandler("refrescar", refresh_command))
    app.add_handler(CommandHandler("programar", schedule_command))
    app.add_handler(CommandHandler("desprogramar", unschedule_command))
    app.add_handler(CommandHandler("duracion", duration_command))
    app.add_handler(CommandHandler("mezcla", shuffle_command))
    app.add_handler(CommandHandler("nomezcla", no_shuffle_command))
    app.add_handler(CommandHandler("faltas", violations_command))
    app.add_handler(CommandHandler("resetfaltas", reset_violations_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("auditarpermisos", permission_audit_command))
    app.add_handler(CommandHandler("transferircanal", transfer_channel_command))

    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    app.add_handler(CallbackQueryHandler(config_link_callback, pattern=r"^cfg_link:"))
    app.add_handler(CallbackQueryHandler(config_color_callback, pattern=r"^cfg_color:"))
    app.add_handler(CallbackQueryHandler(owner_callback, pattern=r"^owner:"))
    app.add_handler(CallbackQueryHandler(participant_callback, pattern=r"^user:"))
    app.add_handler(CallbackQueryHandler(review_callback, pattern=r"^review:"))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern=r"^panel:"))
    app.add_handler(CallbackQueryHandler(system_callback, pattern=r"^system:"))
    app.add_handler(CallbackQueryHandler(admin_category_callback, pattern=r"^admin:"))
    app.add_handler(CallbackQueryHandler(publish_panel_callback, pattern=r"^publish:(confirm|deleteask|deleteconfirm):"))
    app.add_handler(CallbackQueryHandler(template_panel_callback, pattern=r"^template:"))
    app.add_handler(CallbackQueryHandler(schedule_panel_callback, pattern=r"^schedule:"))
    app.add_handler(CallbackQueryHandler(lifetime_panel_callback, pattern=r"^lifetime:"))
    app.add_handler(CallbackQueryHandler(shuffle_panel_callback, pattern=r"^shuffle:"))
    app.add_handler(CallbackQueryHandler(channel_admin_callback, pattern=r"^channel_admin:"))
    app.add_handler(CallbackQueryHandler(manual_panel_callback, pattern=r"^manual_panel:"))
    app.add_handler(CallbackQueryHandler(manual_color_callback, pattern=r"^manual_(add|edit)_color:"))
    app.add_handler(CallbackQueryHandler(sanction_callback, pattern=r"^sanction:"))
    app.add_handler(CallbackQueryHandler(appeal_admin_callback, pattern=r"^appeal:"))

    app.add_handler(MessageHandler(filters.StatusUpdate.CHAT_SHARED & filters.ChatType.PRIVATE, manual_chat_shared))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, photo_input))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, text_input))
    app.add_error_handler(error_handler)
    return app


def main():
    application = build_application()
    log.info("Botoneras iniciado. DB=%s", settings.database_path)
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
