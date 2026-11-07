"""The client address guest quotas are counted against.

The deployment is: user -> Cloudflare (proxied) -> Traefik -> this server,
with exactly one proxy, Traefik, in front of the server. If another proxy
is ever added behind Traefik, the peer is the N-th X-Forwarded-For value
from the right instead of the last.

The peer is the last X-Forwarded-For value: Traefik writes it from the TCP
connection, and whatever a client sends ends up to its left, so it cannot
be forged. Without the header the peer is the TCP peer itself.

- CLIENT_IP_SOURCE=proxy (Cloudflare DNS only): the client is the peer.
- CLIENT_IP_SOURCE=cloudflare (Cloudflare proxying): when the peer is a
  Cloudflare edge and CF-Connecting-IP is a valid address, the client is
  CF-Connecting-IP; otherwise the peer. A forged CF-Connecting-IP from
  anywhere but an edge is ignored.

Cloudflare's ranges are bundled in setting/cloudflare_ips.txt (refresh it
with `python3 server/update_cloudflare_ips.py`); the server never fetches
them. A stale file sends new edges to the peer fallback, which makes
guests share an edge's quota: stricter, never bypassable.
"""

import ipaddress
from collections.abc import Sequence
from pathlib import Path

CLOUDFLARE_RANGES_PATH = Path(__file__).parent / "setting" / "cloudflare_ips.txt"


def load_cloudflare_networks(path: Path) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
	"""Parse the bundled ranges: one CIDR per line, blank lines ignored.

	Raises ValueError for a missing file, a file without ranges, or any
	line that is not a network address, naming every bad line.
	"""
	try:
		text = path.read_text(encoding="utf-8")
	except FileNotFoundError as error:
		raise ValueError(f"{path.name} is missing") from error
	networks = []
	bad = []
	for number, line in enumerate(text.splitlines(), 1):
		line = line.strip()
		if not line:
			continue
		try:
			networks.append(ipaddress.ip_network(line))
		except ValueError:
			bad.append(f"line {number}")
	if bad:
		raise ValueError(f"{path.name} has invalid ranges on " + ", ".join(bad))
	if not networks:
		raise ValueError(f"{path.name} has no ranges")
	return tuple(networks)


def _parse(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
	if not value:
		return None
	try:
		return ipaddress.ip_address(value.strip())
	except ValueError:
		return None


def _is_cloudflare(address, networks) -> bool:
	if address is None:
		return False
	if address.version == 6 and address.ipv4_mapped is not None:
		address = address.ipv4_mapped
	return any(address in network for network in networks)


def select_client_ip(
	*,
	forwarded_for: Sequence[str],
	cf_connecting_ip: str | None,
	peer_host: str | None,
	source: str,
	cloudflare_networks,
) -> str | None:
	"""The client address for one request (see the module docstring).

	`forwarded_for` holds every X-Forwarded-For header line in order. An
	address is returned in its normal text form, so one client always
	counts against one quota; a peer that is not an address (a test
	client's name) is returned as it is, and no peer at all gives None.
	"""
	items = [item.strip() for item in ",".join(forwarded_for).split(",")]
	items = [item for item in items if item]
	peer = items[-1] if items else peer_host
	peer_address = _parse(peer)
	if peer_address is not None:
		peer = str(peer_address)
	if source == "cloudflare" and _is_cloudflare(peer_address, cloudflare_networks):
		client_address = _parse(cf_connecting_ip)
		if client_address is not None:
			return str(client_address)
	return peer
