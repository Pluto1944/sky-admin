# sky-admin repository instructions

This file defines the authoritative project rules for `sky-admin`. Read the
relevant implementation and matching document under `docs/` before changing a
feature. Reconcile documentation with current code and recent Git history.

## Product and technology

`sky-admin` manages Clash of Clans alliance members, CWL registration and team
arrangement, league/war statistics, farm-clan statistics, and WeChat mini-program
access.

- Backend: Python 3.10+, FastAPI, SQLite, pandas, openpyxl
- Frontend: Vue 2 + uni-app + webpack 4, targeting WeChat mini-program
- External systems: official COC API, ClashKing API, Tencent Docs OpenAPI, and
  WeChat code-to-session API
- Production path: Nginx -> FastAPI at `127.0.0.1:8000` -> SQLite
- Production services: `sky-admin` and `sky-scheduler`, managed by systemd

## Change safety

- Inspect `git status --short --branch` before changing code.
- Preserve existing user changes and never overwrite unrelated diffs.
- Keep changes scoped; do not refactor adjacent modules without a requirement.
- Never commit generated data, database files, build artifacts, logs, or secrets.
- Do not run destructive Git commands or `python cli.py reset-db` without exact,
  explicit approval.

## Architecture boundaries

- `modules/player`: authoritative account/member domain. `PlayerService` is the
  only public entry point for reading or writing `accounts`; other business
  modules must not update that table directly.
- `modules/cwl_registration`: registration import, sorting, baseline rebuild,
  promotion/relegation, team building, roster output, and publishing.
- `modules/war_result`: result import and history-score calculation.
- `modules/coc_sync`: authoritative COC synchronization and membership
  reconciliation. All COC API calls go through `CocSyncService`.
- `shared/db`: shared SQLite connection and repositories.
- `api_server`: FastAPI application, routes, and JWT/WeChat authentication.
- `uni-app`: WeChat mini-program frontend.
- `scripts/scheduler.py`: current persistent periodic scheduler.

Keep pure business functions free of I/O where the current design does so,
especially sorting, scoring, status inference, mapping, and promotion logic.
Repositories must share the `Database` connection; do not create independent
SQLite connections inside domain services.

## Core data rules

- `registrations` is a self-contained monthly fact source. Its `player_tag` is
  an optional cache and may be null; do not add an accounts foreign key to it.
- COC data is authoritative for account creation and clan membership. A
  registration unknown to COC must not create a temporary account.
- Preserve COALESCE upsert behavior in `accounts`: null input must not erase an
  existing value owned by another source.
- Unknown accounts are skipped with a warning when importing result rows that
  require an accounts foreign key.
- `team_index` is the unique 0-based team identity. `team_alias` is a non-unique
  human label. `team_name` is the COC clan name; `clan_tag` is the API identity.
- Team categories are `combat` and `shell`.

### Period semantics

Do not interchange registration and result months:

- `registrations.period`: the month the CWL roster will play
- `league_teams.period`: the roster/CWL month
- `league_results.period`: the month the CWL actually occurred
- legacy `results.period`: the month the result occurred

Arranging month `N` reads registrations for `N` and league results/team
configuration for `N-1`. Validate periods as `YYYY-MM` at command boundaries.

## CWL arrangement workflow

The active v3.0 pipeline is:

1. Import and normalize registration rows.
2. Deduplicate by account name, keeping the latest submission.
3. Merge combat-clan members according to current business rules.
4. Save self-contained registration facts.
5. Sort accounts and rebuild the baseline using the prior month.
6. Apply promotion/relegation.
7. Build teams greedily, then apply whitelist and manager assignments.
8. Write assignments and export roster Parts 1-4.

Use `baseline_rebuilder.py` for stages 0-6 and `team_builder.py` for stages 7-9.
`team_filler.py` is retired legacy code even if the file and old tests remain;
do not build new behavior on it.

