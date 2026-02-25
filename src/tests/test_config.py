"""Tests for src/config.py."""

from src.config import settings


class TestSettings:
    def test_es_url_format(self):
        expected = f"{settings.ES_SCHEME}://{settings.ES_HOST}:{settings.ES_PORT}"
        assert settings.es_url == expected

    def test_es_url_contains_host(self):
        assert settings.ES_HOST in settings.es_url

    def test_es_url_contains_port(self):
        assert str(settings.ES_PORT) in settings.es_url
