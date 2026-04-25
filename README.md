# Bot de Telegram — Tienda de Streaming

Bot de Telegram para vender suscripciones de plataformas de streaming (Netflix,
Prime Video, Disney+, HBO Max, Spotify, etc.) con **cobro manual fuera del bot**.

El cliente:

1. Abre el catálogo y elige un servicio y un plan.
2. Recibe las instrucciones de pago (PayPal, transferencia, Binance Pay, etc.,
   configurables).
3. Envía el comprobante por el chat.
4. Recibe automáticamente las credenciales una vez que un administrador aprueba
   el pedido.

El admin gestiona todo desde Telegram: añadir servicios, planes, stock,
revisar pagos, aprobar/rechazar pedidos, ver estadísticas y enviar broadcasts.

> ⚠️ **Importante:** este bot está pensado para que vendas únicamente cuentas
> que tienes legalmente (suscripciones oficiales o planes familiares
> compartidos respetando los términos del servicio). El autor del código no se
> responsabiliza del uso que se le dé.

---

## 1. Requisitos

- Python 3.10+
- Una cuenta de Telegram y un bot creado con [@BotFather](https://t.me/BotFather)
- Tu Telegram ID numérico (lo puedes ver con [@userinfobot](https://t.me/userinfobot))

## 2. Instalación

```bash
# Crear entorno virtual (opcional pero recomendado)
python -m venv .venv
source .venv/bin/activate   # en Windows: .venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Copiar y editar la configuración
cp .env.example .env
# edita .env con tu BOT_TOKEN, ADMIN_IDS, métodos de pago, etc.
```

## 3. (Opcional) Cargar catálogo de ejemplo

```bash
python -m scripts.seed
```

Esto crea Netflix, Prime Video, Disney+, HBO Max y Spotify con planes
predefinidos. Después puedes editar todo desde Telegram con `/admin`.

## 4. Ejecutar el bot

```bash
python main.py
```

En Telegram, abre tu bot y envía `/start`.

---

## 5. Comandos del cliente

| Comando | Descripción |
|---|---|
| `/start` | Menú principal |
| `/catalogo` | Ver servicios disponibles |
| `/pedidos` | Ver tus pedidos |
| `/soporte` | Contactar a un administrador |
| `/help` | Ayuda |

El cliente también puede usar los botones del teclado (Catálogo / Mis pedidos
/ Soporte / Ayuda).

## 6. Comandos de administrador

Solo funcionan para los IDs listados en `ADMIN_IDS` del `.env`.

### Catálogo
- `/admin` — panel con la lista completa de comandos
- `/addservice <nombre> <emoji> [descripción]` — crear servicio
- `/listservices` — listar servicios
- `/editservice <id> <emoji> <nombre>` — renombrar / cambiar emoji
- `/delservice <id>` — eliminar servicio (soft, mantiene historial)
- `/addplan <service_id> <días> <precio> <nombre>` — crear plan
- `/listplans <service_id>` — listar planes con stock
- `/editprice <plan_id> <precio>` — cambiar precio sin recrear el plan
- `/editplan <plan_id> <días> <nombre>` — cambiar duración / nombre
- `/delplan <id>` — eliminar plan (soft)
- `/enableplan <id>` / `/disableplan <id>` — activar/desactivar

### Stock
- `/addstock <plan_id>` — entrar en modo añadir credenciales. Cada mensaje
  (o cada línea de un mensaje) se guarda como una credencial. Termina con
  `/done`. Aborta con `/cancel`.
- **Alertas automáticas**: cuando el stock de un plan cae a ≤ 2 unidades
  después de una venta, el bot avisa a todos los administradores para que
  repongan antes de quedarse sin stock.

### Pedidos
- `/orders` — listar pedidos en revisión
- `/order <id>` — ver detalle de un pedido
- `/expiring` — pedidos que vencen en los próximos 7 días
- Cuando un cliente envía un comprobante, el bot te envía el pedido con
  botones **✅ Aprobar y entregar** y **🚫 Rechazar**. Al aprobar se toma la
  primera credencial libre del stock y se envía al cliente automáticamente.
- **Recordatorio automático de renovación**: el bot avisa al cliente 3 días
  antes del vencimiento de su suscripción para invitarlo a renovar.

### Clientes / soporte
- `/searchuser <id|@username|nombre>` — buscar clientes
- `/orderhistory <user_id>` — todos los pedidos de un cliente
- `/reply <telegram_id> <mensaje>` — responder a un cliente sin abrir
  su chat manualmente
- Cuando un cliente envía un mensaje libre (no comando), el bot lo guarda
  y te lo reenvía con un botón listo para responder con `/reply`.

### FAQ / soporte automático
- `/addfaq <pregunta> | <respuesta> | <palabras,clave>` — crear respuesta
  automática. Si un cliente escribe un mensaje que contiene alguna de las
  palabras clave, el bot responde automáticamente sin esperar al admin.
- `/listfaq` — listar todas las FAQs
- `/delfaq <id>` — eliminar una FAQ
- Los clientes pueden ver el listado completo con `/faq`.

### General
- `/stats` — usuarios, servicios, planes, stock, pedidos e ingresos
- `/broadcast <mensaje>` — envía un mensaje a todos los usuarios

---

## 7. Flujo de un pedido

```
Cliente: /start
Cliente: 🛍 Catálogo → Netflix → 1 Mes Perfil → 🛒 Comprar
Bot:     🧾 Pedido #12 creado. Total 4.50 USD. Métodos de pago: ...
Cliente: [envía foto del comprobante]
Bot:     ✅ Comprobante recibido para el pedido #12, en revisión.
Admin:   [recibe notificación con foto reenviada y botones]
Admin:   pulsa ✅ Aprobar y entregar
Bot →    📦 entrega credenciales al cliente y deja el pedido como entregado.
```

---

## 8. Estructura del proyecto

```
streaming-bot/
├── main.py                  # punto de entrada
├── config.py                # carga de .env
├── requirements.txt
├── .env.example
├── README.md
├── bot/
│   ├── keyboards.py         # botones inline y reply
│   ├── db/
│   │   ├── database.py      # motor SQLAlchemy / sesiones
│   │   └── models.py        # User, Service, Plan, StockItem, Order
│   ├── services/
│   │   ├── catalog_service.py
│   │   └── order_service.py
│   └── handlers/
│       ├── start.py         # /start, /help, soporte, router del menú
│       ├── catalog.py       # navegación del catálogo
│       ├── orders.py        # flujo de compra del cliente
│       └── admin.py         # comandos admin + revisión de pedidos
└── scripts/
    └── seed.py              # carga catálogo de ejemplo
```

## 9. Despliegue

Para mantener el bot 24/7 puedes usar:

- **systemd** (en un VPS Linux): crea un service que lance `python main.py`.
- **Docker**: cualquier imagen base de `python:3.11-slim` sirve. Ejemplo
  mínimo:

  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY requirements.txt ./
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  CMD ["python", "main.py"]
  ```

- **Servicios PaaS**: Railway, Fly.io, Render, etc. Solo recuerda montar
  un volumen persistente para `shop.db` (o usar Postgres cambiando
  `DATABASE_URL`).

## 10. Cambiar a Postgres / MySQL

Solo cambia `DATABASE_URL` en el `.env`, por ejemplo:

```
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname
```

E instala el driver correspondiente (`psycopg2-binary`, `pymysql`, etc.).
SQLAlchemy se encarga del resto.

---

## Licencia

Uso libre para tu negocio. Eres responsable del cumplimiento legal de las
ventas que realices con este bot.
