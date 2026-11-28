/**
 * Domain model of the Open Guild Kit demo.
 * Every business object carries an explicit scope (orgId, and projectId when relevant — RG-01)
 * and a stable id produced by the engine sequence. Relations are stored as ids, never as copies.
 */
import type { Reference } from '@/demo/adapters/catalogue';
import type { RoleId } from './permissions';

export type ID = string;
export type Millis = number;

export type EntityKind =
  | 'member'
  | 'product'
  | 'project'
  | 'relation'
  | 'blueprint'
  | 'rule'
  | 'applicability'
  | 'collection'
  | 'pack'
  | 'expert'
  | 'skill'
  | 'council'
  | 'decision'
  | 'quest'
  | 'task'
  | 'deliverable'
  | 'control'
  | 'run'
  | 'result'
  | 'evidence'
  | 'finding'
  | 'approval'
  | 'exception'
  | 'competitor'
  | 'source'
  | 'signal'
  | 'opportunity'
  | 'share'
  | 'integration'
  | 'review'
  | 'event';
export type RefKind = EntityKind | 'reference' | 'org' | 'user';
export interface Ref {
  kind: RefKind;
  id: ID;
  version?: number;
}

export type Actor = { type: 'human'; userId: ID } | { type: 'agent'; expertId: ID } | { type: 'system' };

export interface User {
  id: ID;
  name: string;
  title: string;
  portrait: PortraitKey;
}
export type PortraitKey = string;

/* ----------------------------------------------------------- organisation */
export type Provenance = 'declared' | 'observed' | 'inferred' | 'unknown';
export interface ContextFact {
  key: string;
  section: string;
  label: string;
  value: string;
  provenance: Provenance;
  /** inferred values stay proposals until a human confirms them (RG-03) */
  confirmedBy?: ID;
  source?: string;
  /** rule or decision keys that cannot be decided while this fact is unknown */
  blocks?: string[];
}

export interface OnboardingState {
  status: 'draft' | 'done';
  mode: 'new' | 'existing';
  step: number;
  answers: Record<string, { value: string; unknown: boolean }>;
  analysis?: { scenario: string | null; target: string; observations: RepoObservation[]; at: Millis };
  updatedAt: Millis;
}
export interface RepoObservation {
  id: string;
  topic: 'langages' | 'dépendances' | 'tests' | 'documentation' | 'structure' | 'configuration';
  label: string;
  value: string;
  provenance: 'observed' | 'inferred';
  corrected?: string;
  dismissed?: boolean;
}

export interface Org {
  id: ID;
  name: string;
  activity: string;
  kind: 'demo' | 'blank';
  createdAt: Millis;
  onboarding: OnboardingState;
  settings: {
    retentionDays: number;
    budget: { monthlyUnits: number; used: number };
    watch: { enabled: boolean; cadence: 'quotidienne' | 'hebdomadaire'; topics: string[]; cursor: number };
    notifications: { approvals: boolean; controls: boolean; exceptions: boolean; watch: boolean };
    demoModel: string;
  };
}

export interface Member {
  id: ID;
  orgId: ID;
  userId: ID;
  role: RoleId;
  projectId?: ID;
  since: Millis;
}

export interface Product {
  id: ID;
  orgId: ID;
  name: string;
  description: string;
  ownerId: ID;
  color: string;
  stack: string[];
  repos: Repo[];
  territory: number;
}
export interface Repo {
  id: ID;
  name: string;
  language: string;
  modules: { id: ID; name: string }[];
}

export interface Project {
  id: ID;
  orgId: ID;
  productId: ID;
  name: string;
  summary: string;
  ownerId?: ID;
  status: 'active' | 'archived';
  statusReason?: string;
  /** explicit Blueprint version followed by the project (RG-04, RG-29) */
  blueprintVersion: number;
  linkedProductIds: ID[];
  environments: string[];
  storage: string[];
  dataSensitivity: string;
  createdAt: Millis;
}

