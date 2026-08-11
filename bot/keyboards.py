from __future__ import annotations

from telegram import (
    ChatAdministratorRights,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestChat,
    ReplyKeyboardMarkup,
)

from .config import BUTTON_STYLES, CATEGORIES


def tg_style(style: str | None) -> str | None:
    if not style or style == "default" or style not in BUTTON_STYLES:
        return None
    return style


def url_button(title: str, url: str, style: str = "default") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=title, url=url, style=tg_style(style))


def rows_two(buttons: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([buttons[i:i + 2] for i in range(0, len(buttons), 2)])


def rows_one(buttons: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    """Botonera pública: exactamente un botón por fila."""
    return InlineKeyboardMarkup([[button] for button in buttons])


def link_type_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Selecciona el comportamiento del enlace, no la visibilidad del canal."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🚪 Ingreso directo",
            callback_data=f"cfg_link:direct:{chat_id}",
            style="success",
        )],
        [InlineKeyboardButton(
            "🛂 Solicitud de ingreso",
            callback_data=f"cfg_link:approval:{chat_id}",
            style="primary",
        )],
    ])


def manual_channel_verification_keyboard(request_id: int = 61001) -> ReplyKeyboardMarkup:
    """Selector nativo de Telegram para recuperar/verificar un canal manualmente.

    El selector limita la elección a canales donde el usuario tenga capacidad de
    promover administradores y solicita para el bot los permisos que necesita el
    sistema de botoneras. La verificación real se repite del lado del bot cuando
    Telegram devuelve ``chat_shared``.
    """
    user_rights = ChatAdministratorRights(
        is_anonymous=False,
        can_manage_chat=True,
        can_delete_messages=True,
        can_manage_video_chats=False,
        can_restrict_members=False,
        can_promote_members=True,
        can_change_info=False,
        can_invite_users=True,
        can_post_stories=False,
        can_edit_stories=False,
        can_delete_stories=False,
        can_post_messages=True,
        can_edit_messages=True,
        can_pin_messages=False,
        can_manage_topics=False,
        can_manage_direct_messages=False,
        can_manage_tags=False,
    )
    bot_rights = ChatAdministratorRights(
        is_anonymous=False,
        can_manage_chat=True,
        can_delete_messages=True,
        can_manage_video_chats=False,
        can_restrict_members=False,
        can_promote_members=False,
        can_change_info=False,
        can_invite_users=True,
        can_post_stories=False,
        can_edit_stories=False,
        can_delete_stories=False,
        can_post_messages=True,
        can_edit_messages=True,
        can_pin_messages=False,
        can_manage_topics=False,
        can_manage_direct_messages=False,
        can_manage_tags=False,
    )
    request = KeyboardButtonRequestChat(
        request_id=request_id,
        chat_is_channel=True,
        user_administrator_rights=user_rights,
        bot_administrator_rights=bot_rights,
        bot_is_member=True,
        request_title=True,
        request_username=True,
    )
    return ReplyKeyboardMarkup(
        [[KeyboardButton("✅ Seleccionar / verificar canal", request_chat=request)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Selecciona el canal que deseas verificar",
    )


def color_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Predeterminado", callback_data=f"cfg_color:default:{chat_id}")],
        [
            InlineKeyboardButton("🔵 Azul", callback_data=f"cfg_color:primary:{chat_id}", style="primary"),
            InlineKeyboardButton("🟢 Verde", callback_data=f"cfg_color:success:{chat_id}", style="success"),
            InlineKeyboardButton("🔴 Rojo", callback_data=f"cfg_color:danger:{chat_id}", style="danger"),
        ],
    ])


def approval_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Aprobar", callback_data=f"review:approve:{chat_id}", style="success"),
            InlineKeyboardButton("❌ Rechazar", callback_data=f"review:reject:{chat_id}", style="danger"),
        ],
        [InlineKeyboardButton("🔄 Recalcular categoría", callback_data=f"review:recalc:{chat_id}", style="primary")],
    ])


