// Reads JSON like Python's openguildkit.storage.parse_json, so ci-check and the coordinator judge the same bytes:
// strict UTF-8 with an optional byte order mark, duplicate keys refused at any depth,
// and the NaN, Infinity and -Infinity constants that Python's json module accepts.
const decoder = new TextDecoder('utf-8', { fatal: true });
const whitespace = /[ \t\n\r]*/y;
const number = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][-+]?\d+)?/y;
const string = /"(?:[^"\\\u0000-\u001f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"/y;
const constants = [['true', true], ['false', false], ['null', null],
  ['NaN', NaN], ['Infinity', Infinity], ['-Infinity', -Infinity]];

function parseText(text) {
  let index = 0;
  const fail = message => {
    throw new SyntaxError(`${message} at position ${index}`);
  };
  const skip = () => {
    whitespace.lastIndex = index;
    whitespace.exec(text);
    index = whitespace.lastIndex;
  };
  const take = pattern => {
    pattern.lastIndex = index;
    const found = pattern.exec(text);
    if (!found) return null;
    index = pattern.lastIndex;
    return found[0];
  };
  const close = (end, label) => {
    skip();
    if (text[index] === ',') {
      index += 1;
      return false;
    }
    if (text[index] !== end) fail(`Expected ',' or '${end}' in ${label}`);
    index += 1;
    return true;
  };
  function value() {
    skip();
    if (text[index] === '{') {
      index += 1;
      const entries = [];
      const keys = new Set();
      skip();
      if (text[index] === '}') {
        index += 1;
        return {};
      }
      do {
        skip();
        const raw = take(string);
        if (raw === null) fail('Expected a property name');
        const key = JSON.parse(raw);
        if (keys.has(key)) fail(`Duplicate JSON key: ${key}`);
        keys.add(key);
        skip();
        if (text[index] !== ':') fail("Expected ':'");
        index += 1;
        entries.push([key, value()]);
      } while (!close('}', 'object'));
      // fromEntries defines own properties, so a "__proto__" key stays data.
      return Object.fromEntries(entries);
    }
    if (text[index] === '[') {
      index += 1;
      const items = [];
      skip();
      if (text[index] === ']') {
        index += 1;
        return items;
      }
      do items.push(value()); while (!close(']', 'array'));
      return items;
    }
    if (text[index] === '"') {
      const raw = take(string);
      if (raw === null) fail('Invalid string');
      return JSON.parse(raw);
    }
    for (const [word, result] of constants) {
      if (text.startsWith(word, index)) {
        index += word.length;
        return result;
      }
    }
    const literal = take(number);
    if (literal === null) fail('Expected a JSON value');
    return Number(literal);
  }
  const result = value();
  skip();
  if (index !== text.length) fail('Extra data');
  return result;
}

export function parseJson(content, label = 'JSON') {
  try {
    return parseText(decoder.decode(typeof content === 'string' ? Buffer.from(content, 'utf8') : content));
  } catch (error) {
    const reason = error instanceof RangeError ? 'nested too deeply' : error.message;
    throw new Error(`Invalid JSON in ${label}: ${reason}`, { cause: error });
  }
}

export function parseJsonObject(content, label = 'JSON') {
  const data = parseJson(content, label);
  if (data === null || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error(`Expected a JSON object in ${label}`);
  }
  return data;
}
