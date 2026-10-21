# TradePulse AI - Task 4 cash-candle lineage and recovery

## Baseline verified before implementation

Repository `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b`, branch `main`, HEAD `abf9f51015a0f6a96096edefd08a0dd0e827480a`. The 37 Python hashes in Task 3's verification record match the current files. Its uncommitted changes and reports are the starting state, not Task 4 changes. `docs/evidence/task4_baseline.json` retains initial status and hashes. The local zero-disclosure configuration check returned exit 0; Upstox, Telegram dry-run and disabled scheduler remain selected. No environment values or credentials were copied into this report.

## Confirmed existing flow and defect

Adapters normalize provider responses. `MultiBrokerScanner.fetch_candles` binds identity and enforces the shared live batch contract; `IntradayBotEngine._fetch_scan_candles` checks canonical identity and rechecks freshness. The scanner obtains index/equity maps, computes breadth, calls existing strategy evaluators, validates/ranks/sizes signals, and persists them through `SQLitePersistenceStore.save_signal`. Signal rows reference `scan_run_id`, not immutable input batches. Scan rows, OI snapshots/baselines and mitigated-zone writes use separate SQLite connections/transactions. The paper coordinator runs afterward with its existing atomic event keys.

The current scanner keeps accepted candle maps only in memory. Signal writes can succeed before zone/scan writes fail. Required persistence already blocks notification dispatch on detected errors, but the overall scan is not an atomic database result. Recovery needs the completed input bars, their validation/reference clock, instrument/provider binding, original zone state, strategy/risk/calendar configuration, code fingerprint, scan result and stable signal/input links. Paper recovery also needs the original scan ID and observations; committed paper effects must continue to use existing idempotency rules.

## Design recorded before coding

Use additive SQLite tables and the existing store. Keep accepted completed cash candles separate from incomplete display tails and auxiliary index/option inputs. A stable content digest detects local content changes only; it does not authenticate a publisher. Natural candle keys reject conflicting corrections rather than silently overwriting old accepted bars.

Transaction A will persist validated cash batches, unique candle facts, their membership and a pending scan/input linkage together. Nothing is accepted before the existing identity, OHLCV, timestamp/grid/session, freshness and provenance checks pass. Incomplete tails are excluded from evaluator input and never inserted as accepted candles. Repeated ingestion is idempotent; a conflicting natural candle key fails closed.

Transaction B will serialize pending work and commit signals, zone state, scan metadata and durable result together, using the existing writer implementations on one borrowed connection. Implicit inner context-manager commits must not escape the outer transaction. Acquisition happens before the write transaction. Notifications run only after successful commit; recovery suppresses them. This is at-most-once recovery behavior, not a durable Telegram outbox or a guarantee of message delivery.

Explicit offline recovery will read and validate retained inputs at their original acceptance reference, require matching nonsecret configuration/code fingerprints and run the existing evaluators without transport. Recovered output must identify its original observation scope and cannot establish current freshness, live acceptance or historical source qualification. The existing paper coordinator remains a separate idempotent handoff after the committed scan; retries recover effects instead of inventing fills.

Implementation and acceptance results are pending.
