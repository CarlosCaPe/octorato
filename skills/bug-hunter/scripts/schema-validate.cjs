#!/usr/bin/env node

const path = require('path');

const {
  getKnownArtifacts,
  validateArtifactFile
} = require('./schema-runtime.cjs');

function usage() {
  console.error('Usage:');
  console.error('  schema-validate.cjs <artifact-name> <file-path>');
  console.error('');
  console.error(`Artifacts: ${getKnownArtifacts().join(', ')}`);
}

function main() {
  const [artifactName, targetPath] = process.argv.slice(2);
  if (!artifactName || !targetPath) {
    usage();
    process.exit(1);
  }

  const result = validateArtifactFile({
    artifactName,
    filePath: path.resolve(targetPath)
  });
  console.log(JSON.stringify(result));
  if (!result.ok) {
    process.exit(1);
  }
}

try {
  main();
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  console.error(message);
  process.exit(1);
}
