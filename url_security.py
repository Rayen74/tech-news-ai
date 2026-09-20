"""
url_security.py
===============
Security utility for SSRF-safe URL validation and client request handling.

Guards against Server-Side Request Forgery (SSRF) by verifying that target hosts
do not resolve to loopback, link-local, private RFC 1918, or multicast IP addresses.
"""

import ipaddress
import socket
from urllib.parse import urlparse
from typing import Tuple


def is_safe_url(url: str) -> Tuple[bool, str]:
    """
    Validate that a URL is safe to fetch and does not resolve to an internal/private address.

    Args:
        url (str): The URL string to validate.

    Returns:
        Tuple[bool, str]: (is_safe, error_reason_if_unsafe)
    """
    if not url or not isinstance(url, str):
        return False, "Empty or invalid URL"

    url = url.strip()
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"URL parse error: {e}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Unsupported scheme '{parsed.scheme}'. Only http and https are allowed."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL does not contain a valid hostname."

    # Disallow known internal/dangerous hostnames
    lower_host = hostname.lower()
    if lower_host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"):
        return False, f"Prohibited loopback/internal hostname: {hostname}"

    # Resolve hostname to IP addresses and verify none are private or restricted
    try:
        # getaddrinfo handles both IPv4 and IPv6
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        return False, f"DNS resolution failed for {hostname}: {e}"
    except Exception as e:
        return False, f"Error resolving hostname {hostname}: {e}"

    if not addr_info:
        return False, f"Could not resolve any IP address for hostname {hostname}"

    for item in addr_info:
        sockaddr = item[4]
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)

            if ip_obj.is_loopback:
                return False, f"SSRF blocked: IP {ip_str} is a loopback address."
            if ip_obj.is_private:
                return False, f"SSRF blocked: IP {ip_str} is a private network address."
            if ip_obj.is_link_local:
                return False, f"SSRF blocked: IP {ip_str} is a link-local address."
            if ip_obj.is_multicast:
                return False, f"SSRF blocked: IP {ip_str} is a multicast address."
            if ip_obj.is_reserved:
                return False, f"SSRF blocked: IP {ip_str} is a reserved address."

            # Explicit check for AWS/GCP/Azure link-local cloud metadata service (169.254.169.254)
            if ip_str.startswith("169.254."):
                return False, f"SSRF blocked: IP {ip_str} belongs to cloud metadata range."

        except ValueError:
            return False, f"Invalid IP address format encountered: {ip_str}"

    return True, "URL is safe"