Configuration belongs in `config/settings.yaml`. Do not reintroduce scattered
Python configuration modules. Treat blacklist, whitelist, team capacity,
reserved slots, and team ordering as business-sensitive configuration.

## API and frontend rules

- Load secrets from environment variables/`.env`; never hard-code or print
  tokens, AppSecret, JWT secrets, document IDs, or credentials.
- Production must have an explicit strong `JWT_SECRET`; the development fallback
  is not acceptable for deployment.
- Validate account identity before expanding the WeChat bind flow; binding is an
  integrity-sensitive area.
- Review CORS deliberately before production changes; do not widen it casually.
- Frontend API calls should go through `uni-app/utils/api.js`.
- After `npm install`, run `bash patches/apply-patches.sh` from `uni-app` when the
  dependency compatibility patch is required.
- Frontend scripts: `npm run dev:mp-weixin` and `npm run build:mp-weixin`.

`docs/11-uni-app.md` contains an old-architecture section and stale TODO items.
The TabBar and statistics pages already exist. Verify the filesystem and Git
history rather than treating those checkboxes as authoritative.

## Testing and verification

Choose verification proportional to the change. Prefer targeted checks first,
then broader checks when risk justifies them.

- Python: use the repository virtual environment, for example
  `venv/bin/python -m pytest <target>`.
- Python syntax/import checks must use the deployed virtual environment.
- Frontend production build: run `npm run build:mp-weixin` in `uni-app`.
- Shell scripts: run `bash -n <script>` and inspect the diff.
- Always run `git diff --check` before committing.
- Never claim a test/build passed unless it ran and its exit status was observed.

Tests and commands may touch the configured SQLite database. Confirm their data
target first; never point tests at production data by assumption.

## Scheduler, operations, and deployment

- Before manually running synchronization, import, deployment, or other
  operational scripts, load the repository environment first (for example,
  `source scripts/load_env.sh` or the project-approved `.env` loader). Do not
  run scripts with an incomplete environment, and never print or expose `.env`
  contents while troubleshooting.

- `scripts/scheduler.py` is authoritative, persists state in `sync_jobs`, and is
  supervised by `sky-scheduler.service`.
- `docs/periodic-scripts.md` and the old timer/cron design are historical. Do not
  restore or operate them.
- Monthly import/arrangement is an explicit business operation. The recommended
  entry point is `scripts/register_and_arrange.sh YYYY-MM`.
- COC member sync runs through the scheduler; Tencent Docs player export remains
  manual.
- Use systemd for production processes. Never start a competing manual uvicorn
  process, especially with `--reload`, while `sky-admin` is active.
- Inspect service status and logs before and after a restart or deploy.
- Back up `data/league.db` before migrations or risky data operations.

## Documentation authority

- `docs/01-architecture.md`: architecture and known issues
- `docs/02-database.md`: schema, ownership, data flow, and period semantics
- `docs/03-sorting.md`: sorting/baseline rebuild and legacy notes
- `docs/04-promotion-relegation.md`: promotion/relegation rules
- `docs/05-roster-output.md`: roster Parts 1-4 and publishing
- `docs/06-operations.md`: monthly operations and troubleshooting
- `docs/10-api-server.md`: API and deployment model
- `docs/11-uni-app.md`: frontend design, with stale sections noted above
- `docs/12-league-stats.md`, `13-war-stats.md`, `14-farm-clans.md`: statistics
- `docs/15-scheduler.md`: authoritative scheduler design
- `deploy/README.md`: authoritative service operations

When behavior changes, update the matching document in the same change. Mark
superseded designs as historical instead of leaving contradictory instructions.

Known gaps must not be silently fixed during unrelated work: history score
currently returns zero, sorting/input-validation edge cases remain, and roster
scripts lack some step-to-step validation.

## Security

- Never display, copy, commit, or transmit private SSH keys or `.env` secrets.
- Do not weaken COC API host validation or tag URL encoding.
- Do not modify SSH, firewall, DNS, proxy, users, permissions, Nginx, or systemd
  configuration without explicit approval.
