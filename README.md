# Telegram Botoneras v7.0.0

Bot en Python para gestionar botoneras programadas de Telegram y un módulo opcional de campañas patrocinadas pagadas con Telegram Stars.

La v7 conserva todas las funciones anteriores: categorías 5K/10K/20K/30K/+50K, panel de participantes y administradores, enlaces directos o con solicitud de ingreso, verificación manual de canales, publicación/eliminación programada, una columna de botones, shuffle, estadísticas, recategorización, sanciones, apelaciones, backups, health check, auditoría de permisos y protección de propiedad.

## Requisitos

- Python 3.11+
- `python-telegram-bot[job-queue]==22.8`
- Bot creado con BotFather
- SQLite (incluido en Python)

## Instalación

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

Linux:

```bash
source .venv/bin/activate
```

Después:

```bash
pip install -r requirements.txt
```

Copia `.env.example` como `.env`, configura `BOT_TOKEN` y `ADMIN_IDS`, y ejecuta:

```bash
python main.py
```

## Actualizar desde v6.2

Haz un respaldo de:

```text
.env
botoneras.sqlite3
```

Reemplaza el código por v7 y conserva tu base. **No borres `botoneras.sqlite3`.** La migración se ejecuta automáticamente al iniciar.

Añade o revisa estas variables:

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

El valor de 300 Stars por 1K es un valor inicial de configuración, no una equivalencia fija a dólares.

---

# 1. Botoneras normales

Las publicaciones continúan funcionando con:

- una imagen;
- texto HTML compatible con Telegram;
- botones en una sola columna;
- categorías 5K, 10K, 20K, 30K y +50K;
- publicación programada;
- duración configurable y eliminación automática;
- eliminación manual global;
- refresco de posts activos;
- mezcla periódica solo de botones de canales;
- botones manuales del administrador fuera del shuffle;
- estadísticas de inicio/fin;
- enlaces de atribución por campaña normal;
- recategorización automática.

## Enlaces de canal

El propietario elige:

- `🚪 Ingreso directo`
- `🛂 Solicitud de ingreso`

No significa público/privado. Describe si el enlace permite entrar directamente o crea una solicitud que requiere aprobación.

## Verificación manual

Si Telegram no entrega correctamente el evento de alta del bot:

```text
/verificarcanal
```

El usuario selecciona el canal mediante el selector nativo de Telegram y el bot comprueba propiedad/admin, permisos y registro existente.

---

# 2. Corrección de sanciones v7

Eliminar el bot de un canal que aún **no fue aprobado** no suma ninguna falta.

Solo se puede registrar `bot_removed` si el canal estaba:

```text
approved
permission_suspended
```

Por ejemplo, estos estados no generan falta al quitar el bot:

```text
configuring
pending_review
rejected
withdrawn
inactive
below_minimum
```

---

# 3. Monetización para participantes

Acceso:

```text
/monetizacion
```

o desde:

```text
/start → 💰 Monetización
```

El usuario debe activar voluntariamente la monetización y aceptar las reglas básicas.

## Oportunidades

Cuando un administrador aprueba una campaña pagada, por defecto se programa para comenzar dentro de 3 horas. Los usuarios monetizados con canales elegibles reciben una oportunidad.

Ejemplo:

```text
💰 Nueva oportunidad · Campaña #31

Canal promocionado: Noticias Premium
Objetivo: 1,000 miembros
Pool participantes: 240 créditos internos
Retención requerida: 24h

[ Canal A ]
[ Canal B ]
[ Confirmar participación ]
[ No participar ]
```

Participar es opcional y el usuario elige sus canales fuente.

---

# 4. Publicidad / anunciantes

Acceso:

```text
/publicidad
```

Flujo:

```text
Seleccionar canal objetivo
→ elegir meta
→ pagar con Telegram Stars
→ pago confirmado
→ revisión administrativa
→ reclutamiento de participantes
→ campaña activa
→ meta de ingresos
→ validar retención
→ resultados
```

Los objetivos disponibles se configuran con `MONETIZATION_GOALS`.

## Telegram Stars

La factura utiliza:

```text
currency = XTR
```

