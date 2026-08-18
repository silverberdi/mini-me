# Metrics

Capture raw facts/events from day one so metrics can be recomputed later.

## Delivery
- lead time: DISCOVERED → DONE
- cycle time: READY → DONE
- active execution time
- waiting-capacity time
- waiting-human time
- throughput by week/month

## Quality
- first-pass review approval rate
- correction rounds
- check failure rate
- findings by severity/category
- human UI validation failure rate
- post-DONE defect linkage
- human override count/rate

## Provider effectiveness
By role/provider/model: executions, duration, timeouts, technical failures, quota events, review outcomes, correction burden and later human outcome.

## Autonomy
- percentage READY → human gate without intervention
- human interruptions before final gate
- ambiguity/block counts
- successful restart/failure recovery
- preserved jobs after quota exhaustion

## Cost
- DeepSeek Direct cost
- OpenRouter cost
- `fallback_drain_cost`
- cost per change/model/role
- budget consumption vs configured limits

GitHub Projects may surface selected portfolio metrics, but PostgreSQL facts/events are the authoritative measurement source.
