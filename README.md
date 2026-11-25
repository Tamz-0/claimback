# Campus Lost & Found – ownership verification and custody chain

**P09 · Track P (Django + PostgreSQL)**

People report lost and found items on campus. The person who finds an item also records **hidden identifying details** about it. These are encrypted and never shown publicly. Anyone who claims the item must answer questions drawn from those details. Security then hands the item over under supervision, and each handover is recorded in a **custody chain** that shows if anyone has tampered with it.

---

## 1. Quick start (Windows)

You need **Python 3.12 or newer**. Check with `python --version`.

```powershell
cd "C:\Users\asus\Desktop\PROJ\LOST AND FOUND"

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
notepad .env
```

In `.env`:

1. Paste your Supabase **Session pooler** connection string into `DATABASE_URL`. Find it in Supabase → your project → **Connect**. Replace `[YOUR-PASSWORD]` with your database password.
2. Generate the two keys and paste them in:
   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(50))"
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   **Don't lose `FIELD_ENCRYPTION_KEY`.** Without it, private details already stored can't be decrypted. If you leave it empty, a key is derived from `SECRET_KEY`, so in that case don't change `SECRET_KEY` later.

Then set up the database and start the server:

```powershell
python manage.py migrate        # creates the tables and enables the pg_trgm extension
python manage.py seed_demo      # categories, campus map, one demo user per role, sample items
python manage.py runserver
```

Open http://127.0.0.1:8000.

### Demo accounts (password for all: `demo1234!`)

| Username | Role | What to try |
|---|---|---|
| `student1` | Student | Has a lost iPhone that was claimed, verified and scheduled for handover. The handover code is in their notifications. |
| `student2` | Student | Found several items, so you can see the hidden details they entered |
| `student3` | Student | Made a claim that failed verification (an example of a false claim) |
| `staff1` | Staff | Reported some unrelated found items |
| `security1`, `security2` | Security | Security desk: intake, verification review, approval, handover, disposal |
| `campusadmin` | Campus Administrator | Reports, plus categories / locations / retention periods in `/admin/` |
| `sysadmin` | System Administrator | Full Django admin and user management |

> Emails are printed in the terminal running `runserver` (the console email backend). That's where OTP codes and match alerts appear during development.

### The nightly job

`python manage.py run_nightly` refreshes match suggestions and moves unclaimed items through ageing and into the disposal queue.

- **Windows:** schedule it with Task Scheduler → Create Basic Task → Daily → Program: `C:\...\LOST AND FOUND\.venv\Scripts\python.exe`, Arguments: `manage.py run_nightly`, Start in: the project folder.
- **Linux server:** add a cron line: `0 2 * * * cd /app && .venv/bin/python manage.py run_nightly`

### Supabase notes

- Free projects **pause after about a week with no activity**. Before a demo, open the Supabase dashboard and click *Restore* if it's paused.
- `pg_trgm` is created automatically by the first migration. Supabase allows this.
- Run the **tests** against a local PostgreSQL rather than Supabase (see section 5).

---

## 2. Features → where they live in the code

| Spec module | App | Key files |
|---|---|---|
| M1 Item reporting | `apps/items` | `services.create_report`, `imaging.py` (EXIF/GPS stripping), `templates/items/report.html` |
| M2 Category & location taxonomy | `apps/catalog` | `Category` (attributes, suggested questions, retention), `Location` tree with map coordinates |
| M3 Matching engine | `apps/matching` | `engine.py`: pg_trgm + full-text search + attributes + location tree + time |
| M4 Private details & verification | `apps/vault` | `models.py` (encrypted, locked manager), `services.py` (the only reader), `scoring.py` |
| M5 Claim workflow | `apps/claims` | `services.py`: submit → verify → review → approve; handles competing claims |
| M6 Custody & handover | `apps/custody` | `CustodyRecord` (hash chain), `Handover` (OTP or signature + proof photo) |
| M7 Disposal & ageing | `apps/custody` | `services.age_items`, `services.dispose`, `run_nightly` command |
| M8 Public board & search | `apps/board` | `public.py` (the **only** public data object), `search.py`, HTMX infinite scroll |
| Admin dashboard, reports | `apps/dashboard` | Security desk views, `analytics.py`, CSV export |
| Audit log & notifications | `apps/audit` | `AuditEntry` (read-only in admin), `Notification`, `notify()` |
| REST API | `apps/api` | `/api/items`, `/api/items/{id}/matches`, `/api/claims`, `/api/claims/{id}/verify`, `/api/handovers`, `/api/board` |

