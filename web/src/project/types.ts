/** Shapes of the JSON the OpenGuildKit CLI prints. Only the fields the interface reads are typed. */

export type TaskStatus = 'draft' | 'consulting' | 'reviewed' | 'approved' | 'changes-requested' | 'done';

export interface TaskListItem { id: string; status: TaskStatus; created: string; owner: string | null; brief: string; next: string; follows?: string }

export interface Evidence { source: string; ref: string; supports: string }
export interface Specialist { id: string; finding: string; basis: string; evidence_refs: number[] }
export interface Blocker { finding: string; owner: string; clears_when: string }
export interface Challenge { specialists: Specialist[]; verdict: string; confidence: string; alternative: string; failure_mode: string; verification: string; blockers: (Blocker | string)[] }
export interface BoardReview { id: string; recommendation: string; evidence: Evidence[]; open_questions: string[]; challenge?: Challenge; reviewer?: string }
export interface Review { consultation_id: string; summary: string; boards: BoardReview[]; execution?: string }

export interface Decision { outcome: 'approved' | 'changes-requested'; by: string; reason: string; at: string; base_revision?: string | null; seal?: string; signature?: { signer: string } }
export interface CheckResult { check: string; status: 'passed' | 'failed' | 'skipped' | 'not-applicable'; evidence?: string; reason?: string; owner?: string; exit_code?: number; seconds?: number }
export interface TaskResult { revision?: string; pull_request?: string; criteria: { criterion: string; status: 'met' | 'not-met'; evidence: string }[]; checks: CheckResult[] }
export interface Answers { kind?: string; surface?: string | string[]; data?: string; research?: string; context?: string; outcome?: string; affected?: string; options?: string }

export interface Consultation {
  id: string;
  boards: string[];
  routing: Record<string, string[]>;
  adjustments?: { action: string; board: string; reason: string }[];
  delegations?: Record<string, string>;
  scope: { open_points?: string[]; packs?: { id: string; title?: string }[]; checks?: string[]; research?: string; market?: unknown };
  markdown: string;
}

export interface TaskRecord {
  id: string;
  brief: string;
  created_at: string;
  status: TaskStatus;
  rounds: { answers?: Answers; consultation?: Consultation; review?: Review; decision?: Decision; archived_at?: string }[];
  answers?: Answers;
  follows?: { task: string; brief: string; status: string; decision?: Decision };
  consultation?: Consultation;
  review?: Review;
  decision?: Decision;
  result?: TaskResult;
  completed_at?: string;
  deliverables?: { deliverable: string; path: string; tool: string; created_at: string }[];
  authorizations?: { action: string; target: string; decision: 'allow' | 'deny'; by: string; reason: string; at: string }[];
  resolutions?: Record<string, { kind: 'cleared' | 'waived'; by: string; evidence?: string; supports?: string; reason?: string; scope?: string; until?: string }>;
  passes?: Record<string, unknown>;
}

export interface Question { id: string; prompt: string; type?: string; choices?: { id: string; label: string }[]; default?: unknown }
export interface QuestionSet { questions: Question[]; follow_ups: string[]; open_points: string[] }
export interface Route { routing: Record<string, string[]>; adjustments: { action: string; board: string; reason: string }[]; delegations: Record<string, string> }
export interface PassProgress { board: string; status: 'done' | 'failed' | 'started' | 'missing'; mode?: string; attempts?: number; reason?: string }
export interface BlockerItem { id: string; board: string; finding: string; owner?: string; clears_when?: string; resolution: null | { kind: string; by: string; evidence?: string; supports?: string; reason?: string; scope?: string; until?: string } }
export interface ExpectedCheck { id: string; kind: 'command' | 'rule' | 'scenario'; command?: string; rule?: string; instruction?: string; verification?: string; mandatory: boolean; result: CheckResult | null }
export interface Deliberation { objections: { id: string; from: string; to: string; point: string; from_position: string; to_position: string }[]; template: { consultation_id: string; responses: unknown[]; decision_needed: string } }

export interface Profile {
  schema_version?: number;
  name: string;
  sector?: string;
  stack?: string[];
  components?: { id?: string; path: string; stack?: string[] }[];
  roles?: string[];
  patterns?: (string | { id: string; components?: string[] })[];
  packs?: string[];
  boards?: string[];
  required_boards?: string[];
  required_rules?: string[];
  research?: 'local-only' | 'public-sources';
  host?: string;
  guard?: 'off' | 'observe' | 'enforce';
  waivers?: { allowed_by: string[]; max_days: number };
  approval?: { mode: 'local' | 'signed'; allowed_signers?: string; approvers?: string[] };
  tools?: string[];
  conventions?: string[];
  checks?: string[];
}