export interface Relation {
  id: ID;
  orgId: ID;
  fromProductId: ID;
  toProductId: ID;
  kind: 'appelle' | 'dépend de' | 'partage des données' | 'intègre';
  note: string;
}

/* --------------------------------------------------------------- blueprint */
export type BlueprintState = 'draft' | 'review' | 'published' | 'archived';
export interface RuleRef {
  ruleId: ID;
  version: number;
}
export interface BlueprintVersion {
  number: number;
  status: BlueprintState;
  context: ContextFact[];
  rules: RuleRef[];
  exclusions: { refId: string; reason: string; authorId: ID; at: Millis }[];
  authorId: ID;
  justification: string;
  basedOn?: number;
  createdAt: Millis;
  submittedAt?: Millis;
  publishedAt?: Millis;
  reviewerId?: ID;
}
export interface Blueprint {
  id: ID;
  orgId: ID;
  name: string;
  versions: BlueprintVersion[];
}

export type RuleLevel = 'org' | 'product' | 'repo' | 'module';
export interface RuleScope {
  level: RuleLevel;
  productId?: ID;
  repoId?: ID;
  moduleId?: ID;
}
export type InheritancePolicy = 'imposed' | 'adjustable' | 'additive';
export interface RuleVersion {
  number: number;
  status: 'draft' | 'published';
  title: string;
  statement: string;
  referenceIds: string[];
  scope: RuleScope;
  ownerId: ID;
  criticality: 'basse' | 'moyenne' | 'haute' | 'critique';
  blocking: boolean;
  derogable: boolean;
  policy: InheritancePolicy;
  /** bounds of the adjustable parameter, when the policy is "adjustable" */
  parameter?: { name: string; unit: string; value: number; min: number; max: number };
  expectedControlIds: ID[];
  /** set when this rule adapts a parent rule at a lower level (RG-05) */
  adapts?: ID;
  /** rules in the same group are competing choices to arbitrate */
  conflictGroup?: string;
  authorId: ID;
  justification: string;
  createdAt: Millis;
}
export interface Rule {
  id: ID;
  orgId: ID;
  code: string;
  versions: RuleVersion[];
}

/* ----------------------------------------------------------- library */
export type ApplicabilityStatus = 'applicable' | 'not_applicable' | 'to_clarify';
export interface Applicability {
  id: ID;
  orgId: ID;
  projectId: ID;
  refId: string;
  status: ApplicabilityStatus;
  reason: string;
  authorId: ID;
  validated: boolean;
  suggestedBy?: string;
  at: Millis;
}
export interface Collection {
  id: ID;
  orgId: ID;
  name: string;
  refIds: string[];
  description: string;
}
export interface Pack {
  id: ID;
  orgId: ID;
  name: string;
  description: string;
  refIds: string[];
  origin: 'cli' | 'local';
  cliId?: string;
  enabled: boolean;
}

export interface CatalogueOverlay {
  /** references added or edited locally; each edit keeps the previous version */
  added: Reference[];
  history: Record<string, { at: Millis; authorId: ID; data: Reference; note: string }[]>;
  proposals: {
    id: ID;
    refId: string;
    incoming: Reference;
    changes: string[];
    status: 'proposed' | 'adopted' | 'dismissed';
    at: Millis;
    origin: string;
  }[];
  favorites: Record<ID, string[]>;
}

/* ----------------------------------------------------------- guild */
export interface InstructionVersion {
  number: number;
  text: string;
  status: 'proposed' | 'active' | 'rejected' | 'retired';
  authorId: ID;
  at: Millis;
  decidedBy?: ID;
}
export interface Expert {
  id: ID;
  orgId: ID;
  key: ExpertKey;
  name: string;
  classTitle: string;
  domain: string;
  specialty: string;
  capabilities: string[];
  sources: string[];
  methods: string[];
  skillIds: ID[];
  toolsAvailable: string[];
  toolsAllowed: string[];
  contextAccess: string[];
  memory: string[];
  limits: string[];
  budget: { units: number; used: number };
  humanOwnerId: ID;
  creatorId: ID;
  approverId: ID;
  instructions: InstructionVersion[];
  boardId: string;
  active: boolean;
}
export type ExpertKey =
  | 'product'
  | 'engineering'
  | 'architecture'
  | 'design'
  | 'security'
  | 'privacy'
  | 'quality'
  | 'performance'
  | 'data'
  | 'platform'
  | 'market'
  | 'marketing'
  | 'commerce'
  | 'documentation';

