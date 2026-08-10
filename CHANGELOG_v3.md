# CHANGELOG v3

## Botoneras en una sola columna

- La publicación pública usa exactamente un botón por fila.
- Los paneles administrativos conservan su distribución compacta.

## Eliminación manual global

- Nuevo botón `🗑 Eliminar publicación activa` en Panel > Publicaciones > Categoría.
- Confirmación obligatoria antes del borrado.
- Nuevo comando `/eliminarpublicacion CATEGORIA`.
- Se recorren todas las copias activas de la categoría.
- Hasta 3 rondas de intento para errores temporales.
- Los mensajes confirmados como borrados o ya inexistentes se marcan inactivos.
- Los fallos reales permanecen activos y se reportan para reintentar.
- Una eliminación administrativa no genera faltas a los propietarios.

## Robustez

- `_delete_row` ya no marca como eliminado un mensaje cuando Telegram devuelve un error real. Esto evita perder el seguimiento de publicaciones que no pudieron borrarse.
- La eliminación global respeta `RetryAfter` de Telegram antes de continuar, útil cuando hay muchos canales.
