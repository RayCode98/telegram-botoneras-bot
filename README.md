# Telegram Botoneras v6.1

Bot en Python para administrar publicaciones programadas de intercambio de canales de Telegram con categorías, revisión, estadísticas, mezcla periódica, sanciones, panel de participantes y herramientas de robustez/operación.

## Requisitos

- Python 3.11+
- `python-telegram-bot[job-queue]==22.8`
- Bot creado con @BotFather
- SQLite (incluido en Python)

## Instalación

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Instala dependencias:

```bash
pip install -r requirements.txt
```

Copia `.env.example` a `.env` y configura tu token y administradores:

```env
BOT_TOKEN=TU_TOKEN
ADMIN_IDS=123456789
TIMEZONE=America/Mexico_City
DATABASE_PATH=botoneras.sqlite3
DISTRIBUTE_MODE=category
MAX_BUTTONS_PER_BOARD=100
MIN_MEMBERS=5000
DEFAULT_POST_LIFETIME_HOURS=6
VIOLATION_LIMIT=3
INTEGRITY_CHECK_SECONDS=300
CLEANUP_CHECK_SECONDS=60
CATEGORY_CHECK_SECONDS=900
UPCOMING_NOTICE_MINUTES=30
LEAVE_CHANNELS_ON_BAN=true
BACKUP_ENABLED=true
BACKUP_DIR=backups
BACKUP_HOUR=3
BACKUP_MINUTE=30
BACKUP_RETENTION_DAYS=14
PERMISSION_CHECK_SECONDS=900
```

Ejecuta:

```bash
python main.py
```

## Panel del participante

El participante abre `/start`, `/miperfil` o `/inicio`.

El panel incluye:

- 📡 Mis canales
- 📊 Estadísticas
- ➕ Agregar canal
- ✅ Verificación manual de un canal cuando el alta automática no llega
- 🕐 Próximas botoneras
- ⚠️ Mi estado
- 🔔 Notificaciones
- ℹ️ Ayuda

Los administradores también ven un botón para entrar al panel administrativo.

### Alta de un canal

1. El usuario debe haber iniciado el bot con `/start`.
2. En `➕ Agregar canal`, pulsa `Agregar bot a un canal`.
3. Telegram abre el selector de canales y solicita los permisos necesarios.
4. Al convertirse el bot en administrador, `my_chat_member` intenta registrar el canal y al responsable automáticamente.
5. Si esa actualización no llega o se perdió, el usuario puede pulsar **Ya lo agregué · Verificar manualmente** o ejecutar `/verificarcanal`. Telegram abre su selector nativo de canales y el bot vuelve a comprobar directamente el `chat_id`, al usuario administrador y sus propios permisos.
6. El participante elige ingreso directo/solicitud de ingreso, título y color.
7. La solicitud pasa a revisión.
8. Al aprobarse, el botón entra en su categoría.

### Edición

Título, color y enlace se pueden modificar desde el detalle del canal. Cualquier cambio vuelve a `pending_review`; el canal queda fuera de la botonera hasta nueva aprobación.

### Retiro voluntario

El dueño puede retirar su canal desde el panel. El bot:

- cambia el estado a `withdrawn`;
- elimina las publicaciones activas de ese canal que pueda borrar;
- quita su botón de las botoneras activas de su categoría;
- no registra ninguna falta.

Si después el dueño elimina el bot del canal estando en estado `withdrawn`, tampoco se genera una falta.

## Estadísticas

Cada copia de una botonera guarda el número de suscriptores al inicio. Al terminar por expiración o eliminación administrativa global, se vuelve a consultar el total y se calcula:

```text
inicio → final = diferencia
```

El participante puede consultar:

- participaciones de los últimos 30 días;
- crecimiento neto;
- promedio;
- mejor resultado;
- peor resultado;
- historial paginado por canal.

## Categorías

Clasificación predeterminada:

- `5K`: 5,000–9,999
- `10K`: 10,000–19,999
- `20K`: 20,000–29,999
- `30K`: 30,000–49,999
- `+50K`: 50,000+

`CATEGORY_CHECK_SECONDS` controla cada cuánto se revisan los suscriptores. Si un canal cruza un límite mientras una campaña está activa, la nueva categoría queda pendiente y se aplica cuando ya no altere la campaña en curso.

