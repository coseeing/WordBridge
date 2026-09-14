import requests
import jwt
from jwt import PyJWKClient
from typing import Optional, Iterable, Literal, Tuple, Dict, Any
from collections import OrderedDict
import threading
import time


# ---------------------------
# Utilities
# ---------------------------

def normalize_scope_str(scopes: Optional[str | Iterable[str]]) -> str:
	"""
	Normalize scopes of type str | Iterable[str] | None into a sorted, space-delimited string.

	Examples:
	- "openid profile"        -> "openid profile"
	- ["email", "openid"]     -> "email openid"
	- ("profile", "openid")   -> "openid profile"
	- None                    -> ""
	"""
	if scopes is None:
		return ""
	if isinstance(scopes, str):
		parts = [s for s in scopes.split() if s]
	else:
		parts = [str(s).strip() for s in scopes if str(s).strip()]
	return " ".join(sorted(set(parts)))


# ---------------------------
# Exceptions
# ---------------------------

class ScopeError(Exception):
	"""Raised when the token is missing one or more required scopes."""


class IntrospectionError(Exception):
	"""Raised when remote introspection or userinfo validation fails."""


# ---------------------------
# Local JWT Verifiers
# ---------------------------

class JWTVerifier:
	"""
	Verify access tokens locally as JWT:
	- Fetch JWKS via OIDC discovery and cache the PyJWKClient
	- Verify signature, issuer, and time-based claims
	- Optional scope subset check

	On failure: raise (jwt.InvalidTokenError | ScopeError)
	On success: return {"sub": <subject>}
	"""

	def __init__(self, issuer: str, client_id: str, algorithms: Optional[list] = None, leeway: int = 10, jwks_client: Optional[PyJWKClient] = None):
		self.issuer = issuer.rstrip("/")
		self.client_id = client_id
		self.algorithms = algorithms or ["RS256"]
		self.leeway = leeway

		self._jwks_url: Optional[str] = None
		self._jwks_client: Optional[PyJWKClient] = jwks_client

	def _get_jwks_client(self) -> PyJWKClient:
		if self._jwks_client:
			return self._jwks_client
		resp = requests.get(f"{self.issuer}/.well-known/openid-configuration", timeout=5)
		resp.raise_for_status()
		self._jwks_url = resp.json()["jwks_uri"]
		self._jwks_client = PyJWKClient(self._jwks_url, cache_keys=True)
		return self._jwks_client

	@staticmethod
	def _str_to_scope_set(scopes: Optional[str | Iterable[str]]) -> set[str]:
		if scopes is None:
			return set()
		if isinstance(scopes, str):
			return {s for s in scopes.split() if s}
		return {str(s) for s in scopes}

	@staticmethod
	def _claims_to_scope_set(claims: dict) -> set[str]:
		if "scp" in claims:
			scp_val = claims["scp"]
			if isinstance(scp_val, Iterable) and not isinstance(scp_val, (str, bytes)):
				return {str(s) for s in scp_val}
			if isinstance(scp_val, str):
				return {s for s in scp_val.split() if s}
		if isinstance(claims.get("scope"), str):
			return {s for s in claims["scope"].split() if s}
		return set()

	def verify(self, token: str, scopes: Optional[str] = None) -> dict:
		"""Verify an access token (JWT)."""
		jwks_client = self._get_jwks_client()
		try:
			signing_key = jwks_client.get_signing_key_from_jwt(token).key
		except Exception as e:
			raise jwt.InvalidTokenError(f"Failed to obtain signing key: {e}") from e

		try:
			claims = jwt.decode(
				token,
				signing_key,
				algorithms=self.algorithms,
				issuer=self.issuer,
				options={"require": ["exp", "iat", "iss"]},
				leeway=self.leeway,
			)
		except Exception as e:
			raise jwt.InvalidTokenError(f"JWT verification failed: {e}") from e

		# Optional scope subset check
		if scopes:
			required_set = self._str_to_scope_set(scopes)
			token_scopes_set = self._claims_to_scope_set(claims)
			if not required_set.issubset(token_scopes_set):
				missing = normalize_scope_str(required_set - token_scopes_set)
				current = normalize_scope_str(token_scopes_set)
				raise ScopeError(f"Missing required scopes: {missing}; token_scopes={current}")

		sub = claims.get("sub")
		if not sub:
			raise jwt.InvalidTokenError("Token missing 'sub' claim")

		return {"sub": sub}

	def verify_id_token(
		self,
		token: str,
		client_id: Optional[str] = None,
		nonce: Optional[str] = None
	) -> dict:
		"""Verify an ID Token (JWT)."""
		cid = client_id or self.client_id
		if not cid:
			raise ValueError("client_id is required to verify id_token")

		jwks_client = self._get_jwks_client()
		try:
			signing_key = jwks_client.get_signing_key_from_jwt(token).key
		except Exception as e:
			raise jwt.InvalidTokenError(f"Failed to obtain signing key: {e}") from e

		try:
			claims = jwt.decode(
				token,
				signing_key,
				algorithms=self.algorithms,
				issuer=self.issuer,
				audience=cid,
				options={"require": ["exp", "iat", "iss", "aud"]},
				leeway=self.leeway,
			)
		except Exception as e:
			raise jwt.InvalidTokenError(f"ID Token verification failed: {e}") from e

		aud = claims.get("aud")
		azp = claims.get("azp")
		if isinstance(aud, (list, tuple)):
			if cid not in aud:
				raise jwt.InvalidTokenError("client_id not included in id_token aud")
			if len(aud) > 1 and azp != cid:
				raise jwt.InvalidTokenError("id_token azp must equal client_id when aud has multiple values")
		else:
			if azp is not None and azp != cid:
				raise jwt.InvalidTokenError("id_token azp does not match client_id")

		if nonce is not None and claims.get("nonce") != nonce:
			raise jwt.InvalidTokenError("id_token nonce mismatch")

		sub = claims.get("sub")
		if not sub:
			raise jwt.InvalidTokenError("id_token missing 'sub' claim")

		return {"sub": sub, "claims": claims}


