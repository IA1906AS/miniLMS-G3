"""Unit tests for the SMTP transport used by password reset and the outbox."""

import pytest

from app import emailer


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.credentials = None
        self.messages = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.credentials = (username, password)

    def send_message(self, message):
        self.messages.append(message)


@pytest.fixture(autouse=True)
def _reset_instances():
    FakeSMTP.instances = []


def base_config(**overrides):
    config = {"SMTP_HOST": "smtp.test", "SMTP_FROM": "noreply@lms.test"}
    config.update(overrides)
    return config


def test_send_email_uses_starttls_and_credentials(monkeypatch):
    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)
    emailer.send_email(
        base_config(SMTP_PORT="2525", SMTP_USERNAME="user", SMTP_PASSWORD="secret"),
        "sv@lms.test",
        "Chủ đề",
        "Nội dung",
        event_id="evt-1",
    )

    client = FakeSMTP.instances[0]
    assert (client.host, client.port) == ("smtp.test", 2525)
    assert client.started_tls is True
    assert client.credentials == ("user", "secret")
    message = client.messages[0]
    assert message["To"] == "sv@lms.test"
    assert message["Subject"] == "Chủ đề"
    assert message["Message-ID"] == "<evt-1@lms.local>"


def test_send_email_without_message_id_leaves_header_empty(monkeypatch):
    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)
    emailer.send_email(base_config(), "sv@lms.test", "Chủ đề", "Nội dung")
    assert FakeSMTP.instances[0].messages[0]["Message-ID"] is None


def test_send_email_uses_implicit_tls_when_configured(monkeypatch):
    monkeypatch.setattr(emailer.smtplib, "SMTP_SSL", FakeSMTP)
    emailer.send_email(base_config(SMTP_USE_SSL=True, SMTP_USE_TLS=False), "sv@lms.test", "S", "B")
    client = FakeSMTP.instances[0]
    assert client.started_tls is False
    assert client.credentials is None


def test_missing_smtp_configuration_raises_runtime_error():
    with pytest.raises(RuntimeError, match="SMTP_HOST and SMTP_FROM"):
        emailer.send_email({"SMTP_FROM": "a@b.c"}, "sv@lms.test", "S", "B")
    with pytest.raises(RuntimeError, match="SMTP_HOST and SMTP_FROM"):
        emailer.send_password_reset_email({}, "sv@lms.test", "https://lms.test/r")


def test_password_reset_email_contains_reset_link(monkeypatch):
    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)
    emailer.send_password_reset_email(
        base_config(), "sv@lms.test", "https://lms.test/reset-password?token=abc"
    )
    body = FakeSMTP.instances[0].messages[0].get_content()
    assert "https://lms.test/reset-password?token=abc" in body
    assert "30 phút" in body
