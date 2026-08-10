# Telegram Botoneras v6

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
- 🕐 Próximas botoneras
- ⚠️ Mi estado
- 🔔 Notificaciones
- ℹ️ Ayuda

Los administradores también ven un botón para entrar al panel administrativo.

### Alta de un canal

1. El usuario debe haber iniciado el bot con `/start`.
2. En `➕ Agregar canal`, pulsa `Agregar bot a un canal`.
3. Telegram abre el selector de canales y solicita los permisos necesarios.
4. Al convertirse el bot en administrador, `my_chat_member` registra el canal y al responsable.
5. El participante elige enlace público/privado, título y color.
6. La solicitud pasa a revisión.
7. Al aprobarse, el botón entra en su categoría.

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
