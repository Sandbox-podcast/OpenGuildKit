/**
 * Single replacement point for external services. The demo implementations are deterministic
 * and synchronous; a future API adapter keeps the same contracts and posts its results back
 * through the same domain commands (see docs/adaptateurs.md).
 */
import { analyzeRepository, REPO_SCENARIOS } from './simulation/repository';
import { clarificationFor, contributionFor, COUNCIL_SCENARIOS, SCENARIO_LIST } from './simulation/council';
import { CONTROL_STEPS, digest, evaluateControl, SKILL_STEPS, STRATEGY_LABELS, TOOL_ERROR } from './simulation/runs';
import { generateContent } from './simulation/generation';
import { WATCH_FEED } from './simulation/watch';

export const services = {
  repository: { analyze: analyzeRepository, scenarios: REPO_SCENARIOS },
  agents: { contribution: contributionFor, clarification: clarificationFor, scenarios: COUNCIL_SCENARIOS, list: SCENARIO_LIST },
  controls: { evaluate: evaluateControl, steps: CONTROL_STEPS, skillSteps: SKILL_STEPS, toolError: TOOL_ERROR, digest, strategyLabels: STRATEGY_LABELS },
  generator: { generate: generateContent },
  watch: { feed: WATCH_FEED },
};
