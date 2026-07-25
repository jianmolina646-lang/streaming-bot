import unittest

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bot.db.models import Base, Order, Plan, Service, StockItem, User
from bot.services.automation_service import (
    create_profile_job,
    decrypt_profile_pin,
    is_automation_stock,
)


class AutomationServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        user = User(telegram_id=1001, username="juan", full_name="Juan Pérez")
        service = Service(name="Netflix")
        plan = Plan(service=service, name="Perfil", duration_days=30, price=10)
        stock = StockItem(
            plan=plan,
            credentials="opaque-account-reference",
            tag="agent-netflix",
        )
        order = Order(user=user, plan=plan, price=10)
        self.session.add_all([user, service, plan, stock, order])
        self.session.commit()
        self.order = order
        self.stock = stock
        self.key = Fernet.generate_key().decode()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_tag_controls_agent_eligibility(self):
        self.assertTrue(is_automation_stock(self.stock))
        self.stock.tag = "manual"
        self.assertFalse(is_automation_stock(self.stock))

    def test_job_is_bound_to_order_and_stock_and_pin_is_encrypted(self):
        job = create_profile_job(
            self.session,
            order=self.order,
            stock_item=self.stock,
            encryption_key=self.key,
            profile_name="Juan",
            profile_pin="4025",
        )
        self.assertEqual(job.order_id, self.order.id)
        self.assertEqual(job.stock_item_id, self.stock.id)
        self.assertNotIn("4025", job.profile_pin_encrypted)
        self.assertEqual(decrypt_profile_pin(job, self.key), "4025")
        self.assertEqual(self.order.status, Order.STATUS_APPROVED)

    def test_creating_same_order_twice_is_idempotent(self):
        first = create_profile_job(
            self.session, order=self.order, stock_item=self.stock,
            encryption_key=self.key, profile_pin="4025",
        )
        second = create_profile_job(
            self.session, order=self.order, stock_item=self.stock,
            encryption_key=self.key, profile_pin="9999",
        )
        self.assertEqual(first.id, second.id)
        self.assertEqual(decrypt_profile_pin(second, self.key), "4025")

    def test_manual_stock_is_rejected(self):
        self.stock.tag = "manual"
        with self.assertRaisesRegex(ValueError, "habilitado"):
            create_profile_job(
                self.session, order=self.order, stock_item=self.stock,
                encryption_key=self.key, profile_pin="4025",
            )


if __name__ == "__main__":
    unittest.main()
