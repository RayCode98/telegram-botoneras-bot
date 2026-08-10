# Changelog v5 — Panel completo del participante

## Nuevo panel del participante

- `/start`, `/miperfil` o `/inicio` muestran un panel visual para el dueño de canales.
- Secciones: Mis canales, Estadísticas, Agregar canal, Próximas botoneras, Mi estado, Notificaciones y Ayuda.
- Los administradores pueden alternar entre `Mi panel` y `Panel administrativo`.

## Mis canales

- Lista visual con estado por canal.
- Detalle con suscriptores actuales, categoría, categoría pendiente, título, color, enlace y próxima botonera.
- Edición de título, color y enlace siempre vuelve a revisión administrativa.
- Retiro voluntario desde el panel sin generar falta.
- Reactivación de canales retirados/suspendidos/inactivos/rechazados cuando vuelvan a cumplir requisitos.

## Estadísticas

- Resumen de los últimos 30 días: participaciones, crecimiento neto, promedio, mejor y peor resultado.
- Historial paginado por canal con suscriptores iniciales, finales y diferencia.
- Progreso visual hacia la siguiente categoría.

## Próximas botoneras

- Vista de próxima participación por canal.
- Muestra horario, duración y mezcla configurada.
- Detecta si la botonera ya está activa.
- Recordatorio automático antes de la publicación (`UPCOMING_NOTICE_MINUTES`, 30 por defecto).
- Los recordatorios se deduplican en SQLite para evitar mensajes repetidos tras reinicios.

## Notificaciones configurables

El participante puede activar/desactivar:

- Canal aprobado.
- Canal rechazado.
- Botonera iniciada.
- Botonera terminada.
- Estadísticas finales.
- Cambio de categoría.
- Próxima botonera.

Las alertas de seguridad, faltas y bloqueos son obligatorias y no se pueden desactivar.

## Apelaciones

- El participante puede enviar una solicitud de revisión desde `Mi estado`.
- Solo se permite una apelación pendiente a la vez.
- El administrador recibe la apelación desde el panel y puede:
  - quitar una falta;
  - reiniciar todas las sanciones/desbloquear;
  - rechazar.
- La resolución se almacena en SQLite y se notifica al participante.

## Categorías automáticas

- 5K: 5,000–9,999
- 10K: 10,000–19,999
- 20K: 20,000–29,999
- 30K: 30,000–49,999
- +50K: 50,000+
- Los canales por debajo del mínimo pasan a `below_minimum`, dejan de participar y continúan siendo auditados para reincorporarse automáticamente.

## Alta guiada

- El panel genera un enlace oficial de Telegram del tipo `?startchannel&admin=...`.
- Solicita permisos de publicar, editar, borrar mensajes e invitar usuarios.
- Después del alta continúa el asistente existente de enlace, título, color y revisión.

## Migración

La v5 usa el mismo `botoneras.sqlite3`. No es necesario borrar la base anterior. Al iniciar, se crean automáticamente:

- `user_preferences`
- `appeals`
- `notification_log`

Además conserva las tablas y columnas de v2/v3/v4.
