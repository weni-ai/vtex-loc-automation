# weni-ai/vtex-loc-automation — seed contents

Copy **everything under this folder** to the root of a new private repo
`weni-ai/vtex-loc-automation` (this directory *is* the repo root).

`weni-ai` is **outside** the VTEX GitHub Enterprise, so product repos cannot
`uses: vtex/localization-tools/...`. This host mirrors only the thin Actions
surface needed in-org. The Loc **ticket + agent** pipeline stays on
`vtex/localization-tools` (via `repository_dispatch`).

## What this repo hosts

| Path | Role |
|---|---|
| `.github/actions/mint-loc-github-app-token` | Mint App installation token |
| `.github/actions/dispatch-loc-ticket` | `repository_dispatch` → `vtex/localization-tools` |
| `.github/actions/localization-lock` | Composite lock (Python bundled) |
| `.github/workflows/localization-lock.yml` | Reusable lock for weni consumers |
| `.github/workflows/examples/` | Copy-paste callers for product repos |

It does **not** run Jira/Crowdin/agent jobs.

## Org admin checklist (once)

1. Create private repo `weni-ai/vtex-loc-automation` and push this tree to `main`.
2. **Settings → Actions → General → Access** → *Accessible from repositories in the weni-ai organization* (required for sibling repos to `uses:` this host).
3. Install the **VTEX Localization Automation** GitHub App on:
   - `weni-ai/vtex-loc-automation` (optional but fine)
   - every product repo that will run lock/ticket
   - (already) `vtex/localization-tools`
4. Add **org** Actions secrets (same values as VTEX org):
   - `LOC_GITHUB_APP_ID`
   - `LOC_GITHUB_APP_PRIVATE_KEY` (full PEM)

## Per product repo

1. Root `crowdin.yml` with required `project_id` + `files` mappings.
2. Copy [examples/consumer-localization-automation.yml](.github/workflows/examples/consumer-localization-automation.yml) → `.github/workflows/localization-automation.yml` (or the lock/ticket-only examples).
3. Adjust `branches:` / ticket `if:` if default branch is not `main`.
4. Smoke: PR that touches a translation file → lock fails; merge source-string change → ticket run on `vtex/localization-tools`.

## Syncing from upstream

When lock/actions change in `vtex/localization-tools`, re-copy:

- `.github/actions/mint-loc-github-app-token`
- `.github/actions/dispatch-loc-ticket`
- `.github/actions/localization-lock`

Keep `uses: weni-ai/vtex-loc-automation/...` and `target_repository: vtex/localization-tools` in consumers.
