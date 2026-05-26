"""Tests for sender module."""

from unittest.mock import patch, MagicMock

from opencold import sender


class TestSendEmail:
    SMTP_CONFIG = {
        "host": "smtp.test.com",
        "port": 587,
        "username": "user@test.com",
        "password": "pass123",
        "sender_email": "user@test.com",
        "sender_name": "Test User",
        "use_tls": True,
    }

    @patch("opencold.sender.smtplib.SMTP")
    def test_sends_via_starttls(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        sender.send_email(
            self.SMTP_CONFIG,
            "alice@acme.com",
            "Alice Smith",
            "Hello",
            "Email body here.",
        )

        mock_smtp_cls.assert_called_once_with("smtp.test.com", 587)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user@test.com", "pass123")
        mock_server.send_message.assert_called_once()

    @patch("opencold.sender.smtplib.SMTP_SSL")
    def test_sends_via_ssl(self, mock_smtp_ssl_cls):
        mock_server = MagicMock()
        mock_smtp_ssl_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_ssl_cls.return_value.__exit__ = MagicMock(return_value=False)

        ssl_config = {**self.SMTP_CONFIG, "port": 465, "use_tls": True}
        sender.send_email(
            ssl_config,
            "bob@acme.com",
            "Bob Jones",
            "Test",
            "Body.",
        )

        mock_smtp_ssl_cls.assert_called_once()
        mock_server.login.assert_called_once_with("user@test.com", "pass123")
        mock_server.send_message.assert_called_once()

    @patch("opencold.sender.smtplib.SMTP")
    def test_sends_without_tls(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        no_tls_config = {**self.SMTP_CONFIG, "use_tls": False}
        sender.send_email(
            no_tls_config,
            "alice@acme.com",
            "Alice",
            "Subject",
            "Body.",
        )

        mock_server.starttls.assert_not_called()
        mock_server.login.assert_called_once()


class TestTestConnection:
    SMTP_CONFIG = {
        "host": "smtp.test.com",
        "port": 587,
        "username": "user@test.com",
        "password": "pass123",
        "sender_email": "user@test.com",
        "use_tls": True,
    }

    @patch("opencold.sender.smtplib.SMTP")
    def test_success_returns_none(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = sender.test_connection(self.SMTP_CONFIG)
        assert result is None

    @patch("opencold.sender.smtplib.SMTP")
    def test_failure_returns_error_message(self, mock_smtp_cls):
        mock_smtp_cls.side_effect = ConnectionRefusedError("Connection refused")

        result = sender.test_connection(self.SMTP_CONFIG)
        assert result is not None
        assert "refused" in result.lower()
