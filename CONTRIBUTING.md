# Contributing

Online Annotator produces scientific ground truth, so changes are held to the rules in
[AGENTS.md](AGENTS.md). In short:

1. Read `AGENTS.md`, the platform governance it links to, and the progress ledger.
2. Put behaviour in `src/online_annotator/services/` with tests; keep API routers thin.
3. For any user-visible change, update the hint texts, `(?)` help, the Help centre
   (`web/static/js/views/help.js`) and the Playwright journeys in the same commit.
4. Run `python -m pytest`, `python -m ruff check src tests`, and for UI/workflow changes
   `npm run test:browser`.
5. Record the change under *Unreleased* in `CHANGELOG.md`; update the ledger.
6. Stage explicit paths, commit, and push to `main`.

Never commit runtime data, real specimen images, secrets, exports, screenshots or build output.
