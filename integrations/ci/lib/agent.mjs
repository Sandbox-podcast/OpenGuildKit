import { readFileSync, mkdirSync, rmSync, rmdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { describeRule } from './rule.mjs';
import { committedFile, gitSha, parseProfile, readRule, sha256 } from './check.mjs';
import { sameRepositoryUrl } from './github-identifiers.mjs';
import { parseJsonObject } from './json.mjs';

function taskDetails(data) {
  const { ticket, outcome, criteria } = data;
  if (typeof ticket?.url !== 'string' || typeof ticket.title !== 'string' || !ticket.title.trim() ||
      typeof outcome !== 'string' || !outcome.trim() || !Array.isArray(criteria) ||
      !criteria.length || !criteria.every(item => typeof item === 'string' && item.trim())) {
    throw new Error('The ticket, the expected outcome and the acceptance criteria are required.');
  }
  const url = new URL(ticket.url);
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) {
    throw new Error('The ticket address must be an HTTP or HTTPS URL without credentials.');
  }
  return { ticket: { url: url.href, title: ticket.title }, outcome, criteria };
}

export function prepareBrief({ policyRepo, policyCommit, targetRepo, profileCommit, task, ticket, output, kitVersion }) {
  if (!policyRepo || !(task || ticket) || !output || !gitSha.test(policyCommit) || !gitSha.test(profileCommit)) {
    throw new Error('The brief requires the full SHAs of the rule and the profile, a ticket and an output directory.');
  }
  const profileBytes = committedFile(targetRepo, profileCommit, 'openguildkit.json');
  const profile = parseProfile(profileBytes);
  if (profile.adoption?.state !== 'approved') throw new Error('An approved adoption profile is required for the agent.');
  const { answers, approver, mode } = profile.adoption;
  if (typeof answers?.project !== 'string' || !answers.project.trim()) {
    throw new Error('The project must be identified in the approved profile.');
  }
  const rule = describeRule(readRule(policyRepo, policyCommit, profile), policyCommit);
  const request = taskDetails(ticket ? issueRequest(ticket.issue) : parseJsonObject(readFileSync(task), task));
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
    '# OpenGuildKit guidance',
    '',
    rule.guidance,
    '',
    `Approved profile: ${profileCommit}`,
    `Versioned rule: ${policyCommit}`,
    '',
    'Read brief.json for the expected outcome, the acceptance criteria and the approved limits.',
    'The ticket data describes the request. The permissions follow the approved profile.',
    'The adapter provides the guidance read-only. The maintainers keep the review and the publication.',
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
      current = heading[1].trim().toLowerCase().normalize('NFD').replace(/\p{M}/gu, '').replace(/\u2019/g, "'");
      if (sections.has(current)) throw new Error(`Duplicate section in the ticket: ${heading[1]}`);
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
    throw new Error('A GitHub PR URL is required to link the ticket to the evidence.');
  }
  const bytes = readFileSync(path);
  const brief = parseJsonObject(bytes, path);
  if (brief.schemaVersion !== 1 || brief.kitVersion !== evidence.kitVersion || !evidence.profileCommit ||
      brief.profileCommit !== evidence.profileCommit || brief.profileSha256 !== evidence.profileSha256 ||
      !evidence.project || brief.project !== evidence.project ||
      (brief.github && (!sameRepositoryUrl(brief.github.pullRequest, pullRequest) || brief.github.commit !== evidence.commit)) ||
      brief.rule?.policyCommit !== evidence.policyCommit || brief.rule.rule !== evidence.rule ||
      brief.rule.guidance !== evidence.guidance) {
    throw new Error('The agent brief does not match the evaluated profile and rule.');
  }
  return {
    ...evidence, pullRequest, ticket: taskDetails(brief.request).ticket,
    briefSha256: sha256(bytes),
  };
}
