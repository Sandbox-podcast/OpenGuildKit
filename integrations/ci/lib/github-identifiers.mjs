export function sameRepository(actual, expected) {
  return typeof actual === 'string' && typeof expected === 'string' &&
    actual.toLowerCase() === expected.toLowerCase();
}

const repositoryUrl = /^https:\/\/github\.com\/([\w.-]+\/[\w.-]+)(\/.*)$/;

export function sameRepositoryUrl(actual, expected) {
  const left = typeof actual === 'string' && repositoryUrl.exec(actual);
  const right = typeof expected === 'string' && repositoryUrl.exec(expected);
  return Boolean(left && right && sameRepository(left[1], right[1]) && left[2] === right[2]);
}
