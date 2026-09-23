# Server Proofreader Migration and SSO Identity Linking

## Purpose and success criteria

Make `/proofreader` in `server/app/main.py` run the WordBridge add-on's local proofreading workflow, and give the server a unified SSO identity flow. Guests can still request corrections under the existing limits. Authenticated callers map from a verified SSO token to the server's own `User`. Deployers can choose the model used by `"default"`. When complete, the server starts, handles corrections and feedback, records interactions, and enforces route permissions through dependencies.

This design reflects the decisions already confirmed in discussion. Only the execution logic in the `execution_channel == LOCAL_CHANNEL` branch of `addon/globalPlugins/WordBridge/__init__.py::correctTypo()` is migrated. Its `else` branch is add-on client code that calls the server; it is not another server execution path. NVDA actions, notifications, and UI state are also outside the server scope.

## Confirmed product and security decisions

| Area | Decision |
| --- | --- |
| Default model | The server resolves `corrector_config_id="default"` to a model ID that can be changed at deployment. |
| Guests | Requests without a token may call `/proofreader`; retain the text length, per-IP, and global guest limits. |
| Login | Accept SSO access tokens only. Disable the old `/login` and stop using server-signed HS256 tokens. |
| Initial linking | Verify the access token, then call SSO UserInfo with that same token. Require matching `sub`, a nonempty email, and `email_verified` **strictly equal to `true`**. |
| User creation | Find an existing `User.account` by the verified email and link its `sub`; otherwise create a server user with that email and link its `sub`. |
| Later requests | Verify the access token on every request. When its `sub` already maps to a local user with `email_verified=True`, use that local field without calling UserInfo again for this purpose. |
| Admin routes | `/users` and `/interactions` CRUD require an authenticated server user with `is_superuser=True`. |
| Feedback | Guests may submit feedback for a correction. For now, look up the interaction by `interaction_id` alone; do not add a feedback credential or IP binding. |
| Dependencies | `coseeing_auth` is already in `server/app/package/coseeing_auth` and is imported from the project source. Install third-party packages with pip. |

## Current state and scope

`/proofreader` still contains add-on-specific names and functions such as `self`, `DEBUG_MODE`, `provider`, `model`, and `_diff_`. It also imports server modules that do not exist: `configManager` and `settings_repository`. The catalog registry is never initialized. `get_auth_user_or_none` already rejects a missing token because it depends on `OAuth2PasswordBearer(auto_error=True)`. `/feedback` and the CRUD routes still rely on the old HS256 login. These execution and authorization gaps are in scope.

Main areas to change:

- `server/app/main.py`: correction, feedback, route dependencies, and initialization.
- `server/app/user/`: SSO dependencies, user lookup and creation, models and schemas; remove the old login and registration routes.
- `server/app/package/coseeing_auth/`: reuse the current code. Do not separately install `coseeing_auth` or change its token verification strategy.
- `server/app/lib/` and `server/requirements.txt`: make the server's correction dependencies use ordinary pip packages, without relying on NVDA `_wb_vendor` or `addonHandler`.
- Alembic migration: add SSO fields, widen the account column, and remove the user password column.
- `server/app/imp.py` and examples under `server/test/` that still reference `User.password`, `/login`, or the old payload: update them for SSO or remove obsolete examples.

The add-on request format, the SSO system, and the add-on's remote request branch stay outside this change.

## Deployment settings and initialization

| Setting | Value and purpose |
| --- | --- |
| `SSO_ISSUER` | Defaults to `https://sso.coseeing.org`; used by the existing `AuthConfig` and `TokenVerifier`. |
| `SSO_CLIENT_ID` | Defaults to `wordbridge`, matching the add-on's SSO client. |
| `SSO_USERINFO_URL` | Defaults to `https://sso.coseeing.org/userinfo`; set it as well when deploying against another SSO environment. |
| `DEFAULT_CORRECTOR_CONFIG_ID` | Defaults to `deepseek-v4-flash&DeepSeek`; deployers may select another enabled, runnable local model ID in the catalog. |
| `<PROVIDER>_API_KEY` | Read according to the selected model's provider, for example `DEEPSEEK_API_KEY`. |

