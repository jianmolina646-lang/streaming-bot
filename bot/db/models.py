"""Modelos de la base de datos."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    balance: Mapped[float] = mapped_column(default=0.0)
    # Referidos
    ref_code: Mapped[str | None] = mapped_column(String(16), unique=True, nullable=True)
    referred_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    # VIP: 0=normal, 1=plata (5%), 2=oro (10%)
    vip_level: Mapped[int] = mapped_column(Integer, default=0)
    # Nota interna sólo visible para admin
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    orders: Mapped[list["Order"]] = relationship(back_populates="user")


class WalletTransaction(Base):
    """Historial de movimientos de saldo del cliente."""

    __tablename__ = "wallet_transactions"

    KIND_TOPUP = "topup"
    KIND_PURCHASE = "purchase"
    KIND_REFUND = "refund"
    KIND_ADJUST = "adjust"
    KIND_REFERRAL = "referral"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column(default=0.0)
    kind: Mapped[str] = mapped_column(String(16), default=KIND_TOPUP)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Service(Base):
    """Una plataforma de streaming (Netflix, Prime, etc.)."""

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    emoji: Mapped[str] = mapped_column(String(8), default="🎬")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    plans: Mapped[list["Plan"]] = relationship(
        back_populates="service", cascade="all, delete-orphan"
    )


class Plan(Base):
    """Un plan vendible dentro de un servicio (ej. Netflix 1 mes perfil)."""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(96))
    duration_days: Mapped[int] = mapped_column(Integer, default=30)
    price: Mapped[float] = mapped_column(default=0.0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    service: Mapped[Service] = relationship(back_populates="plans")
    stock: Mapped[list["StockItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    orders: Mapped[list["Order"]] = relationship(back_populates="plan")


class StockItem(Base):
    """Una credencial disponible para entregar (correo:contraseña, perfil, pin)."""

    __tablename__ = "stock"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    credentials: Mapped[str] = mapped_column(Text)
    is_sold: Mapped[bool] = mapped_column(Boolean, default=False)
    tag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    plan: Mapped[Plan] = relationship(back_populates="stock")


class Order(Base):
    """Un pedido del cliente."""

    __tablename__ = "orders"

    STATUS_PENDING_PAYMENT = "pending_payment"
    STATUS_AWAITING_REVIEW = "awaiting_review"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_DELIVERED = "delivered"
    STATUS_EXPIRED = "expired"
    STATUS_REFUNDED = "refunded"

    PAY_METHOD_MANUAL = "manual"
    PAY_METHOD_WALLET = "wallet"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[str] = mapped_column(String(32), default=STATUS_PENDING_PAYMENT)
    price: Mapped[float] = mapped_column(default=0.0)
    discount_amount: Mapped[float] = mapped_column(default=0.0)
    coupon_id: Mapped[int | None] = mapped_column(
        ForeignKey("coupons.id"), nullable=True
    )
    payment_method: Mapped[str] = mapped_column(String(16), default=PAY_METHOD_MANUAL)
    proof_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    proof_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delivered_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expiry_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expiry_reminded_24h_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expired_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cut_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    automation_stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped[User] = relationship(back_populates="orders")
    plan: Mapped[Plan] = relationship(back_populates="orders")


class AutomationAgent(Base):
    """Agente local emparejado. El token se almacena únicamente como hash."""

    __tablename__ = "automation_agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    capabilities: Mapped[str] = mapped_column(Text, default="[]")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AutomationJob(Base):
    """Trabajo de automatización vinculado inequívocamente a un pedido."""

    __tablename__ = "automation_jobs"

    STATUS_QUEUED = "queued"
    STATUS_CLAIMED = "claimed"
    STATUS_RUNNING = "running"
    STATUS_NEEDS_ATTENTION = "needs_attention"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True, index=True)
    stock_item_id: Mapped[int] = mapped_column(ForeignKey("stock.id"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("automation_agents.id"), nullable=True, index=True)
    service: Mapped[str] = mapped_column(String(32), default="netflix")
    action: Mapped[str] = mapped_column(String(40), default="create_profile")
    profile_name: Mapped[str] = mapped_column(String(80))
    profile_pin_hash: Mapped[str] = mapped_column(String(64))
    profile_pin_encrypted: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=STATUS_QUEUED, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str] = mapped_column(Text, default="{}")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Faq(Base):
    """Pregunta y respuesta del soporte automatizado."""

    __tablename__ = "faqs"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(String(256))
    answer: Mapped[str] = mapped_column(Text)
    keywords: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SupportMessage(Base):
    """Mensaje de soporte enviado por un cliente y reenviado a admins."""

    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    message_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Coupon(Base):
    """Cupón de descuento aplicable a una compra."""

    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # Si discount_percent > 0 se aplica %, si no se aplica monto fijo.
    discount_percent: Mapped[float] = mapped_column(default=0.0)
    discount_amount: Mapped[float] = mapped_column(default=0.0)
    max_uses: Mapped[int] = mapped_column(Integer, default=0)  # 0 = ilimitado
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WarrantyTicket(Base):
    """Reporte de garantía: el cliente dice que su credencial dejó de funcionar."""

    __tablename__ = "warranty_tickets"

    STATUS_OPEN = "open"
    STATUS_RESOLVED = "resolved"
    STATUS_REJECTED = "rejected"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_OPEN)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Review(Base):
    """Calificación post-entrega del cliente."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    rating: Mapped[int] = mapped_column(Integer, default=5)  # 1..5
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WaitlistEntry(Base):
    """Cliente que pidió aviso cuando vuelva el stock de un plan."""

    __tablename__ = "waitlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RuntimeConfig(Base):
    """Configuraciones que se pueden cambiar sin reiniciar el bot.

    Llaves útiles:
      - maintenance_mode: "1" / "0"
      - payment_instructions: texto que sobreescribe al .env
      - shop_name: texto que sobreescribe al .env
      - promo_text: banner que aparece arriba del catálogo
    """

    __tablename__ = "runtime_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
