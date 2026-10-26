export type Preset = { id: string; label: string; acquirer: string; target: string; kind: string };

export type Screen = { id: string; label: string; acquirer: string; targets: string[] };

export type Brand = {query: string; id: string; name: string; popularity: number | null };
export type Shared = { domain: string; name: string; affinity_a: number; affinity_b: number };
export type Clashing = { domain: string; name: string; affinity: number };
export type Demographics = { age: Record<string, number>; gender: Record<string, number> };
export type TraceStep = { agent: string; status: string; ms: number; qloo_calls: number; decision?: string };
export type Bridge = { id: string; name: string; affinity_acquirer: number; affinity_target: number };

export type Diligence = {
  brands: { acquirer: Brand; target: Brand };
  scores: { bci: number; culture_clash: number; churn_risk: "low" | "medium" | "high"; demographic_distance: number };
  domain_overlap: Record<string, number>;
  top_shared: Shared[];
  top_clashing: { acquirer: Clashing[]; target: Clashing[] };
  demographics: { acquirer: Demographics; target: Demographics };
  bridges: Bridge[];
  probed_tags: boolean;
  memo: { verdict: string; headline: string; rationale: string[]; risks: string[] };
  trace: TraceStep[];
};

export const AGENTS = ["Scout", "Cartographer", "Analyst", "Partner"] as const;
