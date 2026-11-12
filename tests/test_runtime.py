# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

"""Offline regressions for real PTB construction and process-local DNS routing."""
import os
os.environ['PYTHON_DOTENV_DISABLED'] = '1'

import socket

import pytest
from telegram.ext import Application
from telegram.request import HTTPXRequest

from relayapp import network, runtime


@pytest.mark.asyncio
async def test_build_application_uses_distinct_real_requests_without_network(monkeypatch):
    def forbid_resolution(*args, **kwargs):
        raise AssertionError('Application construction must not resolve DNS')
    async def forbid_api(*args, **kwargs):
        raise AssertionError('Application construction must not call Telegram')
    monkeypatch.setattr(socket, 'getaddrinfo', forbid_resolution)
    monkeypatch.setattr(HTTPXRequest, 'do_request', forbid_api)
    monkeypatch.setattr(runtime, 'MAIN_BOT_TOKEN', '123456:SYNTHETIC_ONLY_NOT_A_REAL_TOKEN_123456')
    app = runtime.build_application()
    try:
        assert isinstance(app, Application)
        assert app.running is False
        assert app.updater.running is False
        assert app.concurrent_updates == 1
        polling_request, api_request = app.bot._request
        assert isinstance(polling_request, HTTPXRequest)
        assert isinstance(api_request, HTTPXRequest)
        assert app.bot.request is api_request
        assert polling_request is not api_request
        assert polling_request.read_timeout >= 35
        assert api_request.read_timeout >= 35
    finally:
        # HTTPX clients are real but never initialized or connected.
        for request in app.bot._request:
            await request.shutdown()


@pytest.fixture
def resolver(monkeypatch):
    calls = []
    def original(host, port, family=0, type=0, proto=0, flags=0):
        calls.append((host, port, family, type, proto, flags))
        return [(family, type, proto, 'synthetic', (host, port))]
    monkeypatch.setattr(network, '_original_getaddrinfo', original)
    monkeypatch.setattr(socket, 'getaddrinfo', original)
    monkeypatch.delenv('TELEGRAM_API_IPS', raising=False)
    return original, calls


@pytest.mark.parametrize('raw', ['', '   ', ' , , '])
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

def test_dns_without_addresses_does_not_replace_resolver(monkeypatch, resolver, raw):
    original, calls = resolver
    monkeypatch.setenv('TELEGRAM_API_IPS', raw)
    assert network.configure_telegram_dns() == []
    assert socket.getaddrinfo is original
    assert calls == []


@pytest.mark.parametrize('host', ['api.telegram.org', 'API.TELEGRAM.ORG.', b'api.telegram.org'])
def test_dns_override_matches_only_telegram_host_and_preserves_call_options(monkeypatch, resolver, host):
    original, calls = resolver
    monkeypatch.setenv('TELEGRAM_API_IPS', '192.0.2.10,2001:db8::10')
    assert network.configure_telegram_dns() == ['192.0.2.10', '2001:db8::10']
    rows = socket.getaddrinfo(host, 443, socket.AF_UNSPEC, socket.SOCK_STREAM, socket.IPPROTO_TCP, socket.AI_NUMERICHOST)
    assert calls == [
        ('192.0.2.10', 443, socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, socket.AI_NUMERICHOST),
        ('2001:db8::10', 443, socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, socket.AI_NUMERICHOST),
    ]
    assert len(rows) == 2


@pytest.mark.parametrize('family,address', [(socket.AF_INET, '192.0.2.10'), (socket.AF_INET6, '2001:db8::10')])
def test_dns_filters_requested_address_family(monkeypatch, resolver, family, address):
    original, calls = resolver
    monkeypatch.setenv('TELEGRAM_API_IPS', '192.0.2.10,2001:db8::10')
    network.configure_telegram_dns()
    rows = socket.getaddrinfo('api.telegram.org', 443, family, socket.SOCK_STREAM)
    assert calls == [(address, 443, family, socket.SOCK_STREAM, 0, 0)]
    assert rows[0][-1] == (address, 443)


@pytest.mark.parametrize('host', ['example.org', 'api.telegram.org.example.org', 'telegram.org', b'example.org', None])
def test_dns_other_hosts_pass_through_unchanged(monkeypatch, resolver, host):
    original, calls = resolver
    monkeypatch.setenv('TELEGRAM_API_IPS', '192.0.2.10')
    network.configure_telegram_dns()
    rows = socket.getaddrinfo(host, 'https', socket.AF_INET6, socket.SOCK_DGRAM, 17, 4)
    assert calls == [(host, 'https', socket.AF_INET6, socket.SOCK_DGRAM, 17, 4)]
    assert rows == [(socket.AF_INET6, socket.SOCK_DGRAM, 17, 'synthetic', (host, 'https'))]


@pytest.mark.parametrize('raw,family', [('192.0.2.10', socket.AF_INET6), ('2001:db8::10', socket.AF_INET)])
def test_dns_missing_requested_family_raises_without_system_fallback(monkeypatch, resolver, raw, family):
    original, calls = resolver
    monkeypatch.setenv('TELEGRAM_API_IPS', raw)
    network.configure_telegram_dns()
    with pytest.raises(socket.gaierror) as exc:
        socket.getaddrinfo('api.telegram.org', 443, family)
    assert exc.value.errno == socket.EAI_NONAME
    assert calls == []


@pytest.mark.parametrize('raw', ['not-an-ip', '192.0.2.999', '192.0.2.10,invalid', 'https://192.0.2.10', '[2001:db8::10]'])
def test_dns_invalid_address_rejected_before_resolver_is_replaced(monkeypatch, resolver, raw):
    original, calls = resolver
    monkeypatch.setenv('TELEGRAM_API_IPS', raw)
    with pytest.raises(ValueError):
        network.configure_telegram_dns()
    assert socket.getaddrinfo is original
    assert calls == []

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
