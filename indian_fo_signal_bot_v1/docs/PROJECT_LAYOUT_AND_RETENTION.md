# Project layout and retention

The application keeps its existing flat Python layout. Runtime imports, test
discovery and release manifests depend on it; moving modules into new packages is
a separate implementation change.

```text
repository/
  .github/                     CI configuration
  .gitignore                   Local secrets, data, dependencies and caches excluded
  indian_fo_signal_bot_v1/
    *.py                       Runtime modules, offline tooling and Python tests
    test_cash_dashboard.js     Production-renderer regression tests
    public/                    Dashboard source and shipped assets
    docs/
      project/                 Current checkpoint, ledger, progress and master report
      reports/                 Dated findings, independent reviews and acceptance scope
      evidence/                Reproducible receipts, logs, helpers and bound screenshots
      drafts/                  Preserved historical prototypes outside runtime imports
    .local/                    Private inputs and retained offline asset cache
    .venv_phase4/              Required local Python environment
    .env                       Private operator configuration
    operational database      Existing application state; not a cleanup target
    __pycache__/               Regenerable Python bytecode; safe cleanup candidates
```

Use `docs/project/TRADEPULSE_ASTRA_CHECKPOINT.md` to resume work and its referenced
current receipt to assess acceptance. A historical report or screenshot does not
establish present source or live-market acceptance.

Keep source, tests, configuration examples, dependencies, credentials, operational
databases and WAL/SHM, original data, trust/rights inputs, release archives and
verification artifacts. An ignored file is not automatically disposable. The
offline browser asset cache is required to reproduce the retained browser checks.

Existing evidence images are referenced by receipts and their checksums. Deleting
or relocating them breaks those bindings. New browser runs should retain only
screenshots needed for review, use unique stages and clean their temporary browser
profiles automatically. Avoid copying screenshots into the application root.

Remove only positively identified generated files. The current cleanup script is
limited to inventoried, untracked `.pyc`/`.pyo` files in two project cache directories;
it rejects paths outside its allowlist and reparse points. It does not clean the
virtual environment, `.local/`, credentials, databases or unknown test directories.
Run its preview before `-Apply`, and retain the deletion receipt. Future cleanup
requires a fresh inventory rather than reusing an old list blindly.

Use temporary-directory context managers for new tests and fixture browsers.
Perform cleanup after test processes stop. An access-denied directory needs
inspection before it can be classified; changing ACLs or guessing its contents is
not routine project cleanup.
