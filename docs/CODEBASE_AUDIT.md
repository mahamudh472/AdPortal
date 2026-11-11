# AdPortal — Full Codebase Audit

| | |
|---|---|
| **Date** | 2026-11-10 |
| **Scope** | Backend `AdPortal/` (Django 6 / DRF / Celery / Channels / Docker / nginx) and frontend `../adportal_frontend/` (React 19 / Vite / Redux) |
| **Commits reviewed** | backend `6c7474c`, frontend `3adf944` |
| **Goal** | Security, authorization, performance/optimization, caching, rate limiting, bad practices, ops and compliance |

---

## 0. How to read this report

Every finding carries an ID, a severity and an evidence tag.

| Tag | Meaning |
|---|---|
| **[V]** | **Verified** — I reproduced it against the running code with a throwaway proof-of-concept (Django test client, test DB; nothing was changed in the dev DB). |
| **[S]** | **Static** — found by reading the code; not executed. |
| **[T]** | **Tool** — output of `pip-audit` / `npm audit` / DRF route introspection. |

Severity: **Critical** (exploitable now, full compromise or cross-tenant data/money impact) · **High** · **Medium** · **Low** · **Info**.

Not done: no load testing, no live penetration test against a deployed environment, no review of the third-party SDK internals, no review of `.env` values (only that the file is gitignored and `.env.example` is incomplete).

---

## Remediation status (updated 2026-11-11)

Fixed in code (each has regression tests in `apps/main/tests/test_security_hardening.py` unless noted):

| Finding | Status |
|---|---|
| SEC-01 profile privilege escalation | Fixed — field allow-list |
| SEC-02 integration IDOR / SEC-03 unscoped `campaign_id` | Fixed — membership + admin role; org-scoped campaign/asset lookups |
| SEC-04 / SEC-05 role checks, ADMIN→OWNER | Fixed — `IsOrgAdminForWrites`, read-only `status`, role validation, no self role change |
| SEC-06 OTP | Fixed — `secrets`, single active code, 5-attempt lockout, no replay, throttled |
| SEC-07 insecure defaults | Fixed — `DEBUG` off by default, `SECRET_KEY` required, ALLOWED_HOSTS/CORS/WS origin allow-lists, HSTS & headers |
| SEC-08 / SEC-09 / SEC-19 uploads | Fixed — content sniffing (no SVG), size/pixel caps, UUID file names. *Still public via `/media/`* (names are now unguessable; signed URLs are future work) |
| SEC-10 password validation, anonymous change-password 500 | Fixed |
| SEC-11 expired invitations | Fixed (expiry enforced, `secrets` temp password) |
| SEC-13 entitlements | Fixed — suspended orgs read-only, campaign & team limits when the plan defines them, AI rate limit. *Per-org AI token quotas not implemented* |
| SEC-14 Stripe | Fixed — event de-dup (`StripeEvent`), `invoice.paid`, metadata checks, removed `timezone.utc` crash. *Customer objects / idempotency keys / reconcile task not implemented* |
| SEC-15 account deletion | Fixed — password confirmation, owner-with-members block, Stripe cancel. *Meta deletion callback matching not changed* |
| SEC-16 / SEC-17 deployment & nginx | Fixed — port 8000 unpublished, no `makemigrations` at boot, `.dockerignore`, pinned images, nginx rate limits / headers / safe logs / media sandbox / Dozzle allow-list (config validated with `nginx -t`) |
| SEC-18 dependencies | Fixed — Python: 25 → 1 vulnerable package (Twisted, fix only in 26.10 RC); npm: 0 vulnerabilities |
| SEC-20 WebSocket | Fixed — origin validation, safe disconnect, resilient push. *Token still in query string* |
| SEC-22 token housekeeping | Fixed — daily purge task. *Refresh token still in `localStorage`* |
| SEC-23 error leakage | Fixed in views listed by the audit |
| SEC-24 Django hardening | Fixed |
| SEC-25 formula injection | Fixed |
| SEC-26 / SEC-27 / SEC-29 / SEC-30 | Fixed — test endpoint gated, schema & router root staff-only, default `IsAuthenticated`, bounded contact form |
| SEC-28 admin | Fixed — real `UserAdmin` (hashed passwords). *MFA / IP allow-list not done* |
| SEC-32 identifier injection | Fixed |
| SEC-35 frontend route guards | Fixed — role-aware `ProtectedRoute` |
| SEC-37 log redaction | Fixed — redaction filter |
| SEC-38 snowflake ids | Fixed — per-process instance id |
| SEC-41 / SEC-45 / SEC-46 / SEC-47 / SEC-48 | Fixed |
| PERF-02 timeouts | Fixed — all 19 calls |
| PERF-04 / PERF-13 indexes | Fixed — composite indexes (migrations) |
| PERF-05 ad metrics bug | Fixed |
| PERF-06 caching | Partially — public plan list cached with invalidation |
| PERF-09 Celery limits | Partially — time limits, acks_late, prefetch 1 |
| PERF-11 connection reuse | Fixed |
| PERF-17 health | Fixed — `/healthz`, `/readyz` |
| FPERF-01 / FPERF-04 bundle & console | Fixed — lazy routes (main chunk 1.75 MB → 453 KB), vendor chunks, `console` stripped in production |

### Second pass (2026-11-11) — items previously left open

| Finding | Status |
|---|---|
| SEC-12 OAuth tokens | Fixed — encrypted at rest (Fernet, `FIELD_ENCRYPTION_KEYS`, plaintext rows auto-migrated), blind-index lookup, Meta long-lived token exchange, Graph calls use `Authorization` headers, secrets POSTed not put in URLs, provider error bodies no longer echoed. *Meta token auto-refresh is not possible without user re-consent (Meta limitation); the 60-day expiry is stored in `token_expires_at`* |
| SEC-15 Meta deletion callback | Fixed — matched on stored Facebook user id, replay window, deletes only that user's Meta integrations |
| SEC-20 WebSocket token in URL | Fixed — single-use 30 s tickets (`POST /accounts/ws-ticket/`); `?token=` disabled outside DEBUG |
| SEC-21 enumeration | Fixed — uniform responses for resend/reset/verify/check |
| SEC-22 refresh token in `localStorage` | Fixed — HttpOnly cookie mode (frontend uses it; legacy clients still work) |
| SEC-44 / SEC-45 admin actions | Fixed — immutable `AdminAuditLog`, staff protected from non-superusers, confirmed org deletion + Stripe cancel |
| SEC-09 report privacy | Fixed — reports only via authenticated download endpoints, `/media/reports/` blocked in nginx. *Ad creatives remain public by unguessable UUID URL (they must be fetchable by Meta/TikTok and `<img>` tags)* |
| SEC-13 AI cost | Fixed — daily per-organization cap |
| SEC-14 Stripe | Fixed — checkout idempotency key, pending-checkout reuse, abandoned-checkout purge. *No Stripe Customer objects (would need live-Stripe validation)* |
| PERF-01 | Fixed — Gunicorn for HTTP, Daphne only for `/ws/`, multi-stage image, Redis password support |
| PERF-03 / ARCH-01 | Improved — organization resolved once per request and cached |
| PERF-07 | Fixed — `status_counts` in the campaign list (4 calls → 0 extra) |
| PERF-09 / PERF-10 | Fixed — AI insights fan out per campaign on a dedicated queue/worker; OTP e-mails sent via Celery |
| SEC-18 | Fixed — **0** known vulnerable Python packages (Twisted 26.10.0) and 0 npm advisories |
| GDPR | Partially — `GET /accounts/export-data/` and a safer Meta deletion callback. *No soft-delete grace period / retention jobs* |

**Deliberately not done, with reasons:**
* *Default pagination (PERF-14)* — would change the response shape of every list endpoint and break the frontend; add per-endpoint when the UI is migrated.
* *Money as `Decimal` (Q-13)* — billing already uses `Decimal`; the remaining floats are provider analytics metrics where floats are appropriate.
* *TanStack Query migration (FPERF-03)* — a UI-wide rewrite that cannot be validated without browser tests; recommended as a separate project.
* *MFA for the Django admin (SEC-28)* — `/admin/` is now restricted by IP (`ADMIN_ALLOW`); add `django-otp` when a second factor policy is decided.
* *Signed URLs for ad creatives* — requires CDN / object-storage migration (PERF-16).

---

## 1. Executive summary

The product works and has a decent test base (228 test functions, 241 test runs passing), but **the authorization model has serious holes**. Several of them are exploitable by *any registered user* and were reproduced.

### 1.1 The five things that need fixing before anything else

1. **Any user can make themselves a superuser** (`PATCH /accounts/profile/update/` accepts `is_staff` / `is_superuser`) — **[V] SEC-01**. Combined with `IsAdminUser` on the whole `/api/v1/admin/*` surface and Django admin, this is full platform takeover in one request.
2. **Cross-tenant IDOR on ad-platform integrations** — any logged-in user can read another organization's Facebook pages / ad accounts, change which ad account it spends from, or **disconnect** its integrations by passing the victim's `org_id` — **[V] SEC-02**.
3. **Legacy "test" endpoints let any org member create / update / delete ads on another organization's real Meta/Google/TikTok account** by guessing a sequential `campaign_id` — **[V] SEC-03**.
4. **Role checks are missing or incomplete**: a plain `MEMBER` can rename/re-status the organization, archive campaigns, disconnect integrations; an `ADMIN` can promote themselves to `OWNER` — **[V] SEC-04, SEC-05**.
5. **Account takeover via OTP**: 6-digit codes from a non-crypto RNG, no attempt limit, no rate limiting anywhere in the project, and the same code works for e-mail verification *and* password reset — **[V] SEC-06**.

### 1.2 Systemic problems behind the individual bugs

* **No rate limiting / throttling at all** (DRF or nginx). **[V]**
* **No default permission class** — DRF falls back to `AllowAny`, so every view that forgets `permission_classes` is public (3 already are, one of which crashes). **[V]**
* **Tenant isolation is done per view by hand**, and was forgotten in at least 9 views. There is no shared queryset scoping or object-level permission.
* **Subscription entitlements are never enforced**: campaign limits, team limits, AI-copy quota and "active subscription required" exist as data only. Free accounts can burn OpenAI credit. **[S]**
* **Insecure defaults in production settings**: `DEBUG=True`, a hard-coded `SECRET_KEY`, `ALLOWED_HOSTS=*`, `CORS_ALLOW_ALL_ORIGINS=True` when env vars are missing. **[S]**
* **Operational foot-guns**: `makemigrations` runs at container start, the SQLite dev DB is baked into the image, Dozzle (Docker socket) is internet-reachable, port 8000 bypasses nginx. **[S]**
* **Dependencies**: 25 of 135 pinned Python packages have known advisories (Django 6.0 alone has 26; Pillow 58; PyJWT 17; aiohttp 40). Frontend `npm audit`: 15 findings, **2 critical** (`jspdf`, `swiper`). **[T]**
* **Performance**: HTTP is served by Daphne with *synchronous* DRF views — Django's ASGI handler runs all sync views on **one shared thread per process**, and 19 of 40 outbound `requests` calls have no timeout, so one slow Meta/TikTok response can stall the whole API. **[S]**

