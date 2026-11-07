"""Which address a guest's quota is counted against.

Production runs behind Cloudflare and one Traefik. The last
X-Forwarded-For value is the one Traefik wrote from the TCP peer; anything
a client sends ends up to its left. CF-Connecting-IP is trusted only when
that peer is a Cloudflare edge.
"""

import importlib.util
from pathlib import Path

import pytest

from app.client_ip import CLOUDFLARE_RANGES_PATH, load_cloudflare_networks, select_client_ip

CF = load_cloudflare_networks(CLOUDFLARE_RANGES_PATH)
EDGE = "173.245.48.1"
EDGE_V6 = "2400:cb00::1"

_update_spec = importlib.util.spec_from_file_location(
	"update_cloudflare_ips",
	Path(__file__).resolve().parent.parent / "update_cloudflare_ips.py",
)
update_cloudflare_ips = importlib.util.module_from_spec(_update_spec)
_update_spec.loader.exec_module(update_cloudflare_ips)


def _select(forwarded_for=(), cf_connecting_ip=None, peer_host="10.0.0.1", source="cloudflare"):
	return select_client_ip(
		forwarded_for=list(forwarded_for),
		cf_connecting_ip=cf_connecting_ip,
		peer_host=peer_host,
		source=source,
		cloudflare_networks=CF,
	)


def test_proxy_mode_uses_the_last_forwarded_value():
	assert _select(["6.6.6.6, 10.0.0.2"], "1.1.1.1", source="proxy") == "10.0.0.2"


def test_proxy_mode_without_the_header_uses_the_peer():
	assert _select([], None, peer_host="10.0.0.9", source="proxy") == "10.0.0.9"


@pytest.mark.parametrize(
	"forwarded_for, cf_connecting_ip, expected",
	[
		(["9.9.9.9, " + EDGE], "198.51.100.7", "198.51.100.7"),
		([EDGE_V6], "2001:db8::7", "2001:db8::7"),
	],
	ids=["ipv4", "ipv6"],
)
def test_cloudflare_mode_trusts_cf_connecting_ip_from_an_edge(forwarded_for, cf_connecting_ip, expected):
	assert _select(forwarded_for, cf_connecting_ip) == expected


def test_cloudflare_mode_ignores_a_forged_header_from_a_non_edge_peer():
	assert _select([EDGE + ", 203.0.113.5"], "198.51.100.7") == "203.0.113.5"


def test_cloudflare_mode_without_forwarded_for_checks_the_tcp_peer():
	assert _select([], "198.51.100.7", peer_host=EDGE) == "198.51.100.7"
	assert _select([], "198.51.100.7", peer_host="203.0.113.5") == "203.0.113.5"


@pytest.mark.parametrize("cf_connecting_ip", [None, "", "not-an-ip", "1.2.3.4, 5.6.7.8", "1.2.3.4:443"])
def test_cloudflare_mode_falls_back_when_the_header_is_missing_or_malformed(cf_connecting_ip):
	assert _select([EDGE], cf_connecting_ip) == EDGE


def test_select_uses_the_last_header_line():
	assert _select(["1.1.1.1", "203.0.113.5"], source="proxy") == "203.0.113.5"


def test_select_skips_an_empty_last_item():
	assert _select(["203.0.113.5, "], source="proxy") == "203.0.113.5"


def test_select_checks_an_ipv4_mapped_peer_as_ipv4():
	assert _select(["::ffff:" + EDGE], "198.51.100.7") == "198.51.100.7"


def test_select_normalises_cf_connecting_ip():
	assert _select([EDGE_V6], " 2001:DB8::1 ") == _select([EDGE_V6], "2001:db8::1") == "2001:db8::1"


def test_select_normalises_the_peer():
	assert _select(["2001:DB8:0::5"], source="proxy") == "2001:db8::5"


def test_a_peer_that_is_not_an_address_is_kept_as_is():
	# TestClient's peer is the name "testclient"; it is never a Cloudflare edge.
	assert _select([], "198.51.100.7", peer_host="testclient") == "testclient"


def test_select_with_no_peer_returns_none():
	assert _select([], None, peer_host=None) is None
	assert _select([" , "], None, peer_host=None) is None


def test_the_bundled_ranges_load():
	assert len(CF) > 10
	assert {network.version for network in CF} == {4, 6}


def test_a_bad_line_stops_loading(tmp_path):
	path = tmp_path / "ranges.txt"
	path.write_text("173.245.48.0/20\nnope\n10.0.0.1/8\n", encoding="utf-8")

	with pytest.raises(ValueError) as raised:
		load_cloudflare_networks(path)

	assert "line 2" in str(raised.value)
	assert "line 3" in str(raised.value)


def test_a_missing_or_empty_ranges_file_stops_loading(tmp_path):
	with pytest.raises(ValueError, match="missing"):
		load_cloudflare_networks(tmp_path / "absent.txt")

	empty = tmp_path / "empty.txt"
	empty.write_text("\n", encoding="utf-8")
	with pytest.raises(ValueError, match="no ranges"):
		load_cloudflare_networks(empty)


def test_render_ranges_validates_and_round_trips(tmp_path):
	path = tmp_path / "ranges.txt"
	path.write_text(update_cloudflare_ips.render_ranges("173.245.48.0/20\n103.21.244.0/22", "2400:cb00::/32\n"))

	assert [str(network) for network in load_cloudflare_networks(path)] == [
		"173.245.48.0/20",
		"103.21.244.0/22",
		"2400:cb00::/32",
	]
	with pytest.raises(ValueError):
		update_cloudflare_ips.render_ranges("nope", "")
	with pytest.raises(ValueError):
		update_cloudflare_ips.render_ranges("", "")
