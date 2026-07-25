import unittest

from bot.premium_emoji import (
    delivery_message,
    premium_emoji,
    without_custom_emoji,
)
from config import Settings


class PremiumEmojiTests(unittest.TestCase):
    def test_uses_unicode_when_id_is_missing(self):
        settings = Settings(bot_token="test")
        self.assertEqual(premium_emoji(settings, "success", "🎉"), "🎉")

    def test_builds_custom_emoji_html(self):
        settings = Settings(
            bot_token="test",
            premium_emoji_success_id="123456789",
        )
        self.assertEqual(
            premium_emoji(settings, "success", "🎉"),
            '<tg-emoji emoji-id="123456789">🎉</tg-emoji>',
        )

    def test_delivery_escapes_credentials(self):
        settings = Settings(bot_token="test")
        text = delivery_message(
            settings,
            order_id=42,
            product="Netflix <Premium>",
            credentials="user@example.com\npass<&>",
            expires="2026-08-24",
        )
        self.assertIn("Netflix &lt;Premium&gt;", text)
        self.assertIn("pass&lt;&amp;&gt;", text)
        self.assertNotIn("pass<&>", text)

    def test_fallback_removes_only_custom_emoji_tags(self):
        text = '<tg-emoji emoji-id="123">🎉</tg-emoji> <b>Entregado</b>'
        self.assertEqual(
            without_custom_emoji(text),
            "🎉 <b>Entregado</b>",
        )


if __name__ == "__main__":
    unittest.main()