At startup, the server reads `server/app/setting/catalog.json` and builds a catalog with `BundledCatalogSource` and `load_catalog(..., runnable_providers=SUPPORTED_PROVIDERS)`. It reads `server/app/setting/task/corrector.json` for correction-mode templates and optional guidance. The server module or FastAPI app state holds these objects, and request handlers obtain them explicitly, without using add-on `self` or an uninitialized registry. At startup, validate that the configured default model ID points to an enabled local model whose provider can run. Report invalid configuration clearly rather than silently selecting another model. The catalog fallback `"default"` contains only a Coseeing offer; it cannot serve as a server-side local execution model.

Import `coseeing_auth` from `app.package.coseeing_auth`. Its `AuthConfig` requires a loopback `login_redirect_uri`; the server may provide a fixed local URI that meets that type constraint. The server does not perform an OAuth login redirect. `TokenVerifier` uses `OidcProtocol.discovery`. On first use, the current verifier fetches discovery metadata and JWKS, then uses a cache. A new `kid` may trigger another public-key fetch, and JWT verification failure may trigger online introspection. **The token is still verified on every request; the local `email_verified` cache only skips later UserInfo requests.** The design neither promises fully offline verification on every request nor changes the verifier to force it.

## SSO dependencies and local users

Build layered FastAPI dependencies following `/workspace/SSO/SSO/server/fastapi/dependencies.py`, replacing that example's temporary dictionary with database-backed `User` records:

1. Optional Bearer extraction: no `Authorization` header means guest access. A malformed or non-Bearer header is an invalid credential.
2. Access-token verification: call the existing `TokenVerifier.verify_access_token()` and obtain the verified `subject`. Reject failures; never downgrade them to guest access.
3. Local-user resolution or creation: first look up the unique `sso_sub`. Return a matched row directly when `email_verified=True`. If there is no `sub` match, or the matched row has `email_verified=False`, use UserInfo to confirm the identity.
4. Optional-user dependency: return `None` when there is no token; `/proofreader` and `/feedback` use it.
5. Required-user dependency: return 401 when there is no token. The admin dependency additionally requires `is_superuser=True`, returning 403 otherwise.

Call `SSO_USERINFO_URL` with **the same access token** as an HTTP Bearer credential, with an explicit timeout. Require an object response whose `sub` is a string equal to the verified token's `subject`, whose `email` is a nonempty string, and whose `email_verified is True`. If any condition fails, do not create or link a user. Matching the UserInfo `sub` with the token subject also follows the [OpenID Connect Core UserInfo validation requirement](https://openid.net/specs/openid-connect-core-1_0.html#UserInfoResponse). The email comes from UserInfo; an email claim in the access token, if present, cannot replace UserInfo verification on first linking.

Data model and migration:

- `User.sso_sub`: nullable, unique, and long enough for an SSO subject. Existing accounts initially retain `NULL`. The unique index permits multiple `NULL` values.
- `User.email_verified`: non-nullable Boolean, backfilled to `false` for existing rows. Set it to `true` only after the first successful UserInfo check. The local value persistently records that verification and linking happened. Revocation of email verification by SSO later will not be detected on every request.
- `User.account`: remains the unique email/account key, but `String(30)` is too short for ordinary email addresses; widen it to 254 characters. When finding an existing user by email, follow the database's case-insensitive comparison semantics and rely on uniqueness constraints to prevent duplicates.
- `User.password`: remove it directly from the ORM model, database column, and user CRUD schema. The migration deletes existing password data. The server no longer verifies, stores, or returns local passwords. Existing accounts can still be linked to an SSO `sub` through a verified email.

