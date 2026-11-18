# StockFlow public demo

The public build exposes synthetic catalog, inventory, order history, stock movements, and reconciliation without an account. The hosted API rejects all mutating methods, including login. Keep account-based order workflows in the local project and the isolated browser tests.

## Free-tier plan

Verified from provider documentation on 19 November 2026 (IST). Confirm the signed-in plan and any account-specific verification prompts before creating resources.

| Component | Proposed tier | Confirmed limits and conditions |
| --- | --- | --- |
| Frontend | Cloudflare Pages Free, Direct Upload | Free Pages lists 500 Git builds per month, 20,000 files per site, and a 25 MiB per-file limit. Direct Upload accepts a local `dist` build without Git access. Use the free `pages.dev` address and static delivery only. [Pages limits](https://developers.cloudflare.com/pages/platform/limits/) · [Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/) |
| API | Render Free web service | 750 free instance-hours per workspace per calendar month. Idle services spin down after 15 minutes and can take about a minute to wake. Builds and outbound bandwidth are metered. Without a payment method, exceeding the included quotas suspends service or builds. Free has no one-off jobs or remote shell. [Render free instances](https://render.com/docs/free) |
| Database | Neon Free PostgreSQL | No card required. 100 CU-hours, 1 GB storage, and 5 GB public transfer per project, subject to account-level storage limits. Compute suspends after five minutes of inactivity. Reaching compute or transfer limits suspends service until reset. [Neon pricing](https://neon.com/pricing) · [Neon plan limits](https://neon.com/docs/introduction/plans) |
| CI | GitHub Actions, standard Linux runner | Standard runner minutes are free for public repositories. Private repositories use the account's included allowance. Check visibility and remaining allowance before the first hosted run. [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) |

Use only accounts and workspaces without payment methods or paid add-ons. Stop if the selected account requires a card for verification, and do not upgrade after quota exhaustion. Do not schedule synthetic traffic to keep free instances awake. If the hosted API cannot run under these terms, the screenshot and local Compose stack remain usable.

## Publish after approval

1. **Database.** Create one dedicated Neon Free project and empty database. Select a direct connection and use the owner URL only in a trusted local session. Export `DATABASE_URL` with the SQLAlchemy driver prefix `postgresql+psycopg://` and verified TLS. From `backend`, run:

   ```sh
   python -m alembic upgrade head
   python -m alembic check
   python -m app.seed_demo
   ```

   The seeder refuses non-empty data. Use an entirely fresh database for resets. Run `deploy/demo-reader.sql` with `psql` as the owner from the repository root and provide the reader password at the interactive prompt. Keep owner and reader passwords distinct and in a password manager. Confirm as the reader that `SHOW transaction_read_only` returns `on`, that `SELECT count(*) FROM products` succeeds, and that `SELECT count(*) FROM users` fails. To check grants without changing data, use `has_table_privilege(current_user, 'products', 'INSERT')` and `has_schema_privilege(current_user, 'public', 'CREATE')`; both must be false. Neon recommends certificate and hostname verification with `sslmode=verify-full`. With libpq 17 or newer, `sslrootcert=system` uses the operating system trust store. Use the unpooled hostname for startup connection options. [Secure Neon connections](https://neon.com/docs/connect/connect-securely)
2. **Frontend project.** Reserve an approved Cloudflare Pages Direct Upload project and note its actual production origin. Use that exact HTTPS origin in Render CORS. If the project UI only assigns a hostname after its first upload, deploy the API first with the intended origin, then confirm or update it to the assigned production hostname before the smoke check.
3. **API.** Use the repository-root `render.yaml` Blueprint with the approved source branch. A GitHub push and any new GitHub app authorization require approval. Verify the instance is Free, automatic deploys are off, and the workspace has no payment method. Add the reader-only `DATABASE_URL` (with `sslmode=verify-full&sslrootcert=system`) and `CORS_ORIGINS` in Render. The blueprint sets `PUBLIC_DEMO=true`; leave `WRITE_TOKEN` unset. Confirm the Render-assigned HTTPS origin. The Render health check uses `/live`, which does not open a PostgreSQL connection. Use `/health` to check database availability. Migrations and seeding use only the owner connection.
4. **Frontend upload.** From `frontend`, run `npm ci`, set `VITE_PUBLIC_DEMO=true` and `VITE_API_BASE` to the actual HTTPS `onrender.com` origin, and run `npm run build`. Upload only `dist` to Pages. The static headers restrict connections to the app and Render HTTPS hosts. Include no credentials in any `VITE_*` variable. [Pages response headers](https://developers.cloudflare.com/pages/configuration/headers/)
5. **Live verification.** Run `python deploy/verify_demo.py --frontend <actual-https-origin> --api <actual-https-origin>` from the root using the backend virtual environment. In an incognito browser on desktop and mobile, check the populated overview, orders, movement history, reconciliation, and lack of write controls. After an idle period, confirm the loading state and manual refresh recover from cold start. Run the authenticated order flow only on the local or isolated test instance. Add actual URLs to the README after successful verification.

## Recruiter walkthrough

Open the dashboard and note how the overview separates available units from reservations. Find a fulfilled order, find its reservation and fulfillment entries in Stock movements, and confirm that Reconciliation reports matching balances. For the concurrency evidence and workload limits, see [Phase 4 benchmarks](../benchmarks/README.md).
