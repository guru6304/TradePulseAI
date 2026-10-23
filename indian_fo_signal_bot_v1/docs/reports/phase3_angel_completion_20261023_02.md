# TradePulse AI: Angel Phase 3 completion report, 2026-10-23

**Engineering and current offline verification pass. Full live Phase 3 remains
blocked by fresh complete market candles and their real consumer acceptance.
Historical study acceptance remains separately blocked. Phase 4 is not authorized
to begin under the fixed roadmap.**

The current application is
`C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1`.
HEAD remains `4eb7330bf074d9b07733fade6d7a8e08c200fa0b`; the implementation is in
the working tree. No commit, merge, reset or clean was performed. Initially only
the user's untracked `tradepulse_phase1d.db` was present. Both `.env` files, that
database and prior evidence/reports/releases are preserved. The
[baseline](../evidence/phase3_angel_baseline_20261023_01.json) and
[final integrity receipt](../evidence/phase3_angel_closeout_validation_20261023_02.json)
bind their hashes and all 244 pre-existing evidence files. The unrelated IDE
restaurant repository was not accessed.

**Implementation**

Angel REST authentication, quotes and historical candles already existed in
`brokers.py`; no Angel continuous stream implementation was found. Added:

| File | Result |
|---|---|
| `angel_feed.py` | Explicit one-instrument WebSocket2.0 lifecycle; secure TLS; official LTP/Quote/SnapQuote decoding; five-level depth; heartbeat and bounded reconnects; event-time/session/volume gates; complete1m/5m bars; raw/rejected packet and candle SQLite lineage |
| `angel_feed_control.py` | Local preflight and explicit bounded read-only acceptance command; current master byte capture/cross-check; one login; clean stop before history; separate authorization guard for an extended window |
| `angel_history_capture.py` | One completed-session historical request; no login/refresh/retry/redirect; private original bytes, separate normalized candidates and sanitized endpoint-specific receipts |
| `brokers.py` | Inert Angel feed attachment, stop/detach and explicit streaming candle handoff; stream failure cannot fall back to REST; actual authentication HTTP status retained |
| `candle_lineage.py` | Existing cash scanner snapshots retain optional source-event, volume-baseline, connection and master links |
| `scanner_engine.py` | Stops attached Angel feeds before closing storage, through existing lifecycle |
| `release_management.py`, `test_bot.py` | New modules packaged and regressions included in the canonical strict suite |

Added `test_angel_feed.py`, `test_angel_history_capture.py` and
`test_phase3_angel_integration.py`. Reused existing storage, canonical identity,
candle freshness, historical qualification, cost/backtest and dashboard/health
contracts. No strategy evaluator, indicator, news/context feature or Phase4
implementation was added. No dependency or operator configuration was changed.