### How a found item moves through the system

```
Finder reports item ─► OPEN ─► Security intake ─► IN_CUSTODY ─► Claim submitted ─► CLAIM_PENDING
       │                                                              │
       └─ hidden details (encrypted)        Claimant answers 3 hidden-detail questions
                                                     │
                                passed ──► VERIFIED ──► Security approves ──► CLAIM_APPROVED
                              borderline ──► security review                (other claims auto-rejected)
                              failed twice ──► locked/rejected                       │
                                                              Handover scheduled; OTP sent to claimant
                                                                                     │
                                       Security enters OTP (or signature) + proof photo ──► RETURNED
Unclaimed: IN_CUSTODY ──(retention - 7 days)──► AGEING ──(retention)──► DISPOSAL_QUEUE ──► DISPOSED
```

---

## 3. How private details are kept private (structurally)

The spec asks for redaction to be enforced "structurally, not by remembering to omit them". Here is how:

1. **Separate model, no way back from an item.** `PrivateDetail` is in `apps/vault` and points to `Item` with `related_name="+"`, so `item.private_details` doesn't exist.
2. **The default manager is locked.** `PrivateDetail.objects.all()` always returns an empty queryset. Only `apps/vault/services.py` uses the real manager (`PrivateDetail.vault`).
3. **Encrypted at rest** with Fernet (`apps/vault/crypto.py`). The database only ever holds ciphertext.
4. **One public data object.** Every public response, HTML or JSON, is built by `apps/board/public.py::to_public()` from an explicit allow-list. Board templates receive plain dicts, never model objects.
5. **Tests enforce it:** `tests/test_structure.py` fails if any public module imports the vault. `tests/test_private_leak.py` plants canary strings in the private details and checks every public endpoint, for every item status, as both an anonymous and a logged-in user.
6. Not registered in the Django admin. Claimants see the questions only, never the answers.

See **`docs/PUBLIC_VS_PRIVATE_FIELDS.md`** for the field-by-field statement for the security office.

---

## 4. Configuration

Business rules are in `config/settings.py → LOSTFOUND`:

| Setting | Default | Meaning |
|---|---|---|
| `CHALLENGE_QUESTIONS` | 3 | Hidden-detail questions asked per claim |
| `CHALLENGE_MAX_ATTEMPTS` | 2 | Attempts before the claim is locked |
| `CHALLENGE_PASS_SCORE` | 0.66 | Score that passes automatically (about 2 of 3 correct) |
| `CHALLENGE_REVIEW_SCORE` | 0.45 | Scores between this and the pass mark go to security review |
| `MIN_PRIVATE_DETAILS` | 2 | Minimum hidden details a finder must enter |
| `MATCH_THRESHOLD` | 0.40 | Minimum score for a match suggestion to be stored |
| `MATCH_WINDOW_DAYS` | 60 | Maximum gap between when an item was lost and when it was found |
| `OTP_TTL_MINUTES` | 1440 | How long a handover code stays valid |
| `AGEING_WARNING_DAYS` | 7 | Days before the retention limit that a warning is sent |

Retention periods are set **per category** by the Campus Administrator in `/admin/`.

---

## 5. Running the tests

The tests need a PostgreSQL user that is allowed to create a database (Django creates a temporary `test_…` database). A local PostgreSQL is easiest. On Windows, install it from postgresql.org, then:

