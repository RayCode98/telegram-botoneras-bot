# Changelog v7.2.0

## Promoción manual desde administración

- Nuevo botón `➕ Promoción manual USD` dentro de Administración → Monetización.
- El administrador selecciona un canal objetivo registrado/aprobado.
- Después introduce:
  - meta de suscriptores;
  - presupuesto máximo en USD.
- La campaña entra directamente a `recruiting`, sin factura Stars, porque es una campaña cargada manualmente por el administrador.
- Respeta el periodo de reclutamiento configurado por `MONETIZATION_OPPORTUNITY_HOURS`.
- Utiliza el modo de ingreso configurado en el canal objetivo: ingreso directo o solicitud de ingreso.
- El presupuesto USD completo se usa como pool máximo para participantes; no se aplica la comisión de plataforma de Stars a estas campañas.
- La tarifa por conversión verificada es `presupuesto / meta`.
- Solo conversiones verificadas después del periodo de retención acreditan saldo USD.

## Opt-in de monetización por canal

- El participante mantiene un opt-in global desde `💰 Monetización`.
- Además, cada canal tiene ahora su propio switch `💰 Monetización del canal: ON/OFF` en `📡 Mis canales`.
- Solo canales aprobados, operativos, con opt-in global activo y con el switch del canal activo aparecen como fuentes elegibles.
- Desactivar monetización de un canal lo retira inmediatamente de fuentes patrocinadas activas, sin generar sanción.

## Monedero USD y retiros USDT

- Nuevo saldo USD separado del saldo legado Stars-equivalente.
- Nuevo flujo de retiro por USDT:
  1. participante indica el importe bruto;
  2. selecciona red;
  3. proporciona dirección;
  4. confirma solicitud;
  5. administrador recibe y revisa;
  6. administrador aprueba/rechaza;
  7. tras realizar la transferencia puede marcarla como pagada.
- Retiro mínimo por defecto: `$50 USD`.
- Comisión fija por defecto: `$3 USD`.
- El importe que se envía en USDT es `bruto - comisión`.
- Una solicitud pendiente o aprobada reserva el saldo para impedir retiros duplicados.
- Si se rechaza, el saldo bruto vuelve a estar disponible.
- Redes configurables con `MONETIZATION_USDT_NETWORKS`.

## Explicación de monetización

- El panel `💰 Monetización` explica directamente cómo funciona el programa.
- También incluye un botón `ℹ️ Cómo funciona` con explicación ampliada.

## Compatibilidad

- Migración automática desde v7.1.
- No es necesario borrar `botoneras.sqlite3`.
- Las campañas Stars y su contabilidad anterior siguen funcionando.
- El saldo Stars-equivalente se mantiene separado del saldo USD para no aplicar una conversión financiera arbitraria.
