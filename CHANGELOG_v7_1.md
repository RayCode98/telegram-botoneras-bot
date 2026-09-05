# Changelog v7.1.0 — Administración de canales suspendidos

- Nuevo módulo **⏸ Suspendidos** en el panel administrativo.
- Lista paginada de canales con estado `suspended` y `permission_suspended`.
- Vista de motivo, origen, permisos, responsable y faltas.
- Reactivación manual segura: valida permisos, bloqueo del propietario y mínimo de miembros.
- Suspensión manual con confirmación desde el listado de canales aprobados.
- La suspensión administrativa no genera faltas.
- Al suspender, se eliminan las publicaciones activas del canal, se refresca su botón y se deshabilita como fuente de campañas monetizadas.
- Las suspensiones automáticas por permisos y por eliminación anticipada ahora guardan motivo/origen/fecha.
- Migración automática de SQLite: no es necesario borrar la base existente.