class IDTokenVerifier(JWTVerifier):
	"""Alias kept for clarity when used specifically for ID Tokens."""
	pass


# ---------------------------
# Remote Introspection (online)
# ---------------------------

class RemoteTokenIntrospector:
	"""
	Validate access tokens via remote endpoints:
	- Prefer RFC 7662 introspection if advertised
	- For Google, use tokeninfo endpoint for access_token
	- Otherwise, fall back to UserInfo probe (HTTP 200 indicates usable token)

	On failure: raise IntrospectionError or ScopeError
	On success: return {"sub": <subject>}
	"""

	def __init__(
		self,
		issuer: str,
		client_id: str,
		client_auth: Optional[Tuple[str, str]] = None,  # (client_id, client_secret) if needed by introspection
		cache_ttl_seconds: int = 300,
		cache_max_entries: int = 1024,
	):
		self.issuer = issuer.rstrip("/")
		self.client_id = client_id
		self._client_auth = client_auth
		self._discovery: Optional[Dict[str, Any]] = None

		# In-memory cache (thread-safe LRU)
		self._cache_ttl = int(cache_ttl_seconds)
		self._cache_max = int(cache_max_entries)
		self._cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
		self._lock = threading.Lock()

	def _now(self) -> int:
		"""Return current UNIX epoch seconds."""
		return int(time.time())

	def _cache_get(self, token: str, required_set: set[str]) -> Optional[dict]:
		"""Get a cached verification result if valid for required scopes."""
		with self._lock:
			entry = self._cache.get(token)
			if not entry:
				return None
			if entry.get("expires_at", 0) <= self._now():
				# Expired: remove and miss
				self._cache.pop(token, None)
				return None
			scopes = entry.get("scopes")  # Optional[set[str]]
			if required_set:
				if scopes is None:
					# Unknown scopes; must revalidate remotely if scopes are required
					return None
				if not required_set.issubset(scopes):
					# Not enough scopes in cache; treat as miss to revalidate
					return None
			# Hit: refresh LRU position
			self._cache.move_to_end(token, last=True)
			return {"sub": entry["sub"]}

	def _cache_put(self, token: str, sub: str, scopes: Optional[set[str]], expires_at: int) -> None:
		"""Store verification result in cache and enforce LRU size limit."""
		with self._lock:
			self._cache[token] = {"sub": sub, "scopes": scopes, "expires_at": int(expires_at)}
			self._cache.move_to_end(token, last=True)
			while len(self._cache) > self._cache_max:
				self._cache.popitem(last=False)

	def _calc_expires_at(self, body: dict) -> int:
		"""Compute expiry time from response body or fallback to default TTL."""
		now = self._now()
		if isinstance(body.get("exp"), (int, float)):
			return int(body["exp"])
		if isinstance(body.get("expires_in"), (int, float)):
			return now + int(body["expires_in"])
		return now + self._cache_ttl

	def _discover(self) -> Dict[str, Any]:
		if self._discovery:
			return self._discovery
		resp = requests.get(f"{self.issuer}/.well-known/openid-configuration", timeout=6)
		resp.raise_for_status()
		self._discovery = resp.json()
		return self._discovery

	def _is_google(self) -> bool:
		return self.issuer in ("https://accounts.google.com", "https://www.googleapis.com")

	@staticmethod
	def _safe_json(resp: requests.Response) -> dict:
		try:
			return resp.json()
		except Exception:
			return {"text": resp.text}

	@staticmethod
	def _str_to_scope_set(scopes: Optional[str | Iterable[str]]) -> set[str]:
		if scopes is None:
			return set()
		if isinstance(scopes, str):
			return {s for s in scopes.split() if s}
		return {str(s) for s in scopes}

	def verify(self, token: str, required_scopes: Optional[str] = None) -> dict:
		"""
		Remote validation of an access token. Raises on failure.
		Returns {"sub": <subject>} on success.
		"""
		required_set = self._str_to_scope_set(required_scopes)

		# Try cache first
		hit = self._cache_get(token, required_set)
		if hit:
			return hit
		conf = self._discover()
		introspection = conf.get("introspection_endpoint")
		userinfo = conf.get("userinfo_endpoint")

		# 1) RFC 7662 introspection (preferred)
		if introspection:
			data = {"token": token, "token_type_hint": "access_token"}
			auth = self._client_auth or None
			if not auth:
				# Public clients may pass client_id in body; servers may ignore it
				data["client_id"] = self.client_id

			resp = requests.post(introspection, data=data, timeout=6, auth=auth)
			if resp.status_code >= 400:
				raise IntrospectionError(f"Introspection request failed: HTTP {resp.status_code}")

			body = self._safe_json(resp)

			if not bool(body.get("active")):
				raise IntrospectionError("Token is inactive per introspection")

			# scope check (if provided)
			token_scopes_set = set()
			if isinstance(body.get("scope"), str):
				token_scopes_set = {s for s in body["scope"].split() if s}
			if required_set and not required_set.issubset(token_scopes_set):
				missing = normalize_scope_str(required_set - token_scopes_set)
				current = normalize_scope_str(token_scopes_set)
				raise ScopeError(f"Missing required scopes: {missing}; token_scopes={current}")

			sub = body.get("sub") or body.get("username")
			if not sub:
				raise IntrospectionError("Introspection response missing 'sub'")

			# Cache success
			expires_at = self._calc_expires_at(body)
			cached_scopes = set()
			if isinstance(body.get("scope"), str):
				cached_scopes = {s for s in body["scope"].split() if s}
			self._cache_put(token, sub, cached_scopes, expires_at)
			return {"sub": sub}

		# 2) Google tokeninfo for access_token
		elif self._is_google():
			resp = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": token}, timeout=6)
			if resp.status_code != 200:
				raise IntrospectionError(f"Google tokeninfo failed: HTTP {resp.status_code}")

			body = self._safe_json(resp)
			token_scopes_set = set()
			if isinstance(body.get("scope"), str):
				token_scopes_set = {s for s in body["scope"].split() if s}
			if required_set and not required_set.issubset(token_scopes_set):
				missing = normalize_scope_str(required_set - token_scopes_set)
				current = normalize_scope_str(token_scopes_set)
				raise ScopeError(f"Missing required scopes: {missing}; token_scopes={current}")

			sub = body.get("sub")
			if not sub:
				raise IntrospectionError("Google tokeninfo missing 'sub'")

			# Cache success
			expires_at = self._calc_expires_at(body)
			cached_scopes = set()
			if isinstance(body.get("scope"), str):
				cached_scopes = {s for s in body["scope"].split() if s}
			self._cache_put(token, sub, cached_scopes, expires_at)
			return {"sub": sub}

		# 3) Fallback: UserInfo probe (some providers)
		elif userinfo:
			resp = requests.get(userinfo, headers={"Authorization": f"Bearer {token}"}, timeout=6)
			if resp.status_code != 200:
				raise IntrospectionError(f"UserInfo probe failed: HTTP {resp.status_code}")

			body = self._safe_json(resp)

			# If scopes are present in response, verify; many providers don't return them.
			if required_set:
				token_scopes_set = set()
				if isinstance(body.get("scope"), str):
					token_scopes_set = {s for s in body["scope"].split() if s}
					if not required_set.issubset(token_scopes_set):
						missing = normalize_scope_str(required_set - token_scopes_set)
						current = normalize_scope_str(token_scopes_set)
						raise ScopeError(f"Missing required scopes: {missing}; token_scopes={current}")
				# If no 'scope' exists, accept based on successful UserInfo (common practice).

			sub = body.get("sub")
			if not sub:
				raise IntrospectionError("UserInfo response missing 'sub'")

			# Cache success (userinfo often lacks scopes; store None when absent)
			expires_at = self._calc_expires_at(body)
			cached_scopes: Optional[set[str]] = None
			if isinstance(body.get("scope"), str):
				cached_scopes = {s for s in body["scope"].split() if s}
			self._cache_put(token, sub, cached_scopes, expires_at)
			return {"sub": sub}

		# No remote mechanism available
		else:
			raise IntrospectionError("Issuer exposes no remote validation mechanism (no introspection or userinfo)")


