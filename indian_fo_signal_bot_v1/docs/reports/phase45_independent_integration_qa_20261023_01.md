# Independent Phase 4/5 integration QA

Execution completed 2026-10-24 IST under the mission stage dated 2026-10-23.
Worker `/root/historical_track_a` owned only new
`test_phase45_integration.py` during this independent integration review. The
coordinator and the other workers owned production integration and corrections.

The focused command was:

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning -m unittest test_phase45_integration -v
```

Final result: **15 tests passed, exit 0, 2.002 seconds**. The test module SHA-256
at freeze was
`8612a2bfd8a89dfd311d03cc28bc54b19e2191826b9e02eacbd9a876f1bc7292`.
The coordinator's subsequent canonical run must establish final source-bound
acceptance; this focused execution alone is not either phase's overall verdict.

All application executions used SQLite `:memory:`, authored source documents,
public test keys and separately constructed fixture policy. The actual broker
adapter/scanner/evaluator/persistence/API handlers and outbox implementations ran
against explicitly injected candle fixtures. Socket/network guards remained in
place. No listener, provider request, operational database, credential file,
scheduler or Telegram transmission was used.

| Verified execution path | Positive and failure behavior checked |
|---|---|
| Persisted actual candidate -> signed fixture import -> automatic decision-time enrichment | Context matches canonical identity, candidate ID and original Phase 4 digest; strategy/candidate/signal arrays stay identical to the committed result |
| Existing signal/scan history and new context handlers | Exact context fields plus snapshot/time/mode metadata reconcile across the actual handlers; supported import/enrich POST handlers reuse retained context and intent |
| Qualification boundaries | Default policy remains unverified; separately locally qualified other-company context never attaches; rejected candidate cannot become alert-eligible |
| Point-in-time availability | Late intake with backdated collection is absent from the historical decision; an explicitly labelled current-information view can show it; future collection and future cutoff reject |
| Local preview lifecycle | Render failure records RETRY, immediate retry defers, actual clock advancement acknowledges; decision-time cutoff remains unchanged |
| Semantic deduplication | Unchanged context reuses its original intent; a new qualified source record creates exactly one additional intent; repeated enrichment creates no further intent |
| Missing and warning states | Legacy history stays missing; stale and conflicting sources remain warning-only and create no new eligible alert |
| Optional failure isolation | Context snapshot write failure rolls back the overlay, reports unavailable context and leaves the already committed Phase 4 candidate and signals intact |
| Request trust and corruption | Import requests cannot inject policy, identities or capture time; malformed source rejects; rehashed inconsistent context fails context/signal/scan read routes with 503 and no substituted content |

The first six-case integration execution had three passes and three errors. It
reproduced a production validation cycle after an eligible context intent existed:
context snapshot validation loaded the full cash result, whose outbox validation
loaded that context snapshot again. The context-workflow owner removed that
recursive dependency and retained direct committed-result, checksum, evaluation
and source bindings. The unchanged behavioral tests then passed. This worker
reported the actual failure to the coordinator and both affected owners; the
initial raw tool output was not separately serialized by this worker.

A later exact-equality assertion was adapted to the agreed additive API metadata
contract by asserting every original context field and every added timestamp/mode
field. One intermediate test-edit error misplaced three repeat-dedup assertions,
causing a NameError; their placement was corrected. That was a test construction
error, not an application defect or a relaxed criterion.

The retry-clock issue was identified by source review before the coordinator's
correction; this worker did not execute a pre-correction failure for it. The final
regression executes the corrected actual-clock retry path.

No independently reproduced integration failure remains in these fifteen cases.
The source policy used here is explicitly a synthetic local approval fixture.
Passing signature, mapping, enrichment and preview tests establishes software
mechanics only: it proves no genuine publisher authority, legal rights, live
source availability, external message delivery, profitability or operational
market acceptance. Context remains non-actionable and cannot affect ranking.