```powershell
psql -U postgres -c "CREATE USER lf WITH PASSWORD 'lf' CREATEDB;"
$env:DATABASE_URL="postgresql://lf:lf@localhost:5432/lostfound"; $env:DATABASE_SSL="false"
pytest
```

`TEST_REPORT.md` lists the results from the last full run (65 tests, all passing) and maps each test to an acceptance criterion.

---

## 6. Deploy to Render (free)

The repo includes everything Render needs: `render.yaml` (the Blueprint), `build.sh` (install → collectstatic → migrate → seed) and gunicorn.

### Step 1 – Supabase Storage for photos (Render's free disk is wiped on every deploy)
1. Supabase → **Storage** → **New bucket** → name it `media` and turn on **Public bucket**.
2. Supabase → **Project Settings → Storage → S3 Connection** (or Storage → Settings → S3 access keys) → **New access key**. Copy the **Access key ID** and **Secret access key**. Note the **Region** shown there (e.g. `ap-south-1`).
3. Your **project ref** is the random part of your project URL: `https://<project-ref>.supabase.co`.

### Step 2 – Create the service
1. Go to https://dashboard.render.com → **New → Blueprint** → connect GitHub → choose this repo.
2. Render reads `render.yaml` and asks for the secret values:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Supabase **Session pooler** string (same as in your `.env`) |
| `FIELD_ENCRYPTION_KEY` | **Exactly the same** key as in your `.env`, otherwise hidden details already in the database can't be decrypted |
| `SUPABASE_PROJECT_REF` | e.g. `yotnbarwfuivsoecbwnu` |
| `SUPABASE_S3_ACCESS_KEY_ID` / `SUPABASE_S3_SECRET_ACCESS_KEY` | From step 1 |
| `DJANGO_SUPERUSER_USERNAME` / `_EMAIL` / `_PASSWORD` | Admin account to create (or leave empty) |

If your region isn't `ap-south-1`, edit `SUPABASE_S3_REGION` after the service is created.

3. Click **Apply**. The first build takes about 3–5 minutes. Your site will be at `https://claimback.onrender.com` (or similar).

`SEED_DEMO=true` loads the demo users and sample items (only if the database has no items yet). **The demo password `demo1234!` is public in this README**, so before sharing the link widely, set `SEED_DEMO=false` and change those passwords in `/admin/`, or deactivate the demo users.

### Step 3 – Nightly job (free, via GitHub Actions)
Render cron jobs are paid, so `.github/workflows/nightly.yml` runs `run_nightly` every night at 02:00 IST from GitHub instead. In GitHub → repo **Settings → Secrets and variables → Actions → New repository secret**, add `DATABASE_URL`, `SECRET_KEY` (any long random value) and `FIELD_ENCRYPTION_KEY`. Test it from the **Actions** tab → *Nightly matching & ageing* → **Run workflow**.

### Good to know
- **The free tier sleeps after 15 minutes without visitors.** The first request then takes 30–60 seconds, so open the site a minute before a demo.
- **Real emails:** set `EMAIL_HOST=smtp.gmail.com`, `EMAIL_HOST_USER`, and `EMAIL_HOST_PASSWORD` (a Gmail *App password*). Without these, emails are only printed in Render's logs, and claimants see handover codes in their in-app notifications.
- **Every `git push` to the main branch redeploys automatically.**

## 7. Deployment notes

- Set `DEBUG=false`, a real `SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `ALLOWED_HOSTS`, and `CSRF_TRUSTED_ORIGINS` (e.g. `https://lostfound.example.edu`).
- Run `python manage.py collectstatic`. WhiteNoise serves the static files.
- Run with `gunicorn config.wsgi` on Linux.
- Photos are stored in `media/`. For production, configure object storage (S3-compatible, e.g. Supabase Storage) with `django-storages`.
- The public board's data is cached for `BOARD_CACHE_SECONDS` (default 60) using Django's cache framework. Use Redis or Memcached in production.
- **Integration points (stubs in v1):** campus SSO / ERP replaces `accounts/signup`, and `apps/audit/services.send_sms` is where an SMS gateway would plug in.
