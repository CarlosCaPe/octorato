#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

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

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function writeJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

const options = parseArgs(process.argv.slice(2));
const scanFilesJson = options['scan-files-json'];
const findingsJson = options['findings-json'];
const factsJson = options['facts-json'];
const seenFilesPath = options['seen-files'];
const chunkId = options['chunk-id'] || 'chunk';
const confidence = Number.parseInt(String(options.confidence || '60'), 10);

const scanFiles = scanFilesJson ? readJson(scanFilesJson) : [];
if (seenFilesPath) {
  const current = fs.existsSync(seenFilesPath) ? readJson(seenFilesPath) : [];
  const merged = [...new Set([...current, ...scanFiles])];
  writeJson(seenFilesPath, merged);
}

if (findingsJson && scanFiles.length > 0) {
  writeJson(findingsJson, [
    {
      bugId: `BUG-${chunkId}`,
      severity: 'Critical',
      category: 'security',
      file: scanFiles[0],
      lines: '1',
      claim: `Low-confidence risk in ${path.basename(scanFiles[0])}`,
      evidence: `${scanFiles[0]}:1 fixture evidence`,
      runtimeTrigger: `Load ${path.basename(scanFiles[0])} through the low-confidence worker`,
      crossReferences: ['Single file'],
      confidenceScore: Number.isInteger(confidence) ? confidence : 60,
      stride: 'Tampering',
      cwe: 'CWE-20'
    }
  ]);
}

if (factsJson) {
  writeJson(factsJson, {
    apiContracts: scanFiles.map((filePath) => {
      return `${path.basename(filePath)} contract`;
    }),
    authAssumptions: ['Auth decisions must remain explicit'],
    invariants: [`Chunk ${chunkId} invariants captured`]
  });
}
