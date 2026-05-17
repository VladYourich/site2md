import ipaddress
import re
import socket
from urllib.parse import urlparse

BLOCKED_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
]

METADATA_ENDPOINTS = ["169.254.169.254", "metadata.google.internal"]


def is_private_ip(hostname: str) -> bool:
    if hostname in METADATA_ENDPOINTS:
        return True
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            addr = ipaddress.ip_address(socket.gethostbyname(hostname))
        except (socket.gaierror, OSError):
            return False
    if addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved or addr.is_unspecified:
        return True
    return any(addr in network for network in BLOCKED_RANGES)


def validate_url_safety(url: str) -> tuple[bool, str | None]:
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format"

    if parsed.scheme not in ("http", "https"):
        return False, f"Scheme '{parsed.scheme}' not allowed. Only http and https are supported."

    hostname = parsed.hostname
    if not hostname:
        return False, "No hostname found in URL"

    if is_private_ip(hostname):
        return False, f"URL blocked by SSRF prevention: {hostname}"

    if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?$", hostname.split(":")[0]):
        pass

    return True, None


def validate_chunk_delimiter(delimiter: str) -> tuple[bool, str | None]:
    if len(delimiter) > 10:
        return False, "chunk_delimiter must be <= 10 characters"
    if len(delimiter) == 0:
        return False, "chunk_delimiter cannot be empty"
    return True, None
