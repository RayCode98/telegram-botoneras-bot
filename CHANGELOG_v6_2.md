# Changelog v6.2.0 — Campañas y atribución precisa

## Estadísticas por campaña

- Cada publicación de una categoría crea ahora una **campaña** con ID propio.
- Cada canal que aparece como botón recibe un **enlace exclusivo para esa campaña**.
- El enlace tiene `expire_date` igual al final de la botonera.
- Al terminar la campaña el bot intenta revocar todos los enlaces creados.
- Los enlaces permanentes guardados en `channels.invite_url` quedan como fallback/vista previa; las publicaciones reales v6.2 usan enlaces de campaña.

## Solicitudes de ingreso

Para canales configurados como **Solicitud de ingreso**:

- se escuchan updates `chat_join_request`;
- se identifica el enlace exacto usado;
- se guardan solicitudes únicas por `campaign_id + chat_id + user_id`;
- si un mismo usuario vuelve a solicitar, se conserva una sola solicitud única y se incrementa `request_events`;
- se cuentan ingresos confirmados mediante actualizaciones `chat_member` atribuibles al enlace.

El reporte muestra:

- solicitudes únicas atribuidas;
- intentos totales (si son mayores a las solicitudes únicas);
- ingresos confirmados;
- solicitudes sin ingreso confirmado al cierre;
- conversión solicitud → ingreso;
- miembros al inicio/fin y crecimiento neto.

## Ingreso directo

Para canales configurados como **Ingreso directo**:

- se crea igualmente un enlace exclusivo por campaña;
- los cambios `chat_member` que incluyen ese enlace se registran como ingresos atribuibles;
- no se confunden con tráfico procedente de `@username`, enlaces externos u otras fuentes.

## Historial

El panel del participante ahora combina:

- historial legado de v6.1 basado en crecimiento neto;
- nuevas campañas v6.2 con solicitudes e ingresos atribuibles.

La pantalla de estadísticas de 30 días agrega:

- solicitudes atribuidas;
- ingresos atribuidos;
- crecimiento neto;
- promedio/mejor/peor crecimiento neto.

## Base de datos

Nuevas tablas:

- `campaigns`
- `campaign_channels`
- `campaign_users`

Nueva columna:

- `board_messages.campaign_id`

La migración es automática y conserva los datos existentes.

## Compatibilidad

- Requiere `python-telegram-bot 22.8` (sin cambio respecto a v6.1).
- No agrega variables obligatorias al `.env`.
- `Update.ALL_TYPES` continúa utilizándose para solicitar también `chat_member`.
