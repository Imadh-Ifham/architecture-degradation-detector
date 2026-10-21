// GENERATED from backend/app/components/degradation_scoring/docs/schemas/severity_report.schema.json - do not edit.
// Regenerate: cd backend; powershell -ExecutionPolicy Bypass -File scripts/c4_export_ts_types.ps1

/**
 * @minItems 1
 */
export type ActiveDimensions = [Dimension, ...Dimension[]];
export type Dimension = "blast_radius" | "hotspot" | "adr_violation" | "persistence";
export type AhpCr = number;
export type DataProvenance = "fixture" | "fixture-events+live-history" | "live";
export type NormalizationMode = "robust_minmax" | "minmax_small_n";
export type Lower = number;
export type Upper = number;
export type Detail = string;
export type EventId = string | null;
export type QuarantineReason = "malformed_payload" | "unresolved_element";
export type Quarantined = QuarantinedEvent[];
export type AntiPatternType = string;
export type ClaimsContradicted = number;
export type ClaimsGrounded = number;
export type ClaimsTotal = number;
export type ClaimsUnsupported = number;
export type Flagged = string[];
export type Groundedness = number;
export type ContextTag = "GENUINE" | "INTENTIONAL" | "UNCERTAIN";
export type Active = boolean;
export type Normalized = number;
export type Raw = number;
export type Weight = number;
export type Elements = string[];
export type EventId1 = string;
export type Id = string;
export type Provenance = string;
export type EvidenceSource = "metric" | "subgraph" | "cochange" | "adr" | "commit";
export type Text = string;
export type Evidence = EvidenceItem[];
export type Explanation = string | null;
export type Rank = number;
export type Confidence = number;
export type ResolutionStatus = "exact" | "prefix_fallback";
export type ReviewStatus = "PENDING" | "CONFIRMED" | "REJECTED" | "NEEDS_INVESTIGATION";
export type Scope = "ELEMENT" | "INSTANCE" | "SYSTEM";
export type Severity = number;
export type Records = SeverityRecord[];
export type ReleaseId = string;
export type ResolutionRate = number;
export type RunId = string;
export type SchemaVersion = string;
export type EventId2 = string;
export type SkipReason = "not_confirmed" | "rejected" | "intentional" | "system_scope_not_rankable" | "superseded";
export type Skipped = SkippedEvent[];
export type SystemId = string;
export type WeightsProvenance = "provisional-author-elicited" | "supervisor-elicited";
export type WeightsVersion = string;

export interface SeverityReportV1 {
  active_dimensions: ActiveDimensions;
  ahp_cr: AhpCr;
  data_provenance: DataProvenance;
  normalization: NormalizationMode;
  normalization_bounds?: NormalizationBounds;
  quarantined?: Quarantined;
  records?: Records;
  release_id: ReleaseId;
  resolution_rate: ResolutionRate;
  run_id: RunId;
  schema_version?: SchemaVersion;
  skipped?: Skipped;
  system_id: SystemId;
  weights_provenance: WeightsProvenance;
  weights_version: WeightsVersion;
}
export interface NormalizationBounds {
  [k: string]: NormalizationBounds1;
}
export interface NormalizationBounds1 {
  lower: Lower;
  upper: Upper;
}
export interface QuarantinedEvent {
  detail?: Detail;
  event_id?: EventId;
  reason: QuarantineReason;
}
export interface SeverityRecord {
  anti_pattern_type: AntiPatternType;
  audit?: AuditSummary | null;
  context_tag: ContextTag;
  contributions: Contributions;
  dimensions: Dimensions;
  elements?: Elements;
  event_id: EventId1;
  evidence?: Evidence;
  explanation?: Explanation;
  rank: Rank;
  resolution: Resolution;
  review_status: ReviewStatus;
  scope: Scope;
  severity: Severity;
}
export interface AuditSummary {
  claims_contradicted: ClaimsContradicted;
  claims_grounded: ClaimsGrounded;
  claims_total: ClaimsTotal;
  claims_unsupported: ClaimsUnsupported;
  flagged?: Flagged;
  groundedness: Groundedness;
}
export interface Contributions {
  [k: string]: number;
}
export interface Dimensions {
  [k: string]: DimensionScore;
}
export interface DimensionScore {
  active?: Active;
  features?: Features;
  normalized: Normalized;
  raw: Raw;
  weight: Weight;
}
export interface Features {
  [k: string]: boolean | number | null;
}
export interface EvidenceItem {
  id: Id;
  provenance: Provenance;
  source: EvidenceSource;
  text: Text;
}
export interface Resolution {
  confidence: Confidence;
  status: ResolutionStatus;
}
export interface SkippedEvent {
  event_id: EventId2;
  reason: SkipReason;
}