/* ----------------------------------------------------------- forge */
export interface SkillVersion {
  version: string;
  permissions: string[];
  changelog: string;
  dependencies: string[];
  publishedAt: Millis;
}
export interface Skill {
  id: ID;
  orgId: ID;
  name: string;
  summary: string;
  origin: string;
  license: string;
  capabilities: string[];
  scope: string;
  params: Record<string, string>;
  versions: SkillVersion[];
  installed: string | null;
  active: boolean;
  update?: { version: string; status: 'proposed' | 'review' | 'adopted' | 'dismissed'; reviewerId?: ID; at: Millis };
  previous?: string;
  produces?: DeliverableType;
}

/* ----------------------------------------------------------- council */
export type CouncilState = 'prepared' | 'running' | 'suspended' | 'awaiting' | 'done' | 'cancelled';
export type Stance = 'pour' | 'réservé' | 'contre';
export interface Contribution {
  id: ID;
  expertId: ID;
  at: Millis;
  round: number;
  facts: string[];
  hypotheses: string[];
  questions: string[];
  risks: string[];
  recommendation: string;
  reservation?: string;
  deliverable?: string;
  sourceRefIds: string[];
  stances: Record<ID, Stance>;
  limited?: boolean;
  simulated: true;
}
export interface CouncilOption {
  id: ID;
  title: string;
  summary: string;
  pros: string[];
  cons: string[];
  impacts: Record<string, string>;
  blocking: string[];
}
export interface Council {
  id: ID;
  orgId: ID;
  projectId: ID;
  title: string;
  objective: string;
  scenario: string | null;
  context: string;
  documentIds: ID[];
  constraints: string[];
  ruleIds: ID[];
  participantIds: ID[];
  ownerId: ID;
  status: CouncilState;
  statusReason?: string;
  blueprintVersion: number;
  requiredFacts: string[];
  contributions: Contribution[];
  options: CouncilOption[];
  annotations: { id: ID; text: string; authorId: ID; contributionIds: ID[]; optionId?: ID; at: Millis }[];
  clarifications: { id: ID; expertId: ID; question: string; answer: string; at: Millis }[];
  origin?: Ref;
  createdAt: Millis;
}

export type DecisionState = 'draft' | 'review' | 'approved' | 'refused' | 'replaced' | 'cancelled';
export interface Decision {
  id: ID;
  orgId: ID;
  projectId: ID;
  councilId?: ID;
  title: string;
  number: number;
  revisionOf?: ID;
  replacedBy?: ID;
  status: DecisionState;
  statusReason?: string;
  optionId?: ID;
  optionTitle: string;
  justification: string;
  ownerId: ID;
  authorId: ID;
  considered: { blueprintVersion: number; rules: RuleRef[] };
  questIds: ID[];
  questPlan: QuestPlan[];
  createdAt: Millis;
  decidedAt?: Millis;
}
export interface QuestPlan {
  title: string;
  objective: string;
  type: QuestType;
  criteria: string[];
  deliverables: DeliverableType[];
  controlIds: ID[];
  tasks: string[];
}

