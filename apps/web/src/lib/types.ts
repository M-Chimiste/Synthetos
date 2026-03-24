export type Dictionary = Record<string, unknown>;

export interface ResearchCharter {
  public_id: string;
  title: string;
  problem_statement: string;
  success_criteria: Dictionary;
  budget_envelope: Dictionary;
  source_scope: Dictionary;
  stop_conditions: Dictionary;
  constraints: Dictionary;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ResearchCycle {
  public_id: string;
  current_status: string;
  last_error?: string | null;
  budget_max_compute_minutes?: number | null;
  budget_max_total_runs?: number | null;
  budget_max_wall_clock_hours?: number | null;
  budget_max_runs_per_hypothesis?: number | null;
  budget_used_compute_minutes: number;
  budget_used_run_count: number;
  budget_runs_per_hypothesis: Record<string, number>;
  autonomy_mode: string;
  created_at: string;
  updated_at: string;
}

export interface ResearchStateSnapshot {
  public_id: string;
  state: string;
  transition_reason: string;
  context: Dictionary;
  actor_id: string;
  scope_used?: string | null;
  created_at: string;
}

export interface JobRecord {
  public_id: string;
  operator_name: string;
  status: string;
  payload: Dictionary;
  attempts: number;
  max_attempts: number;
  claimed_by?: string | null;
  lease_expires_at?: string | null;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DomainEvent {
  sequence_id: number;
  public_id: string;
  cycle_public_id?: string | null;
  job_public_id?: string | null;
  actor_id: string;
  scope_used?: string | null;
  event_type: string;
  payload: Dictionary;
  created_at: string;
}

export interface SkillBinding {
  public_id: string;
  operator_name: string;
  binding_reason: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SkillExecutionRecord {
  public_id: string;
  operator_name: string;
  status: string;
  run_public_id?: string | null;
  payload: Dictionary;
  created_at: string;
  updated_at: string;
}

export interface ReportSummary {
  public_id: string;
  cycle_public_id?: string | null;
  report_type: string;
  title: string;
  artifact_path: string;
  created_at: string;
}

export interface ReportDetail extends ReportSummary {
  markdown: string;
  quality_metadata?: {
    structural_score?: number;
    word_count?: number;
    section_checklist?: Record<string, boolean>;
    has_tables?: boolean;
    has_metrics?: boolean;
  };
}

export interface TimelineEntry {
  timestamp: string;
  event_type: string;
  category: "state_change" | "operator" | "run" | "report" | "user_action" | "system";
  summary: string;
  details: Dictionary;
  directional_signal?: string | null;
  verification_outcome?: string | null;
  frontier_snapshot?: FrontierSnapshot | null;
}

export interface TimelineResponse {
  cycle_public_id: string;
  items: TimelineEntry[];
}

export interface CycleSummaryResponse {
  cycle: ResearchCycle;
  charter: ResearchCharter;
  state_snapshot?: ResearchStateSnapshot | null;
}

export interface CycleDetailResponse {
  cycle: ResearchCycle;
  charter: ResearchCharter;
  current_state_snapshot?: ResearchStateSnapshot | null;
  recent_jobs: JobRecord[];
  recent_events: DomainEvent[];
  bound_skills: SkillBinding[];
  skill_execution_records: SkillExecutionRecord[];
  reports: ReportSummary[];
}

export interface SkillDefinition {
  public_id: string;
  skill_key: string;
  phase: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SkillVersion {
  public_id: string;
  version: string;
  content_hash: string;
  manifest: Dictionary;
  body_markdown: string;
  hook_exports: string[];
  is_valid: boolean;
  created_at: string;
  updated_at: string;
}

export interface SkillSummaryResponse {
  definition: SkillDefinition;
  latest_version?: SkillVersion | null;
}

export interface SkillDetailResponse {
  definition: SkillDefinition;
  versions: SkillVersion[];
  validation_issues: Dictionary[];
}

export interface PaperCardSummary {
  public_id: string;
  title: string;
  source_type: string;
  external_id: string;
  lifecycle_status: string;
  triage_score?: number | null;
  triage_rationale?: string | null;
  shortlist_rank?: number | null;
  shortlist_reason?: string | null;
  escalation_reason?: string | null;
  escalation_type?: string | null;
  retrieval_provenance_summary: string[];
  created_at: string;
}

export interface SourceRetrievalSession {
  public_id: string;
  source_type: string;
  query_params: Dictionary;
  status: string;
  result_count: number;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface LiteratureTriageResponse {
  retrieval_sessions: SourceRetrievalSession[];
  total_papers: number;
  screened_count: number;
  shortlisted_count: number;
  escalated_count: number;
  papers: PaperCardSummary[];
}

export interface EvidenceCardSummary {
  public_id: string;
  paper_public_id: string;
  claim: string;
  evidence_type: string;
  strength: string;
  relevance_score: number;
  read_depth: string;
  created_at: string;
}

export interface EvidenceSummaryResponse {
  total_evidence: number;
  by_type: Record<string, number>;
  by_strength: Record<string, number>;
  conflicts_detected: number;
  redundancies_detected: number;
}

export interface EvidenceListResponse {
  items: EvidenceCardSummary[];
  total: number;
}

export interface HypothesisCardSummary {
  public_id: string;
  title: string;
  portfolio_rank: number | null;
  portfolio_score: number | null;
  status: string;
  novelty_score: number | null;
  feasibility_score: number | null;
  impact_score: number | null;
  created_at: string;
}

export interface HypothesisListResponse {
  items: HypothesisCardSummary[];
  total: number;
}

export interface PortfolioRankingResponse {
  cycle_public_id: string;
  hypotheses: HypothesisCardSummary[];
  ranking_method: string;
  total: number;
}

export interface ExperimentSpecSummary {
  public_id: string;
  hypothesis_public_id: string;
  title: string;
  status: string;
  gpu_required: boolean;
  estimated_runtime_minutes: number | null;
  created_at: string;
}

export interface ExperimentSpecListResponse {
  items: ExperimentSpecSummary[];
  total: number;
}

export interface RunSummary {
  public_id: string;
  experiment_spec_public_id: string;
  status: string;
  execution_profile: string;
  failure_classification?: string | null;
  verification_outcome?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
}

export interface RunSpec {
  workspace_path: string;
  image: string;
  build_recipe: Dictionary;
  command: string[];
  env_vars: Record<string, string>;
  mounts: Dictionary[];
  hardware_profile: string;
  timeout_seconds: number;
  memory_limit_mb: number;
  cpu_limit?: string | null;
  gpu_enabled: boolean;
  network_mode: string;
  artifact_output_path: string;
  patch_archive_path?: string | null;
}

export interface RunRecord {
  public_id: string;
  cycle_public_id: string;
  experiment_spec_public_id: string;
  status: string;
  execution_profile: string;
  run_spec: RunSpec;
  workspace_path: string;
  artifact_root: string;
  stdout_path?: string | null;
  stderr_path?: string | null;
  patch_archive_path?: string | null;
  base_commit?: string | null;
  base_branch?: string | null;
  bound_skill_keys: string[];
  prompt_lineage: Dictionary[];
  model_lineage: Dictionary[];
  latest_resource_snapshot: Dictionary;
  metrics_summary: Dictionary;
  artifact_manifest: Dictionary;
  failure_classification?: string | null;
  verification_outcome?: string | null;
  last_error?: string | null;
  exit_code?: number | null;
  attempt_count: number;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunTelemetryEvent {
  sequence_id: number;
  public_id: string;
  run_public_id: string;
  event_type: string;
  stream?: string | null;
  message?: string | null;
  payload: Dictionary;
  created_at: string;
}

export interface RunArtifactManifest {
  run_public_id: string;
  manifest_path: string;
  metrics_path?: string | null;
  checkpoint_path?: string | null;
  predictions_path?: string | null;
  artifacts: Dictionary[];
}

export interface SelfCriticFlag {
  issue: string;
  severity: "critical" | "warning";
}

export interface SelfCriticResult {
  passed: boolean;
  flags: SelfCriticFlag[];
  rationale: string;
  blocking: boolean;
}

export interface FrontierSnapshot {
  metric_name?: string | null;
  current_value?: number | null;
  best_value: number;
  best_run_public_id: string;
  runs_since_improvement: number;
  series_tail: number[];
}

export interface TrendDiagnostics {
  sample_size: number;
  slope: number;
  normalized_slope: number;
  mann_kendall_tau: number;
  coefficient_of_variation?: number | null;
  frontier_delta: number;
  frontier_delta_ratio: number;
  recent_change_ratio: number;
  runs_since_improvement: number;
  significance_threshold: number;
  threshold_source: "charter" | "default";
  reasons: string[];
}

export interface MetricConflict {
  metric: string;
  signal: string;
  value?: number | null;
  lower_bound?: number | null;
  upper_bound?: number | null;
  violates_bound: boolean;
  detail: string;
}

export interface TradeoffResolution {
  resolution: "accept_tradeoff" | "reject_tradeoff" | "needs_investigation";
  rationale: string;
  recommendation: string;
  resolved_by: "deterministic" | "verifier_llm" | "fallback";
}

export interface DirectionalSignalReconciliation {
  overall?: string | null;
  conflicts: MetricConflict[];
  tradeoff_resolution?: TradeoffResolution | null;
}

export interface DirectionalSignalDetail {
  primary_metric?: string | null;
  primary_signal?: string | null;
  per_metric_signals: Record<string, string>;
  assessments: Record<string, TrendDiagnostics>;
  frontier?: FrontierSnapshot | null;
  threshold_warning?: string | null;
  reconciliation: DirectionalSignalReconciliation;
}

export interface RunListResponse {
  items: RunSummary[];
  total: number;
}

export interface VerificationReportSummary {
  public_id: string;
  run_public_id: string;
  experiment_spec_public_id: string;
  outcome: string;
  reviewer_summary: string;
  created_at: string;
}

export interface VerificationReportDetail extends VerificationReportSummary {
  cycle_public_id: string;
  hypothesis_public_id?: string | null;
  outcome_rationale: string;
  baseline_comparison: Dictionary;
  historical_comparisons: Dictionary[];
  metric_sanity_checks: Dictionary[];
  artifact_checks: Dictionary[];
  output_contract_checks: Dictionary[];
  leakage_signals: Dictionary[];
  split_validation: Dictionary;
  rerun_note?: string | null;
  model_route_id: string;
  prompt_id: string;
  directional_signal?: string | null;
  directional_signal_detail: DirectionalSignalDetail;
  self_critic_result: SelfCriticResult;
  updated_at: string;
}

export interface FailurePostmortemSummary {
  public_id: string;
  run_public_id: string;
  failure_class: string;
  failure_stage: string;
  root_cause_summary: string;
  created_at: string;
}

export interface FailurePostmortemDetail extends FailurePostmortemSummary {
  cycle_public_id: string;
  verification_report_public_id?: string | null;
  contributing_factors: Dictionary[];
  remediation_suggestions: Dictionary[];
  retrieval_hints: Dictionary[];
  protocol_update_hints: Dictionary[];
  similar_prior_failures: Dictionary[];
  model_route_id: string;
  prompt_id: string;
  updated_at: string;
}

export interface NextStepRecommendation {
  recommendation_type: string;
  rationale: string;
  payload: Dictionary;
}

export interface VerificationSummaryResponse {
  cycle_public_id: string;
  total_runs: number;
  robust_count: number;
  tentative_count: number;
  rejected_count: number;
  invalid_count: number;
  pending_count: number;
  postmortem_count: number;
  latest_cycle_summary_report_public_id?: string | null;
  next_step_recommendations: NextStepRecommendation[];
}

export interface HistoricalComparisonResponse {
  run_public_id: string;
  experiment_spec_public_id: string;
  hypothesis_public_id?: string | null;
  charter_public_id?: string | null;
  comparison_scope: string;
  comparisons: Dictionary[];
  memory_references: Dictionary[];
  total_prior_runs: number;
}

export interface RemediationAction {
  public_id: string;
  cycle_public_id: string;
  run_public_id: string;
  attempt_number: number;
  failure_classification: string;
  prompt_mode: string;
  prompt_id: string;
  model_route_id: string;
  diagnosis: string;
  fix_type: string;
  fix_description: string;
  fix_payload: Dictionary;
  prior_attempts_summary: Dictionary[];
  outcome: string;
  created_at: string;
  updated_at: string;
}

export interface RunDetailResponse {
  run: RunRecord;
  artifact_manifest?: RunArtifactManifest | null;
  telemetry_events: RunTelemetryEvent[];
  skill_execution_records: SkillExecutionRecord[];
  remediation_actions: RemediationAction[];
  frontier_snapshot?: FrontierSnapshot | null;
  reports: ReportSummary[];
  verification_report?: VerificationReportSummary | null;
  postmortem?: FailurePostmortemSummary | null;
}
