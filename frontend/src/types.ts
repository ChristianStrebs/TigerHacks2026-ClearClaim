export interface Source {
  document: string;
  snippet: string;
  score: number;
}

export type PlanField = "deductible_total" | "coinsurance_rate" | "oop_max";

export interface BenefitsSnapshot {
  deductible_total: number;
  deductible_met: number;
  deductible_remaining: number;
  coinsurance_rate: number;
  oop_max: number;
  demo_fields: PlanField[];
}

/** "none" until the visitor picks sample data or submits their own plan. */
export type PlanSource = "none" | "demo" | "document";

export interface PlanResponse {
  plan_name: string | null;
  source: PlanSource;
  benefits: BenefitsSnapshot | null;
  summary: string;
  demo_mode: boolean;
}

export interface CostEstimate {
  billed_amount: number;
  applied_to_deductible: number;
  coinsurance: number;
  estimated_out_of_pocket: number;
  explanation: string;
}

export interface ChatResponse {
  answer: string;
  sources: Source[];
  benefits: BenefitsSnapshot;
  cost_estimate: CostEstimate | null;
  /** The saved bill scan the answer could draw on, if any. */
  bill_scan_id: string | null;
  demo_mode: boolean;
}

export type Network = "in" | "out" | "unknown";

export type ProviderType =
  | "facility"
  | "primary_care"
  | "specialist"
  | "surgeon"
  | "emergency_medicine"
  | "anesthesiology"
  | "radiology"
  | "pathology"
  | "laboratory"
  | "neonatology"
  | "assistant_surgeon"
  | "hospitalist"
  | "intensivist"
  | "air_ambulance"
  | "ground_ambulance"
  | "pharmacy"
  | "other";

export interface EobLineItem {
  code: string;
  description: string;
  billed: number;
  plan_expected: number | null;
  covered: boolean;
  flag: string | null;
  /** Whether the provider who billed this line is in network. */
  network: Network;
  /** Whether the hospital or surgery center where it happened is in network. */
  facility_in_network: boolean | null;
  emergency: boolean;
  preventive: boolean;
  provider_type: ProviderType;
}

/** A patient protection that may apply to some of a bill's charges. */
export interface RightsFinding {
  rule_id: string;
  title: string;
  explanation: string;
  you_should_owe: string;
  action: string;
  /** The charges it applies to, as "description (code)". */
  lines: string[];
  source_name: string;
  citation_url: string;
}

export interface EobScanResponse {
  scan_id: string;
  file_name: string;
  scanned_at: string;
  plan_name: string;
  provider: string | null;
  total_billed: number;
  line_items: EobLineItem[];
  overcharge_flags: string[];
  potential_savings: number;
  /** What the member should pay once flagged charges are fixed. */
  you_owe: number;
  /** How much of you_owe counted toward the deductible when it was scanned. */
  applied_to_deductible: number;
  /** Scanning the same file again replaces the earlier scan. */
  file_sha256: string | null;
  rights: RightsFinding[];
  summary: string;
  demo_mode: boolean;
}

export interface HealthResponse {
  status: string;
  version: string;
  gemini_enabled: boolean;
  /** True when visitors sign in and their data is saved in Supabase. */
  supabase_enabled: boolean;
  storage: "in-memory" | "supabase";
  chat_model: string;
  embed_model: string;
}

export interface ChatHistoryItem {
  question: string;
  response: ChatResponse;
}

export interface SampleFile {
  name: string;
  kind: "bill" | "benefits";
  description: string;
  url: string;
}

export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}
