Incident Post-Mortem: Event Processing Pipeline Outage
Date: 2025-12-15
Duration: 2 hours 34 minutes (14:12 UTC - 16:46 UTC)
Severity: P1 (Customer-facing impact)
Incident Commander: James Park

## Timeline

14:12 - Monitoring alert: Kafka consumer lag exceeding 60s threshold
14:15 - On-call engineer (Maria Santos) acknowledged, began investigation
14:22 - Identified Flink checkpoint failures starting at 14:08
14:28 - Escalated to P1; incident bridge opened
14:35 - Root cause identified: Flink TaskManager OOM on pod atlas-flink-tm-07
14:40 - Attempted restart of affected TaskManager pod
14:45 - Restart failed; pod in CrashLoopBackOff due to state recovery exceeding memory limit
14:55 - Decision: scale Flink cluster from 8 to 12 TaskManagers
15:10 - New pods scheduled but blocked by Kubernetes resource quota
15:18 - Platform team updated resource quota
15:25 - New TaskManager pods running, checkpoint recovery in progress
15:48 - Checkpoint recovery complete, processing resumed
16:15 - Consumer lag decreasing, approaching normal levels
16:46 - All systems nominal, consumer lag under 5s, incident resolved

## Impact

- 847,000 events delayed by more than 60 seconds
- 12,300 events lost (0.0014% loss rate during incident window)
- 23 enterprise customers reported stale dashboard data
- 3 customers triggered their own incident processes due to missing alerts
- Estimated revenue impact: $45,000 (SLA credit obligations)

## Root Cause

The Flink TaskManager pod `atlas-flink-tm-07` ran out of memory during a
windowed aggregation operation. The pod was allocated 8GB of memory, but the
RocksDB state backend grew to 9.2GB due to:

1. A new customer onboarded 48 hours prior with 3x the average event volume
2. The customer's device IDs created 340,000 new keys in the aggregation state
3. RocksDB compaction backlog grew, preventing state cleanup
4. Combined memory pressure from state + JVM heap exceeded the 8GB pod limit

## Contributing Factors

- No per-customer quota or rate limiting at the ingestion layer
- Flink memory monitoring only checks JVM heap, not total pod memory
- RocksDB state size alerts set at 80% of limit (6.4GB) but the growth was
  rapid enough to skip the 80% threshold between monitoring intervals (60s)
- Kubernetes resource quota was set at cluster creation and never updated
  to reflect growth in workload

## Action Items

1. [P0] Increase TaskManager memory to 16GB (owner: Maria Santos, ETA: done)
2. [P0] Add RocksDB native memory monitoring (owner: James Park, ETA: 2025-12-20)
3. [P1] Implement per-customer ingestion rate limits (owner: Alex Kim, ETA: 2026-01-15)
4. [P1] Split monolithic Flink job into routing + aggregation (owner: Maria Santos, ETA: 2026-01-31)
5. [P2] Automate Kubernetes resource quota reviews (owner: Platform team, ETA: 2026-02-15)
6. [P2] Add state size to pre-deployment capacity checks (owner: James Park, ETA: 2026-02-28)