/* ----------------------------------------------------------- quests */
export type QuestState = 'todo' | 'ready' | 'doing' | 'blocked' | 'review' | 'done' | 'cancelled';
export type QuestType = 'fonctionnalité' | 'correction' | 'sécurité' | 'documentation' | 'design' | 'performance' | 'campagne';
export interface Criterion {
  id: ID;
  text: string;
  required: boolean;
  met: boolean;
}
export interface Comment {
  id: ID;
  authorId: ID;
  text: string;
  at: Millis;
}
export interface Quest {
  id: ID;
  orgId: ID;
  projectId: ID;
  title: string;
  objective: string;
  type: QuestType;
  origin: 'decision' | 'direct' | 'finding' | 'signal';
  originRef?: Ref;
  decisionId?: ID;
  ownerId?: ID;
  priority: 'P1' | 'P2' | 'P3' | 'P4';
  due?: string;
  status: QuestState;
  statusReason?: string;
  resumeTo?: QuestState;
  criteria: Criterion[];
  expectedDeliverables: DeliverableType[];
  deliverableIds: ID[];
  controlIds: ID[];
  needsHumanApproval: boolean;
  comments: Comment[];
  order: number;
  createdAt: Millis;
  closedAt?: Millis;
  /** incremented on reopening: approvals given before no longer match (RG-15) */
  revision: number;
}
export interface Task {
  id: ID;
  orgId: ID;
  questId: ID;
  title: string;
  status: QuestState;
  statusReason?: string;
  assigneeId?: ID;
  dependsOn: ID[];
  order: number;
}

/* ----------------------------------------------------------- deliverables */
export type DeliverableType =
  | 'spec'
  | 'adr'
  | 'code'
  | 'tests'
  | 'component'
  | 'gallery'
  | 'api'
  | 'doc'
  | 'changelog'
  | 'roadmap'
  | 'landing'
  | 'presentation'
  | 'video';
export type DeliverableState = 'draft' | 'review' | 'approved' | 'published' | 'replaced' | 'archived';
export type DocCategory = 'tutoriel' | 'guide' | 'référence' | 'explication' | 'api' | 'changelog' | 'roadmap' | 'commercial';

export type Content =
  | { kind: 'markdown'; body: string }
  | { kind: 'files'; files: { path: string; language: string; body: string }[] }
  | {
      kind: 'component';
      name: string;
      description: string;
      variants: { name: string; props: Record<string, string | boolean> }[];
      checks: string[];
    }
  | { kind: 'gallery'; componentIds: ID[]; intro: string }
  | { kind: 'api'; spec: string }
  | { kind: 'roadmap'; items: { horizon: string; title: string; status: string; note: string }[] }
  | { kind: 'landing'; hero: string; subtitle: string; features: { title: string; text: string }[]; cta: string; note: string }
  | { kind: 'slides'; slides: { title: string; bullets: string[]; note: string }[] }
  | { kind: 'storyboard'; scenes: { title: string; seconds: number; visual: string; voice: string }[] };

export interface DeliverableVersion {
  number: number;
  content: Content;
  authorId: ID | null;
  authorKind: 'human' | 'agent' | 'system';
  createdAt: Millis;
  note: string;
  simulated: boolean;
  /** proposals (regenerations, unaccepted edits) do not replace the adopted version (RG-29, RG-34) */
  proposal: boolean;
  /** versions of the source objects this version describes (RG-35) */
  describes: Ref[];
}
export interface Deliverable {
  id: ID;
  orgId: ID;
  projectId: ID;
  questId?: ID;
  type: DeliverableType;
  title: string;
  status: DeliverableState;
  current: number;
  versions: DeliverableVersion[];
  ownerId: ID;
  docCategory?: DocCategory;
  docPath?: string;
  audience?: string;
  createdAt: Millis;
}

