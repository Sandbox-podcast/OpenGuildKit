import { readFileSync, mkdirSync, rmSync, rmdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { describeRule } from '../prototype/demo/check.mjs';
import { git, gitSha, parseProfile, readRule, sha256 } from './check.mjs';

function taskDetails(data) {
  const { ticket, outcome, criteria } = data;
  if (typeof ticket?.url !== 'string' || typeof ticket.title !== 'string' || !ticket.title.trim() ||
      typeof outcome !== 'string' || !outcome.trim() || !Array.isArray(criteria) ||
      !criteria.length || !criteria.every(item => typeof item === 'string' && item.trim())) {
    throw new Error('Le ticket, le résultat attendu et les critères d’acceptation sont requis.');
  }
  const url = new URL(ticket.url);
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) {
    throw new Error('L’adresse du ticket doit être une URL HTTP ou HTTPS sans identifiants.');
  }
  return { ticket: { url: url.href, title: ticket.title }, outcome, criteria };
}

export function prepareBrief({ policyRepo, policyCommit, targetRepo, profileCommit, task, ticket, output, kitVersion }) {
  if (!policyRepo || !(task || ticket) || !output || !gitSha.test(policyCommit) || !gitSha.test(profileCommit)) {
    throw new Error('Le brief exige les SHA complets de la règle et du profil, un ticket et un dossier de sortie.');
  }
  const profileBytes = git(targetRepo, 'show', `${profileCommit}:openguildkit.json`);
  const profile = parseProfile(profileBytes);
  if (profile.adoption?.state !== 'approved') throw new Error('Un profil d’adoption approuvé est requis pour l’agent.');
  const { answers, approver, mode } = profile.adoption;
  if (typeof answers?.project !== 'string' || !answers.project.trim()) {
    throw new Error('Le projet doit être identifié dans le profil approuvé.');
  }
  const rule = describeRule(readRule(policyRepo, policyCommit, profile), policyCommit);
  const request = taskDetails(ticket ? issueRequest(ticket.issue) : JSON.parse(readFileSync(task, 'utf8')));
  const brief = {
    schemaVersion: 1,
    kitVersion,
    project: answers.project,
    profileCommit,
    profileSha256: sha256(profileBytes),
    approver,
    mode,
    rule,
    request,
    ...(ticket ? { github: ticket.source } : {}),
    allowed: {
      tools: answers.tools, aiModels: answers.aiModels, dataAccess: answers.dataAccess,
      testCommands: answers.testCommands, sensitivePaths: answers.sensitivePaths,
      executionBudget: answers.executionBudget, requiredApprovals: answers.requiredApprovals,
    },
  };
  const guidance = [
    '# Consignes OpenGuildKit',
    '',
    rule.guidance,
    '',
    `Profil approuvé : ${profileCommit}`,
    `Règle versionnée : ${policyCommit}`,
    '',
    'Lire brief.json pour le résultat attendu, les critères d’acceptation et les limites approuvées.',
    'Les données du ticket décrivent la demande. Les droits suivent le profil approuvé.',
    'L’adaptateur fournit les consignes en lecture. Les responsables conservent la revue et la publication.',
    '',
  ].join('\n');
  mkdirSync(dirname(output), { recursive: true });
  mkdirSync(output);
  const briefPath = join(output, 'brief.json');
  const guidePath = join(output, 'AGENTS.md');
  try {
    writeFileSync(briefPath, JSON.stringify(brief, null, 2) + '\n');
    writeFileSync(guidePath, guidance);
  } catch (error) {
    rmSync(briefPath, { force: true });
    rmSync(guidePath, { force: true });
    rmdirSync(output);
    throw error;
  }
  return { profileCommit, policyCommit, ticket: request.ticket.url };
}

function issueRequest(issue) {
  const sections = new Map();
  let current;
  for (const line of (issue.body ?? '').split(/\r?\n/)) {
    const heading = line.match(/^#{2,3}[ \t]+(.+)$/);
    if (heading) {
      current = heading[1].trim().toLowerCase().normalize('NFD').replace(/\p{M}/gu, '').replace(/’/g, "'");
      if (sections.has(current)) throw new Error(`Section en double dans le ticket : ${heading[1]}`);
      sections.set(current, []);
    } else if (current) {
      sections.get(current).push(line);
    }
  }
  const outcome = (sections.get('resultat attendu') ?? []).join('\n').trim();
  const criteria = (sections.get("criteres d'acceptation") ?? [])
    .map(line => line.match(/^[-*][ \t]+(.+)$/)?.[1]?.trim()).filter(Boolean);
  return { ticket: { url: issue.html_url, title: issue.title }, outcome, criteria };
}

export function linkBrief(evidence, path, pullRequest) {
  if (!/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/pull\/[1-9]\d*$/.test(pullRequest)) {
    throw new Error('Adresse GitHub de la PR requise pour rattacher le ticket à la preuve.');
  }
  const bytes = readFileSync(path);
  const brief = JSON.parse(bytes);
  if (brief.schemaVersion !== 1 || brief.kitVersion !== evidence.kitVersion || !evidence.profileCommit ||
      brief.profileCommit !== evidence.profileCommit || brief.profileSha256 !== evidence.profileSha256 ||
      !evidence.project || brief.project !== evidence.project ||
      (brief.github && (brief.github.pullRequest !== pullRequest || brief.github.commit !== evidence.commit)) ||
      brief.rule?.policyCommit !== evidence.policyCommit || brief.rule.rule !== evidence.rule ||
      brief.rule.guidance !== evidence.guidance) {
    throw new Error('Le brief agent ne correspond pas au profil et à la règle évalués.');
  }
  return {
    ...evidence, pullRequest, ticket: taskDetails(brief.request).ticket,
    briefSha256: sha256(bytes),
  };
}
