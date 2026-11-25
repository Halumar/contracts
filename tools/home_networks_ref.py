#!/usr/bin/env python3
"""Reference of the household's home networks. Standard library only.

normalize(entries) turns the admin input [{cidr, name?}] into the stored list or an error code:
host bits cleared, only private ranges, duplicates and networks inside another merged into the
larger one (its name wins, else the first name found), sorted (IPv4 before IPv6, then by
address); more than 10 entries are refused. contains(networks, address) tells whether an address lies inside one of
the stored networks. Hub, integration and apps port both and run the vectors in
fixtures/network/home-networks (tools/validate.py does the same).

  python tools/home_networks_ref.py fixtures/network/home-networks/<vector>.json
"""

from __future__ import annotations

import ipaddress
import json
import sys
from pathlib import Path

MAX_NETWORKS = 10
MAX_NAME = 40
ALLOWED = tuple(
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")
)


class HomeNetworkError(ValueError):
    def __init__(self, code: str, cidr: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.cidr = cidr


def parse(cidr: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """One network; host bits cleared. Raises HomeNetworkError."""
    text = cidr.strip() if isinstance(cidr, str) else ""
    if "/" not in text:
        raise HomeNetworkError("home_network_invalid", cidr)
    try:
        net = ipaddress.ip_network(text, strict=False)
    except ValueError:
        raise HomeNetworkError("home_network_invalid", cidr) from None
    if not any(net.version == a.version and net.subnet_of(a) for a in ALLOWED):
        raise HomeNetworkError("home_network_public", cidr)
    return net


def _name(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()[:MAX_NAME]
    return text or None


def normalize(entries: list[dict]) -> list[dict]:
    """Stored form of the admin input. Raises HomeNetworkError."""
    if len(entries) > MAX_NETWORKS:
        raise HomeNetworkError("home_networks_too_many")
    parsed = [(parse(e.get("cidr", "")), _name(e.get("name"))) for e in entries]
    order = sorted(range(len(parsed)), key=lambda i: (parsed[i][0].version, parsed[i][0].prefixlen))
    kept: list[tuple] = []  # (network, name), larger networks first
    for i in order:
        net, name = parsed[i]
        outer = next((k for k in kept if k[0].version == net.version and net.subnet_of(k[0])), None)
        if outer is None:
            kept.append((net, name))
        elif outer[1] is None and name is not None:
            kept[kept.index(outer)] = (outer[0], name)
    kept.sort(key=lambda k: (k[0].version, int(k[0].network_address), k[0].prefixlen))
    return [{"cidr": str(net), "name": name} for net, name in kept]


def cidrs(networks: list[dict]) -> list[str]:
    """client_config / snapshot form: the canonical CIDRs only."""
    return [n["cidr"] for n in networks]


def contains(networks: list[str], address: str) -> bool:
    """Whether an IP address (IPv4-mapped IPv6 counts as IPv4) is inside one of the networks."""
    try:
        ip = ipaddress.ip_address(address.strip("[]").split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in ipaddress.ip_network(n) for n in networks)


def check_list(cidr_list: list[str], where: str) -> list[str]:
    """A stored list (client_config, snapshot, answer): canonical, private, sorted, no overlaps."""
    out = []
    try:
        expected = cidrs(normalize([{"cidr": c} for c in cidr_list]))
    except HomeNetworkError as err:
        return [f"{where}: {err.code} {err.cidr or ''}".rstrip()]
    if expected != cidr_list:
        out.append(f"{where}: not the normalized form, expected {expected}")
    return out


def run_vector(vector: dict) -> list[str]:
    out = []
    if ("networks" in vector["expect"]) == ("error" in vector["expect"]):
        return [f"{vector['name']}: expect holds exactly one of networks and error"]
    try:
        got = {"networks": normalize(vector["input"])}
    except HomeNetworkError as err:
        got = {"error": err.code}
    if got != vector["expect"]:
        out.append(f"{vector['name']}: normalize gives {got}, expected {vector['expect']}")
    nets = cidrs(got.get("networks", []))
    for case in vector.get("hosts", []):
        if contains(nets, case["address"]) != case["home"]:
            out.append(f"{vector['name']}: {case['address']} home should be {case['home']}")
    return out


if __name__ == "__main__":
    errors = []
    for arg in sys.argv[1:]:
        errors += run_vector(json.loads(Path(arg).read_text(encoding="utf-8")))
    print("\n".join(errors) or "ok")
    sys.exit(1 if errors else 0)