/* ----------------------------------------------------------- controls */
export type RunState = 'pending' | 'running' | 'suspended' | 'done' | 'error' | 'cancelled';
export type ResultState = 'not_evaluated' | 'passed' | 'failed' | 'inconclusive' | 'not_applicable';
export type ControlCategory = 'qualité' | 'tests' | 'sécurité' | 'dépendances' | 'accès' | 'performance' | 'fiabilité';
export interface ControlDef {
  id: ID;
  orgId: ID;
  code: string;
  name: string;
  category: ControlCategory;
  description: string;
  ruleIds: ID[];
  blocking: boolean;
  version: number;
  strategy: string;
  appliesTo: DeliverableType[];
}
export interface RunInputs {
  blueprintVersion: number;
  rules: RuleRef[];
  controlVersion?: number;
  subject?: { deliverableId: ID; version: number };
  params: Record<string, string>;
}
export interface Run {
  id: ID;
  orgId: ID;
  projectId: ID;
  kind: 'control' | 'skill';
  controlId?: ID;
  skillId?: ID;
  questId?: ID;
  title: string;
  inputs: RunInputs;
  steps: { label: string; status: 'pending' | 'running' | 'done' | 'error' | 'skipped' }[];
  stepIndex: number;
  status: RunState;
  statusReason?: string;
  log: { at: Millis; level: 'info' | 'warn' | 'error'; text: string }[];
  attempt: number;
  previousRunId?: ID;
  plannedFailure?: 'tool-error' | 'inconclusive' | null;
  startedAt: Millis;
  endedAt?: Millis;
  costPerStep: number;
  resultId?: ID;
  outputDeliverableId?: ID;
  actor: Actor;
  suspendable: boolean;
}
export interface Result {
  id: ID;
  orgId: ID;
  projectId: ID;
  runId: ID;
  controlId: ID;
  outcome: ResultState;
  observation: string;
  justification?: string;
  inputs: RunInputs;
  evaluatedAt: Millis;
  simulated: true;
}
export interface Evidence {
  id: ID;
  orgId: ID;
  projectId: ID;
  resultId: ID;
  runId: ID;
  controlId: ID;
  inputs: RunInputs;
  at: Millis;
  actor: Actor;
  provenance: string;
  digest: string;
  excerpt: string;
  simulated: true;
}
export type FindingStatus = 'open' | 'in_progress' | 'resolved' | 'waived';
export interface Finding {
  id: ID;
  orgId: ID;
  projectId: ID;
  severity: 'critique' | 'haute' | 'moyenne' | 'basse';
  category: ControlCategory;
  title: string;
  subject: Ref;
  ruleId?: ID;
  resultId?: ID;
  runId?: ID;
  observation: string;
  source: string;
  ownerId?: ID;
  status: FindingStatus;
  remediation: string;
  questId?: ID;
  createdAt: Millis;
}

/* ----------------------------------------------------------- approvals and exceptions */
export type ApprovalState = 'expected' | 'approved' | 'refused' | 'expired' | 'revoked';
export interface Approval {
  id: ID;
  orgId: ID;
  projectId?: ID;
  subject: Ref & { version: number };
  purpose: 'décision' | 'clôture' | 'livrable' | 'exception' | 'blueprint' | 'instruction' | 'skill' | 'revue';
  authorId: ID;
  approverId?: ID;
  requireDistinct: boolean;
  status: ApprovalState;
  reason?: string;
  decidedBy?: ID;
  decidedAt?: Millis;
  expiresAt?: Millis;
  createdAt: Millis;
}
export type ExceptionState = 'draft' | 'requested' | 'approved' | 'refused' | 'expired' | 'revoked';
export interface RuleException {
  id: ID;
  orgId: ID;
  projectId: ID;
  ruleId: ID;
  subject?: { deliverableId: ID; version: number };
  scope: string;
  reason: string;
  riskAccepted: string;
  compensatingMeasures: string;
  ownerId?: ID;
  approverId?: ID;
  expiresAt?: Millis;
  status: ExceptionState;
  statusReason?: string;
  authorId: ID;
  decidedBy?: ID;
  createdAt: Millis;
}
export interface ReviewFlag {
  id: ID;
  orgId: ID;
  projectId?: ID;
  subject: Ref;
  cause: Ref;
  reason: string;
  status: 'open' | 'done';
  createdAt: Millis;
  doneBy?: ID;
}