def owner_channel_keyboard(chat_id: int, status: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("✏️ Título", callback_data=f"owner:title:{chat_id}"),
            InlineKeyboardButton("🎨 Color", callback_data=f"owner:color:{chat_id}"),
        ],
        [InlineKeyboardButton("🔗 Tipo de ingreso", callback_data=f"owner:link:{chat_id}")],
    ]
    if status in {"suspended", "inactive", "rejected", "withdrawn", "below_minimum"}:
        rows.append([InlineKeyboardButton("🔁 Solicitar reactivación", callback_data=f"owner:reactivate:{chat_id}", style="primary")])
    if status in {"configuring", "inactive", "permission_suspended"}:
        rows.append([InlineKeyboardButton("✅ Verificar con Telegram", callback_data="user:verifychannel", style="success")])
    return InlineKeyboardMarkup(rows)


def admin_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📣 Publicaciones", callback_data="panel:publish", style="primary"),
            InlineKeyboardButton("🖼 Plantillas", callback_data="panel:templates"),
        ],
        [
            InlineKeyboardButton("⏰ Horarios", callback_data="panel:schedules"),
            InlineKeyboardButton("⌛ Duración", callback_data="panel:lifetimes"),
        ],
        [
            InlineKeyboardButton("🔀 Mezcla", callback_data="panel:shuffles"),
            InlineKeyboardButton("📡 Canales", callback_data="panel:channels"),
        ],
        [
            InlineKeyboardButton("✅ Pendientes", callback_data="panel:pending", style="success"),
            InlineKeyboardButton("🔘 Botones", callback_data="panel:buttons"),
        ],
        [
            InlineKeyboardButton("🚫 Sanciones", callback_data="panel:sanctions", style="danger"),
            InlineKeyboardButton("📨 Apelaciones", callback_data="panel:appeals"),
        ],
        [InlineKeyboardButton("🩺 Sistema", callback_data="panel:system", style="primary")],
        [InlineKeyboardButton("👤 Mi panel", callback_data="user:home"), InlineKeyboardButton("🔄 Actualizar", callback_data="panel:home")],
    ])


def category_keyboard(action: str, back: str = "panel:home") -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(CATEGORIES), 2):
        chunk = CATEGORIES[i:i + 2]
        rows.append([InlineKeyboardButton(cat, callback_data=f"admin:{action}:{cat}") for cat in chunk])
    rows.append([InlineKeyboardButton("⬅️ Volver", callback_data=back)])
    return InlineKeyboardMarkup(rows)


def template_actions_keyboard(category: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 Imagen + texto", callback_data=f"template:photo:{category}", style="primary")],
        [InlineKeyboardButton("📝 Solo texto", callback_data=f"template:text:{category}")],
        [InlineKeyboardButton("👁 Previsualizar", callback_data=f"template:preview:{category}")],
        [InlineKeyboardButton("⬅️ Categorías", callback_data="panel:templates")],
    ])


def schedule_actions_keyboard(category: str, enabled: bool) -> InlineKeyboardMarkup:
    toggle = "⏹ Desactivar" if enabled else "▶️ Activar"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 Cambiar hora", callback_data=f"schedule:set:{category}", style="primary")],
        [InlineKeyboardButton(toggle, callback_data=f"schedule:toggle:{category}")],
        [InlineKeyboardButton("⬅️ Categorías", callback_data="panel:schedules")],
    ])


def lifetime_actions_keyboard(category: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⌛ Cambiar duración", callback_data=f"lifetime:set:{category}", style="primary")],
        [InlineKeyboardButton("⬅️ Categorías", callback_data="panel:lifetimes")],
    ])


def shuffle_actions_keyboard(category: str, enabled: bool) -> InlineKeyboardMarkup:
    toggle = "⏹ Desactivar mezcla" if enabled else "▶️ Activar mezcla"
    rows = [
        [InlineKeyboardButton("⏱ Cambiar intervalo", callback_data=f"shuffle:set:{category}", style="primary")],
        [InlineKeyboardButton(toggle, callback_data=f"shuffle:toggle:{category}")],
    ]
    if enabled:
        rows.append([InlineKeyboardButton("🔀 Mezclar ahora", callback_data=f"shuffle:now:{category}")])
    rows.append([InlineKeyboardButton("⬅️ Categorías", callback_data="panel:shuffles")])
    return InlineKeyboardMarkup(rows)


