# v7.3.0 — Monetización centralizada y canales solo para promoción

## Monetización del participante

- Se elimina la ambigüedad del interruptor global separado.
- La monetización ahora se controla desde `💰 Monetización → 📡 Configurar mis canales`.
- Cada canal elegible puede ponerse en ON/OFF desde el mismo panel.
- El estado general se considera **activo automáticamente** cuando existe al menos un canal aprobado, con permisos correctos y monetización ON.
- Si todos los canales quedan OFF (o dejan de ser elegibles), la monetización general queda desactivada automáticamente.
- Los botones antiguos `Monetización del canal` redirigen al nuevo panel central para conservar compatibilidad.

## Canales que solo compran suscriptores

- Se separa el concepto de **canal fuente/participante** y **canal objetivo/anunciante**.
- Un canal puede configurarse como:
  - `📣 Participar en botoneras`
  - `🎯 Solo promocionar / comprar subs`
  - `🔄 Ambos usos`
- Un canal `solo promoción`:
  - no publica botoneras;
  - no aparece como botón participante;
  - no genera ingresos como fuente;
  - sí puede ser objetivo de campañas Stars o promociones manuales USD;
  - puede estar por debajo de 5K, porque su categoría no condiciona la compra de promoción.
- Para un canal solo promoción, el bot solo exige ser administrador y tener permiso para invitar usuarios/crear enlaces.
- Quitar el bot de un canal que nunca participó como fuente de botonera no genera infracción.

## Publicidad

- Nuevo apartado `📢 Publicidad → 🎯 Mis canales para promocionar`.
- Nuevo flujo `➕ Agregar canal solo para promoción` con selector nativo de Telegram.
- El cliente puede registrar un canal para comprar suscriptores sin aceptar publicar la botonera en ese canal.
- El tipo de ingreso de un canal objetivo puede configurarse como ingreso directo o solicitud de ingreso.
- Las promociones manuales del administrador también pueden seleccionar estos canales objetivo.

## Base de datos

Nuevas columnas en `channels`:

- `board_participation_enabled`
- `promotion_target_enabled`

La migración es automática. Los canales existentes se migran con ambos valores activos para conservar el comportamiento previo.
