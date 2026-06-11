# Software Architecture Review — Project Atlas

## Overview

Project Atlas is a distributed event-processing platform designed to handle
real-time telemetry from IoT devices at scale. The system ingests, transforms,
and routes events to downstream consumers with sub-second latency SLAs.

## Current Architecture

### Ingestion Layer
- Apache Kafka cluster (3 brokers, replication factor 2)
- Custom Kafka Connect connectors for MQTT and CoAP protocols
- Average throughput: 120,000 events/second at peak

### Processing Layer
- Apache Flink cluster for stream processing
- Stateful transformations with RocksDB state backend
- Exactly-once semantics via Flink's checkpoint mechanism
- Event time processing with 30-second watermark lag

### Storage Layer
- Apache Cassandra for hot data (30-day retention)
- Apache Parquet files on S3 for cold storage (indefinite)
- TimescaleDB for aggregated metrics and dashboards

### API Layer
- REST API (Go, using gin framework)
- GraphQL gateway for frontend consumers
- WebSocket push for real-time dashboards

## Identified Issues

### Issue 1: Kafka Consumer Lag Spikes
Under burst traffic (>200k events/sec), consumer group `atlas-flink-main`
experiences lag spikes of up to 45 seconds. Root cause appears to be
back-pressure from Flink's windowed aggregation operators when state size
exceeds 8GB.

**Recommendation:** Increase Flink task manager memory from 8GB to 16GB.
Consider splitting the monolithic Flink job into separate topology for
aggregation vs. routing. Evaluate Apache Kafka Streams as a lighter alternative
for simple routing logic.

### Issue 2: Cassandra Write Timeouts
During peak hours (14:00-18:00 UTC), Cassandra write latency p99 exceeds
800ms, causing timeouts at the default 2-second threshold. The `events_by_device`
table has grown to 2.3TB with suboptimal partition key design causing hot
partitions.

**Recommendation:** Redesign partition key to include a time-bucket component
(e.g., `device_id:YYYYMMDD`). Add a second Cassandra data center for write
scaling. Consider migrating hot-path writes to ScyllaDB for better tail latency.

### Issue 3: API Gateway Memory Leaks
The Go REST API exhibits a slow memory leak (~50MB/hour) traced to unclosed
response bodies in the HTTP client used for internal service calls. The leak
compounds during high-traffic periods, requiring pod restarts every 18 hours.

**Recommendation:** Audit all `http.Client` usage for proper `resp.Body.Close()`
calls. Add a middleware to track response body lifecycle. Implement memory
limits and automatic graceful restart in Kubernetes deployment.

### Issue 4: Schema Evolution Challenges
The Avro schema registry has 847 registered schemas with poor versioning
discipline. Backward-incompatible changes have been deployed 12 times in the
past quarter, causing consumer failures.

**Recommendation:** Enforce FULL_TRANSITIVE compatibility mode in the schema
registry. Implement a CI/CD gate that validates schema compatibility before
deployment. Create a schema governance committee with representatives from
each consuming team.

## Performance Metrics (Last 30 Days)

| Metric                      | Value        | Target   | Status  |
|-----------------------------|-------------|----------|---------|
| Event ingestion rate (avg)  | 85k/sec     | 100k/sec | Warning |
| Event ingestion rate (peak) | 215k/sec    | 200k/sec | OK      |
| End-to-end latency (p50)    | 120ms       | 200ms    | OK      |
| End-to-end latency (p99)    | 890ms       | 500ms    | Critical|
| Data loss rate              | 0.002%      | 0.001%   | Warning |
| System uptime               | 99.94%      | 99.99%   | Warning |

## Security Considerations

- All inter-service communication uses mTLS
- Kafka traffic encrypted with TLS 1.3
- API authentication via OAuth 2.0 + JWT
- Data at rest encrypted (AES-256) in Cassandra and S3
- No PII stored in event payloads (anonymized at ingestion)
- SOC 2 Type II audit completed in November 2025
