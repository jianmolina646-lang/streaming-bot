# Actualización a v4 — pack avanzado

Esta versión **mantiene todo lo de v3** (saldo, vencimiento, corte) y le suma
13 paquetes nuevos: cupones, garantía/reembolso, referidos, reseñas, lista de
espera, VIP, modo mantenimiento, broadcast filtrado, reportes, exportación,
renovación 1-click y más.

## Cómo actualizar (mismo procedimiento de siempre)

1. **Detén el bot** (`Ctrl+C` en la terminal donde corre `main.py`).
2. **Descomprime el ZIP nuevo** y copia los archivos sobre el proyecto actual,
   reemplazando los viejos. **NO borres `.env` ni `shop.db`** — son tus datos.
3. **Reinstala dependencias** (no hay nuevas, por seguridad):
   ```powershell
   .venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
   ```
4. **Arranca**:
   ```powershell
   .venv\Scripts\python.exe main.py
   ```
   La primera vez añade las columnas y tablas nuevas. No pierdes nada.

---

## 🆕 Lo que trae v4

### 🎟 Cupones de descuento
- **Admin**:
  - `/addcoupon CÓDIGO % o monto [max_usos] [días_validez]`
    - Ej. con porcentaje: `/addcoupon NETFLIX20 20% 50 30` → 20%, 50 usos, 30 días.
    - Ej. con monto fijo: `/addcoupon AMIGOS 5 100 7` → −S/ 5, 100 usos, 7 días.
  - `/listcoupons` — todos los cupones, usos y vencimiento.
  - `/delcoupon <id>` — borra un cupón.
- **Cliente**: `/cupon NETFLIX20` antes de comprar y el descuento se aplica solo en la siguiente compra.

### 🎁 Garantía y reembolso
- **Cliente**: `/garantia <pedido_id>` abre un ticket si su cuenta dejó de funcionar.
- **Admin**:
  - `/tickets` lista los tickets abiertos.
  - `/replace <pedido_id>` entrega una credencial nueva del stock al cliente
    (reposición, sin tocar saldo).
  - `/refund <pedido_id>` devuelve el monto al saldo del cliente y la
    credencial al stock para que la puedas revender.
  - `/resolveticket <id>` cierra un ticket (también se cierran solos al hacer
    `/replace` o `/refund`).

### 👥 Referidos con comisión
- Cada cliente tiene un **link único**: `t.me/TuBot?start=REF1AB23C`.
- Cuando alguien entra con ese link y hace su **primera compra**, el referidor
  recibe **10%** del valor en saldo (ajustable en `referral_service.py`).
- Cliente: `/referidos` muestra su link, total de referidos invitados y
  comisiones acumuladas.

### ⭐ Reseñas
- Después de cada entrega, el bot le pregunta al cliente: "¿Cómo te fue?"
  con botones de 1 a 5 estrellas (puede saltarlo).
- **Admin**: `/reviews` muestra el promedio y las últimas reseñas con comentarios.

### 👤 Gestión de clientes
- `/blockuser <tg_id>` y `/unblock <tg_id>` — bloquea estafadores.
  Los bloqueados no pueden comprar.
- `/note <tg_id> <texto>` — guarda nota interna del cliente (sólo admin la ve).
- `/vip <tg_id> <0|1|2>` — niveles VIP automáticos:
  - 0 = normal (sin descuento)
  - 1 = Plata (5% descuento automático en cada compra)
  - 2 = Oro (10% descuento automático)

> Los descuentos VIP y de cupón **se acumulan**: primero VIP, luego cupón.

### 🔔 Lista de espera ("Avisarme cuando regrese")
- Cuando un plan está sin stock, el cliente ya no ve "⛔ Sin stock", ve un
  botón **"🔔 Avisarme cuando regrese"**.
- Cuando el admin agrega stock con `/addstock` o `/bulkstock`, el bot le manda
  automáticamente un mensaje a todos los que estaban esperando.

### 🔄 Renovación 1-click
- Los avisos de vencimiento (3 días antes y el día mismo) ahora incluyen un
  botón **"🔄 Renovar ahora"** que lleva directo al detalle del plan, listo
  para comprar (saldo o pago manual).

### 📦 Stock avanzado
- `/bulkstock <plan_id>` igual que `/addstock` pero también acepta un archivo
  `.txt` adjunto con muchas cuentas (una por línea). Ideal para cargar 100+ de
  golpe.
- `/stocklist <plan_id>` muestra todas las credenciales del plan: cuáles están
  disponibles y cuáles se vendieron.
- `/delstock <stock_id>` elimina una credencial mala antes de venderla.

### 📣 Marketing
- `/broadcast_service <service_id> <mensaje>` — envío sólo a quienes
  compraron ese servicio. (`/broadcast` clásico sigue mandando a todos.)
- `/promo <texto>` — muestra un banner arriba del catálogo (ej.
  `/promo 🔥 -20% en Netflix sólo hoy`). Borrarlo: `/promo off`.

### 📊 Reportes
- `/stats hoy` `/stats semana` `/stats mes` — métricas filtradas por período.
- `/topservices` — top servicios por número de ventas.
- `/topclientes` — top clientes por monto gastado.
- `/export` — exporta un CSV con todos los pedidos para abrirlo en Excel.

### ⚙ Configuración runtime
- `/maintenance on` — pausa todas las compras nuevas (los clientes ven un
  mensaje "🛠 Tienda en mantenimiento"). `/maintenance off` para reactivar.
- `/setpayment <texto>` — sobrescribe en vivo las instrucciones de pago.
  `/setpayment off` para volver al `.env`.
- `/setshop <texto>` — cambia el nombre/banner de la tienda. `/setshop off`
  para volver al `.env`.

---

## Ejemplos rápidos

**Cupón con 30% por una semana**:
```
/addcoupon BLACKFRIDAY 30% 200 7
```
El cliente: `/cupon BLACKFRIDAY` y compra. Verá el desglose con VIP +
cupón aplicado.

**Marcar un cliente como Oro**:
```
/vip 555666777 2
```
A partir de ahora compra siempre con −10% automático.

**Reposición por garantía**:
```
/replace 42
```
El cliente recibe una nueva credencial del stock con la misma fecha de
vencimiento original.

**Reembolso**:
```
/refund 42
```
El monto vuelve al saldo del cliente y la credencial regresa al stock.

**Modo mantenimiento mientras reorganizas inventario**:
```
/maintenance on
... agregas/limpias stock ...
/maintenance off
```

---

## Migración

Todas las columnas y tablas nuevas se crean automáticamente al arrancar.
No tienes que tocar la base de datos manualmente. Tus pedidos, saldos,
clientes y stock viejos siguen tal cual.