/* ----------------------------------------------------------- observatory */
export interface Competitor {
  id: ID;
  orgId: ID;
  name: string;
  kind: 'direct' | 'indirect';
  description: string;
  fictional: true;
  strengths: string[];
  weaknesses: string[];
  favorite: boolean;
}
export interface WatchSource {
  id: ID;
  orgId: ID;
  name: string;
  url: string;
  type: string;
  fictional: true;
  active: boolean;
}
export type SignalType = 'fonctionnalité' | 'annonce' | 'financement' | 'site' | 'communication' | 'marché' | 'écosystème';
export interface Signal {
  id: ID;
  orgId: ID;
  competitorId?: ID;
  sourceId: ID;
  type: SignalType;
  title: string;
  publishedAt: Millis;
  consultedAt: Millis;
  context: string;
  facts: string[];
  interpretations: string[];
  hypotheses: string[];
  recommendations: string[];
  relevance: { level: 'faible' | 'moyenne' | 'forte'; reasons: string[] };
  projectIds: ID[];
  notes: Comment[];
  favorite: boolean;
  opportunityId?: ID;
  councilId?: ID;
  questId?: ID;
  reevaluation?: 'proposed' | 'done';
  fictional: true;
}
export interface Opportunity {
  id: ID;
  orgId: ID;
  title: string;
  description: string;
  signalIds: ID[];
  status: 'open' | 'council' | 'retained' | 'dismissed';
  councilId?: ID;
  createdAt: Millis;
}

/* ----------------------------------------------------------- docs, sharing, integrations */
export interface Share {
  id: ID;
  orgId: ID;
  deliverableId: ID;
  version: number;
  audience: string;
  mode: 'lecture' | 'contribution';
  expiresAt: Millis;
  status: 'active' | 'revoked';
  token: string;
  createdBy: ID;
  createdAt: Millis;
  accessLog: { at: Millis; visitor: string; outcome: 'autorisé' | 'refusé' | 'expiré' | 'révoqué' }[];
}
export type IntegrationState = 'not_configured' | 'connecting' | 'available' | 'error' | 'expired' | 'disconnected';
export interface Integration {
  id: ID;
  orgId: ID;
  name: string;
  category: string;
  status: IntegrationState;
  detail: string;
  changedAt: Millis;
  account?: string;
}

/* ----------------------------------------------------------- audit */
export interface AuditEvent {
  id: ID;
  orgId: ID;
  projectId?: ID;
  at: Millis;
  actor: Actor;
  action: string;
  summary: string;
  object: Ref;
  provenance: 'local' | 'simulation' | 'démo';
  justification?: string;
  related: Ref[];
  compensates?: ID;
}

/* ----------------------------------------------------------- workspace */
export interface EntityMap {
  member: Member;
  product: Product;
  project: Project;
  relation: Relation;
  blueprint: Blueprint;
  rule: Rule;
  applicability: Applicability;
  collection: Collection;
  pack: Pack;
  expert: Expert;
  skill: Skill;
  council: Council;
  decision: Decision;
  quest: Quest;
  task: Task;
  deliverable: Deliverable;
  control: ControlDef;
  run: Run;
  result: Result;
  evidence: Evidence;
  finding: Finding;
  approval: Approval;
  exception: RuleException;
  competitor: Competitor;
  source: WatchSource;
  signal: Signal;
  opportunity: Opportunity;
  share: Share;
  integration: Integration;
  review: ReviewFlag;
  event: AuditEvent;
}
export type DB = { [K in EntityKind]: Record<ID, EntityMap[K]> };

export interface Preferences {
  mode: 'explorer' | 'focus';
  motion: 'system' | 'reduced' | 'full';
  sound: boolean;
  textScale: 1 | 1.125 | 1.25;
  favoriteProjects: ID[];
  readNotifications: ID[];
  guideOpen: boolean;
}
export interface Session {
  orgId: ID | null;
  actor: Actor;
  projectId: ID | null;
}
export interface DemoSettings {
  timeOffsetMs: number;
  nextFailure: 'tool-error' | 'inconclusive' | null;
}

export interface AppState {
  schema: number;
  seq: number;
  orgs: Record<ID, Org>;
  users: Record<ID, User>;
  db: DB;
  catalogue: CatalogueOverlay;
  session: Session;
  prefs: Preferences;
  demo: DemoSettings;
  drafts: Record<string, unknown>;
  appliedOps: string[];
}
