# Changelog v6.0.0

## Robustez y cierre de esta etapa

### 1. Backups automáticos de SQLite
- Snapshot diario configurable.
- Usa `sqlite3.Connection.backup()` para una copia consistente con la base en uso.
- `PRAGMA quick_check` sobre cada backup.
- Rotación automática por días de retención.
- Backup manual desde `/backup` y `/panel → 🩺 Sistema`.

### 2. Health check
- Nuevo `/health` y sección `🩺 Sistema`.
- Verifica conexión del bot, SQLite, jobs, uptime, publicaciones, canales, último backup, errores y conflictos de propiedad.
- Los errores no controlados quedan registrados en `system_events`.

### 3. Verificación preventiva de permisos
- Job periódico configurable con `PERMISSION_CHECK_SECONDS`.
- Verificación inmediata antes de cada envío.
- Derechos requeridos: publicar, editar, eliminar e invitar usuarios.
- Estado `permission_suspended` sin sanción cuando faltan permisos.
- Reactivación automática al recuperar permisos.
- Nueva auditoría manual `/auditarpermisos`.

### 4. Protección contra duplicados/apropiación
- El `chat_id` conserva al propietario original.
- Un segundo usuario no puede reasignarse el canal volviendo a agregar el bot.
- Los intentos se guardan en `ownership_conflicts` y notifican a admin/propietario.
- Transferencia legítima solo por administrador con `/transferircanal CHAT_ID USER_ID`.
- La transferencia vuelve a colocar el canal en revisión.

## Migración
La base v5 se actualiza automáticamente. No es necesario eliminar `botoneras.sqlite3`.