El pago se valida mediante `pre_checkout_query` y `successful_payment`.

El sistema conserva `telegram_payment_charge_id` para poder solicitar un reembolso completo cuando corresponda.

Comando de soporte:

```text
/paysupport
```

---

# 5. Revisión administrativa

Después de un pago, la campaña queda en:

```text
paid_review
```

El administrador puede:

```text
✅ Aprobar y reclutar
❌ Rechazar + reembolsar
```

Al aprobar se abre la ventana de reclutamiento. Al rechazar, el bot intenta reembolsar el pago en Stars.

Si al iniciar no hay ninguna fuente válida, no se pueden crear enlaces, o el canal anunciado ya no tiene permisos adecuados, la campaña se cancela y se intenta reembolsar automáticamente.

---

# 6. Atribución de conversiones

Cada canal participante obtiene un enlace exclusivo hacia el canal anunciado:

```text
Campaña #31
├─ Canal fuente A → enlace A
├─ Canal fuente B → enlace B
└─ Canal fuente C → enlace C
```

Por ello el sistema sabe qué fuente originó la conversión.

## Primera atribución

La clave lógica es:

```text
campaign_id + telegram_user_id
```

Un usuario solo puede producir una conversión dentro de una campaña.

Si primero llega desde Canal A y posteriormente pulsa Canal B:

```text
Fuente pagable = Canal A
```

## Solicitudes repetidas

Se guardan dos métricas:

```text
Solicitudes únicas
Intentos de solicitud
```

Una misma persona puede generar varios intentos pero únicamente una solicitud/conversión única.

---

# 7. Antifraude y retención

No se almacena IP. La atribución utiliza el identificador único del usuario de Telegram y los eventos de membresía.

Reglas incluidas:

- un usuario = máximo una conversión por campaña;
- primera fuente gana la atribución;
- bots no generan pago;
- administradores/propietarios del canal objetivo no generan pago;
- reentradas no generan conversiones nuevas;
- abandonar antes de validar invalida la conversión;
- reingresar después de un abandono temprano no reinicia la posibilidad de cobro;
- retención mínima configurable (24h por defecto);
- el saldo queda `pending` hasta superar la validación;
- solo después pasa a `available`.

---

# 8. Botones patrocinados

Los patrocinados se muestran encima del bloque normal:

```text
[ ⭐ Canal patrocinado ]
[ Canal normal A ]
[ Canal normal B ]
[ Botón manual admin ]
```

Reglas:

- una sola columna;
- patrocinados no participan en el shuffle;
- cada copia usa el enlace correspondiente a su canal fuente;
- los botones normales de canales sí pueden mezclarse;
- los manuales del admin mantienen su orden.

Cuando se alcanza la meta de ingresos atribuidos:

1. la adquisición se cierra;
2. se revocan los enlaces;
3. desaparece el botón patrocinado de todos los posts activos de las fuentes;
4. se conserva la validación de retención pendiente;
5. posteriormente se acreditan las conversiones válidas.

Si un canal fuente se retira, elimina el bot o pierde elegibilidad, su enlace patrocinado se revoca de inmediato. Las conversiones válidas registradas antes de ese momento pueden seguir su proceso de validación.

---

# 9. Economía v7

Ejemplo con valores predeterminados:

```text
Precio anunciante: 300 Stars / 1,000 objetivo
Comisión plataforma: 20%
Pool participantes: 80%
Retención: 24h
```

Para 1,000:

```text
300 Stars cobradas
→ 20% plataforma
→ 240 unidades Star-equivalentes de contabilidad interna para participantes
→ 0.240 por conversión verificada
```

La distribución es proporcional: quien genera más conversiones verificadas acumula más saldo.

### Importante sobre el monedero

El saldo de participantes se expresa internamente en milésimas para poder repartir cantidades pequeñas. **No representa una transferencia automática de Telegram Stars al usuario.** Es un libro contable interno preparado para una futura liquidación externa.

Esta versión permite:

```text
saldo pendiente
saldo disponible
histórico
solicitud de retiro
revisión admin del retiro
```

La liquidación real del retiro es manual en v7.

---

# 10. Variables de monetización

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

