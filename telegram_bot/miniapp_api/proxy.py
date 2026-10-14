"""Mijoz IP/sxemasini aniqlash: forwarded sarlavhalarga FAQAT ishonchli
proksi orqali kelganda ishoniladi.

Qoidalar:
  * sukut: sarlavhalar e'tiborsiz — IP = TCP peer, sxema = ``http``;
  * ``MINIAPP_TRUSTED_PROXY_CIDRS``: TCP peer shu tarmoqlarga kirsa sarlavhalar
    o'qiladi;
  * ``MINIAPP_PROXY_ASSERT_EDGE_ONLY=1``: operator konteynerga FAQAT proksi
    orqali kirilishini kafolatlaydi (kod buni tekshira olmaydi);
  * ``X-Forwarded-For`` o'ngdan ``MINIAPP_PROXY_HOPS``-chi element (chapdagilarni
    mijoz soxtalashtiradi); ro'yxat qisqa/yaroqsiz/takroriy sarlavha bo'lsa —
    peer IP;
  * ``X-Forwarded-Proto`` — faqat ``http``/``https`` (o'ngdan hops-chi).
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from .settings import MiniAppSettings


@dataclass(frozen=True)
class ClientInfo:
    ip: str
    scheme: str
    trusted_proxy: bool


def _parse_ip(raw: str):
    try:
        return ipaddress.ip_address(raw.strip())
    except ValueError:
        return None


def _peer_trusted(peer_ip, settings: MiniAppSettings) -> bool:
    if settings.proxy_assert_edge_only:
        return True
    if peer_ip is None:
        return False
    return any(peer_ip in net for net in settings.trusted_proxy_cidrs
               if net.version == peer_ip.version)


def _single_header(headers, name: str) -> str | None:
    """Sarlavha aynan BIR marta kelgan bo'lsa qiymati, aks holda ``None``."""
    getall = getattr(headers, "getall", None)
    values = getall(name, []) if getall else ([headers[name]] if name in headers else [])
    if len(values) != 1:
        return None
    return values[0]


def resolve_client(peername, headers, transport_scheme: str,
                   settings: MiniAppSettings) -> ClientInfo:
    peer_raw = peername[0] if isinstance(peername, (tuple, list)) and peername else ""
    peer_ip = _parse_ip(str(peer_raw)) if peer_raw else None
    peer_text = str(peer_ip) if peer_ip else "unknown"
    scheme = "https" if transport_scheme == "https" else "http"

    if not _peer_trusted(peer_ip, settings):
        return ClientInfo(peer_text, scheme, False)

    hops = settings.proxy_hops
    ip = peer_text
    xff = _single_header(headers, "X-Forwarded-For")
    if xff is not None:
        parts = [p.strip() for p in xff.split(",")]
        if 0 < hops <= len(parts):
            candidate = _parse_ip(parts[-hops])
            if candidate is not None:
                ip = str(candidate)
    xfp = _single_header(headers, "X-Forwarded-Proto")
    if xfp is not None:
        parts = [p.strip().lower() for p in xfp.split(",")]
        if 0 < hops <= len(parts) and parts[-hops] in ("http", "https"):
            scheme = parts[-hops]
    return ClientInfo(ip, scheme, True)