# ---------------------------
# Orchestrator
# ---------------------------

class TokenVerifier:
	"""
	Coordinator for access token verification:
	- mode="jwt"    -> local JWT verification only
	- mode="remote" -> remote introspection only
	- mode="auto"   -> try JWT first, then fall back to remote introspection

	On failure: raise (jwt.InvalidTokenError | IntrospectionError | ScopeError)
	On success: return {"sub": <subject>}
	"""

	def __init__(
		self,
		issuer: str,
		client_id: str,
		jwt_algorithms: Optional[list] = None,
		leeway: int = 10,
		client_auth: Optional[Tuple[str, str]] = None,
	):
		self.issuer = issuer.rstrip("/")
		self.client_id = client_id
		self.jwt_algorithms = jwt_algorithms or ["RS256"]
		self.leeway = leeway
		self._jwt = JWTVerifier(
			issuer=self.issuer,
			client_id=self.client_id,
			algorithms=self.jwt_algorithms,
			leeway=self.leeway
		)
		self._remote = RemoteTokenIntrospector(
			issuer=self.issuer,
			client_id=self.client_id,
			client_auth=client_auth,
		)

	def verify_access_token(
		self,
		token: str,
		required_scopes: Optional[str] = None,
		mode: Literal["jwt", "remote", "auto"] = "auto",
	) -> dict:
		if mode == "jwt":
			return self._jwt.verify(token, scopes=required_scopes)
		if mode == "remote":
			return self._remote.verify(token, required_scopes=required_scopes)

		# auto: try JWT, then remote
		try:
			return self._jwt.verify(token, scopes=required_scopes)
		except Exception:
			return self._remote.verify(token, required_scopes=required_scopes)

	def verify_id_token(
		self,
		token: str,
		client_id: Optional[str] = None,
		nonce: Optional[str] = None,
		mode: Literal["jwt", "remote", "auto"] = "auto",
	) -> dict:
		if mode in ("jwt", "auto"):
			return self._jwt.verify_id_token(token, client_id, nonce)
		# Remote verification for ID Tokens is not supported here by design.
		raise jwt.InvalidTokenError("id_token verification must use the JWT verifier")


# ---------------------------
# Example usage
# ---------------------------
if __name__ == "__main__":
	# Hydra / Coseeing (JWT access_token) -> auto will succeed via JWT path
	access = TokenVerifier(
		issuer="https://sso.dev.coseeing.org/hydra",
		client_id="wordbridge",
	)
	try:
		res1 = access.verify_access_token(
			"YOUR_HYDRA_ACCESS_TOKEN",
			required_scopes="openid profile email offline_access",
			mode="auto",
		)
	except (jwt.InvalidTokenError, IntrospectionError, ScopeError) as e:
		print("[hydra] verification failed:", e)

	# Google (opaque access_token) -> auto will fall back to remote path
	google_access = TokenVerifier(
		issuer="https://accounts.google.com",
		client_id="392802191827-xxx.apps.googleusercontent.com",
	)
	try:
		res2 = google_access.verify_access_token(
			"YOUR_GOOGLE_ACCESS_TOKEN",
			required_scopes="openid",
			mode="auto",
		)
		print("[google]", res2)  # {"sub": "..."}
	except (jwt.InvalidTokenError, IntrospectionError, ScopeError) as e:
		print("[google] verification failed:", e)
