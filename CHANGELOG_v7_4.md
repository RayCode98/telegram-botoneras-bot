# v7.4.0 · Publicidad por canal + solicitudes manuales

## Publicidad pagada por canal

- El participante ahora ve claramente si cada canal acepta o no campañas patrocinadas.
- `monetization_enabled` se presenta en la interfaz como **Publicidad pagada en mi botonera: ON/OFF**.
- Desde `💰 Monetización -> 📢 Publicidad pagada por canal` se administran todos los canales desde un único lugar.
- Si al menos un canal está en ON, la monetización del participante se considera activa.
- Un canal en OFF no se ofrece como fuente en nuevas campañas y sus enlaces patrocinados activos se revocan al apagarlo.

## Solicitud manual de campaña

Después de seleccionar canal y objetivo, el anunciante puede elegir:

- `⭐ Telegram Stars`: checkout normal con Telegram Stars.
- `🪙 USDT · coordinar con administrador`: crea una **solicitud manual**; no activa publicidad automáticamente.

La solicitud manual:

1. queda en estado `contact_pending`;
2. muestra al anunciante el contacto configurado en `MONETIZATION_ADMIN_CONTACT`;
3. notifica a los administradores con botones para contactar, activar o rechazar;
4. al pulsar `Activar publicidad`, el admin introduce el presupuesto USD acordado;
5. la campaña pasa a `recruiting` y se envían oportunidades a participantes monetizados.

## Configuración

Nueva variable opcional:

```env
MONETIZATION_ADMIN_CONTACT=@TU_USUARIO_ADMIN
```

Acepta `@username`, `https://t.me/username` o un enlace `tg://...`. Si está vacío, el bot intenta usar el primer `ADMIN_IDS` como contacto.

## Base de datos

No se requiere una tabla nueva. Las solicitudes manuales utilizan `sponsored_campaigns` con:

- `funding_type = manual_contact`
- `status = contact_pending`

Al activarse por un administrador se convierten en campañas `manual_usd`.
