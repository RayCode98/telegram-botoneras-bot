# Changelog v6.1

- Corrige el significado del tipo de enlace: ahora es **Ingreso directo** o **Solicitud de ingreso**.
- Los dos modos generan un enlace administrado por el bot usando `creates_join_request=False/True`.
- Intenta revocar el enlace de invitación anterior creado por el bot antes de generar uno nuevo.
- Migra valores antiguos `public`/`private` a `direct` sin borrar canales.
- Agrega `✅ Ya lo agregué · Verificar manualmente` en el panel de participante.
- Agrega `/verificarcanal`.
- Usa `KeyboardButtonRequestChat`/`ChatShared` para obtener el `chat_id` del canal de forma nativa.
- La verificación manual comprueba al bot como administrador, permisos requeridos y que el usuario sea propietario/administrador.
- Mantiene protección contra apropiación de canales y sanciones existentes.
- Registra recuperaciones manuales en `system_events`.
