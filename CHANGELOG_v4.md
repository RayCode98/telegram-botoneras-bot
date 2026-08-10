# CHANGELOG v4

## Estadísticas al finalizar

Cada copia de una botonera ahora guarda:

- suscriptores al momento de publicación;
- suscriptores al finalizar;
- diferencia neta;
- categoría del canal al iniciar;
- estado de entrega del reporte al propietario.

Al expirar una botonera o eliminarla manualmente desde administración, el bot consulta nuevamente el número de miembros y manda al propietario un reporte privado con el resultado.

Los reportes que fallen temporalmente quedan pendientes y se reintentan (máximo 5 intentos) desde el mantenimiento periódico.

## Recategorización automática

Se agregó `pending_category` a los canales.

El bot revisa periódicamente los suscriptores (`CATEGORY_CHECK_SECONDS`, por defecto 900 segundos) y también vuelve a medir al finalizar una botonera.

Si el canal cruza un umbral:

- 5K: 5,000–9,999
- 10K: 10,000–19,999
- 20K: 20,000–29,999
- 30K: 30,000–49,999
- +50K: 50,000+

el cambio se guarda como categoría pendiente si existe una campaña activa en la categoría de origen o destino. Se aplica automáticamente cuando sea seguro, evitando que el botón cambie de botonera a mitad de una publicación activa.

## Mezcla periódica de botones

Cada categoría ahora puede tener:

- mezcla activa/desactivada;
- intervalo en minutos;
- mezcla manual inmediata desde el panel.

Solo se mezclan los botones generados por canales aprobados. Los botones agregados manualmente por un administrador conservan su orden y permanecen después del bloque de canales.

La mezcla se ejecuta editando exclusivamente el `reply_markup` de cada publicación activa. Cada publicación guarda un `shuffle_seed`, de modo que el auditor de integridad puede reconstruir exactamente el orden vigente y no deshacer la mezcla.

Comandos:

```text
/mezcla 5K 10
/nomezcla 5K
```

El intervalo permitido es de 5 a 1440 minutos.

## Persistencia y migración

La migración agrega automáticamente a bases anteriores:

- `channels.pending_category`
- `schedules.shuffle_enabled`
- `schedules.shuffle_interval_minutes`
- campos de estadísticas en `board_messages`
- `board_messages.shuffle_seed`

No es necesario borrar `botoneras.sqlite3` al actualizar desde v3.
