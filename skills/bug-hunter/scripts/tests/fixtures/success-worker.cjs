#!/usr/bin/env node

const fs = require('fs');

function parseArgs(argv) {
  const options = {};
  let index = 0;
  while (index < argv.length) {
    const token = argv[index];
    if (!token.startsWith('--')) {
      index += 1;
      continue;
    }
    const key = token.slice(2);
    const value = argv[index + 1];
    if (!value || value.startsWith('--')) {
      options[key] = 'true';
      index += 1;
      continue;
    }
    options[key] = value;
    index += 2;
  }
  return options;
}

const options = parseArgs(process.argv.slice(2));
const findingsJson = options['findings-json'];
if (!findingsJson) {
  process.exit(0);
}

const payload = [
  {
    bugId: `BUG-${options['chunk-id'] || '0'}`,
    severity: 'Low',
    category: 'logic',
    file: 'src/example.ts',
    lines: '1',
    claim: 'example',
    evidence: 'src/example.ts:1 example evidence',
    runtimeTrigger: 'Run the success worker fixture',
    crossReferences: ['Single file'],
    confidenceScore: 80
  }
];
fs.writeFileSync(findingsJson, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