The official [SmartAPI docs](https://smartapi.angelone.in/docs),
[legacy official documentation](https://smartapi.angelbroking.com/docs) and
[official SDK source](https://raw.githubusercontent.com/angel-one/smartapi-python/main/SmartApi/smartWebSocketV2.py)
were reviewed before protocol work. Direct current docs/FAQ opens returned
access-denied pages; indexed official contracts and SDK source were accessible.
The implementation uses the existing pinned `websockets==15.0.1`; it does not
inherit the SDK's disabled certificate verification or SDK logging.

Supported binary modes are51/123/379-byte LTP/Quote/SnapQuote. Depth is five
levels; mode4/20-level depth is explicitly unsupported. Feed timestamps are
epoch milliseconds. The provider table does not establish the last-trade integer
unit; raw values are retained, with normalization only when exactly one seconds/
milliseconds interpretation agrees with the explicit provider clock within30s.
This clock-consistency resolution is labelled; ambiguity withholds candles.
LTP/Quote updates and pending order depth cannot establish executed volume.
Unobserved trade-volume jumps, unresolved trade times, gaps, stale/future events,
forming bars and fixture transports cannot become accepted LIVE scanner candles.
These conservative limits may also block candles during an open session; elapsed
observation time alone is insufficient.

**Actual read-only acceptance attempt**

Exactly one private flow ran after860/860 strict tests and receipt validation:

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning angel_feed_control.py --provider angelone --symbol RELIANCE --smoke --fetch-master --seconds 15 --history-session 2026-10-22 --stage live_20261023_01
```

Exit1 records the rejected live observation, not a software test failure. The
[original sanitized probe receipt](../evidence/phase3_angel_probe_live_20261023_01.json)
is unchanged after the run.

| Sub-gate | Actual result |
|---|---|
| Configuration | Angel credentials present locally; saved provider remains `paper_sim`; runtime command explicitly selects Angel data; execution is paper-only |
| Current identity | Public master HTTP200;37,256,888 original bytes; unique RELIANCE-EQ/NSE token2885 agrees with pinned canonical identity |
| Master SHA256 | `5112b4838af0c65006059a69c303677950a7feec96cfe3a8b9a7af564e63da30` |
| Login | `/rest/auth/angelbroking/user/v1/loginByPassword`, HTTP200,16:52:54–16:52:55IST; one successful login |
| WebSocket/subscription | Genuine scoped mode3 SnapQuote received from the fixed official stream endpoint; this proves connection and permitted subscription independently of candle freshness |
| Packet |379-byte SnapQuote; SHA256 `a47c37865dd90cf7bc8d2a5ac40132c98960c0e906dd1f1f3f013f9426f2b957` |
| Provider feed clock |2026-10-23 16:08:10IST |
| Local receive clock |2026-10-23 16:52:55.357048IST |
| Quality |`STALE_EXCHANGE_TIMESTAMP`; accepted fresh observations0; completed1m=0,5m=0 |
| Observation bound |Stream started16:52:55.093IST and stopped16:52:55.398IST after the stale packet; no extension of the15s cap |
| Persistence |One rejected raw packet plus sanitized rejection metadata retained in provider-specific SQLite; zero accepted event/candle rows |
| Cleanup |Feed closed before historical HTTP acquisition; SQLite subsequently closed; clean shutdown true |

Private originals and the new evidence database are under ignored
`.local/phase3-angel/live_20261023_01/`. They are excluded from release ZIPs.
Rejected packet lineage is distinct from accepted event lineage. The feed status
correctly reports `UNAVAILABLE`, zero accepted events and `live_signal_allowed=false`.
No scanner engine or live recommendation was started for this connection test.

The existing scanner handoff, durable snapshot metadata, no-fallback behavior,
fixture rejection, stale status and shutdown are covered by deterministic tests.
Real completed-candle storage and real consumer acceptance remain pending.

**Historical endpoint reconciliation and research**

After the socket stopped, one POST to
`https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData`
used NSE/2885/FIVE_MINUTE,2026-10-22 09:15 through15:25. It returned HTTP200 at
16:52:55IST,4,772 original response bytes, SHA256
`0eaf8e57fcf31c88e04a2721fb5623abec91e2d4c3db1de6d2b84966eed54f5b`.
It contains **73 original bars**, with **15:15 and15:20 missing** out of75
expected session bars. Quality is `INCOMPLETE_MISSING_BARS`; no gap was filled.
Original `response.bin` and separate `normalized_candidate.json` are private.

The retained older reports describe a RELIANCE quote success and separate
historical HTTP403 on2026-10-19. Their original transport captures were not found.
The reported74-bar response has no corresponding bound original receipt in the
inspected public workspace. Those reports cannot establish matching windows,
credential contexts or the cause of403. Today's success establishes today's
specific historical request only; it neither explains the earlier403 nor proves
WebSocket candle readiness. See the
[source reconciliation](../evidence/phase3_angel_history_source_review_20261023_01.json)
and [TrackA report](phase3_angel_history_20261023_01.md).

Authenticated HTTPS capture is acquisition evidence, not a detached publisher
Ed25519 signature. A current master is not dated historical authority, and free
access is not a research/redistribution rights grant. Existing trust and rights
policy was preserved. No qualifying publisher manifest, approved trust root,
reviewed rights document/grant or frozen multi-session qualified study was supplied.
No real walk-forward study, metrics, profitability or Strategy3 acceptance is
claimed. Exact dated option contracts, executable historical premium/depth and
proper prior-close OI remain separate missing inputs.

The fresh historical input check, stage `angel_operator_01`, returns logical
exit2 (PowerShell wrapper1), with source unchanged and the exact outstanding
operator contract recorded in its
[receipt](../evidence/task3_completion_track_a_20261023_01_angel_operator_01.json).
Its `HISTORICAL_CASH_DATA_MISSING` refers to qualified operator input files; it
does not mean the new unaccepted73-bar original capture is absent.

**Verification and release**

| Actual command/run | Result |
|---|---|
| `-m unittest test_angel_feed -v` |35/35 focused protocol tests pass |
| TrackA focused runner |25/25 pass:12 capture cases plus13 existing historical-study cases |
| `-m unittest test_phase3_angel_integration -q` |11/11 final integration/control cases pass |
| `verify_offline.py --stage phase3_angel_20261023_01` |860/860Python,11/11Node,68Python files compiled; source/log validation PASS; source used for actual private probe |
| `verify_offline.py --stage phase3_angel_20261023_02` |**862/862Python PASS**,238.308s; zero failures/errors/skips/unraisable exceptions; **11/11Node PASS**, **68Python files compiled**; identical source before/after |
| `verify_offline.py --validate-evidence docs/evidence/master_phase3_angel_20261023_03.json` |Exit0, current source and exact logs PASS |
| Release candidate |97 files; scope/checksums PASS; no `.env`, databases, `.local/` or raw market originals |

The final `_03` run also verifies truthful completed-candle versus scanner diagnostics. The preserved `_02` run verified861 tests for the extended-window guard; `_01` and `_02` remain historical snapshots.
No second or longer private probe ran. ResourceWarnings were treated as errors,
and the strict verifier blocked external sockets. Initial Windows sandbox temp
ACL errors were resolved by the approved offline test execution context; a test
clock fixture was corrected without relaxing production checks. A PowerShell
one-line release command failed before writing a ZIP due to quote stripping;
the file-based evidence helper then built and inspected the candidate successfully.
The old Task2 mismatched Python log remains preserved historical evidence; current
fresh evidence validates independently.

Review the [current full receipt](../evidence/master_phase3_angel_20261023_03.json),
[closeout](../evidence/phase3_angel_closeout_20261023_02.json),
[release inspection](../evidence/phase3_angel_release_inspect_20261023_02.json) and
[final integrity validation](../evidence/phase3_angel_closeout_validation_20261023_02.json).
The ZIP is `docs/evidence/phase3_angel_release_20261023_02.zip`; its hash is bound
by the build/inspection receipts. Public operational docs were updated; earlier
reports/evidence were retained. Progress scores were not recalculated.

**Safety and acceptance matrix**

No orders, account/profile mutations, token refresh, Telegram sends, scheduler
activation, paid subscription, Dhan request or Upstox request occurred. The
operator's saved configuration remains unchanged. The data-provider selector was
already independent of the existing paper execution path; no new order-capable
mode or configuration rewrite was needed. Secret/private-file exclusion and
original database/config preservation are checked in the final integrity receipt.

| Required Phase3 gate | Verdict |
|---|---|
|1. Current compilation/regression |PASS |
|2. Genuine authenticated connection and scoped subscription |PASS, genuine stale packet observed |
|3. Current instrument mapping |PASS |
|4. Fresh genuine market observations |BLOCKED |
|5. Complete valid1m and5m candles |BLOCKED |
|6. Completed live candle storage/lineage |Offline PASS; real completed input pending |
|7. Existing scanner consumes qualified live input |Offline PASS; real completed input pending |
|8. Failure blocks signals/no fallback |PASS for observed stale failure plus offline regressions |
|9. Honest health/dashboard |Offline PASS; no interactive browser acceptance claimed |
|10. Paper/read-only safety |PASS |
|11. Current evidence/release integrity |PASS, separately bound final validation |

The [machine acceptance matrix](../evidence/phase3_angel_acceptance_20261023_02.json)
and [precise operator blockers](../evidence/phase3_angel_operator_blockers_20261023_02.md)
include affected gates, actual commands/exits, safe corrections, owners and exact
verification commands. The remaining historical blockers are qualified cash
coverage, publisher root/authenticity, actual rights document, approved research
scope and dated identity; option execution inputs remain separately blocked.
None is cleared by passing offline tests or by today's historical HTTP200.

**Authorized next live observation**

The user delegated the choice of the most useful proposed window. One later
market-open RELIANCE run of up to420seconds was selected and is authorized with
the same safeguards; do not ask again for that same run. It has not been
performed or automatically scheduled. At an actually open verified NSE cash
session, preferably near the last minute before a5m boundary, use a fresh stage:

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning angel_feed_control.py --provider angelone --symbol RELIANCE --smoke --fetch-master --seconds 420 --extended-observation-authorized --stage market_open_authorized_01
```

Expect fresh scoped observations and auditable completed bars; reject missing
trades, gaps or stale data. The diagnostics command alone does not mint scanner
or full Phase3 acceptance. Review actual real input persistence/handoff against
the matrix. Additional runs/windows require their own authorization. Production
scheduling remains disabled. Phase4's already-defined scanner/explanation scope
can begin only after the mandatory live Phase3 criteria pass.

Final review corrected a diagnostic-only issue: a future probe with valid complete candles now reports that sub-gate PASS while retaining the separate scanner-consumer acceptance requirement. It no longer falsely labels that case an insufficient window. The original real probe, previous closeout/report/release and their hashes are preserved; no second private probe occurred. Current release/acceptance/closeout names end in `_02`, and current full-source verification ends in `_03`.