`MONETIZATION_PLATFORM_FEE_BPS` usa basis points:

```text
1000 = 10%
1500 = 15%
2000 = 20%
2500 = 25%
```

---

# 11. Comandos principales

Participante:

```text
/start
/miscanales
/verificarcanal
/monetizacion
/publicidad
/paysupport
```

Administrador:

```text
/panel
/pendientes
/publicar 5K
/eliminarpublicacion 5K
/programar 5K 18:00
/duracion 5K 6
/mezcla 5K 10
/nomezcla 5K
/plantilla 5K
/preview 5K
/health
/backup
/auditarpermisos
/transferircanal CHAT_ID USER_ID
```

---

# 12. Base de datos nueva

La v7 añade principalmente:

```text
monetization_profiles
sponsored_campaigns
sponsored_sources
sponsored_users
wallet_ledger
withdrawal_requests
```

Las migraciones son automáticas y no requieren borrar tablas anteriores.

---

# 13. Recomendación antes de producción

Antes de aceptar campañas reales:

1. configura tu tarifa real de Stars;
2. prueba una campaña completa con cuentas/canales de prueba;
3. confirma reembolsos de Stars;
4. prueba ingreso directo y solicitud de ingreso;
5. prueba abandono antes/después de retención;
6. define tu proceso manual de liquidación de retiros;
7. conserva backups automáticos activos.

La monetización puede desactivarse completamente con:

```env
MONETIZATION_ENABLED=false
```

sin afectar las botoneras normales.


## v7.1 — Canales suspendidos

El panel administrativo incluye **⏸ Suspendidos**. Desde ahí se pueden revisar suspensiones manuales, por moderación y por permisos, recalcular miembros y quitar la suspensión. La reactivación comprueba primero que el bot conserve sus permisos, que el propietario no esté bloqueado y que el canal cumpla el mínimo de miembros.

Desde **📡 Canales** también se puede suspender manualmente un canal aprobado. La suspensión administrativa no genera una falta, elimina las publicaciones activas de ese canal, retira su botón de las botoneras y lo deshabilita como fuente de campañas pagadas.

---

# v7.2 · Promociones manuales USD y retiros USDT

La v7.2 añade una segunda modalidad de campañas patrocinadas además de las campañas pagadas con Telegram Stars.

## Promoción manual creada por administrador

Desde:

`/panel → 💰 Monetización → ➕ Promoción manual USD`

el administrador selecciona un canal objetivo aprobado y después escribe la meta de suscriptores y el presupuesto máximo en USD.

Ejemplo:

```text
Canal objetivo: Noticias Premium
Meta: 1,000
Presupuesto: $15 USD
```

La tarifa queda en `$15 / 1,000 = $0.015` por conversión verificada. Un canal fuente que produzca 400 conversiones válidas acumula `$6 USD`; otro que produzca 100 acumula `$1.50 USD`.

El presupuesto de una campaña manual es un pool máximo. Las conversiones que no superen la retención/antifraude no generan saldo.

## Activación por participante y por canal

El dueño debe activar primero el programa desde `💰 Monetización`. Después puede entrar a `📡 Mis canales → canal` y activar `💰 Monetización del canal: ON`.

Solo esos canales serán ofrecidos como fuentes cuando aparezca una nueva oportunidad.

## Retiros USDT

El saldo generado por promociones manuales se almacena en USD. El participante puede solicitar USDT cuando alcanza el mínimo configurado.

Valores por defecto:

```env
MONETIZATION_USDT_MIN_WITHDRAW_USD=50
MONETIZATION_USDT_FEE_USD=3
MONETIZATION_USDT_NETWORKS=TRC20,BEP20
```

Ejemplo de retiro:

```text
Solicitud bruta: $75 USD
Comisión: $3 USD
USDT a enviar: 72 USDT
```

El bot no realiza la transferencia cripto automáticamente. La solicitud llega al panel administrativo, donde debe aprobarse. Después de realizar manualmente la transferencia, el administrador marca el retiro como pagado.

El bot conserva por separado cualquier contabilidad antigua relacionada con campañas Stars. No convierte automáticamente Stars a USD/USDT.