After the initial UserInfo confirmation, update the email verification flag if a user already has that `sso_sub`. Otherwise, look up `User.account` by the verified email. If the matching existing user has no `sso_sub`, set `sso_sub` and `email_verified=True`. If the email belongs to a **different** `sso_sub`, return 409; do not take over that user. If no email matches, create a user with `account=<verified email>`, `sso_sub=<verified subject>`, `email_verified=True`, `is_active=True`, `is_superuser=False`, and a 24-hour `quota=0.1`. Use the UserInfo `name` when available; otherwise use the email, respecting the column length. Handle concurrent linking and creation with a transaction and database uniqueness constraints: on a uniqueness conflict, roll back, reread `sso_sub` and email, and accept the result only if it matches the same subject. An existing inactive user remains inactive after linking and receives 403 on authorization.

Once local `email_verified=True`, UserInfo is no longer required for that user. Every request still verifies the SSO token and looks up the server user by its verified `sub`. This cache behavior is a confirmed requirement; it does not treat an access-token email claim as verified. If the UserInfo connection or response fails, return 503 for first-time linking or a locally unverified user. Do not treat that request as a guest.

## Route permissions

| Route | No token | Valid SSO token | Invalid token |
| --- | --- | --- | --- |
| `POST /proofreader` | Guest limits | Local-user quota; superusers exempt | 401 |
| `POST /feedback` | May submit by `interaction_id` | May submit by `interaction_id`; record the feedback user | 401 |
| `/users` CRUD | 401 | Superusers only; ordinary users get 403 | 401 |
| `/interactions` CRUD | 401 | Superusers only; ordinary users get 403 | 401 |
| `/login`, `/register` | No longer provided | No longer provided | No longer provided |

`/feedback` keeps the `interaction_id` and `review_content` request fields. Return 404 when the interaction does not exist. Keep `review_user_id` as `NULL` for guest feedback; record the user ID for authenticated feedback. Under the confirmed interaction-ID-only rule, **anyone who knows a valid interaction ID can write or overwrite its feedback**. That is an explicit limitation of this phase; it does not establish that the feedback author submitted the original correction. Remove the unreachable code after `raise` in the current `feedback` function.

## `/proofreader` correction flow

Keep the JSON request currently sent by the add-on:

```json
{
  "request": "待校正文字",
  "corrector_config_id": "default",
  "language": "zh_traditional",
  "typo_correction_mode": "standard",
  "customized_words": []
}
```

`request` is a nonempty string; `corrector_config_id`, `language`, and `typo_correction_mode` are required strings. `customized_words` is an array of strings and may default to an empty array when omitted. `language` accepts only the add-on values `zh_traditional` and `zh_simplified`. Validate the mode against the task configuration file and obtain `template_name` and `optional_guidance_enable`. Return 422 for other invalid payloads instead of raising the current `KeyError` or using undefined names. Use `customized_words` directly from the payload; do not read the add-on's local dictionary or UI settings.

