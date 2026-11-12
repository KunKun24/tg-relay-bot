# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

"""Optional process-local Telegram DNS override; URL hostname and TLS verification stay intact."""
from __future__ import annotations

import ipaddress
import os
import socket

_original_getaddrinfo = socket.getaddrinfo


def configure_telegram_dns():
    """Override only api.telegram.org when explicitly configured, never the system resolver."""
    raw = os.getenv('TELEGRAM_API_IPS', '').strip()
    addresses = [str(ipaddress.ip_address(part.strip())) for part in raw.split(',') if part.strip()]
    if not addresses:
        return []
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询


    def resolve(host, port, family=0, type=0, proto=0, flags=0):
        name = host.decode('ascii') if isinstance(host, bytes) else host
        if isinstance(name, str) and name.rstrip('.').lower() == 'api.telegram.org':
            results = []
            for address in addresses:
                version = ipaddress.ip_address(address).version
                addr_family = socket.AF_INET if version == 4 else socket.AF_INET6
                if family not in (0, socket.AF_UNSPEC, addr_family):
                    continue
                results.extend(_original_getaddrinfo(address, port, addr_family, type, proto, flags))
            if results:
                return results
            raise socket.gaierror(socket.EAI_NONAME, 'Configured Telegram addresses do not support requested family')
        return _original_getaddrinfo(host, port, family, type, proto, flags)

    socket.getaddrinfo = resolve
    return addresses

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
