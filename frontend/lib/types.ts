// TypeScript mirrors of the backend response shapes (kept intentionally light).

export interface TableColumn {
  field_name: string;
  label: string;
  field_type: string;
  required: boolean;
}

export interface FieldDefinition {
  field_name: string;
  label: string;
  field_type: string;
  classification: string;
  description: string;
  required: boolean;
  enum_values: string[];
  default: unknown;
  node_ids: string[];
  section_key: string | null;
  columns: TableColumn[];
  confidence: number;
}

export interface ValidationRule {
  rule_id: string;
  rule_type: string;
  field_name: string | null;
  params: Record<string, unknown>;
  message: string | null;
  severity: string;
}

export interface ElementClassification {
  node_id: string;
  classification: string;
  field_name: string | null;
  field_type: string | null;
  description: string;
  required: boolean;
  confidence: number;
  validation_hints: string[];
  static_prefix: string | null;
  static_suffix: string | null;
  enum_values: string[];
  source: string;
  rationale: string;
}

export interface SectionUnderstanding {
  section_key: string;
  title: string;
  purpose: string;
  expected_content: string;
  field_names: string[];
  related_sections: string[];
}

export interface ReviewElement {
  node_id: string;
  type: string;
  text: string;
  classification: string;
  field_name: string | null;
  static_prefix: string | null;
  optional: boolean;
  headers: string[] | null;
}

export interface AnalysisJob {
  id: string;
  status: string;
  progress: number;
  stage: string | null;
  elements: ReviewElement[];
  name: string | null;
  document_type_guess: string | null;
  representative_document_id: string | null;
  source_document_ids: string[];
  model_used: string | null;
  ai_warning: string | null;
  error: string | null;
  diff_summary: Record<string, number> | null;
  sections: SectionUnderstanding[];
  classifications: ElementClassification[];
  field_definitions: FieldDefinition[];
  validation_rules: ValidationRule[];
  created_at: string;
}

export interface Template {
  id: string;
  name: string;
  document_type: string | null;
  description: string | null;
  latest_version: number;
  project_id: string | null;
  created_at: string;
  updated_at: string;
  // Only populated by getTemplate (the detail view), for the inheritance display.
  project_name?: string;
  project_metadata?: Record<string, string>;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  metadata: Record<string, string>;
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail extends Project {
  templates: Template[];
}

export interface TemplateVersion {
  id: string;
  template_id: string;
  version: number;
  renderer: string;
  model_used: string | null;
  n_fields: number;
  source_file_names: string[];
  notes: string | null;
  changelog: string | null;
  created_at: string;
}

export interface TemplateElement {
  node_id: string;
  type: string;
  text: string;
  scope: string | null;
  classification: string;
  field_name: string | null;
  static_prefix: string | null;
  headers: string[] | null;
}

export interface VersionDetail {
  manifest: Record<string, unknown>;
  intelligence: Record<string, unknown>;
  fields: FieldDefinition[];
  rules: ValidationRule[];
  source_examples: string[];
  elements: TemplateElement[];
}

export interface TemplateDetail extends Template {
  versions: TemplateVersion[];
  latest?: VersionDetail;
}

export interface ValidationIssue {
  rule_id: string | null;
  field_name: string | null;
  node_id: string | null;
  severity: string;
  message: string;
  suggested_fix: string;
}

export interface ValidationReport {
  status: string;
  issues: ValidationIssue[];
  checked_fields: string[];
  summary: Record<string, number>;
}

export interface PlacementInstruction {
  field_name: string;
  value: unknown;
  confidence: number;
  source_excerpt: string;
  ambiguous: boolean;
  alternatives: string[];
  note: string;
}

export interface RoutingResult {
  template_id: string;
  version: number;
  placements: PlacementInstruction[];
  missing_required: string[];
  ambiguous_fields: string[];
  unmapped_content: string[];
  model_used: string | null;
  source: string;
}

export interface GenerationResult {
  id: string;
  template_id: string;
  version: number;
  mode: string;
  status: string;
  error: string | null;
  routing: RoutingResult | null;
  context_used: Record<string, unknown> | null;
  validation: ValidationReport | null;
  output_filename: string | null;
  generated_document_id: string | null;
  download_url: string | null;
  created_at: string;
}

export interface Health {
  status: string;
  version: string;
  ai_active: boolean;
  ai_provider: string | null;
  ai_model: string | null;
  pdf_export: boolean;
  generation_modes: string[];
}

export interface AISettings {
  provider: string;
  enabled: boolean;
  base_url: string;
  model: string;
  has_key: boolean;
  no_think: boolean;
  active: boolean;
}

// Free-tier AI allowance for the signed-in user. The shared key is never exposed.
export interface AIUsage {
  free_enabled: boolean;
  free_limit: number;
  free_used: number;
  free_remaining: number;
  has_own_key: boolean;
}

export interface AISettingsResponse {
  ai: AISettings;
  usage: AIUsage;
}

// A server-side log line for the in-app Logs page (scoped to the current user).
export interface LogEntry {
  ts: number;
  time: string;
  level: string;
  logger: string;
  rid: string | null;
  user: string | null;
  message: string;
}

export interface ComplianceDifference {
  kind: string;
  node_id: string | null;
  field_name: string | null;
  severity: string;
  expected: string;
  found: string;
  message: string;
}

export interface DimensionScore {
  name: string;
  satisfied: number;
  total: number;
  score: number;
}

export interface ComplianceAlignedPair {
  node_id: string;
  classification: string;
  status: string; // match | changed | missing | field | field_missing | table | table_changed | missing_table | extra
  severity: string;
  template_text: string;
  document_text: string;
  field_name: string | null;
  is_table: boolean;
  template_headers: string[];
  document_headers: string[];
}

export interface ComplianceReport {
  template_id: string;
  version: number;
  document_name: string;
  score: number;
  grade: string;
  dimensions: DimensionScore[];
  differences: ComplianceDifference[];
  matched_fields: string[];
  missing_fields: string[];
  alignment: ComplianceAlignedPair[];
  fixable: boolean;
  document_preview: PreviewBlock[];
}

export interface PreviewBlock {
  type: string; // paragraph | heading | table
  text?: string;
  style?: string;
  headers?: string[];
  rows?: string[][];
}

export interface PreviewResult {
  blocks: PreviewBlock[];
  validation: ValidationReport | null;
  routing: RoutingResult | null;
  context_used: Record<string, unknown>;
}

export interface RouteDocumentResult {
  routing: RoutingResult;
  extracted: PreviewBlock[];
  version: number;
}