1. Obtain the optional user and client IP. Apply the existing 24-hour limits first: reject guest text longer than 128 characters; reject a guest IP whose cost has reached 0.06; reject all guests when their global cost has reached 0.3; reject an authenticated user when their cost has reached `quota`. Superusers are exempt from their quota. Query `Interaction.cost` as Decimal amounts over UTC time and return 429 at the limit. Keep the current `get_client_ip()` handling of `X-Forwarded-For` for this phase.
2. Resolve `corrector_config_id="default"` to `DEFAULT_CORRECTOR_CONFIG_ID`; otherwise use the requested ID. An explicit ID must be an enabled catalog `coseeings` offer with a matching enabled local `models` entry. Confirm that the provider entry exists and is supported by the server. `CorrectorCatalog.get_model()` does not itself check `active`, so check it here. Return 404 for an unknown or unrunnable requested model. Startup configuration validation should already have failed if the deployment default is invalid.
3. Obtain the API key from the environment variable for the model's provider. Call `run_typo_correction(request=text, batch_mode=True, provider_name=..., model_name=..., credential=..., provider_entry=..., price_entry=..., language=..., template_name=..., corrector_mode=..., optional_guidance_enable=..., customized_words=..., retries=2, backoff=1)`. These are the execution parameters of the add-on's `LOCAL_CHANNEL` branch. Server `batch_mode=True` corresponds to production `DEBUG_MODE=False`. A missing credential or provider failure should produce a clear 5xx and safely logged diagnostic information, without exposing the API key or raw token in responses or logs, and without writing a successful interaction.
4. Read `result.corrected_text` and `result.cost`, then create a diff with `strings_diff(text, corrected_text)`. On success, write one `Interaction` with UTC request and response times, original and corrected text, IP, Decimal cost, the **actual model ID used**, existing category/version values, and an optional user relationship. Respond only after the transaction commits.

Keep the fields expected by the add-on in the response:

```json
{
  "request": "待校正文字",
  "response": "校正結果",
  "diff": [],
  "interaction_id": 123,
  "cost": "0.000001"
}
```

The actual `diff` structure is returned by `strings_diff()`. Continue representing `cost` as a decimal string through `decimal_to_str_0()`. Roll back on a database write failure and return 5xx; do not return an `interaction_id` that was never saved.

## Error boundaries

| Condition | External result |
| --- | --- |
| No token on a guest-enabled route | Guest flow |
| Malformed, expired, or unverifiable token | 401 with a Bearer authentication header |
| UserInfo `sub` mismatch, empty email, or `email_verified` other than Boolean `true` | 403; no user is linked or created |
| UserInfo temporarily unavailable, timed out, or unparseable | 503, only when UserInfo is needed |
| Email already linked to a different `sub`, or a uniqueness conflict that cannot be safely recovered | 409 |
| Inactive user; ordinary user accessing admin CRUD | 403 |
| Quota limit reached | 429 |
| Invalid payload or mode | 422 |
| Explicit model unknown, disabled, or without a runnable local entry | 404 |
| Provider or database execution failure | 5xx; server logs provide safe diagnostics and responses contain no secrets |

## Acceptance and evidence that it runs

During implementation, install the third-party dependencies in a supported Python environment and confirm that `app.main` imports, FastAPI starts, and `_wb_vendor`, `self`, missing modules, or undefined names do not prevent requests. Update `requirements.txt` with `Authlib`, `PyJWT[crypto]`, `requests`, and the text packages needed by the correction workflow, while using the local `coseeing_auth` source. Confirm that the Alembic migration applies to existing data.

Exercise the routes with simulated SSO responses and provider execution so automated checks do not spend real model credits:

- A caller without a token can request a correction and write an interaction. The guest text length, per-IP, and global limits return 429 at their boundaries.
- A valid token triggers UserInfo on first use. A matching `User.account` is linked; otherwise an email account is created. Later requests with the same `sub` and a true local verification flag skip UserInfo but still verify the token each time.
- A false local flag triggers UserInfo again. A mismatched `sub`, empty email, value other than strict true, invalid token, SSO timeout, and cross-`sub` conflict follow the table above. Concurrent first requests do not create duplicate users.
- An ordinary user is subject to the 24-hour quota; a superuser may proceed. Guests and ordinary users cannot use either CRUD group; superusers can.
- Guests and authenticated users can submit feedback by `interaction_id`. Guest `review_user_id` is null, and an unknown ID returns 404.
- Both `default` and an enabled explicit model resolve to a local catalog entry. The response contains a usable diff, correct cost, and interaction ID; the database stores the actual model. Disabled and unknown models are rejected.

Real SSO UserInfo and model calls require an integration check in a deployment environment with a suitable token, API key, and network. Passing local simulations does not establish that those external services are available.
