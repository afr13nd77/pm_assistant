"""Tests for shared.langfuse_client module."""

import logging

import pytest

from shared import langfuse_client


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset singleton state before each test."""
    langfuse_client._langfuse = None
    langfuse_client._init_attempted = False
    yield
    langfuse_client._langfuse = None
    langfuse_client._init_attempted = False


class TestGetLangfuseNoKey:
    """When LANGFUSE_PUBLIC_KEY is not set, client should be None."""

    def test_returns_none_without_key(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        result = langfuse_client.get_langfuse()
        assert result is None

    def test_logs_info_without_key(self, monkeypatch, caplog):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        with caplog.at_level(logging.INFO, logger="shared.langfuse_client"):
            langfuse_client.get_langfuse()
        assert "LANGFUSE_PUBLIC_KEY not set" in caplog.text


class TestGetLangfuseDisabledFlag:
    """When LANGFUSE_ENABLED is set to false, client should be None."""

    def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
        monkeypatch.setenv("LANGFUSE_ENABLED", "false")
        result = langfuse_client.get_langfuse()
        assert result is None

    def test_logs_info_when_disabled(self, monkeypatch, caplog):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
        monkeypatch.setenv("LANGFUSE_ENABLED", "False")
        with caplog.at_level(logging.INFO, logger="shared.langfuse_client"):
            langfuse_client.get_langfuse()
        assert "Langfuse disabled via LANGFUSE_ENABLED" in caplog.text

    def test_returns_none_when_disabled_uppercase(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
        monkeypatch.setenv("LANGFUSE_ENABLED", "FALSE")
        result = langfuse_client.get_langfuse()
        assert result is None


class TestGetLangfuseSingleton:
    """Singleton behavior: init only once."""

    def test_second_call_returns_cached(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        first = langfuse_client.get_langfuse()
        assert first is None
        assert langfuse_client._init_attempted is True

        # Set key after first call — should still return None (cached)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        second = langfuse_client.get_langfuse()
        assert second is None  # cached from first attempt


class TestGetLangfuseImportError:
    """When langfuse package is not installed."""

    def test_returns_none_on_import_error(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "langfuse":
                raise ImportError("No module named 'langfuse'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        result = langfuse_client.get_langfuse()
        assert result is None

    def test_logs_warning_on_import_error(self, monkeypatch, caplog):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "langfuse":
                raise ImportError("No module named 'langfuse'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        with caplog.at_level(logging.WARNING, logger="shared.langfuse_client"):
            langfuse_client.get_langfuse()
        assert "langfuse package not installed" in caplog.text


class TestGetLangfuseInitException:
    """When Langfuse() constructor raises an exception."""

    def test_returns_none_on_init_exception(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

        import builtins
        real_import = builtins.__import__

        class FakeLangfuseModule:
            class Langfuse:
                def __init__(self, **kwargs):
                    raise ConnectionError("Cannot reach Langfuse server")

        def mock_import(name, *args, **kwargs):
            if name == "langfuse":
                return FakeLangfuseModule()
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        result = langfuse_client.get_langfuse()
        assert result is None

    def test_logs_warning_on_init_exception(self, monkeypatch, caplog):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

        import builtins
        real_import = builtins.__import__

        class FakeLangfuseModule:
            class Langfuse:
                def __init__(self, **kwargs):
                    raise ConnectionError("Cannot reach Langfuse server")

        def mock_import(name, *args, **kwargs):
            if name == "langfuse":
                return FakeLangfuseModule()
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        with caplog.at_level(logging.WARNING, logger="shared.langfuse_client"):
            langfuse_client.get_langfuse()
        assert "failed to initialize Langfuse" in caplog.text


class TestShutdown:
    """Tests for shutdown() function."""

    def test_shutdown_when_no_client(self):
        """shutdown() should not raise when _langfuse is None."""
        langfuse_client._langfuse = None
        langfuse_client.shutdown()  # should not raise

    def test_shutdown_calls_flush(self, caplog):
        """shutdown() should call flush on the client."""

        class MockLangfuse:
            flushed = False

            def flush(self):
                MockLangfuse.flushed = True

        langfuse_client._langfuse = MockLangfuse()
        with caplog.at_level(logging.INFO, logger="shared.langfuse_client"):
            langfuse_client.shutdown()
        assert MockLangfuse.flushed is True
        assert "flushed successfully" in caplog.text

    def test_shutdown_handles_flush_error(self, caplog):
        """shutdown() should not raise even if flush fails."""

        class MockLangfuse:
            def flush(self):
                raise RuntimeError("flush exploded")

        langfuse_client._langfuse = MockLangfuse()
        with caplog.at_level(logging.WARNING, logger="shared.langfuse_client"):
            langfuse_client.shutdown()  # should not raise
        assert "flush failed" in caplog.text
