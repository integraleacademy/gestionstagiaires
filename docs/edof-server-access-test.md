# Test V2: fresh server-side EFP connection

This experiment is available only on Render service `srv-d928tc19rddc7388qie0`,
branch `test-v2`, at `/admin/edof-test/server`. It is separate from the manual
Chrome observation pilot and from all business data and WEDOF automations.

## What it actually tests

1. **Access**: launch a browser on Render and reach the official EFP login form
   via EDOF's normal login redirect. No credentials are submitted.
2. **Read**: with `EDOF_EFP_USERNAME` and `EDOF_EFP_PASSWORD` set in this service's
   Render Environment settings, create a fresh browser, submit the normal EFP
   form once, and try to read one dossier. Secrets are not requested by the app,
   returned to the administrator, added to URLs, or written to the repository.
3. Optionally find a dossier from exact normalized first/last name through the
   EDOF “Par Nom de stagiaire” UI. Search is limited to the “en cours” screen.
   A paginated/incomplete result or multiple matches stops selection. A unique
   name result is a read candidate, never an automatic business association.

Each run uses a new ephemeral browser context. No auth state, cookies, traces,
screenshots, HARs, or full API responses are saved. It does not depend on the
user's Chrome, extension or cookies. A successful read proves that particular
fresh login/read, not continuous reliability. Repeat after a service restart
and on a later day before claiming an unattended connector is viable.

The login form selectors were observed on the current official EFP/EDOF form.
Authenticated search, SIRET selection and read paths remain an experiment until
tested with valid credentials. Authentication errors, OTPs, CAPTCHAs, changed UI,
or absent dossier response stop the run; no challenge bypass or credential retry.
No endpoint for EDOF mutations has been reverse engineered or implemented.

## Isolation and lifecycle

- Super-admin only, no partner/assisted session, per-session CSRF token.
- At most one browser per service, file lock inherited by its process. One
  authenticated attempt per five minutes, including failures; no scheduler.
- 150-second subprocess timeout; process group killed on completion or timeout.
  Browser credentials and unrelated CRM/database secrets are never logged.
- All non-read HTTP methods are blocked, except the official EFP password-form
  POST and OIDC token POST. Every EDOF business mutation is blocked. If normal
  login needs another POST, the flow must be reviewed, not broadly allowed.
- A response from the wrong SIRET or dossier is never retained. Only the
  existing observation schema is projected; billing/payment unknowns stay null.
- Results only in `/var/data/edof_server_test.sqlite3`, permissions 0600, scoped
  to the initiating admin browser session. Expire after 24h, purged on access.
- Gunicorn serves the job asynchronously. Closing the client does not cancel
  it; a restart may interrupt it, which is never reported as success.
- Playwright and Chromium headless shell are installed only when Docker's
  `RENDER_SERVICE_ID` build argument equals Test V2. No plan or service change.

## Acceptance evidence to collect

- Actual access result from the Render deployment, not from a developer browser.
- First fresh authenticated read and an independent repeat after restart.
- Name search with one match, homonyms, and paginated results.
- Authentication expiry and site challenges reported honestly.
- No EDOF mutation or business `data.json` write during any of these tests.

Real entry/exit/service-fait declarations are a separate future step, requiring
the actual effective dates/completion evidence and a verified write workflow.
