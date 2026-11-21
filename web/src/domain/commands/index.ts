/** All domain commands, addressed by the UI as `cmd.<name>`. */
import * as workspace from './workspace';
import * as blueprint from './blueprint';
import * as knowledge from './knowledge';
import * as work from './work';
import * as forge from './forge';
import * as oversight from './oversight';
import { transition } from './transitions';
import { loadDemo } from './scenarios';

export const cmd = {
  transition,
  loadDemo,
  ...pick(workspace, ['createBlankOrg', 'switchOrg', 'setActor', 'setProjectContext', 'updateOnboarding', 'analyzeRepository', 'editObservation', 'publishFirstBlueprint', 'createProject', 'updateProject', 'archiveProject', 'restoreProject', 'toggleFavoriteProject', 'saveProduct', 'addRelation', 'removeRelation', 'addMember', 'changeRole', 'removeMember', 'updateSettings', 'setIntegration', 'setPreference', 'markNotificationsRead', 'saveDraft', 'demoAdvanceTime', 'demoInjectFailure', 'demoExpire']),
  ...pick(blueprint, ['startBlueprintDraft', 'setFact', 'confirmInferred', 'addRule', 'editRule', 'removeRuleFromDraft', 'arbitrateConflict', 'excludeReference', 'adoptBlueprint', 'resolveReview']),
  ...pick(knowledge, ['toggleFavoriteReference', 'setApplicability', 'validateApplicability', 'linkReferenceToRule', 'editReference', 'restoreReference', 'applyCatalogueImport', 'proposeReferenceUpdate', 'decideReferenceProposal', 'saveCollection', 'toggleInCollection', 'savePack', 'proposeInstructions', 'restrictTools', 'updateExpert']),
  ...pick(work, ['createCouncil', 'updateCouncil', 'inviteExpert', 'requestClarification', 'annotateCouncil', 'proposeDecision', 'reviseDecision', 'editDecision', 'convertDecision', 'createQuest', 'updateQuest', 'setCriterion', 'addTasks', 'updateTask', 'setDependency', 'addComment', 'linkToQuest', 'requestApproval']),
  ...pick(forge, ['installSkill', 'setSkillActive', 'setSkillParams', 'checkSkillUpdate', 'decideSkillUpdate', 'launchControl', 'launchSkill', 'retryRun', 'createDeliverable', 'editDeliverable', 'adoptDeliverableVersion', 'restoreDeliverableVersion', 'regenerateDeliverable', 'dismissProposal', 'setDocMeta']),
  ...pick(oversight, ['assignFinding', 'correctiveQuest', 'markNotApplicable', 'saveException', 'collectSignals', 'updateSignal', 'saveOpportunity', 'saveCompetitor', 'saveSource', 'createShare', 'openShare', 'recordExport', 'compensateEvent', 'tick']),
};

function pick<T extends object, K extends keyof T>(mod: T, keys: K[]): Pick<T, K> {
  return Object.fromEntries(keys.map((k) => [k, mod[k]])) as Pick<T, K>;
}