Si cae por debajo de `MIN_MEMBERS`, pasa a `below_minimum`, deja de participar y continúa siendo revisado para reincorporarse automáticamente.

## Progreso de categoría

Desde cada canal se muestra una barra de progreso, siguiente categoría, meta de suscriptores y cuántos faltan.

## Próximas botoneras

El participante puede consultar el próximo horario, duración y mezcla de su categoría. Si la publicación ya está activa, se muestra su expiración.

Además existe un recordatorio automático antes del inicio:

```env
UPCOMING_NOTICE_MINUTES=30
```

Los avisos se guardan en `notification_log`, por lo que un reinicio no duplica el mismo recordatorio.

## Notificaciones

Cada participante puede activar/desactivar:

- aprobación;
- rechazo;
- inicio;
- finalización;
- estadísticas;
- cambio de categoría;
- recordatorio de próxima botonera.

Las alertas de seguridad son obligatorias.

## Sistema de faltas

Se mantiene el sistema de sanciones de v4. Por defecto:

```env
VIOLATION_LIMIT=3
```

Al alcanzar el límite se bloquea al usuario para nuevas altas/modificaciones y sus canales se retiran del sistema según la configuración.

El participante puede ver su estado e historial de incidencias.

## Apelaciones

Desde `⚠️ Mi estado → 📨 Solicitar revisión` se envía una explicación al administrador.

En `🛡 Panel administrativo → 📨 Apelaciones`, el administrador puede:

- retirar una falta;
- desbloquear y resetear todas las faltas;
- rechazar la apelación.

Solo puede existir una apelación pendiente por usuario.

## Panel administrativo

Mantiene las funciones de v4:

- 📣 Publicaciones
- 🖼 Plantillas
- ⏰ Horarios
- ⌛ Duración
- 🔀 Mezcla
- 📡 Canales
- ✅ Pendientes
- 🔘 Botones manuales
- 🚫 Sanciones
- 📨 Apelaciones
- 🩺 Sistema / mantenimiento
- 👤 Mi panel

## Publicación

Cada categoría tiene imagen, texto y botones en una sola columna.

Los botones de canales pueden mezclarse periódicamente. Los botones manuales del administrador nunca participan en la mezcla y mantienen su orden.

## Eliminación

Las publicaciones pueden:

- expirar automáticamente según la duración;
- borrarse manualmente de todos los canales desde el panel o `/eliminarpublicacion CATEGORIA`.

El sistema mantiene los registros que Telegram no pudo borrar para permitir reintentos.

## Mantenimiento y robustez (v6)

### Backups automáticos

Si `BACKUP_ENABLED=true`, el bot crea diariamente una instantánea consistente de SQLite a la hora definida por `BACKUP_HOUR` y `BACKUP_MINUTE`. Usa la Online Backup API de SQLite, por lo que no copia a ciegas un archivo que pueda estar siendo escrito.

- `/backup`: crea un backup manual.
- `BACKUP_DIR`: carpeta de destino.
- `BACKUP_RETENTION_DAYS`: elimina automáticamente snapshots antiguos.
- Cada snapshot ejecuta `PRAGMA quick_check` antes de considerarse válido.

Desde `/panel → 🩺 Sistema` también puede crearse un backup manual.

### Health check

`/health` o `/panel → 🩺 Sistema → Health check` muestra:

- conexión con Telegram;
- `PRAGMA quick_check` de SQLite;
- cantidad de jobs programados;
- uptime del proceso;
- canales aprobados;
- canales suspendidos por permisos;
- publicaciones activas;
- último backup;
- errores recientes;
- conflictos recientes de propiedad.

### Auditoría preventiva de permisos

El bot revisa periódicamente que conserve en cada canal los permisos necesarios para:

- publicar mensajes;
- editar mensajes;
- eliminar mensajes;
- invitar usuarios / generar enlaces.

Además, vuelve a validar los permisos inmediatamente antes de publicar cada botonera. Si faltan permisos, el canal pasa a `permission_suspended`, no recibe nuevas publicaciones y el propietario es avisado. Esto **no genera una falta**. Cuando los permisos vuelven a estar correctos, el sistema lo reactiva automáticamente.

