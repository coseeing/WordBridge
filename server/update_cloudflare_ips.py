"""Refresh app/setting/cloudflare_ips.txt from Cloudflare's published ranges.

Run by hand during development, then commit the file:

	python3 server/update_cloudflare_ips.py

The server never contacts Cloudflare; it reads the bundled file at startup
(app/client_ip.py).
"""

import ipaddress
import urllib.request
from pathlib import Path

RANGES_FILE = Path(__file__).resolve().parent / "app" / "setting" / "cloudflare_ips.txt"
SOURCES = ("https://www.cloudflare.com/ips-v4", "https://www.cloudflare.com/ips-v6")


def render_ranges(v4_text: str, v6_text: str) -> str:
	"""The file content: every range, IPv4 first, one per line.

	Raises ValueError when a line is not a network address, or when either
	list is empty, so a broken download never replaces a good file.
	"""
	lines = []
	for text, version in ((v4_text, 4), (v6_text, 6)):
		ranges = [line.strip() for line in text.splitlines() if line.strip()]
		if not ranges:
			raise ValueError(f"the IPv{version} list is empty")
		for line in ranges:
			network = ipaddress.ip_network(line)
			if network.version != version:
				raise ValueError(f"{line} is not an IPv{version} range")
			lines.append(str(network))
	return "\n".join(lines) + "\n"


def _fetch(url: str) -> str:
	# Cloudflare answers 403 to urllib's default User-Agent.
	request = urllib.request.Request(url, headers={"User-Agent": "WordBridge-update-cloudflare-ips"})
	with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 -- fixed https URLs
		return response.read().decode("ascii")


def main() -> None:
	RANGES_FILE.write_text(render_ranges(*(_fetch(url) for url in SOURCES)), encoding="utf-8", newline="\n")


if __name__ == "__main__":
	main()