export interface Rule { id: string; instruction: string; verification: string }
export interface Pack { id: string; title: string; version: string; description: string; sources: { title: string; url: string }[]; rules: Rule[]; requires?: string[]; applies_to?: unknown }
export interface Lens { id: string; title: string; focus: string }
export interface Brain {
  id: string; title: string; description: string; expertises: string[]; triggers: string[]; questions: string[];
  sources: { title: string; url: string }[];
  review?: { specialists: Lens[]; evidence: string[]; challenge: string[]; decision_criteria: string[] };
  knowledge?: { methods?: { id: string; title: string }[]; references?: { id: string; title: string }[] } & Record<string, unknown>;
}
export interface Sector { id: string; title: string; description: string; context: string[]; sources: { title: string; url: string }[] }
export interface Catalog { packs: Record<string, Pack>; boards: Record<string, Brain>; sectors: Record<string, Sector> }
export interface PlanPack { id: string; title: string; version: string; provenance: string[]; scope: unknown; rules: string[] }
export interface RulePlan { packs: PlanPack[]; excluded: unknown[]; conflicts: unknown[]; conventions: string[]; checks: string[] }

export interface Reference { id: string; aliases?: string[]; title: string; category: string; kind: string; brains?: string[]; summary: string; applies_when: string; sources: { url: string; title: string }[]; status: string; family: string; family_title: string }
export interface Pattern { id: string; title: string; description: string; sources: { title: string; url: string }[]; roles: string[]; packs: string[]; match?: unknown; matched_stack?: string[] }
export interface Recommendation { matched: Pattern[]; suggested: Pattern[]; excluded: Pattern[]; recommended_packs: string[]; review: { id: string; reasons: string[] }[] }

export interface Alert { id: string; ecosystem: string; package: string; version: string; advisory: string; aliases: string[]; severity: string; summary: string; fix?: string; url?: string; status: 'open' | 'confirmed' | 'dismissed' | 'resolved'; scanners: string[]; tasks: string[]; first_seen: string; last_seen: string; by?: string; reason?: string; decided_at?: string; accepted?: { by: string; reason: string; at: string } }
export interface AlertRegister { summary: { total: number; by_status: Record<string, number>; by_severity: Record<string, number>; imports: { tool: string; file: string; sha256: string; at?: string }[] }; alerts: Alert[] }
export interface Share { id: string; deliverable: string; recipients: string[]; until: string; portal: string; by: string; created_at: string; revoked_at: string | null; state: 'active' | 'expired' | 'revoked' | string }
export interface HostControl { id: string; title: string; status: 'enforced' | 'instruction' | 'missing' | string; detail: string }
export interface Update { changes: { record?: string; kind?: string; id?: string; change?: string; rules?: unknown[] }[]; conflicts: unknown[]; applied: boolean; stale_tasks: string[] }
export interface Guard { mode: string; covered_by: string[] }
export interface Tool { id: string; title: string; vendor: string; summary: string; homepage: string; brains: string[]; servers: { name?: string; id?: string; kind?: string; maintainer?: string; transport?: string }[]; api?: { kind: string; docs: string }; notes?: string; category: string; mock: boolean }
export interface ToolStatus { tool: string; server?: string; host?: string; recorded?: boolean; present?: boolean; missing?: string[] }

export interface Dossier {
  id: string; title: string; market: string; audience: string; feature: string;
  competitors: { id: string; name: string; kind: 'direct' | 'substitute'; segment?: string; url?: string }[];
  observations: { id: string; competitor: string; claim: string; feature?: string; source: { ref: string; date: string } }[];
  unknowns: string[];
  watch?: { every_days: number; paused: boolean; sources: { competitor: string; url: string; kind: string; last_checked?: string }[]; changes: { competitor: string; what: string; date: string; source: string; verified_by: string }[] };
}
export interface MarketDue { dossiers: { dossier: string; due: { competitor: string; url: string; kind: string; dossier: string }[]; paused: boolean }[]; due: { competitor: string; url: string; kind: string; dossier: string }[] }

export interface StorybookProposal { id: string; kind?: string; name?: string; status?: string; decision?: string; source?: string; group?: string; [key: string]: unknown }
