# Cambios v2

- Panel visual `/panel`.
- Duración configurable 0.25–47h por categoría.
- `expires_at` persistente por publicación.
- Limpieza automática de publicaciones expiradas.
- Auditor de integridad de posts activos.
- Suspensión automática si un post desaparece antes de expirar.
- Refresco automático para retirar el botón del canal infractor.
- Detección de eliminación/pérdida de administrador mediante `my_chat_member`.
- Sistema de faltas por usuario.
- Bloqueo automático al alcanzar `VIOLATION_LIMIT` (3 por defecto).
- Rechazo automático de altas de usuarios bloqueados.
- Panel de sanciones y reset/desbloqueo.
- Reactivación de canales suspendidos con nueva revisión.
- Actualización de imagen/texto sobre posts activos.
- Administración visual de botones manuales.
- Migración automática de SQLite v1 a v2.
- Nuevas variables de mantenimiento en `.env`.
