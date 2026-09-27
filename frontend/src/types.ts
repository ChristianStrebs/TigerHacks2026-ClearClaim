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

export interface PlanResponse {
  plan_name: string;
  source: "demo" | "document";
  benefits: BenefitsSnapshot;
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
  demo_mode: boolean;
}

export interface EobLineItem {
  code: string;
  description: string;
  billed: number;
  plan_expected: number | null;
  covered: boolean;
  flag: string | null;
}

export interface EobScanResponse {
  provider: string | null;
  total_billed: number;
  line_items: EobLineItem[];
  overcharge_flags: string[];
  potential_savings: number;
  summary: string;
  demo_mode: boolean;
}

export interface HealthResponse {
  status: string;
  version: string;
  gemini_enabled: boolean;
  supabase_enabled: boolean;
  vector_store: string;
  chat_model: string;
  embed_model: string;
  indexed_chunks: number;
}
