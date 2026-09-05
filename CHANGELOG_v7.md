# Changelog v7.0.0 — Monetización con Telegram Stars

## Módulo de anunciantes

- Nuevo acceso `📢 Publicidad` y comando `/publicidad`.
- Creación de campañas patrocinadas sobre canales registrados por el anunciante.
- Objetivos configurables (por defecto 1K, 2K y 5K).
- Cobro nativo mediante Telegram Stars (`XTR`).
- Validación de `pre_checkout_query` y almacenamiento de `telegram_payment_charge_id`.
- Revisión administrativa obligatoria después del pago.
- Reembolso mediante `refundStarPayment` cuando una campaña pagada es rechazada o no puede arrancar por falta de inventario/permisos.
- `/paysupport` para soporte de pagos.

## Reclutamiento voluntario de participantes

- Nuevo módulo `💰 Monetización` y comando `/monetizacion`.
- Activación voluntaria con aceptación de reglas básicas.
- Al aprobar una campaña se programa su inicio con una ventana de reclutamiento (3h por defecto).
- Solo usuarios que activaron monetización reciben oportunidades.
- Cada participante elige qué canales aprobados aporta a cada campaña.
- Desactivar monetización no borra saldo ni cancela compromisos ya iniciados.

## Atribución por canal fuente

- Cada fuente obtiene un enlace de invitación exclusivo hacia el canal anunciado.
- Primera fuente por usuario/campaña: un usuario no puede generar ganancias para varias fuentes en la misma campaña.
- Solicitudes repetidas se guardan como intentos, pero no crean usuarios/conversiones únicas adicionales.
- Ingreso directo y solicitud de ingreso son compatibles.
- Al alcanzar la meta de ingresos atribuidos se revocan enlaces y desaparece inmediatamente el botón patrocinado de las botoneras activas.
- Los enlaces de una fuente se revocan también si el canal fuente pierde permisos, se retira o elimina al bot.

## Antifraude y retención

- Retención configurable, 24h por defecto.
- Un usuario que abandona antes de validar queda rechazado y reingresar no reinicia la posibilidad de cobro.
- Bots no cuentan.
- Propietarios/administradores del canal objetivo no generan conversiones pagables.
- Una conversión solo pasa a saldo disponible después de confirmar que continúa como miembro al finalizar la retención.
- No se requiere ni almacena IP del usuario.

## Economía

- Precio por 1,000 objetivo configurable en Stars.
- Comisión de plataforma configurable en basis points (20% por defecto).
- Pool interno de participantes calculado automáticamente.
- Ganancia proporcional por conversión verificada.
- Monedero interno con saldo pendiente, disponible e histórico.
- Solicitudes de retiro manuales para preparar una futura integración de payout externo.
- Importante: el saldo del participante es contabilidad interna; esta versión no afirma ni intenta transferir Stars arbitrariamente a usuarios.

## Integración con botoneras

- Los botones patrocinados se muestran arriba y en una sola columna.
- No participan en el shuffle de canales normales.
- Los botones manuales del administrador siguen fuera del shuffle.
- Cada canal fuente recibe su propio enlace de atribución aun cuando la misma campaña aparece en múltiples canales.
- Las botoneras publicadas posteriormente mientras la campaña siga activa también incorporan el patrocinado.

## Corrección de sanciones solicitada

- Quitar el bot de un canal **no aprobado** ya no genera infracción.
- Solo `approved` o `permission_suspended` (un canal que ya estaba aprobado) pueden generar la falta `bot_removed`.
- Estados como `configuring`, `pending_review`, `rejected`, `withdrawn`, `inactive` o por debajo del mínimo se desactivan sin sumar faltas.

## Nuevas variables `.env`

```env
MONETIZATION_ENABLED=true
MONETIZATION_STARS_PER_1000=300
MONETIZATION_PLATFORM_FEE_BPS=2000
MONETIZATION_RETENTION_HOURS=24
MONETIZATION_OPPORTUNITY_HOURS=3
MONETIZATION_MAX_CAMPAIGN_HOURS=72
MONETIZATION_MIN_WITHDRAW_STARS=10
MONETIZATION_GOALS=1000,2000,5000
```

`MONETIZATION_STARS_PER_1000=300` es solo un valor inicial configurable. Debe ajustarse al modelo comercial real antes de producción.