Comando manual: `/auditarpermisos`.

### Protección contra canales duplicados / apropiación

El `chat_id` de un canal queda ligado al primer propietario registrado. Si otra cuenta intenta agregar nuevamente el bot para reclamar ese mismo canal:

- no se cambia el propietario;
- se registra un conflicto;
- se avisa al propietario original y a los administradores;
- el bot abandona esa alta conflictiva.

Para una transferencia legítima, el nuevo propietario debe ejecutar `/start` y un administrador usa:

```text
/transferircanal CHAT_ID USER_ID
```

La transferencia deja el canal en `pending_review` antes de volver a participar.

## Migrar desde v5

Haz respaldo de:

```text
.env
botoneras.sqlite3
```

Reemplaza el código por v6, conserva tu `.env` y agrega las variables nuevas de backup/permisos si deseas personalizarlas. No borres `botoneras.sqlite3`: la migración agrega automáticamente las nuevas columnas/tablas.

## Archivos principales

```text
bot/
  app.py
  config.py
  db.py
  keyboards.py
  moderation.py
  publisher.py
  maintenance.py
main.py
requirements.txt
.env.example
CHANGELOG_v6.md
README.md
```


## v6.1 — Enlaces de ingreso y verificación manual

### Ingreso directo vs solicitud de ingreso

La configuración de enlace ya no significa público/privado. Ahora significa:

- **🚪 Ingreso directo**: `creates_join_request=False`. Quien pulse el botón puede entrar mediante ese enlace sin aprobación previa.
- **🛂 Solicitud de ingreso**: `creates_join_request=True`. Quien pulse el botón genera una solicitud que debe ser aprobada por un administrador del canal.

El bot genera un enlace de invitación propio en ambos casos. Para hacerlo necesita el permiso **Invitar usuarios**.

> Nota: si el canal tiene un `@username` público, seguirá existiendo la posibilidad de encontrar/abrir el canal mediante ese enlace público fuera de la botonera. El enlace generado por el bot sí respetará el modo elegido. Para exigir aprobación como única vía de entrada, el canal debe ser privado en Telegram.

### Recuperar un canal que no fue detectado

Si el bot aparece como administrador pero nunca llegó el mensaje de confirmación:

1. Abre el bot en privado.
2. Entra a `➕ Agregar canal`.
3. Pulsa `✅ Ya lo agregué · Verificar manualmente`.
4. Telegram mostrará el selector nativo de canales.
5. Selecciona el canal.
6. El bot comprueba en tiempo real:
   - que el chat sea un canal;
   - que el bot sea administrador;
   - que tenga publicar, editar, eliminar e invitar;
   - que el usuario que lo está verificando sea propietario/administrador;
   - que el canal no pertenezca ya a otro participante.
7. Si todo está correcto, continúa con ingreso directo/solicitud, título, color y revisión administrativa.

También puede abrirse directamente con:

```text
/verificarcanal
```

Esta vía no depende de recibir de nuevo `my_chat_member`, por lo que sirve para canales que ya tenían al bot como administrador antes de que el sistema registrara correctamente el alta.

---

## v6.2 — Campañas con enlaces exclusivos y estadísticas atribuibles

Desde v6.2 una botonera ya no usa el enlace permanente del canal para medir resultados. Cada ejecución crea una **campaña** y genera un enlace independiente para cada canal que aparece como botón.

Ejemplo:

```text
Campaña #214 · 10K
├─ Canal A → enlace exclusivo campaña #214
├─ Canal B → enlace exclusivo campaña #214
└─ Canal C → enlace exclusivo campaña #214
```

Los botones manuales agregados por un administrador no cambian y siguen fuera de la medición/mezcla de canales.

### Solicitud de ingreso

Si el canal tiene configurado:

```text
🛂 Solicitud de ingreso
```

el enlace de esa campaña se crea con:

```python
creates_join_request=True
```

y expira cuando termina la publicación.

El bot recibe `chat_join_request`, reconoce el `invite_link` utilizado y registra la solicitud dentro de esa campaña. La clave lógica de una solicitud única es:

```text
campaign_id + channel_chat_id + telegram_user_id
```

Por eso si una persona manda dos veces la solicitud durante la misma campaña se obtiene, por ejemplo:

