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