def publish_confirm_keyboard(category: str, has_active: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("✅ Publicar ahora", callback_data=f"publish:confirm:{category}", style="success")],
        [InlineKeyboardButton("👁 Previsualizar", callback_data=f"template:preview:{category}")],
    ]
    if has_active:
        rows.append([
            InlineKeyboardButton(
                "🗑 Eliminar publicación activa",
                callback_data=f"publish:deleteask:{category}",
                style="danger",
            )
        ])
    rows.append([InlineKeyboardButton("⬅️ Categorías", callback_data="panel:publish")])
    return InlineKeyboardMarkup(rows)


def publish_delete_confirm_keyboard(category: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🗑 Sí, eliminar de todos",
                callback_data=f"publish:deleteconfirm:{category}",
                style="danger",
            )
        ],
        [InlineKeyboardButton("↩️ Cancelar", callback_data=f"admin:publish:{category}")],
    ])


def channel_admin_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Suspender", callback_data=f"channel_admin:suspend:{chat_id}", style="danger")],
        [InlineKeyboardButton("🔄 Recalcular", callback_data=f"channel_admin:recalc:{chat_id}")],
        [InlineKeyboardButton("⬅️ Canales", callback_data="panel:channels")],
    ])


def sanction_keyboard(user_id: int, banned: bool) -> InlineKeyboardMarkup:
    label = "✅ Desbanear y resetear" if banned else "♻️ Resetear faltas"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f"sanction:reset:{user_id}", style="success")],
        [InlineKeyboardButton("⬅️ Sanciones", callback_data="panel:sanctions")],
    ])

# ---------------------------------------------------------------------
# Participant panel
# ---------------------------------------------------------------------
def participant_home_keyboard(is_admin_user: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📡 Mis canales", callback_data="user:channels", style="primary"), InlineKeyboardButton("📊 Estadísticas", callback_data="user:stats")],
        [InlineKeyboardButton("➕ Agregar canal", callback_data="user:add"), InlineKeyboardButton("🕐 Próximas botoneras", callback_data="user:next")],
        [InlineKeyboardButton("⚠️ Mi estado", callback_data="user:status"), InlineKeyboardButton("🔔 Notificaciones", callback_data="user:notifications")],
        [InlineKeyboardButton("ℹ️ Ayuda", callback_data="user:help")],
    ]
    if is_admin_user:
        rows.append([InlineKeyboardButton("🛡 Panel administrativo", callback_data="panel:home", style="danger")])
    return InlineKeyboardMarkup(rows)


def participant_channels_keyboard(channels: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    icon_map = {"approved": "🟢", "pending_review": "🟡", "configuring": "🟠", "suspended": "🔴", "inactive": "⚫️", "rejected": "❌", "banned": "🚫", "withdrawn": "⚪️", "below_minimum": "📉", "permission_suspended": "⚠️"}
    for ch in channels[:40]:
        title = ch.get("telegram_title") or str(ch["chat_id"])
        rows.append([InlineKeyboardButton(f"{icon_map.get(ch.get('status'), '•')} {title[:48]}", callback_data=f"user:channel:{ch['chat_id']}")])
    rows.append([InlineKeyboardButton("➕ Agregar otro canal", callback_data="user:add", style="success")])
    rows.append([InlineKeyboardButton("⬅️ Inicio", callback_data="user:home")])
    return InlineKeyboardMarkup(rows)


def participant_channel_keyboard(chat_id: int, status: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("✏️ Editar título", callback_data=f"owner:title:{chat_id}"), InlineKeyboardButton("🎨 Cambiar color", callback_data=f"owner:color:{chat_id}")],
        [InlineKeyboardButton("🔗 Cambiar enlace", callback_data=f"owner:link:{chat_id}")],
        [InlineKeyboardButton("📊 Estadísticas", callback_data=f"user:statsch:{chat_id}:0"), InlineKeyboardButton("📈 Progreso", callback_data=f"user:progress:{chat_id}")],
    ]
    if status == "approved":
        rows.append([InlineKeyboardButton("🚪 Retirar canal", callback_data=f"user:withdrawask:{chat_id}", style="danger")])
    elif status in {"withdrawn", "suspended", "permission_suspended", "inactive", "rejected", "below_minimum"}:
        rows.append([InlineKeyboardButton("♻️ Solicitar reactivación", callback_data=f"owner:reactivate:{chat_id}", style="primary")])
    if status in {"configuring", "inactive", "permission_suspended"}:
        rows.append([InlineKeyboardButton("✅ Verificar con Telegram", callback_data="user:verifychannel", style="success")])
    rows.append([InlineKeyboardButton("⬅️ Mis canales", callback_data="user:channels")])
    return InlineKeyboardMarkup(rows)


