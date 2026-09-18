# Coseeing native refresh-token storage

## Goal

Store Coseeing refresh tokens in Windows Credential Manager through the bundled
`coseeing_auth` storage API, instead of treating the NVDA configuration as the
active token store.

## Scope

This change applies to the WordBridge NVDA add-on on Windows.  The bundled
`coseeing_auth` package already provides `WindowsCredentialStore` and its
refresh-token lifecycle; this work integrates that API into WordBridge rather
than changing its implementation.

The credential target is exactly:

```
org.coseeing.wordbridge/refresh
```

There is no legacy-token migration.  Existing
`config.conf["WordBridge"]["settings"]["api_key"]["Coseeing"]` values are
neither read nor modified by this change.

## Design

### Native store wiring

`_NvdaAuthAdapter.client_factory()` will create:

```python
WindowsCredentialStore("org.coseeing.wordbridge/refresh")
```

and pass it as `refresh_token_store` when it constructs `CoseeingAuthClient`.
The client remains wrapped in `FutureAuthClient` for the existing UI-thread
boundary.

### Session flow

`CoseeingAuthSession` will no longer accept callbacks for reading or saving a
refresh token, and it will not call `get_refresh_token()` after receiving an
access token.

For an unprepared session, it will call `restore_saved_session()`:

- A restored result marks the session ready and proceeds to obtain an access
  token.
- A `None` result means no native credential exists and proceeds to the
  existing sign-in-or-guest prompt.
- A storage or restore failure follows the existing failure/notification path.

After an interactive login or token refresh, `coseeing_auth` persists a new or
rotated refresh token itself.  Its logout operations delete the native
credential.  WordBridge continues to own UI concerns only: prompting for
sign-in versus guest access, dispatching work to NVDA's UI thread, closing its
dialog, and presenting a generic failure notification.

### Settings UI and configuration

The Coseeing-specific Refresh Token field is removed from the settings panel,
including the change-detection/reset behavior that existed only to react to
manual edits.  Other provider API-key controls are unchanged.

The existing `api_key["Coseeing"]` configuration value is left untouched for
this release.  It is not displayed, loaded, saved, cleared, or migrated by the
new authentication flow.

## Error handling

`TokenPersistenceError` remains observable through the existing auth-session
failure path.  Notifications and logs use stable error metadata and must not
include token values.  A failed storage delete is reported as an auth failure;
WordBridge must not report it as a successful logout.

## Tests

Update the auth-session and NVDA-panel tests to cover:

- construction of `WindowsCredentialStore` with
  `org.coseeing.wordbridge/refresh` and injection into `CoseeingAuthClient`;
- an empty native store (`restore_saved_session() -> None`) reaching the
  established login/guest prompt;
- a restored native session proceeding to access-token acquisition without
  config-token callbacks or `get_refresh_token()`;
- removal of the Refresh Token UI control and its reset-on-edit behavior;
- continued generic handling of persistence errors without logging a token.

The package bundle test should also include the new `coseeing_auth/storage`
modules so the Windows adapter is present in the shipped add-on.

## Non-goals

- Importing, deleting, or otherwise modifying historical plaintext Coseeing
  values in NVDA configuration.
- Adding a non-Windows plaintext fallback.
- Changing the Coseeing login dialog, endpoint configuration, or provider
  selection behavior.
