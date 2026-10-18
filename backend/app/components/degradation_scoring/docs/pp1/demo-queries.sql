-- C4 demo queries for DBeaver (C4-T16b). Synthetic fixture data, not results.
-- Fill the tables first, from backend/:
--     uv run python -m scripts.c4_run_features --run-id fixture-demo-adr-on
--     uv run python -m scripts.c4_run_features --no-adr --run-id fixture-demo-adr-off
-- Story: the run -> what happened to each input event -> each ranked event's numbers
-- (-> later, layer 3: c4_event_scores with the 0-1 values, weights, severity and rank).

-- 1. Runs: one row per C4 run. Counts per outcome, how many events could be matched to
--    the graph, and which criteria were on (hotspot needs a repository, AV needs C2's links).
SELECT run_id, system_id, release_id, created_at, data_provenance,
       payloads, ranked, skipped, quarantined, resolution_rate,
       hotspot_active, hotspot_inactive_reason,
       adr_active, adr_inactive_reason
FROM c4_scoring_run
ORDER BY created_at DESC;

-- 2. Layer 1, ingestion: what happened to every input payload of one run, in input order,
--    and why. Malformed payloads stay visible (event_id can be empty).
SELECT payload_index, event_id, anti_pattern_type, scope, review_status, context_tag,
       outcome, reason, detail
FROM c4_event_ingestion
WHERE run_id = 'fixture-demo-adr-on'
ORDER BY payload_index;

-- 3. Layer 1, resolution: which graph nodes each ranked event matched, and how
--    (exact id = confidence 1.0, folder-path fallback = 0.7).
SELECT event_id, nodes, resolution_status, resolution_confidence
FROM c4_event_ingestion
WHERE run_id = 'fixture-demo-adr-on' AND outcome = 'ranked'
ORDER BY resolution_confidence, event_id;

-- 4. Layer 2, features: the raw numbers per ranked event, sorted by blast radius (fan-in =
--    share of the system that depends on it). eh_* are empty when hotspot was off.
SELECT f.event_id, i.anti_pattern_type,
       round(f.br_fan_in_ratio::numeric, 3) AS fan_in,
       round(f.br_pagerank::numeric, 4)     AS pagerank,
       round(f.br_betweenness::numeric, 4)  AS betweenness,
       f.br_depth                            AS depth,
       f.ps_consecutive_releases             AS releases_in_a_row,
       round(f.ps_growth_slope::numeric, 3)  AS growth_per_release,
       f.ps_growth_metric,
       f.av_weight, f.av_adr_id,
       f.eh_churn_decayed, f.eh_authors, f.eh_coupling, f.eh_bugfix_ratio
FROM c4_event_features f
JOIN c4_event_ingestion i ON i.run_id = f.run_id AND i.event_id = f.event_id
WHERE f.run_id = 'fixture-demo-adr-on'
ORDER BY f.br_fan_in_ratio DESC;

-- 5. Honesty check: events whose numbers rest on a stand-in or a fallback.
--    presence_fallback = C3 did not send instance_history; prefix_fallback = matched by
--    folder path; growth slope unavailable = fewer than two values.
SELECT f.event_id,
       f.ps_presence_fallback,
       i.resolution_status,
       f.ps_growth_slope_available,
       f.eh_first_seen_fallback
FROM c4_event_features f
JOIN c4_event_ingestion i ON i.run_id = f.run_id AND i.event_id = f.event_id
WHERE f.run_id = 'fixture-demo-adr-on'
  AND (f.ps_presence_fallback OR i.resolution_status = 'prefix_fallback'
       OR NOT f.ps_growth_slope_available OR f.eh_first_seen_fallback)
ORDER BY f.event_id;

-- 6. AV on vs off: the same events with and without the ADR index. With it off, the
--    criterion is dropped for the whole run (av_weight empty), never guessed.
SELECT on_run.event_id, on_run.av_weight AS av_with_index, off_run.av_weight AS av_without
FROM c4_event_features on_run
JOIN c4_event_features off_run
  ON off_run.event_id = on_run.event_id AND off_run.run_id = 'fixture-demo-adr-off'
WHERE on_run.run_id = 'fixture-demo-adr-on'
ORDER BY on_run.av_weight DESC NULLS LAST, on_run.event_id;