### 1.3 Finding counts

| Area | Critical | High | Medium | Low / Info |
|---|---|---|---|---|
| Security (`SEC-*`) | 7 (SEC-01…07) | 14 (SEC-08…21) | 17 (SEC-22…38) | 10 (SEC-39…48) |
| Backend performance (`PERF-*`) | – | 5 (PERF-01…05) | 12 (PERF-06…17) | – |
| Frontend performance (`FPERF-*`) | – | – | 5 | – |
| Architecture / quality / ops (`ARCH`, `Q-*`) | – | 1 | 14 | – |

(Index of every ID is in Appendix A; endpoint-by-endpoint recommendations are in section 8.)


---

## 2. Verified proofs-of-concept (what was actually run)

All run with Django's test client against the test database. Results below are real output.

| # | Action | Result |
|---|---|---|
| 1 | Regular user: `PATCH /accounts/profile/update/ {"is_staff":true,"is_superuser":true}` | `200`, DB row now `is_staff=True, is_superuser=True` |
| 2 | Anonymous: `POST /accounts/change-password/` | `500` (`NotImplementedError: Django doesn't provide a DB representation for AnonymousUser`) |
| 3 | `POST /accounts/register/` with password `"1"` | `201` — no password validation |
| 4 | 30 consecutive wrong OTPs to `/accounts/verify-email/` | 30 × `400`, never `429` |
| 5 | `POST /accounts/resend-otp/` for an unknown address | `400 "User with this email does not exist"` (account enumeration) |
| 6 | `GET /api/schema/` unauthenticated | `200` (full API map) |
| 7 | User B calls `POST /main/disconnect-integration/?org_id=<A's org>` | `200`, A's integration row deleted |
| 8 | User B calls `POST /main/select-meta-page/?org_id=<A's org>` | `200`, A's `page_id` overwritten |
| 9 | User B calls `GET /main/get-meta-pages/?org_id=<A's org>` | `200` (A's token used to query Facebook) |
| 10 | User B calls `POST /main/meta/delete-ad/` with B's own `org_id` and **A's** `campaign_id` | request passed authorization and reached the Meta delete routine (`500` only because A's integration had already been removed in step 7) |
| 11 | User B calls `POST /main/create-platform-campaign/` with A's `campaign_id` | request passed authorization (`500`) |
| 12 | `MEMBER` of A: `PATCH /main/organization/ {"name":"pwned","status":"TRIAL"}` | `200`, name and status changed |
| 13 | `MEMBER` of A: `PATCH /main/campaign/<id>/ {"status":"ARCHIVED"}` | `200`, status changed |
| 14 | `ADMIN` of A: `PATCH /main/team-member/<own id>/ {"role":"OWNER"}` | `200`, role is now `OWNER` |
| 15 | `POST /main/accept-invitation/<token>/` for an invitation created 30 days ago | `200` — expiry is never checked |
| 16 | 5 × `POST /accounts/test-notifications/` | 5 × `201` |
| 17 | `POST /accounts/contact-us/` with a 2 MB message, unauthenticated | `201` |

---

## 3. Security findings

### 3.1 Critical

#### SEC-01 — Privilege escalation through profile update **[V]**
* **Where:** `apps/accounts/serializers.py` → `UserSerializer` (`exclude = ['password','groups','user_permissions']`), used by `UpdateProfileView` (`apps/accounts/views.py`, `PATCH /accounts/profile/update/`).
* **Problem:** an `exclude` list makes every other model field writable: `is_staff`, `is_superuser`, `is_active`, `status`, `last_login`, `username`. Only `id`, `email`, `joined_at` are read-only.
* **Impact:** a user sends one PATCH and becomes staff/superuser → every `IsAdminUser` endpoint (all users, all organizations, all payments, contact messages, organization deletion, user suspension) and the Django admin.
* **Fix:** use an allow-list:
  ```python
  class ProfileUpdateSerializer(serializers.ModelSerializer):
      class Meta:
          model = User
          fields = ['full_name', 'phone_number', 'avatar', 'gender', 'age', 'date_of_birth', 'timezone']
  ```
  Never use `exclude` / `__all__` on write serializers. Add a regression test that PATCHing `is_staff` does not change it. Review every other `fields='__all__'` serializer (`NotificationSerializer`, `ContactUsMessageSerializer`, `AdminNotificationSettingsSerializer`, `TempCampaignSerializer`).
* **After fixing:** audit `users` for rows that were already escalated (`SELECT email FROM users WHERE is_staff OR is_superuser`).

#### SEC-02 — Integration endpoints are not tenant-scoped (IDOR) **[V]**
* **Where:** `apps/main/integration_handler.py` — `AdProfileListView`, `SelectAdProfileView`, `MetaPageListView`, `SelectMetaPageView`, `DisconnectAdIntegrationView`. Their only permission is `IsRegularPlatformUser`; `RequiredOrganizationIDMixin.get_org_id()` only checks that the organization *exists*.
* **Impact:** any authenticated user can (a) enumerate another organization's Facebook pages / ad accounts / Google sub-accounts using *their* OAuth token, (b) switch the selected `ad_account_id` / `page_id` so future ads and spend go elsewhere, (c) delete the integration (cascade-deletes its `PlatformCampaign`s, ad groups and ads locally).
* **Fix:** `permission_classes = [IsRegularPlatformUser, IsOrganizationMember]` at minimum, and `IsAdminOrOwnerOfOrganization` for select/disconnect (changing where money is spent is an admin action). Better: make `IsOrganizationMember` stash the resolved organization on `request` and have views read it from there so they cannot forget the check (see ARCH-01).

#### SEC-03 — Unscoped `campaign_id` in legacy/"test" endpoints **[V]**
* **Where:** `apps/main/views.py` — `MetaCreateAdTestAPIView`, `MetaUpdateCampaignTestAPIView`, `MetaDeleteAdTestAPIView` (`/main/meta/*`) and `CreatePlatformCampaignAPIView` (`/main/create-platform-campaign/`). They load `UnifiedCampaign` / `AdAsset` by raw ID with no `organization=` filter. `PlatformCreateAdTestAPIView` is scoped correctly and shows the right pattern.
* **Impact:** campaign IDs are sequential integers. Any org member can create, modify or **delete real ads on a stranger's ad account** and read raw exception text. `create-platform-campaign` also does `UnifiedCampaign.objects.get(...)` → unhandled `DoesNotExist` → 500.
* **Fix:** delete these endpoints from production (they are documented as test endpoints). If any is needed, scope by `organization`, require owner/admin and return 404 for foreign IDs.

#### SEC-04 — Missing role checks on state-changing endpoints **[V]**
`IsOrganizationMember` only proves membership (and does not even check `status='ACTIVE'`). A role `MEMBER` can:

| Endpoint | What a MEMBER can do |
|---|---|
| `PATCH /main/organization/` | rename the org and change `status` (e.g. un-suspend; `OrganizationSerializer.status` is writable) |
| `PATCH/PUT/DELETE /main/campaign/<id>/` | `CampaignSerializer.status` is writable → archive/activate a campaign and bypass the publish validation; `DELETE` is guarded (owner/admin) but `PATCH` is not |
| `POST /main/campaign/<id>/toggle-status/` | pause/resume spend on every platform |
| `POST /main/sync-ads/`, `/sync-analytics/` | trigger platform API calls (rate-limit exhaustion on your Meta/TikTok app) |
| `POST /main/create-ad/`, `/update-ad/` | create and publish campaigns (spend) |
| `POST /main/ai-optimization/run/` | (new endpoint) |
| integration select/disconnect | see SEC-02 |

* **Fix:** define a role matrix (OWNER / ADMIN / MEMBER) and encode it as permission classes (`IsOrgAdmin`, `IsOrgMember`, `ReadOnlyForMembers`). Make `status` read-only on `OrganizationSerializer` and `CampaignSerializer` for non-staff; drive status changes through dedicated actions only.

#### SEC-05 — Role escalation in team management **[V]**
* **Where:** `UpdateDeleteTeamMemberAPIView.update` (`apps/main/views.py`) → `TeamService.update_team_member`.
* **Problem:** `new_role = request.data.get('role', instance.role)` is never validated. An `ADMIN` can set `role='OWNER'` for themselves (verified) or any 20-char string (the field is a free `CharField`; choices are not enforced on assignment). An ADMIN can also demote/remove other ADMINs, and invite another ADMIN with no owner approval. Self-removal of the last admin is not prevented.
* **Fix:** validate against `{ADMIN, MEMBER}`; only an `OWNER` may assign `ADMIN`; nobody may assign `OWNER` (use an explicit "transfer ownership" flow with re-authentication); forbid changing your own role; forbid removing the last OWNER/ADMIN.

#### SEC-06 — OTP design allows brute force and cross-purpose reuse **[V]**
* **Where:** `RegisterView`, `SendOTPView` (also mounted as `/password-reset/` and `/resend-otp/`), `VerifyEmailView`, `CheckOTPView`, `PasswordResetConfirmView` in `apps/accounts/views.py`.
* **Problems**
  1. Codes come from `random.randint` (Mersenne Twister, not cryptographically secure). Use `secrets.randbelow(10**6)`.
  2. **No attempt counter and no throttling.** 30 wrong guesses → 30 × 400 (verified). Search space is 10⁶ and the code lives 10 minutes.
  3. One `OTP` table, no `purpose` column: an e-mail-verification code is accepted by `password-reset-confirm`, and vice versa.
  4. Old codes are not invalidated when a new one is issued; `SendOTPView` can be called unlimited times (mail bombing, unbounded table growth).
  5. `OTP.objects.filter(...).exists()` then `.get()` → `MultipleObjectsReturned` (500) if two identical codes exist; the generic `except Exception` returns `str(e)` to the caller.
  6. `CheckOTPView` / `VerifyEmailView` are an oracle for valid codes.
* **Fix:** store a *hash* of the code with `purpose`, `attempts`, `expires_at`; delete previous codes on re-issue; lock after 5 failed attempts; throttle per e-mail **and** per IP (see section 8); use `secrets`; constant-time compare; return identical responses for existing/unknown accounts.

#### SEC-07 — Insecure production defaults in `settings.py` **[S]**
```python
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-e7iz@(00au76(vdf40adk+@dbtl_wvgf@=zbh+u2szp(z1zu68')  # line 31
DEBUG = os.getenv('DEBUG', 'True') == 'True'                                                              # line 34
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*').split(',')                                                # line 36
CORS_ALLOW_ALL_ORIGINS = True ; CORS_ALLOW_CREDENTIALS = True                                             # lines 265-266
```
A forgotten env var silently produces a debug-mode server signing JWTs with a key that is public in git history. The JWT `SIGNING_KEY` defaults to `SECRET_KEY`, so **anyone who reads the repo can forge access tokens** on such a deployment. `DEBUG=True` also leaks the OTP in the register response (`views.py` ~line 59) and enables the DRF browsable API with settings/traceback pages.
* **Fix:** no defaults for `SECRET_KEY`; `DEBUG` default `False`; fail fast at boot if `SECRET_KEY`, `ALLOWED_HOSTS`, `STRIPE_*`, DB creds are missing when `DEBUG=False`; explicit `CORS_ALLOWED_ORIGINS = [FRONTEND_URL, ...]`; rotate the current key (it is in history). Use a dedicated `JWT_SIGNING_KEY`.

---

### 3.2 High

#### SEC-08 — Uploads: type trusted from the client, SVG allowed, served from the API origin **[S]**
* `CreateAdSerializer.validate_ad_file` (`apps/main/serializers.py`) only checks `value.content_type`, which is the client-supplied multipart header. `image/svg+xml` and `image/x-icon` etc. are on the allow-list. Files are written to `media/ad_assets/` under their original name and served by nginx at `https://api…/media/` with `Access-Control-Allow-Origin: *` and no `X-Content-Type-Options` / `Content-Disposition` / CSP.
* **Impact:** an SVG with `<script>` is served as `image/svg+xml` and executes when opened directly → stored XSS **on the same origin as `/admin/`** (session cookie) and the API. Fake content types also feed arbitrary bytes to Meta/TikTok uploads and to Pillow (see SEC-19).
* **Fix:** remove SVG; verify magic bytes (`python-magic`/`filetype`) and decode images with Pillow (`Image.verify()`), cap pixel dimensions (`Image.MAX_IMAGE_PIXELS`) and file size per type (e.g. 10 MB image / 200 MB video); randomise stored filenames (UUID); serve media from a separate cookieless domain/bucket with `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`; `Content-Disposition: attachment` for non-image types. Profile avatars (`ImageField`) need the same size cap.

#### SEC-09 — Customer reports and uploads are public and guessable **[S]**
Reports are saved as `"{Type}_report_{organization.name}_{YYYYMMDD}_{YYYYMMDD}.xlsx"` (`apps/analysis/tasks.py`) under `media/reports/`, which nginx serves to the world. File names are fully predictable from public info (org name + date range) → anyone can download spend/performance data of any customer. Uploaded creatives and avatars have the same exposure.
* **Fix:** store private files in a private bucket/dir and serve them through an authenticated view (`FileResponse`) or short-lived signed URLs (S3 pre-signed, or nginx `X-Accel-Redirect` after an auth check). At minimum use `uuid4().hex` file names. Do the same for admin reports (`media/reports/admin/`).

#### SEC-10 — No password-strength enforcement; password endpoints are fragile **[V]**
* `AUTH_PASSWORD_VALIDATORS` is configured but **never called**: `RegisterSerializer`, `ResetPasswordConfirmSerializer`, `ChangePasswordSerializer` are plain `CharField`s. `"1"` registers successfully (verified).
* `ChangePasswordView` declares `permission_classes = []` → anonymous call crashes with 500 (verified) instead of 401.
* Changing/resetting a password does not revoke existing refresh tokens (30-day lifetime), and requires no re-authentication to change e-mail-linked data.
* **Fix:** call `django.contrib.auth.password_validation.validate_password(value, user)` in all three serializers; use `IsAuthenticated`; after change/reset blacklist all outstanding tokens for the user (`OutstandingToken` table is available) and rotate.

#### SEC-11 — Expired and un-throttled team invitations; temp password by e-mail **[V]**
* `TeamService.accept_invitation` filters `status='PENDING'` but never calls `TeamInvitation.is_expired()` — a 30-day-old invite is accepted (verified).
* Accepting creates the account with a random 10-char password generated with `random.choices` (non-crypto) and e-mails it in clear text (`send_account_created_email`). Users are `is_active=True` without e-mail verification and the new account's password is the only secret.
* No limit on invites per organization/day, no de-duplication of pending invites, and the plan's `team_member_limit` is never enforced.
* **Fix:** check expiry; use a "set your password" link (signed, single-use) instead of mailing a password; `secrets`; enforce `team_member_limit` and an invite rate limit; make tokens single-use and bind accept to the invited e-mail.

#### SEC-12 — Platform OAuth tokens: stored in clear, weak lifecycle, leaked via URLs **[S]**
* `AdIntegration.access_token` / `refresh_token` are plain `TextField`s. A DB dump or backup leaks every customer's ad-account access.
* Meta short-lived tokens (≈1–2 h) are saved as-is; there is no exchange for a long-lived token and no refresh path, so integrations silently die. TikTok has no refresh at all. Google refresh code is duplicated in `manage_ad.py` and `sync_ad.py`.
* Meta calls pass `access_token` as a **query parameter** (`integration_handler.py`), so tokens end up in access logs, `requests` exception messages and Sentry-style traces. TikTok sends `secret` as a query parameter.
* Callbacks return provider error bodies verbatim (`return Response(token_res, status=400)`), `User.objects.get(id=user_id)` can 500, and OAuth `state` is `"<token>:<org_id>"` where `org_id` is *outside* the cached secret (membership is re-checked, so low impact).
* **Fix:** encrypt at rest (e.g. `django-fernet-encrypted-fields` or KMS envelope encryption, key outside the DB); send tokens in `Authorization` headers; implement Meta long-lived exchange + token expiry checks + refresh tasks; redact tokens in log formatters; sanitise callback errors; require OWNER/ADMIN to connect/disconnect.

#### SEC-13 — Entitlements/plan limits are never enforced; suspended orgs keep working **[S]**
* `Plan.get_campaign_limit()` / `get_team_member_limit()` are only read for display. `grep` shows no enforcement in `create-ad`, `publish_campaign`, `invite_team_member` or the AI views. Reports check "active subscription" (good) but nothing else does.
* `Organization.status == SUSPENDED` is only used for admin counters; a suspended organization can still use every API.
* **Impact:** free or unpaid accounts can create unlimited campaigns, invite unlimited members and call GPT-4o (`/generate-ai-copy/`, `/generate-ad-copy/`) with no quota → direct cost exposure.
* **Fix:** one `entitlements` service (`can_create_campaign(org)`, `can_invite(org)`, `ai_quota_remaining(org)`) called from the views/services and a permission class `OrganizationIsActive` that denies suspended/unpaid orgs; add per-org AI quotas and the throttles from section 8.

#### SEC-14 — Stripe integration gaps (money-related) **[S]**
* `StripeWebhookView`: no event-ID de-duplication (Stripe retries; `invoice.payment_failed` inserts a new `Payment` each time); `session["metadata"]["plan_id"]` raises `KeyError` → 500 → endless retries; handlers are not wrapped in `transaction.atomic`; no logging of unhandled event types.
* **Renewals are never recorded**: there is no `invoice.paid` / `invoice.payment_succeeded` handler, so only the first payment appears in billing history and `current_period_end` only moves via `subscription.updated`.
* `BuyPlanAPIView`: `int(plan_id)` on bad input → 500; Stripe network calls happen *inside* `transaction.atomic()` while holding a `select_for_update` row lock (long lock, and local DB diverges if Stripe succeeds but the commit fails); upgrade updates the local plan *before* payment confirmation; every attempt creates an `incomplete` `Subscription` row (abandoned checkouts accumulate); no Stripe `idempotency_key`; `customer_email=` creates a new Stripe Customer each time (no `stripe_customer_id` stored, so no billing portal / saved cards); `int(price*100)` on a Decimal.
* Environment variable for the signing secret is named `HTTP_STRIPE_SIGNATURE` (`webhook.py`), easy to confuse with the header; `stripe.error.*` is the deprecated exception path in current SDKs — prefer `stripe.SignatureVerificationError` / `stripe.StripeError`.
* **Fix:** persist `stripe_event_id` (unique) and ignore repeats; add `invoice.paid`; use `Customer` objects; pass idempotency keys; move Stripe calls outside DB locks and reconcile with the webhook as the single source of truth; add a periodic "reconcile subscriptions" Celery task.

#### SEC-15 — Account deletion and Meta data-deletion callback are dangerous **[S]**
* `DELETE /accounts/delete-account/` hard-deletes the user with no password/OTP confirmation, does not cancel the Stripe subscription (customer keeps being billed), and cascades into organizations the user *owns* even when they have other members.
* `MetaDataDeletionCallbackView` (public, signature verified — good) maps a Facebook UID to users by comparing it with `ad_account_id` / `page_id` (which are *not* the Facebook user ID) by loading **all** Meta integrations into Python, then deletes **all data of the integration owner**. It can delete the wrong customer's data, ignores `issued_at` (replay), and the docstring says the user record is preserved while the code path leaves orphan state.
* **Fix:** require re-authentication, cancel Stripe in a task, soft-delete with a grace period, transfer or block deletion when other members exist; store the Facebook `user_id` returned at OAuth time on the integration and match on that; log an audit record.

#### SEC-16 — Container and deployment exposure **[S]**
* `docker-compose.yml`: `web` publishes `8000:8000` to the host (plain HTTP, bypasses nginx/TLS/headers; `SECURE_PROXY_SSL_HEADER` then trusts a spoofable `X-Forwarded-Proto`). Remove `ports:` and keep `expose:`.
* `dozzle` mounts `/var/run/docker.sock` and is published under `https://api…/dozzle/` behind a single static user file. The Docker socket (even `:ro`) is root-equivalent information disclosure and application logs contain PII. Put it behind VPN/IP allow-list or remove it; use a log shipper instead.
* `entrypoint.sh` runs **`makemigrations --noinput`** on every web start (creates migration files inside the container, hides model drift, and races when multiple replicas start) and `collectstatic --clear`. Run `migrate` as a release step only.
* `.dockerignore` has `# db.sqlite3` commented out → the developer SQLite DB (users, tokens) is copied into the image; `frontend/`, `docs/`, `.agents/`, `.github/` are copied too. Image runs as non-root (good) but uses `python:3.12-slim` unpinned digest and installs `gcc` in the runtime layer (use multi-stage).
* `certbot`/`dozzle` use `:latest`; containers have no health checks, resource limits or `read_only` filesystems; Redis has no password; Postgres/Redis lack TLS (acceptable on an internal network, document it).

#### SEC-17 — nginx: no rate limiting, no security headers, media served unsafely **[S]**
`nginx/nginx.conf` (see section 9 for a replacement): no `limit_req`/`limit_conn`, no HSTS / `X-Content-Type-Options` / `X-Frame-Options` / `Referrer-Policy` / CSP, no gzip/brotli, `listen 443 ssl http2` syntax is deprecated on nginx ≥ 1.25, static/media locations return `Access-Control-Allow-Origin: *` and `Allow-Headers: *`, API has global `client_max_body_size 20M`, no timeouts for slow clients, access log contains full query strings (JWT in `?token=` for WebSocket, `org_id`, OAuth `code`/`state`). The SPA server block has no `Cache-Control: no-cache` for `index.html`.

#### SEC-18 — Known-vulnerable dependencies **[T]**
`pip-audit -r requirements.txt` (no-deps mode): **25 vulnerable packages of 135**:

| Package | Pinned | # advisories | Fixed in | Why it matters here |
|---|---|---|---|---|
| Django | 6.0 | 26 | ≥ 6.1.1 (apply the latest 6.0.x patch at minimum) | core framework |
| Pillow | 12.0.0 | 58 | 13.0.0 | processes user-uploaded images |
| aiohttp | 3.13.2 | 40 | 3.14.4 | pulled in by channels/openai/tooling |
| PyJWT | 2.10.1 | 17 | 2.15.0 | JWT verification |
| Twisted | 25.5.0 | 9 | 26.4.0 | Daphne's engine (public HTTP/WS) |
| cryptography | 46.0.3 | 7 | ≥ 47 | TLS/JWT primitives |
| djangorestframework | 3.16.1 | 5 | 3.18.2 | API layer |
| urllib3 / requests / certifi / idna | 2.6.0 / 2.32.5 / 2025.11.12 / 3.11 | 5 / 1 / 1 / 1 | 2.8.0 / 2.33.0 / 2026.10.18 / 3.15 | every outbound call |
| daphne | 4.2.1 | 2 | 4.2.2 | public server |
| ujson, sqlparse, pyasn1, anyio, pyopenssl, filelock, msgpack, werkzeug, autobahn, cbor2, multidict, python-dotenv, snowflake-connector-python | – | 1–8 each | see `pip-audit` | transitive |

Frontend `npm audit --omit=dev`: 15 findings (2 moderate, 11 high, **2 critical: `jspdf`, `swiper`**), including `axios`, `react-router(-dom)`, `vite`, `rollup`, `postcss`, `dompurify`. Run `npm audit fix` and re-test.
Also: `requirements.txt` contains dev/typing tools (`mypy`, `django-stubs`, `types-*`, `pandas-stubs`), unused libraries (`boto3`, `snowflake-connector-python`, `snowflake.core`, `django-silk` which is disabled, `numpy`) and has no hashes. Split into `requirements/base.txt`, `dev.txt`; remove unused; enable Dependabot/Renovate and `pip-audit` in CI. The frontend also ships the server-side `stripe` SDK in `dependencies` (only `@stripe/stripe-js` is needed in a browser app).

#### SEC-19 — Image/video parsing of untrusted uploads
`tiktok_handler.py` opens uploads with Pillow and hashes them; combined with the Pillow advisories above and no size/pixel limits, a decompression bomb or crafted image can exhaust memory in the web/Celery process. Set `Image.MAX_IMAGE_PIXELS`, enforce byte limits before reading, and do the processing in a Celery task with `soft_time_limit`.

#### SEC-20 — WebSocket channel **[S]**
* The JWT is passed in the query string (`/ws/notifications/?token=…`) → stored in nginx/Daphne/browser history logs. Prefer a short-lived one-time ticket issued by an authenticated REST call, or send the token in the first message / `Sec-WebSocket-Protocol`.
* `ASGI` stack lacks `AllowedHostsOriginValidator` → cross-site WebSocket hijacking is possible when a victim's token is available (e.g. from XSS); add it.
* `NotificationConsumer.disconnect` uses `self.group_name` which does not exist when `connect()` closed an anonymous socket → `AttributeError` on every rejected connection.
* Notification signal handlers push over the channel layer synchronously; if Redis is down the *business request* that created the notification fails (the signal handler is not wrapped in `try/except`, unlike `_ws_push`). See PERF-12 for the duplicate push.

#### SEC-21 — Account enumeration and registration abuse **[V]**
`resend-otp`/`password-reset` answer `400 "User with this email does not exist"`; `verify-email`, `check-otp`, `password-reset-confirm` answer `404 "User not found"`. `RegisterView` **deletes any existing inactive user with the same e-mail** before creating a new one (anyone can wipe someone else's pending registration or race it), and sends the OTP synchronously inside the request (slow, and failure is swallowed).
* **Fix:** uniform "if the address exists we sent a code" responses; do not delete — resend; send mail from Celery; add CAPTCHA/Turnstile on register, login-after-N-failures, contact-us and password reset.

---

### 3.3 Medium

| ID | Finding | Evidence / fix |
|---|---|---|
| SEC-22 | **JWT lifecycle**: 30-day refresh tokens in `localStorage` (frontend), 1 h access. `OutstandingToken`/`BlacklistedToken` tables never flushed (`manage.py flushexpiredtokens` not scheduled). Logout takes any refresh token string from the body (fine) but returns `str(e)`. Suspending a user relies on SimpleJWT's `is_active` check. | Move refresh token to an `HttpOnly; Secure; SameSite=Strict` cookie, shorten to 7–14 d, schedule `flushexpiredtokens`, add per-device session list. |
| SEC-23 | **Error-detail leakage**: 83 `except Exception` blocks; views return `str(exc)` (test endpoints, `VerifyEmailView.detail`, `LogoutView`, integration callbacks, `fetch_google_child_accounts`). | Return generic messages + a correlation ID; log the exception server-side. Add a global DRF `EXCEPTION_HANDLER`. |
| SEC-24 | **No Django security hardening**: `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_REFERRER_POLICY`, `SECURE_CONTENT_TYPE_NOSNIFF`, `SESSION_COOKIE_SAMESITE`, `CSRF_COOKIE_HTTPONLY`, `SECURE_CROSS_ORIGIN_OPENER_POLICY` not set; `python manage.py check --deploy` would fail. | See section 10.1. |
| SEC-25 | **Spreadsheet formula injection**: `apps/analysis/tasks.py` writes campaign names (user-controlled, platform-synced) with `sheet.cell(value=…)`; openpyxl turns strings starting with `=`, `+`, `-`, `@` into formulas (Excel/LibreOffice execute `=HYPERLINK(...)`/DDE). Same in admin reports. | Prefix with `'` or set `cell.data_type = 's'` for any string starting with those characters. |
| SEC-26 | **Test/diagnostic endpoints in production**: `/accounts/test-notifications/` (spams the DB/WS), `/main/meta/*`, `/main/test/create-ad-on-platform/`, `create test account google ad.py`, `ApplyBudgetRecommendation` (see SEC-04). | Gate behind `settings.DEBUG`/feature flag or delete. |
| SEC-27 | **API schema + browsable API public**: `/api/schema/`, `/api/schema/swagger-ui/` are `AllowAny` [V]; DRF default renderers include `BrowsableAPIRenderer`; `/api/v1/admin/` router root is public. | Restrict schema to staff or disable in prod; set `DEFAULT_RENDERER_CLASSES = [JSONRenderer]` when not DEBUG. |
| SEC-28 | **Django admin on the public API host** with Unfold, no MFA/IP allow-list. `UserAdmin` subclasses plain `ModelAdmin`, not `django.contrib.auth.admin.UserAdmin` → the password field is edited as a raw hash text box and "add user" would store a plaintext password. | Mount admin on an internal host/VPN, add `django-otp`/`allauth` MFA, base on the real `UserAdmin`. Change the default URL. |
| SEC-29 | **No default DRF permission/auth/throttle/pagination/renderer** in `REST_FRAMEWORK` (lines 209–214). Missing `permission_classes` ⇒ `AllowAny` (`change-password`, `contact-us`, `login`, `token/refresh`, `get-plans`, `stripe/webhook`, `delete-data` are all "default"). | `DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]`, opt-in `AllowAny` explicitly; add `DEFAULT_THROTTLE_*`, `DEFAULT_PAGINATION_CLASS` + `PAGE_SIZE`, `DEFAULT_RENDERER_CLASSES`, `EXCEPTION_HANDLER`. |
| SEC-30 | **Unbounded/unauthenticated write**: `contact-us` accepts arbitrary-length `message` (verified 2 MB), no throttle/CAPTCHA, `ContactUsMessageSerializer.fields='__all__'`. | `max_length` on every field, throttle, honeypot/CAPTCHA, `DATA_UPLOAD_MAX_MEMORY_SIZE`. |
| SEC-31 | **Org lookups trust query-string `org_id`** and are done three times per request (mixin + permission + view). Not an auth bug by itself (membership is checked), but it is why SEC-02/03 happened. | See ARCH-01. |
| SEC-32 | **Path/parameter injection into provider URLs**: `page_id`, `manager_id`, `acc_id` are interpolated into Graph/Google URLs and the `login-customer-id` header without validation. | Validate with `^\d{1,30}$` (or `act_\d+`). |
| SEC-33 | **Hard-coded `CSRF_TRUSTED_ORIGINS`** contain internal IPs (`10.10.13.88`), `localhost`, and an `ngrok` tunnel; `CORS_ALLOW_ALL_ORIGINS=True` with `CORS_ALLOW_CREDENTIALS=True` reflects any origin to the session-cookie surface (`/admin/`). | Env-driven lists per environment. |
| SEC-34 | **Frontend token storage**: `accessToken`/`refreshToken` in `localStorage` (readable by any XSS, including third-party script/CDN compromise). Dev interceptor logs token previews (`console.log` count: 282). | HttpOnly cookie for refresh; in-memory access token; strip `console.*` in production build (`esbuild.drop`). |
| SEC-35 | **Frontend authorization is UI-only**: `ProtectedRoute` checks "is logged in" only; `/admin-dashboard/*` renders for any user (backend still returns 403, but the UI leaks structure and invites probing). | Role-aware guards driven by `/profile/` (`is_admin`) + redirect. |
| SEC-36 | **LLM safety / privacy**: user text (`product`, `audience`, `benefits`) is interpolated into prompts (prompt injection can change output; outputs are rendered by React so XSS is mitigated); campaign names + performance data are sent to OpenAI without a documented DPA/opt-out; no `max_tokens`, `timeout`, moderation, or per-call cost accounting. | Put user text in a separate message, validate JSON schema of outputs, set `timeout=20`, `max_tokens`, log token usage per org. |
| SEC-37 | **Logs**: `logs/app.log` (16 MB locally) contains IPs and request lines; log level INFO to both file and console; errors log full exception strings that may include tokens (Meta URLs). | Redact `access_token`/`secret`/`code`, ship stdout only in containers, retention policy. |
| SEC-38 | **Snowflake ID generator** `SnowflakeGenerator(1)` is created at import time with a fixed instance ID in every process (web, Celery workers, beat) → possible duplicate `Organization.snowflake_id` across processes (unique constraint → 500 on signup). | Derive instance from `os.getpid()`/host/env, or use UUIDs for public IDs. |

### 3.4 Low / Informational

* SEC-39 `Organization`, `User.full_name` (`max_length=30`), `Report.name` lengths are small/inconsistent; `Organization.name` nullable.
* SEC-40 `NotificationSerializer.fields='__all__'` exposes `user` and `organization` IDs (own data only).
* SEC-41 `MarkNotificationRead`/`Delete…` use `id__in=<unvalidated list>` → 500 for non-integers.
* SEC-42 `TeamInvitation.token` is a UUID4 in the URL path (single-use not enforced, appears in logs and e-mail clients).
* SEC-43 Stripe `return_url` and invitation links are built from `FRONTEND_URL`; keep it HTTPS-only in production.
* SEC-44 `UserAdminViewSerializer.role` is `Admin/User` only; no distinction between staff and superuser, no audit trail for admin actions (suspend user, delete organization, report generation).
* SEC-45 `ChangeUserStatusAPIView` allows staff to deactivate other staff; `AdminOrganizationDetailAPIView.delete` hard-deletes with no confirmation, no Stripe cancellation and no audit log.
* SEC-46 Frontend `<a target="_blank">` without `rel="noopener noreferrer"` in 2 places; `window.open(redirect_url)` for OAuth (fine, but validate the host).
* SEC-47 No `Permissions-Policy`, `Cross-Origin-Opener-Policy` headers anywhere.
* SEC-48 `/media/` is served by Django's `static()` helper in `urls.py` too (harmless when `DEBUG=False`, but it means two code paths).

---

## 4. Authorization model — the root cause and the fix (ARCH-01)

Today every view repeats:

```python
org = Organization.objects.filter(snowflake_id=self.get_org_id()).first()
if not org: raise ValidationError(...)
```
plus a `permission_classes` pair. Nine views forgot the membership permission, several forgot the role permission, and nothing scopes IDs (`campaign_id`, `ad_asset_id`, `payment_id`).

**Recommended structure**

```python
# apps/accounts/permissions.py
class OrgPermission(BasePermission):
    allowed_roles = None            # None = any ACTIVE member
    def has_permission(self, request, view):
        org_id = request.query_params.get("org_id")
        m = (OrganizationMember.objects
             .select_related("organization")
             .filter(user=request.user, status="ACTIVE", organization__snowflake_id=org_id)
             .first())
        if not m or m.organization.status == "SUSPENDED": return False
        if self.allowed_roles and m.role not in self.allowed_roles: return False
        request.organization, request.membership = m.organization, m       # 1 query, reused everywhere
        return True

class IsOrgMember(OrgPermission): pass
class IsOrgAdmin(OrgPermission): allowed_roles = ("OWNER", "ADMIN")
class IsOrgOwner(OrgPermission): allowed_roles = ("OWNER",)
```
Then a mixin whose `get_queryset()` always starts from `Model.objects.filter(organization=request.organization)`. This (a) removes the 3-query-per-request overhead (PERF-03), (b) makes SEC-02/03/04 impossible by construction, and (c) enforces `ACTIVE` membership and suspended orgs in one place. Add a **generic cross-tenant test** that iterates every route with `org_id` and asserts a non-member gets 403/404.

---

## 5. Performance & optimization findings

### 5.1 High impact

#### PERF-01 — Sync views on Daphne run on a single thread **[S]**
`docker-compose.yml` runs `daphne … AdPortal.asgi:application` for **all** HTTP traffic. All DRF views are synchronous; under ASGI Django runs sync code with `sync_to_async(thread_sensitive=True)`, i.e. **one shared worker thread per process** — requests are effectively serialized. With 19 of 40 outbound HTTP calls lacking timeouts (PERF-02) one stuck Meta/TikTok call blocks every user of that process.
* **Fix (pick one):** serve HTTP with **Gunicorn (gthread/sync workers) behind nginx** and keep Daphne/Uvicorn only for `/ws/`; or run several Daphne processes and set `ASGI_THREADS`. Size workers = 2–4 × CPU. Move slow integrations to Celery (most already are).

#### PERF-02 — Outbound HTTP without timeouts / retries / circuit breaking **[S]**
Of 40 `requests.*` calls (counted with an AST scan), **19 have no `timeout`**: 10 in `integration_handler.py` (all `fetch_meta_*`, `fetch_tiktok_ads_account`, the Meta/TikTok callbacks) and 9 in the legacy part of `tiktok_handler.py`. Many requests are made in loops (`fetch_meta_pages`: one call per business + one per page edge; `fetch_google_ads_account`: one `search` call per accessible customer, ×3 API-version fallbacks).
* **Fix:** a single `apps/main/utils/http.py` wrapper (`requests.Session` with `HTTPAdapter(max_retries=Retry(...))`, default `timeout=(3.05, 20)`), connection pooling, structured error mapping, and per-provider circuit breaker; cache provider list endpoints (see section 8).

#### PERF-03 — Three organization lookups + one membership query on every request **[S]**
`RequiredOrganizationIDMixin.get_org_id()` (`exists()`), the permission (`Organization.get` + membership `exists()`), and the view (`Organization.filter().first()`) each hit the DB. Resolve once in the permission and store on `request` (ARCH-01). Saves 3 queries on ~50 endpoints.

#### PERF-04 — Unbounded aggregations over the whole `AnalysisDaily` history **[S]**
* Campaign list/detail annotate `Sum('daily_analyses__…')` with **no date bound** (`CampaignService.annotate_queryset_with_metrics`); cost grows linearly with history × campaigns on every page view.
* `AnalysisDaily` has no composite index for its dominant filter `(organization, date)`; only the `unique_together` (platform, account_id, campaign_id, adgroup_id, date) exists, which does not help org-scoped range scans.
* **Fix:** add `Index(fields=['organization','date'])`, `Index(fields=['unified_campaign','date'])`; keep lifetime totals in a rollup table/materialized view refreshed after each analytics sync; cache dashboards (section 8).

#### PERF-05 — N+1 queries in serializers **[S]**
* `PlatformAdSerializer.get_matrics` runs an `AnalysisDaily` aggregate **per ad** (and filters `adgroup_id=obj.ad_group_id`, comparing a platform string column to a local PK — it effectively always returns zeros; this is a correctness bug).
* `CampaignSerializer.get_budgets/get_audience_targeting/get_platform_sync_statuses/get_file_url` issue extra queries per campaign; `get_platform_sync_statuses` loads *all* events then dedupes in Python (use Postgres `DISTINCT ON (platform)`).
* `notify_org_members` does `get_or_create(NotificationSetting)` per member; `weekly_performance_summary_task` loops every organization with 2 queries each.
* `get_user_list` returns an unordered queryset into a paginator (inconsistent pages) and `icontains` on `email`/`full_name` is an un-indexed scan (add `pg_trgm` GIN index).

### 5.2 Medium impact

| ID | Finding | Fix |
|---|---|---|
| PERF-06 | No application cache at all (Redis cache is used only for OAuth state). Dashboards, analytics, plans, current plan (called by the sidebar on **every** page), integration status, team and notification counts are recomputed on every request. | Section 8 cache plan. |
| PERF-07 | Frontend calls `/main/campaigns/` **4×** on load just for status counts (`all/active/paused/draft`). | Return `status_counts` in the list response (one `GROUP BY`). |
| PERF-08 | Reports: `data = list(qs.values())` loads the entire result set into memory in the Celery worker; no row cap or streaming. | Iterate with `.iterator(chunk_size=2000)`, write with `openpyxl` write-only mode, cap date range. |
| PERF-09 | **Celery**: no `time_limit`/`soft_time_limit`, no `acks_late`/`reject_on_worker_lost`, no routing (long AI/sync tasks share the queue with OTP/e-mail), fixed `-c 2`. `generate_ai_insights_for_active_campaigns` processes *every* active campaign **serially in one task** and calls `self.retry()` inside the loop, so one failure restarts the whole batch and duplicates previously saved insights; insights are never de-duplicated (grows daily). Beat schedule runs at fixed UTC hours for all tenants. | Fan out one task per campaign (`group`/`chord`), `autoretry_for`, idempotency key per `(campaign, date)`, per-queue workers (`default`, `sync`, `ai`, `mail`), `task_time_limit`, `worker_prefetch_multiplier=1`, retention job for old insights/notifications/OTPs/Outstanding tokens. |
| PERF-10 | E-mail (SMTP to Gmail, 500/day cap, blocking) is sent **inside the HTTP request**; failures are swallowed. | Celery task + transactional provider (SES/Postmark/SendGrid). |
| PERF-11 | DB connections: no `CONN_MAX_AGE`/pooling; every request opens a Postgres connection. | `CONN_MAX_AGE=60` (or PgBouncer / Django 6 `OPTIONS: {"pool": True}`), `ATOMIC_REQUESTS` not needed. |
| PERF-12 | **Duplicate WebSocket pushes**: `Notification.objects.create()` fires `post_save` → handler pushes; `notify_user` then calls `_ws_push` again → each `notify_user` notification is pushed twice (the bulk path is correct). | Keep one mechanism (signal *or* helper). Wrap the signal push in `try/except` and run it in `transaction.on_commit`. |
| PERF-13 | Missing/weak indexes: `Notification(user, read, created_at)`, `OTP(user, code)` + `expires_at`, `AdIntegration(organization, platform, is_active)`, `Payment(organization, paid_at)`, `TeamInvitation(token)` (unique already) and `(organization, status, created_at)`. Large tables with no retention: `Notification`, `AnalysisDaily`, `OTP`, `PlatformSyncEvent`, `OutstandingToken`. | Add indexes via migration; add a nightly retention task. |
| PERF-14 | Unpaginated list endpoints (`team-members`, `ai-optimization/history`, `scheduled-reports`, `get-plans`) because DRF has no default pagination. | `DEFAULT_PAGINATION_CLASS`. |
| PERF-15 | `entrypoint.sh` collects static with `--clear` on every start; static served by nginx from a volume (good) but no `ManifestStaticFilesStorage`/WhiteNoise hashed names. | Use hashed static + long cache (see nginx). |
| PERF-16 | Media volume is 863 MB locally and lives on the container host; no CDN, no object storage (`boto3` is installed but unused). | S3/R2 + CDN; keep only signed URLs. |
| PERF-17 | `get_system_status()` returns hard-coded `"operational"`, `uptime_percent: 100.0` — no real probes. | Implement real health checks (DB ping, Redis ping, Celery inspect, queue depth) and expose `/healthz` + `/readyz`. |

### 5.3 Frontend performance

| ID | Finding | Fix |
|---|---|---|
| FPERF-01 | Single JS bundle **1.75 MB** (no `React.lazy`, 0 usages; `Router.tsx` imports ~70 pages eagerly; recharts, jspdf, swiper, stripe in the main chunk). | Route-level `lazy()` + `Suspense`, `manualChunks` for vendor libs, dynamic-import `jspdf`/`recharts`. |
| FPERF-02 | `src/assets` is **7.2 MB** (several 0.8–1.4 MB SVGs that are probably embedded rasters, a 1.3 MB PNG). | Re-export as optimized SVG/WebP/AVIF, `loading="lazy"`, `width/height`. |
| FPERF-03 | Hand-rolled `axios` + `useEffect` fetching on every page; no request de-duplication, caching, stale-while-revalidate or abort on unmount; `api.get` is repeated for org/plan/profile on many components. | Adopt TanStack Query (cache keys per `org_id`), central `useOrganization()`; `AbortController` in effects. |
| FPERF-04 | 179 `any` usages and 282 `console.*` calls; large commented-out blocks (≈150 lines in `lib/axios.ts`, whole old `Payment.tsx`, `AudienceAndPlacements.tsx`). | Enable `@typescript-eslint/no-explicit-any` as error gradually; remove dead code; `esbuild.drop: ['console','debugger']` for prod. |
| FPERF-05 | `Dockerfile` uses `npm install` (non-reproducible), `node:20` unpinned, default nginx config (no SPA fallback ⇒ deep links 404, no gzip/headers). Build artifacts are committed twice (`adportal_frontend/dist` is ignored but `AdPortal/frontend/` is tracked). | `npm ci`, pin versions, ship an `nginx.conf` with `try_files … /index.html`, CSP and cache headers; build in CI, don't commit. |

---

## 6. Code quality & bad practices

| ID | Finding | Recommendation |
|---|---|---|
| Q-01 | **Giant, duplicated provider modules**: `meta_engine/manage_ad.py` 1486 lines, `google_engine/manage_ad.py` 1091, `tiktok_handler.py` 993 (contains old script-style code with module-level `ACCESS_TOKEN/ADVERTISER_ID/HEADERS` read from env, "PASTE YOUR CREDENTIALS HERE", demo functions like `create_tiktok_ad_flow`). `_tiktok_get/_tiktok_post` are duplicated in three files; Google token refresh is duplicated. | Introduce a `PlatformClient` interface (create/update/pause/delete/report), one implementation per provider, one HTTP wrapper; delete the demo/sandbox functions. |
| Q-02 | **83 broad `except Exception`** (mostly swallowing) and 0 bare `except:`; views return `str(e)`. | Catch specific exceptions; central DRF exception handler; log with `logger.exception`. |
| Q-03 | **Fat views**: business logic and Stripe/HTTP calls inside views (`BuyPlanAPIView`, `PlatformCreateAdTestAPIView`, auth views). | Move to services; views become thin. (The repo already has `services/`; use it consistently.) |
| Q-04 | **Settings hacks**: `os.path.exists('/.dockerenv')`, `TESTING = 'test' in sys.argv`, `load_dotenv()` conditional, `import sys` mid-file, Celery config at the bottom, Gmail SMTP host hard-coded. | Use `django-environ`/`pydantic-settings`, `settings/base.py`, `dev.py`, `prod.py`, `test.py`. |
| Q-05 | **Implicit global behavior**: a signal creates an `Organization` for **every** `User` created, including staff accounts and users created by team invitations, so invited users get an empty personal org they never use. | Create the org in the registration service, not in `post_save`. |
| Q-06 | **Naming/typos in public API**: `matrics` (metrics), `campaings`, `NotifcationListPagination`, `camaigns`; `snowflake_id` doubling as the external org ID. | Fix with API versioning (`/api/v2/`) or keep aliases during deprecation. |
| Q-07 | Stray/unused imports: `from asyncio import threads`, `from urllib3 import request` (in `accounts/serializers.py`), duplicated `RequiredOrganizationIDMixin` import, unused `time` etc.; a Bengali comment in a React file; mixed tabs/spaces (`admin_dashboard/views.py`, `consumers.py`). | `ruff` + `ruff format` + `isort` in pre-commit and CI. |
| Q-08 | Files that shouldn't be in the repo: `create test account google ad.py` (script reading real tokens from settings), `subscription plans.json` (listed in `.gitignore` but tracked), `frontend/` (built SPA), `.agents/`, `logs/` and `db.sqlite3` present in the working dir. | Remove, add to `.gitignore`/`.dockerignore`. |
| Q-09 | `get_system_status`, `RecentCampaigns`, `SpendOverview` (unused components with sample numbers), "Retry Sync" `alert()`, "Billing FAQ"/"Manage Payment" toasts — placeholder behavior that looks real. | Implement or remove. |
| Q-10 | **Documentation drift**: `docs/ENDPOINT_LIST.md` omits `cancel-plan`, `delete-data`; `HTTP_STRIPE_SIGNATURE` env var undocumented; `.env.example` lacks Google Ads, CORS/CSRF, `USE_HTTPS`, TikTok engine variables. | Generate docs from the OpenAPI schema; keep `.env.example` complete. |
| Q-11 | **Tests**: 228 test functions but no negative cross-tenant tests, no role-matrix tests, no throttling tests, no webhook idempotency tests, no coverage report, no CI for the backend (`.github/workflows` exists only in the frontend and only deploys). | Add the tests listed in section 11; run on every PR. |
| Q-12 | **CI/CD** (`adportal_frontend/.github/workflows/deploy.yml`): deploys on every push to `main` with no test/lint/audit gate; pins nothing (`actions/checkout@v3`, `appleboy/ssh-action@master`), pushes an unversioned `latest` tag, `docker run` without env/volumes/restart policy, SSH as `ubuntu`. | Add build+test+audit jobs, pin actions by SHA, tag images with the commit SHA, deploy via compose/Kubernetes with a health-gated rollout and rollback. |
| Q-13 | **Money handling**: `float` used for budgets (`_budget_to_minor_units(round(float(value)*100))`) and `FloatField` for `spend`, `ctr`, `roas` in `AnalysisDaily`. | `Decimal`/`DecimalField` for monetary values. |
| Q-14 | **Frontend structure**: duplicated create/update wizard steps (7 + 7 near-identical files), `getOrgId()` re-implemented in ~12 files, Redux used for a few slices while the rest is local state + `localStorage` flags (`campaignId`, `api_response`, `campaign_builder_data`). | Shared `useOrgId`, one wizard parameterised by mode, move wizard draft state to the server (it already exists as `draft_data`). |

---

## 7. Data, privacy and compliance notes

* **PII**: e-mail, phone, gender, age, date of birth, avatar, IPs in logs, ad-platform identities. No data-export endpoint (GDPR Art. 15/20), deletion is hard-delete without grace (SEC-15), no retention schedule, no consent record for cookies/marketing e-mails.
* **Third-party processors**: OpenAI (campaign + product text), Stripe, Meta/TikTok/Google, SMTP provider. Document them in a privacy policy and sign DPAs.
* **Platform-policy risk**: Meta/TikTok/Google review expects token encryption, deauthorization/data-deletion callbacks that are correct (SEC-15), and least-privilege scopes — the Meta flow requests `pages_show_list,pages_read_engagement,business_management,ads_management` for every user.
* **PCI**: card data never touches the app (Stripe Embedded Checkout) — keep it that way; never log `raw_payload` (it contains customer e-mail and invoice URLs; `Payment.raw_payload` stores full Stripe objects in the DB, apply retention + admin-only access).
* **Backups/DR**: none described. Postgres has a named volume only; media is a local volume. Add automated `pg_dump`/WAL archiving, tested restores, and object-storage versioning.
* **Monitoring**: no Sentry/APM, no uptime probe, no Celery monitoring (Flower/Prometheus), no alerting on failed webhooks or failed syncs.

---

## 8. Endpoint matrix — authorization, rate limiting, caching

Legend. **Auth now** = what the code does today (from DRF introspection). **Auth target** = what it should be. `OrgMember` = active member of `org_id`; `OrgAdmin` = OWNER/ADMIN; `Owner`; `Staff` = `is_staff`. Throttle scopes are defined in section 10.2. Cache TTLs assume Redis; "private" means `Cache-Control: private` + `Vary: Authorization`. "Invalidate" lists the events that must delete the key.

### 8.1 Accounts (`/api/v1/accounts/`)

| Endpoint | Auth now | Auth target | Rate limit | Cache | Notes / findings |
|---|---|---|---|---|---|
| `POST login/` | AllowAny | AllowAny | `auth_login` 5/min/IP + 10/hour/e-mail, exponential lockout, CAPTCHA after 5 fails | none | uniform error; send mail on new-device login |
| `POST token/refresh/` | AllowAny | AllowAny | `auth_refresh` 30/min/IP | none | rotate + blacklist already on; flush expired tokens nightly |
| `POST logout/` | IsAuthenticated | IsAuthenticated | `user` | none | return generic error (SEC-23) |
| `POST register/` | AllowAny | AllowAny | `auth_register` 5/hour/IP, 3/day/e-mail, CAPTCHA | none | SEC-06, SEC-10, SEC-21; don't delete inactive users |
| `POST verify-email/` | AllowAny | AllowAny | `otp_verify` 5 attempts/code + 10/min/IP | none | SEC-06 (purpose, attempts, hash) |
| `POST resend-otp/` | AllowAny | AllowAny | `otp_send` 3/10 min/e-mail + 10/hour/IP | none | SEC-21 uniform response |
| `POST password-reset/` | AllowAny | AllowAny | `otp_send` | none | currently the same view as resend-otp |
| `POST check-otp/` | AllowAny | AllowAny | `otp_verify` | none | remove oracle: confirm only in the reset call |
| `POST password-reset-confirm/` | AllowAny | AllowAny | `otp_verify` | none | validate password; revoke tokens (SEC-10) |
| `POST change-password/` | **default AllowAny** | IsAuthenticated | `password_change` 5/hour/user | none | anon call returns 500 [V]; SEC-10 |
| `GET profile/` | IsAuthenticated | IsAuthenticated | `user` | private, 60 s, per user; invalidate on profile update | |
| `PATCH profile/update/` | IsRegularPlatformUser | IsRegularPlatformUser | `user` 30/hour | none | **SEC-01 critical** |
| `GET notifications/` | IsAuthenticated | IsAuthenticated | `user` | none (or ≤ 5 s); add cheap `GET notifications/unread-count/` cached 10 s and pushed by WS | |
| `POST read-notification/`, `read-all-notifications/`, `delete-notification/`, `delete-all-notifications/` | IsRegularPlatformUser | same | `user` | invalidate unread-count | validate id list types (SEC-41) |
| `GET/PATCH notification-settings/` | IsRegularPlatformUser | same | `user` | private 5 min; invalidate on PATCH | |
| `DELETE delete-account/` | IsRegularPlatformUser | IsRegularPlatformUser + password/OTP re-auth | `sensitive` 3/day | none | SEC-15 |
| `POST delete-data/` (Meta callback) | AllowAny (HMAC) | AllowAny (HMAC) | nginx `limit_req` 10/min/IP | none | verify `issued_at`; SEC-15 |
| `POST test-notifications/` | IsAuthenticated | **remove** (or DEBUG only) | – | – | SEC-26 |
| `POST contact-us/` | **default AllowAny** | AllowAny | `contact` 3/hour/IP + CAPTCHA | none | `max_length` on all fields (SEC-30) |

### 8.2 Main (`/api/v1/main/`)

| Endpoint | Auth now | Auth target | Rate limit | Cache | Notes / findings |
|---|---|---|---|---|---|
| `GET dashboard/` | OrgMember | OrgMember | `org_read` 60/min | Redis 60–120 s per `(org, time_range, start, end)`; invalidate on analytics sync completion, campaign status change | heavy aggregation (PERF-04) |
| `POST apply-budget-recommendation/` | OrgMember (owner/admin check inside) | OrgAdmin | `org_write` 10/hour | none | currently also works with *any* campaign of the org if the id is wrong (falls back to `.first()`) — require a valid `campaign_id` |
| `GET/PUT/PATCH organization/` | OrgMember | GET: OrgMember, write: OrgAdmin; `status` read-only | `org_write` | GET private 5 min; invalidate on write | **SEC-04** [V] |
| `GET integrations-status/` | OrgMember | OrgMember | `org_read` | Redis 60 s; invalidate on connect/select/disconnect | |
| `GET campaigns/` | OrgMember | OrgMember | `org_read` | micro-cache 10–15 s per `(org, page, filters)` or none; add `status_counts` | PERF-04/07; trends added recently |
| `GET campaign/<id>/` | OrgMember | OrgMember | `org_read` | ETag/conditional GET; Redis 30 s; invalidate on update/sync | per-ad N+1 (PERF-05) |
| `PUT/PATCH campaign/<id>/` | OrgMember | OrgAdmin; `status` read-only | `org_write` | invalidate campaign, dashboard | **SEC-04** [V] |
| `DELETE campaign/<id>/` | OrgMember + owner/admin check in service | OrgAdmin | `org_write` 20/hour | invalidate | ok, move check into permission class |
| `POST campaign/<id>/toggle-status/` | OrgMember | OrgAdmin | `org_write` 30/hour/org | invalidate | race: use `select_for_update` |
| `POST create-ad/`, `update-ad/` | OrgMember | OrgAdmin (publish) / OrgMember (draft edits) | `org_write` 60/hour + `upload` 20/hour | none | SEC-08; entitlement check (SEC-13); `draft=false` is the publish call |
| `POST audience-reach-estimate/` | OrgMember | OrgMember | `org_read` 30/min | Redis 10 min on request hash | new endpoint |
| `GET get-ad-profiles/`, `GET get-meta-pages/` | **IsRegularPlatformUser only** | OrgAdmin | `provider_read` 10/min/org | Redis 5–10 min per `(integration, page_id/manager_id)`; invalidate on reconnect | **SEC-02** [V]; external calls without timeouts |
| `POST select-ad-profile/`, `select-meta-page/`, `disconnect-integration/` | **IsRegularPlatformUser only** | OrgAdmin (+ re-auth for disconnect) | `org_write` 10/hour | invalidate integrations-status | **SEC-02** [V] |
| `POST generate-ai-copy/`, `generate-ad-copy/` | OrgMember | OrgMember + active subscription + quota | `ai` 20/hour/org + 5/min/user | cache identical prompts 24 h (hash of inputs) — optional | **SEC-13** cost control; `max_tokens`, timeout |
| `GET ai-insights/` | OrgMember | OrgMember | `org_read` | Redis 60 s; invalidate when insights are created/applied | |
| `GET/PATCH ai-optimization/settings/` | OrgMember | GET OrgMember; PATCH OrgAdmin (enforced in view) | `org_write` | private 5 min; invalidate on PATCH | new |
| `GET ai-optimization/history/` | OrgMember | OrgMember | `org_read` | 60 s | currently illustrative data |
| `POST ai-optimization/run/` | OrgMember | OrgAdmin | `ai` 5/hour/org | none | currently only stamps a time; when real: queue task + lock |
| `GET analytics/` | OrgMember | OrgMember | `org_read` | Redis 5 min per `(org, range)`; invalidate on analytics sync | |
| `POST create-platform-campaign/` | OrgMember | **remove** | – | – | **SEC-03** [V] |
| `GET team/`, `GET team-members/` | OrgMember | OrgMember | `org_read` | Redis 60 s; invalidate on invite/accept/role change/remove | add pagination |
| `GET/PATCH/PUT/DELETE team-member/<id>/` | OrgAdmin | OrgAdmin (+ owner-only for role changes to ADMIN) | `org_write` 30/hour | invalidate team | **SEC-05** [V] |
| `POST invite-team-member/` | OrgAdmin | OrgAdmin | `invite` 20/day/org | none | SEC-11; enforce `team_member_limit` |
| `POST accept-invitation/<token>/` | AllowAny | AllowAny | `invite_accept` 10/hour/IP | none | expiry (SEC-11) [V] |
| `POST sync-ads/`, `sync-analytics/` | OrgMember | OrgAdmin | `sync` 1 per 5 min per integration (cache lock) | none | validate `start_date/end_date` (max range 90 d) |
| `POST meta/create-ad/`, `meta/update-campaign/`, `meta/delete-ad/`, `test/create-ad-on-platform/` | OrgMember | **remove from prod** | – | – | **SEC-03** [V], SEC-26 |

### 8.3 OAuth (`/api/v1/auth/`)

| Endpoint | Auth now | Auth target | Rate limit | Cache | Notes |
|---|---|---|---|---|---|
| `GET {meta,tiktok,google}/connect/` | OrgMember | OrgAdmin | `oauth` 10/hour/user | none | state in Redis (good); add PKCE for Google |
| `GET {meta,tiktok,google}/callback/` | AllowAny (state-validated) | AllowAny | nginx `limit_req` 30/min/IP | none | sanitise errors, timeouts, encrypt tokens (SEC-12) |

### 8.4 Finance (`/api/v1/finance/`)

| Endpoint | Auth now | Auth target | Rate limit | Cache | Notes |
|---|---|---|---|---|---|
| `GET get-plans/` | AllowAny | AllowAny | `anon` | **public**, Redis 10–15 min + `Cache-Control: public, max-age=300`; invalidate on `Plan`/`PlanFeature` save | static catalogue |
| `POST buy-plan/` | OrgAdmin | OrgOwner | `billing` 10/hour/org | none | SEC-14; idempotency keys |
| `POST cancel-plan/` | OrgAdmin | OrgOwner | `billing` | none | not in `ENDPOINT_LIST.md` |
| `GET get-current-plan/` | OrgMember | OrgMember | `org_read` | Redis 60 s per org (sidebar hits it on every page); invalidate on webhook events and plan change | |
| `GET billing-history/` | OrgAdmin | OrgAdmin | `org_read` | private 5 min; invalidate on webhook | add pagination |
| `GET invoices/<id>/download/`, `invoices/download-all/` | OrgAdmin | OrgAdmin | `billing_download` 10/hour | none (URLs are short-lived) | ZIP is built synchronously and downloads every PDF from Stripe in the request → move to Celery + signed URL when >10 invoices |
| `POST stripe/webhook/` | AllowAny (signature) | AllowAny (signature) | nginx `limit_req` generous (e.g. 100/min), IP allow-list Stripe ranges optional | none | SEC-14 idempotency |

### 8.5 Analysis (`/api/v1/analysis/`)

| Endpoint | Auth now | Auth target | Rate limit | Cache | Notes |
|---|---|---|---|---|---|
| `GET reports/` | OrgMember or OrgAdmin | OrgMember | `org_read` | private 30 s; invalidate on report completion | file URLs must become signed (SEC-09) |
| `POST generate-report/` | OrgAdmin | OrgAdmin + entitlement | `report` 5/hour/org | none | cap range; PERF-08, SEC-25 |
| `GET report-insights/` | OrgMember | OrgMember | `org_read` | Redis 5 min per `(org, start, end)` | |
| `GET scheduled-reports/` | OrgMember | OrgMember | `org_read` | 5 min; invalidate on PATCH | seeds defaults on first GET (write on GET) |
| `GET/PATCH scheduled-reports/<id>/` | OrgAdmin | OrgAdmin | `org_write` | invalidate list | scheduler task still missing |

### 8.6 Admin (`/api/v1/admin/`) — all `IsAdminUser`

| Endpoint | Rate limit | Cache | Notes |
|---|---|---|---|
| `GET dashboard/`, `finance/`, `platform-analysis/`, `user-management/` (stats), `organizations/stats/` | `admin_read` 60/min | Redis 5–15 min (global data, per query-string); invalidate by TTL | expensive global aggregates; `get_system_status` is fake (PERF-17) |
| `GET campaigns/`, `user-management-list/`, `organizations/`, `transactions/`, `reports/`, `contact-messages/`, `invoices/upcoming/` | `admin_read` | none / 30 s | add stable ordering + trigram indexes on search |
| `PATCH user-management/<uuid>/` | `admin_write` 30/hour | invalidate user stats | audit log required; block staff-on-staff changes |
| `PATCH/DELETE organizations/<snowflake_id>/` | `admin_write` | invalidate | DELETE: soft delete + cancel Stripe + audit |
| `POST generate-report/`, `POST reports/<id>/download/` | `report` 5/hour | none | counter increments are fine |
| `GET/PATCH notification-settings/` | `admin_write` | none | |
| `…/contact-messages/` (CRUD) | `admin_write` | none | admin can create contact messages (ModelViewSet) – make read/update/delete only |
| (all) | – | – | Staff privileges are all-or-nothing; add roles (support, finance, superadmin), MFA, IP allow-list, audit log. Together with SEC-01, `IsAdminUser` is currently reachable by any user. |

### 8.7 Non-API

| Endpoint | Auth | Rate limit | Cache | Notes |
|---|---|---|---|---|
| `/api/schema/`, `/api/schema/swagger-ui/` | AllowAny → **Staff or disabled** | `anon` | 1 h if kept | SEC-27 |
| `/admin/` | Django admin | nginx `limit_req` 10/min/IP, MFA | none | SEC-28 |
| `/static/` | public | – | nginx `expires 1y` + hashed names | |
| `/media/` | public → **private/signed** | nginx `limit_req` | per-file, immutable if UUID names | SEC-08/09 |
| `/ws/notifications/` | JWT query param → one-time ticket | max connections per user (e.g. 5) | – | SEC-20 |
| `/dozzle/` | basic auth | – | – | remove or VPN-only (SEC-16) |

---

## 9. Infrastructure recommendations

### 9.1 Compose / Docker
* Remove `ports: "8000:8000"` from `web`; keep `expose`.
* Add `healthcheck` for `web` (`/healthz`), `celery` (`celery inspect ping`), set `deploy.resources`, `read_only: true` + `tmpfs`, `no-new-privileges`, `cap_drop: [ALL]`.
* Multi-stage Dockerfile (builder with `gcc`, runtime without), pin base digest, `pip install --require-hashes`.
* Release step: `python manage.py migrate --noinput` once (init container / CI job); remove `makemigrations`; `collectstatic` in the image build.
* Dozzle → remove, or VPN + `DOZZLE_ENABLE_ACTIONS=false`; consider Loki/Grafana or a hosted log service.
* Redis: `requirepass`, `maxmemory` + `allkeys-lru` for the cache DB; use separate Redis DBs/instances for cache vs Celery broker.
* Add a `docker-compose.override.yml` for dev; keep prod strict.

### 9.2 nginx (replace the API block with something like)
```nginx
limit_req_zone $binary_remote_addr zone=api:10m   rate=20r/s;
limit_req_zone $binary_remote_addr zone=auth:10m  rate=5r/m;
limit_req_zone $binary_remote_addr zone=hooks:10m rate=100r/m;
limit_conn_zone $binary_remote_addr zone=perip:10m;

server {
  listen 443 ssl; http2 on;
  add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
  add_header X-Content-Type-Options "nosniff" always;
  add_header X-Frame-Options "DENY" always;
  add_header Referrer-Policy "strict-origin-when-cross-origin" always;
  add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
  gzip on; gzip_types application/json text/css application/javascript image/svg+xml;
  client_max_body_size 25m; client_body_timeout 30s; limit_conn perip 30;
  # never log query strings (tokens, OAuth codes)
  map $request_uri $loggable_uri { ~^([^?]*) $1; }

  location ~ ^/api/v1/accounts/(login|register|resend-otp|password-reset|verify-email|check-otp|password-reset-confirm)/ {
      limit_req zone=auth burst=5 nodelay;  proxy_pass http://web:8000;  }
  location /api/v1/finance/stripe/webhook/ { limit_req zone=hooks burst=50; proxy_pass http://web:8000; }
  location /api/ { limit_req zone=api burst=40 nodelay; proxy_read_timeout 60s; proxy_pass http://web:8000; }
  location /media/ { # only public assets; private files go through the app
      add_header Content-Security-Policy "default-src 'none'; img-src 'self'; media-src 'self'; sandbox" always;
      add_header X-Content-Type-Options nosniff always; expires 7d; alias /app/media/; }
  location /admin/ { allow 10.0.0.0/8; deny all; proxy_pass http://web:8000; }  # or VPN
}
```
SPA server: `Cache-Control: no-cache` for `/index.html`, `immutable` for `/assets/`, CSP with the Stripe/Google domains actually used, `try_files … /index.html`.

### 9.3 Observability & delivery
* Sentry (backend + frontend) with PII scrubbing; Prometheus metrics (django-prometheus, celery exporter); structured JSON logs with request IDs; alerts on webhook failures, Celery queue depth, 5xx rate, token-refresh failures.
* CI: ruff, mypy (already in repo), `pytest`/`manage.py test` with coverage ≥ 80 % on `accounts`, `finance`, permissions; `pip-audit`, `npm audit`, `bandit`, `gitleaks`; build image; run `manage.py check --deploy`; Trivy image scan; deploy only from tagged builds.
* Backups: nightly `pg_dump` + WAL to object storage, tested restore, media bucket versioning, secrets in a manager (SSM/Vault/Doppler) instead of `.env` on the host.

---

## 10. Reference configuration snippets

### 10.1 Django settings (production)
```python
DEBUG = env.bool("DEBUG", False)
SECRET_KEY = env("SECRET_KEY")                     # no default
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")          # no default
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS")

SECURE_HSTS_SECONDS = 31536000; SECURE_HSTS_INCLUDE_SUBDOMAINS = True; SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True; SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SAMESITE = CSRF_COOKIE_SAMESITE = "Lax"; CSRF_COOKIE_HTTPONLY = True
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024; FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATABASES["default"]["CONN_MAX_AGE"] = 60

SIMPLE_JWT.update(SIGNING_KEY=env("JWT_SIGNING_KEY"), REFRESH_TOKEN_LIFETIME=timedelta(days=7),
                  ALGORITHM="HS256", AUDIENCE="adportal-api", ISSUER="adportal")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination", "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["apps.common.throttling.UserOrIPThrottle"],
    "DEFAULT_THROTTLE_RATES": THROTTLE_RATES,   # next section
}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache",
                      "LOCATION": env("REDIS_CACHE_URL"), "KEY_PREFIX": "adportal", "TIMEOUT": 300}}
```

### 10.2 Throttle scopes referenced in section 8
```python
THROTTLE_RATES = {
  "anon": "60/min", "user": "300/min",
  "auth_login": "5/min", "auth_refresh": "30/min", "auth_register": "5/hour",
  "otp_send": "3/10min", "otp_verify": "10/min", "password_change": "5/hour",
  "contact": "3/hour", "sensitive": "3/day",
  "org_read": "120/min", "org_write": "60/hour", "upload": "20/hour",
  "provider_read": "10/min", "sync": "12/hour", "oauth": "10/hour",
  "ai": "20/hour", "report": "5/hour", "invite": "20/day", "invite_accept": "10/hour",
  "billing": "10/hour", "billing_download": "10/hour",
  "admin_read": "60/min", "admin_write": "30/hour",
}
```
Scope throttles by **org** (not only IP) for authenticated tenant endpoints, by **e-mail address** for OTP/login, and keep counters in Redis. Use a lock (`cache.add(f"sync:{integration_id}", 1, 300)`) for the one-per-5-minutes sync rule.

### 10.3 Cache helper (pattern used in section 8)
```python
def cached_for_org(key_fn, ttl):
    def deco(fn):
        def wrapper(self, request, *a, **kw):
            key = f"v1:{key_fn(request)}"
            hit = cache.get(key)
            if hit is not None: return Response(hit)
            resp = fn(self, request, *a, **kw)
            if resp.status_code == 200: cache.set(key, resp.data, ttl)
            return resp
        return wrapper
    return deco
# invalidate with cache.delete_many([...]) from services / Celery tasks / Stripe webhook
```
Always include `org_id` (and every filter) in the key; never cache per-user data under a shared key; add `Vary: Authorization` and `Cache-Control: private` on tenant responses.

---

## 11. Tests to add (so these never regress)

1. **Cross-tenant matrix test**: iterate every URL that takes `org_id`; user B (member of another org) must get 403/404 for GET/POST/PATCH/DELETE; B must never mutate A's rows.
2. **Role matrix test**: MEMBER vs ADMIN vs OWNER for each mutating endpoint.
3. **Mass-assignment tests** for `profile/update`, `organization`, `campaign`, `team-member`: privileged fields ignored.
4. **Auth abuse tests**: OTP attempt lock, throttle returns 429, OTP purpose separation, password validators, token revocation after password change, uniform responses.
5. **Webhook tests**: duplicate event ID, missing metadata, renewal (`invoice.paid`) creates `Payment`, bad signature.
6. **Entitlement tests**: campaign/team/AI limits, suspended org, no subscription.
7. **Upload tests**: SVG rejected, fake content type rejected, oversized rejected, filename randomised.
8. **Report tests**: formula-injection cells are neutralised; files are not publicly addressable.
9. **Performance guards**: `assertNumQueries` on dashboard, campaign list, analytics; Locust/k6 smoke for the top 10 endpoints.
10. **Security CI gates**: `manage.py check --deploy`, `bandit`, `pip-audit`, `npm audit --audit-level=high`.

---

## 12. Prioritised remediation roadmap

### Now (this week — stops active exploitation)
| # | Task | Findings | Effort |
|---|---|---|---|
| 1 | Allow-list `UserSerializer` fields; audit `users` for escalated rows; rotate JWT signing key if the default `SECRET_KEY` was ever deployed | SEC-01, SEC-07 | 2 h |
| 2 | Add `IsOrganizationMember` (+ admin role) to the 5 integration views; remove/gate the `/main/meta/*`, `create-platform-campaign`, `test/*`, `test-notifications` endpoints | SEC-02/03/26 | 3 h |
| 3 | Make `status` read-only on Organization/Campaign serializers; validate team roles; block ADMIN→OWNER | SEC-04/05 | 3 h |
| 4 | Set production env: `DEBUG=False`, real `SECRET_KEY`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`; remove `ports: 8000` and Dozzle exposure | SEC-07/16 | 2 h |
| 5 | Add `DEFAULT_PERMISSION_CLASSES=IsAuthenticated` and throttles on auth/OTP/contact endpoints; OTP attempt counter + `secrets` | SEC-06/29/30 | 1 day |
| 6 | Move reports/uploads off public `/media/` (UUID names + signed access); drop SVG | SEC-08/09 | 1 day |
| 7 | Upgrade Django/DRF/Pillow/PyJWT/Twisted/Daphne/aiohttp/requests/urllib3 and `npm audit fix` (jspdf, swiper, axios, react-router, vite) | SEC-18 | 0.5–1 day + regression run |

### Next (2–4 weeks)
* Central `OrgPermission` + queryset mixin; cross-tenant & role test suites (ARCH-01, section 11).
* Password validation, token revocation, uniform auth responses, CAPTCHA; e-mail via Celery.
* Entitlement service + AI quotas; org-suspension enforcement (SEC-13).
* Stripe hardening: event de-dup, `invoice.paid`, Customer objects, idempotency (SEC-14).
* Encrypt platform tokens; Meta long-lived exchange + refresh tasks; HTTP wrapper with timeouts/retries (SEC-12, PERF-02).
* Serve HTTP with Gunicorn workers, Daphne for WS only (PERF-01); DB indexes and caching plan (PERF-04/06, section 8).
* Security headers (Django + nginx), nginx rate limits, log redaction (SEC-17/24/37).
* Frontend: lazy routes, httpOnly refresh cookie, role-aware routing, drop `console.*` in prod (FPERF-01, SEC-34/35).

### Later (quarter)
* Split provider engines behind a `PlatformClient` interface; delete duplicated code (Q-01).
* Real health/monitoring stack; backups and DR drills; Sentry; Celery fan-out/queues/time limits (PERF-09/17).
* GDPR features: export, soft-delete with grace, retention jobs; admin RBAC + MFA + audit log (SEC-15/28/44).
* Money as `Decimal`; API v2 naming cleanup; TanStack Query migration (Q-13/Q-06/FPERF-03).
* Private-bucket storage + CDN for media; image/video pipeline in workers (SEC-19, PERF-16).

---

## 13. Appendix

### A. Finding index

| Area | IDs |
|---|---|
| Critical security | SEC-01 … SEC-07 |
| High security | SEC-08 … SEC-21 |
| Medium security | SEC-22 … SEC-38 |
| Low / info | SEC-39 … SEC-48 |
| Architecture | ARCH-01 |
| Backend performance | PERF-01 … PERF-17 |
| Frontend performance | FPERF-01 … FPERF-05 |
| Quality / ops | Q-01 … Q-14 |

### B. Things that are already done well
* Stripe webhook verifies the signature; Meta data-deletion callback verifies HMAC with `compare_digest`.
* JWT refresh rotation with blacklist is enabled; short access lifetime.
* OAuth `state` is random, single-use and time-limited (cache TTL 5 min); callback re-checks org membership.
* Celery tasks use `on_commit` hooks for platform sync; Stripe upgrade/downgrade logic is thoughtful (schedules, proration).
* Non-root container user; `.env` is gitignored; `DEBUG`-gated OTP echo only in debug.
* `IsRegularPlatformUser` correctly separates staff from tenant APIs; `PlatformCreateAdTestAPIView` and `TeamInvitationAPIView` show the right scoping pattern.
* Test suite exists and is green (241 runs) — a good base for the regression tests above.

### C. Tooling output
* `pip-audit -r requirements.txt --no-deps`: 25/135 vulnerable packages (table in SEC-18); raw JSON was generated locally (not committed).
* `npm audit --omit=dev`: 15 vulnerabilities (2 moderate, 11 high, 2 critical).
* DRF route introspection: 99 URL patterns under `api/` (≈85 distinct endpoints once format-suffix duplicates are removed); permission classes quoted in section 8 come from that output.
* PoC scripts (section 2) were throwaway files outside the repository and are intentionally not included.