def participant_stats_channels_keyboard(channels: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton((ch.get("telegram_title") or str(ch["chat_id"]))[:54], callback_data=f"user:statsch:{ch['chat_id']}:0")] for ch in channels[:40]]
    rows.append([InlineKeyboardButton("⬅️ Inicio", callback_data="user:home")])
    return InlineKeyboardMarkup(rows)


def participant_stats_history_keyboard(chat_id: int, page: int, pages: int) -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"user:statsch:{chat_id}:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{max(1,pages)}", callback_data="user:noop"))
    if page + 1 < pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"user:statsch:{chat_id}:{page+1}"))
    return InlineKeyboardMarkup([nav, [InlineKeyboardButton("⬅️ Estadísticas", callback_data="user:stats")]])


def participant_status_keyboard(can_appeal: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("📜 Historial de faltas", callback_data="user:violations")]]
    if can_appeal:
        rows.append([InlineKeyboardButton("📨 Solicitar revisión", callback_data="user:appeal", style="primary")])
    rows.append([InlineKeyboardButton("⬅️ Inicio", callback_data="user:home")])
    return InlineKeyboardMarkup(rows)


def participant_notifications_keyboard(prefs: dict) -> InlineKeyboardMarkup:
    items = [("notify_approved", "Canal aprobado"), ("notify_rejected", "Canal rechazado"), ("notify_board_started", "Botonera iniciada"), ("notify_board_finished", "Botonera terminada"), ("notify_stats", "Estadísticas"), ("notify_category_change", "Cambio de categoría"), ("notify_next_board", "Próxima botonera")]
    rows = []
    for key, label in items:
        enabled = bool(prefs.get(key, 1))
        rows.append([InlineKeyboardButton(f"{'✅' if enabled else '☑️'} {label}", callback_data=f"user:notify:{key}")])
    rows.append([InlineKeyboardButton("🔒 Alertas de seguridad: siempre activas", callback_data="user:noop")])
    rows.append([InlineKeyboardButton("⬅️ Inicio", callback_data="user:home")])
    return InlineKeyboardMarkup(rows)


def participant_withdraw_confirm_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Sí, retirar sin penalización", callback_data=f"user:withdraw:{chat_id}", style="danger")], [InlineKeyboardButton("❌ Cancelar", callback_data=f"user:channel:{chat_id}")]])


def participant_add_channel_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    rights = "post_messages+edit_messages+delete_messages+invite_users"
    url = f"https://t.me/{bot_username}?startchannel&admin={rights}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Agregar bot a un canal", url=url, style="success")],
        [InlineKeyboardButton("✅ Ya lo agregué · Verificar manualmente", callback_data="user:verifychannel", style="primary")],
        [InlineKeyboardButton("⬅️ Inicio", callback_data="user:home")],
    ])


def appeal_admin_keyboard(appeal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Quitar 1 falta", callback_data=f"appeal:one:{appeal_id}", style="success"), InlineKeyboardButton("🔓 Desbloquear", callback_data=f"appeal:reset:{appeal_id}", style="primary")],
        [InlineKeyboardButton("❌ Rechazar", callback_data=f"appeal:reject:{appeal_id}", style="danger")],
        [InlineKeyboardButton("⬅️ Apelaciones", callback_data="panel:appeals")],
    ])


def system_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🩺 Health check", callback_data="system:health", style="primary")],
        [InlineKeyboardButton("💾 Crear backup ahora", callback_data="system:backup", style="success")],
        [InlineKeyboardButton("🔐 Auditar permisos", callback_data="system:permissions")],
        [InlineKeyboardButton("🧩 Conflictos de propiedad", callback_data="system:conflicts")],
        [InlineKeyboardButton("⬅️ Panel", callback_data="panel:home")],
    ])


def system_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Actualizar", callback_data="system:health")],
        [InlineKeyboardButton("⬅️ Sistema", callback_data="panel:system")],
    ])