```text
Solicitudes únicas: 1
Intentos de solicitud: 2
```

Cuando Telegram confirma que el usuario pasó a ser miembro mediante el enlace de campaña, se registra un ingreso confirmado.

Reporte de ejemplo:

```text
📊 Resultados · Campaña #214

Canal: Noticias México
Categoría: 10K

🛂 Solicitudes de ingreso
Solicitudes únicas atribuidas: 326
Ingresos confirmados: 241
Sin ingreso confirmado: 85
Conversión solicitud → ingreso: 73.9%

👥 Crecimiento neto del canal
Al iniciar: 12,450
Al finalizar: 12,681
Diferencia neta: +231
```

`Sin ingreso confirmado` **no significa necesariamente rechazado**. Puede incluir solicitudes pendientes, canceladas o no convertidas durante la ventana de la campaña. El bot no inventa un estado de rechazo si Telegram no se lo informó.

### Ingreso directo

Si el canal usa:

```text
🚪 Ingreso directo
```

el bot también crea un enlace exclusivo, pero con:

```python
creates_join_request=False
```

Los ingresos que Telegram atribuya a ese enlace se guardan como ingresos de la campaña.

Ejemplo:

```text
🚪 Ingresos atribuidos al enlace: 187
Miembros inicio: 8,532
Miembros fin: 8,703
Crecimiento neto: +171
```

Los valores no tienen por qué ser iguales. Durante la campaña pueden existir bajas y entradas por otras fuentes.

### Por qué se mantienen dos métricas

**Atribución de campaña**:

- solicitudes generadas por el enlace exclusivo;
- ingresos confirmados atribuibles al enlace.

**Crecimiento neto**:

- total de miembros al iniciar;
- total de miembros al finalizar;
- diferencia.

Esto evita afirmar que todo el crecimiento neto fue generado por la botonera.

### Ciclo de vida del enlace

Al publicar:

```text
Crear campaña
→ generar enlace exclusivo por canal
→ publicar la botonera
→ contar solicitudes/ingresos
→ terminar duración
→ eliminar publicaciones
→ revocar enlaces
→ cerrar campaña
→ enviar estadísticas
```

Además de revocarlos al cierre, los enlaces se crean con fecha de expiración como segunda protección.

### Cambios durante una campaña

- El `shuffle` reconstruye el teclado usando los mismos enlaces exclusivos de la campaña.
- Un refresco de botones no crea una campaña nueva.
- Los botones manuales del administrador no reciben enlaces de atribución.
- Si un canal aprobado entra mientras una campaña sigue activa, se genera su enlace exclusivo con la misma expiración de la campaña.
- Si cambia de Ingreso directo a Solicitud de ingreso (o viceversa) y vuelve a aprobarse durante una campaña, se reemplaza el enlace de esa campaña por uno del modo correcto.

### Historial del participante

El apartado `📊 Estadísticas` muestra ahora también:

```text
🛂 Solicitudes atribuidas
✅ Ingresos atribuidos
📈 Crecimiento neto
```

Por canal, las campañas nuevas muestran:

```text
13/08/2026 · 9,850 → 10,021 · +171
   🛂 248 solicitudes · ✅ 190 ingresos
```

El historial creado antes de v6.2 sigue apareciendo, simplemente sin las métricas de atribución que no existían en esas versiones.

### Permisos necesarios

Para que la medición funcione correctamente el bot debe continuar siendo administrador y conservar **Invitar usuarios**. Telegram exige ese permiso para recibir solicitudes de ingreso y para crear/revocar enlaces de invitación.

La aplicación además solicita `chat_member` explícitamente mediante `Update.ALL_TYPES` para poder registrar cambios de membresía.

### Actualización desde v6.1

1. Haz respaldo de:

```text
.env
botoneras.sqlite3
```

2. Reemplaza el código por v6.2.
3. Conserva tu mismo `.env`.
4. Instala/actualiza dependencias:

```bash
pip install -r requirements.txt
```

5. Arranca normalmente:

```bash
python main.py
```

No elimines `botoneras.sqlite3`. Al iniciar, el sistema crea automáticamente las tablas de campañas y agrega `campaign_id` a las publicaciones existentes.

No se requieren variables nuevas de `.env` para esta versión.
