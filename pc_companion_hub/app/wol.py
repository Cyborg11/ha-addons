"""Wake-on-LAN: Magic Packet per UDP-Broadcast."""
from __future__ import annotations

import re
import socket


def magic_packet(mac: str) -> bytes:
    hexmac = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(hexmac) != 12:
        raise ValueError("Ungültige MAC-Adresse")
    raw = bytes.fromhex(hexmac)
    return b"\xff" * 6 + raw * 16


def send_magic_packet(mac: str, broadcast_ip: str = "255.255.255.255", port: int = 9) -> None:
    packet = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(packet, (broadcast_ip, port))
