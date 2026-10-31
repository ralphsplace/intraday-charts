# intraday-charts

A self-hosted, read-only intraday charting dashboard for stocks and ETFs, fed by Trader Workstation (TWS) and run in
Docker on a home NAS. FastAPI server (`app/`), a TWS collector and other tools (`tools/`), and browser pages written
as ES modules with no build step (`app/static/`). The user guide is in `docs/` (MkDocs, published to GitHub Pages);
`docs/development.md` describes how the code is organized.

## Commands

```bash
pip install -r requirements-dev.txt && python -m playwright install chromium
ruff check app tools tests                 # lint
pytest --cov                               # every test, browser tests included
pytest -m "not ui"                         # without the browser tests
pip install -r requirements-docs.txt && mkdocs build --strict    # the user guide
```

## Standing rules

- **Desktop only.** The pages are designed for desktop browsers; phone layouts are out of scope.

## Agent skills

### Issue tracker

Issues and specs live in this repo's GitHub Issues (`gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

The five default triage labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See
`docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root, created when terms or decisions are settled. See
`docs/agents/domain.md`.

### Plugins and skills

`.claude/settings.json` enables, for everyone who opens this repo in Claude Code, from the official marketplace:
superpowers, feature-dev, pr-review-toolkit, code-simplifier, security-guidance and mattpocock-skills. security-guidance's Opus reviews (each turn's diff, and each commit) are
off (`ENABLE_CODE_SECURITY_REVIEW=0` in the same file), so only its free pattern warnings run.
`.claude/skills/` holds TradingView's Lightweight Charts skills (see `.claude/skills/NOTICE.md`).
