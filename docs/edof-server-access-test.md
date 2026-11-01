# Test V2: EFP authentication with Gmail codes

Available only on Render service `srv-d928tc19rddc7388qie0`, branch `test-v2`,
at `/admin/edof-test/server`. Isolated from production, WEDOF and business data.
No entry, exit or service-fait write is implemented or enabled.

## One-time Google setup

1. Keep `EDOF_EFP_USERNAME` and `EDOF_EFP_PASSWORD` in the Test V2 Render
   environment. The username must equal the primary Gmail address authorized
   below; aliases are deliberately not inferred.
2. Enable Gmail API in an organization-controlled Google Cloud project.
   Configure its OAuth audience/consent screen and create a Web application
   OAuth client with this exact authorized redirect URI:
   `https://gestionstagiaires-test-v2.onrender.com/admin/edof-test/server/gmail/callback`.
3. Set `EDOF_GOOGLE_CLIENT_ID` and `EDOF_GOOGLE_CLIENT_SECRET` in Test V2 Render
   Environment, then deploy. Never send these secrets in chat or commit them.
   A stable `SECRET_KEY` of at least 32 characters is also required; the unsafe
   application default is rejected for connector encryption.
4. On the module page, read the permission disclosure, consent to this specific
   use and authorize Google. Only `gmail.readonly` with offline access is
   requested. **It can read the whole mailbox.** Restricting use to EFP is an
   application filter, not a provider-enforced single-sender permission.
   No Gmail send/modify/delete operation or scope exists.
5. Launch a dossier-read test. Nothing starts automatically after authorization.

Google external apps in Testing normally receive seven-day refresh tokens for
Gmail. Durable use needs an appropriate publishing/audience configuration and
any applicable verification. Revocation/password changes can require consent
again; permanent zero-intervention is not guaranteed.
References:
- https://developers.google.com/workspace/gmail/api/auth/scopes
- https://developers.google.com/identity/protocols/oauth2#expiration
- https://developers.google.com/identity/protocols/oauth2/web-server

## Authentication and message selection

The public Access test always starts without saved cookies or credentials.
Read tests first try server-generated cookies. Otherwise they refresh Google,
record pre-existing EFP mail IDs, and submit the EFP password form once.

Mail queries use the exact EFP recipient, sender `no-reply@emploi.gouv.fr` and
login timestamp. At most ten hits and one page are accepted. Stale messages,
wrong recipients, unauthenticated senders and reset/create-account messages
are rejected. The first Google ingress Authentication-Results must authenticate
an emploi.gouv.fr domain using DKIM or DMARC. Only text MIME bodies are read;
attachments and HTML scripts are ignored. The current parser accepts one
explicitly labelled 6–8-digit code. Unrecognized templates fail closed and
need validation against an actual login message.

OTP input must be unique, on the official EFP host and in the already allowlisted
authentication POST form. The target is rechecked after the mail wait.
At most one OTP submission, no resend/retry, no CAPTCHA bypass.

OAuth state is per-admin, encrypted, single-use and ten-minute-lived, with PKCE.
The Google profile must exactly match EFP. Mail bodies, codes and tokens are
never returned by the status endpoint or intentionally logged by application
code. Infrastructure access logs must protect OAuth callback query parameters.

## Storage and isolation

- Google refresh tokens and server-created EFP/EDOF cookies are Fernet-encrypted
  in `/var/data/edof_connector_private.sqlite3` (0600). A module-specific HMAC
  derives the key from the existing application secret. Rotating that secret
  invalidates the stored connection.
- Cookies are saved only after a successful actual dossier read, for up to 24h.
  No localStorage, user-Chrome material, screenshots, HARs or full API responses.
- Disconnect clears the local grant and cookies, refusing while a job runs.
  Provider revocation remains available in the user's Google permissions page.
- Super-admin only, no assisted/partner sessions; CSRF on initiating POSTs.
- One browser per service using an inherited file lock, at least five minutes
  between read attempts; no scheduler or periodic synchronization.
- 210-second subprocess deadline; terminate the process group and clean its
  temporary profile even after timeout/crash. Only required runtime, EFP,
  Google client and derived encryption-key variables reach the child process.
- Browser methods are restricted to reads plus EFP authentication/OIDC POSTs.
  Every EDOF business mutation remains blocked.
- Name search is exact-normalized in en-cours; homonyms, missing totals and
  paginated results are not automatically selected or associated to business data.
- Only the requested dossier/SIRET and the normalized observation schema are
  retained. Unknown billing/payment fields remain unknown.
- Results are separate, per-admin-owner SQLite records (0600), expiring after
  24h and purged on access. Closing Chrome does not stop the server job.

## Acceptance evidence still required

The earlier real test reached the EFP verification-code step; no server-side
authentication or dossier read succeeded. Unit tests of OAuth, encryption,
message filtering and errors do not prove external integration.

Before claiming autonomy, verify initial Google authorization, fresh EFP login
with automatic code, actual dossier read, session reuse after process restart,
and fresh login after expiration. Test name lookup and ambiguous cases separately.
Real entry/exit/service-fait declarations are a separate future workflow needing
effective dates/completion evidence and verified mutation semantics.
