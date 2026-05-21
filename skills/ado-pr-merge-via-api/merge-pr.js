#!/usr/bin/env node
/**
 * merge-pr.js — generic ADO Pull Request merge via REST API.
 *
 * Implements the full sequence documented in SKILL.md:
 *  1. Verify mergeStatus + capture lastMergeSourceCommit
 *  2. Optionally set reviewer vote to approve
 *  3. Optionally close open threads owned by the merger
 *  4. Complete the PR with chosen merge strategy
 *  5. On 403 from policy gate: diagnose and surface the specific failure
 *
 * Usage:
 *   node merge-pr.js \
 *     --org <ado-org> \
 *     --project <project-name> \
 *     --repo-id <repo-guid> \
 *     --pr-id <pr-number> \
 *     --pat-env-var ADO_PAT \
 *     [--vote 10] \
 *     [--close-threads-i-own] \
 *     [--strategy noFastForward|squash|rebase] \
 *     [--delete-source-branch] \
 *     [--bypass-policy --bypass-reason "..."] \
 *     [--dry-run]
 *
 * Exit codes:
 *   0  merge completed
 *   1  argument error
 *   2  HTTP error (with diagnosed cause printed)
 *   3  dry-run finished without performing the merge
 */
const https = require('https');

function parseArgs() {
  const args = process.argv.slice(2);
  const out = {};
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (!a.startsWith('--')) continue;
    const key = a.slice(2);
    const next = args[i + 1];
    if (!next || next.startsWith('--')) {
      out[key] = true;  // flag
    } else {
      out[key] = next;
      i++;
    }
  }
  return out;
}

function buildAuth(pat) {
  return 'Basic ' + Buffer.from(':' + pat).toString('base64');
}

function request(method, host, path, auth, body) {
  return new Promise((res, rej) => {
    const data = body ? JSON.stringify(body) : null;
    const headers = {
      Authorization: auth,
      Accept: 'application/json',
    };
    if (data) {
      headers['Content-Type'] = 'application/json';
      headers['Content-Length'] = Buffer.byteLength(data);
    }
    const req = https.request({ host, path, method, headers }, r => {
      let d = '';
      r.on('data', c => (d += c));
      r.on('end', () => {
        let parsed;
        try { parsed = JSON.parse(d); } catch { parsed = d; }
        if (r.statusCode < 200 || r.statusCode >= 300) {
          const err = new Error(`${method} ${path} -> ${r.statusCode}`);
          err.statusCode = r.statusCode;
          err.body = parsed;
          return rej(err);
        }
        res(parsed);
      });
    });
    req.on('error', rej);
    if (data) req.write(data);
    req.end();
  });
}

function diagnosePolicyError(body) {
  const msg = (body && body.message) || '';
  if (msg.includes('comments in this pull request have to be addressed')) {
    return 'unresolved-threads';
  }
  if (msg.includes('reviewers reject')) {
    return 'reviewer-rejected';
  }
  if (msg.includes('Continuous Integration') && msg.includes('must succeed')) {
    return 'ci-policy-stale';
  }
  return 'unknown';
}

async function getPR(org, project, repoId, prId, auth) {
  return request('GET', 'dev.azure.com',
    `/${org}/${project}/_apis/git/repositories/${repoId}/pullRequests/${prId}?api-version=7.1`,
    auth);
}

async function setVote(org, project, repoId, prId, userId, vote, auth) {
  return request('PUT', 'dev.azure.com',
    `/${org}/${project}/_apis/git/repositories/${repoId}/pullRequests/${prId}/reviewers/${userId}?api-version=7.1`,
    auth, { vote, id: userId });
}

async function getThreads(org, project, repoId, prId, auth) {
  return request('GET', 'dev.azure.com',
    `/${org}/${project}/_apis/git/repositories/${repoId}/pullRequests/${prId}/threads?api-version=7.1`,
    auth);
}

async function setThreadStatus(org, project, repoId, prId, threadId, status, auth) {
  return request('PATCH', 'dev.azure.com',
    `/${org}/${project}/_apis/git/repositories/${repoId}/pullRequests/${prId}/threads/${threadId}?api-version=7.1`,
    auth, { status });
}

async function completePR(org, project, repoId, prId, body, auth) {
  return request('PATCH', 'dev.azure.com',
    `/${org}/${project}/_apis/git/repositories/${repoId}/pullRequests/${prId}?api-version=7.1`,
    auth, body);
}

(async () => {
  const args = parseArgs();
  const required = ['org', 'project', 'repo-id', 'pr-id'];
  for (const k of required) {
    if (!args[k]) {
      console.error(`Missing --${k}`);
      process.exit(1);
    }
  }
  const patVar = args['pat-env-var'] || 'ADO_PAT';
  const pat = process.env[patVar];
  if (!pat) {
    console.error(`PAT env var ${patVar} is not set`);
    process.exit(1);
  }
  const auth = buildAuth(pat);
  const { org, project } = args;
  const repoId = args['repo-id'];
  const prId = args['pr-id'];

  const pr = await getPR(org, project, repoId, prId, auth);
  console.log(`PR #${prId}: ${pr.title}`);
  console.log(`  status=${pr.status}  mergeStatus=${pr.mergeStatus}`);
  console.log(`  tip=${pr.lastMergeSourceCommit && pr.lastMergeSourceCommit.commitId.slice(0, 9)}`);

  if (pr.status === 'completed') {
    console.log('Already completed. Nothing to do.');
    return;
  }
  if (pr.mergeStatus !== 'succeeded') {
    console.error(`Cannot merge: mergeStatus is "${pr.mergeStatus}". Resolve conflicts first.`);
    process.exit(2);
  }

  if (args.vote) {
    const me = (pr.reviewers || []).find(r => r.uniqueName && r.uniqueName.toLowerCase().includes(
      (process.env.ADO_USER || '').toLowerCase()
    )) || (pr.reviewers || [])[0];
    if (me) {
      console.log(`Setting vote=${args.vote} for ${me.displayName}`);
      if (!args['dry-run']) {
        await setVote(org, project, repoId, prId, me.id, Number(args.vote), auth);
      }
    } else {
      console.warn('Could not identify "me" in reviewers list; skipping vote update.');
    }
  }

  if (args['close-threads-i-own']) {
    const t = await getThreads(org, project, repoId, prId, auth);
    const myThreads = (t.value || []).filter(th => {
      if (th.status !== 'active') return false;
      const text = (th.comments || []).find(c => c.commentType === 'text' || c.commentType === 1);
      if (!text) return false;
      const author = text.author && text.author.uniqueName;
      return author && author.toLowerCase().includes((process.env.ADO_USER || '').toLowerCase());
    });
    for (const th of myThreads) {
      console.log(`Closing thread ${th.id} (status: fixed)`);
      if (!args['dry-run']) {
        await setThreadStatus(org, project, repoId, prId, th.id, 'fixed', auth);
      }
    }
  }

  const completionOptions = {
    mergeStrategy: args.strategy || 'noFastForward',
    deleteSourceBranch: !!args['delete-source-branch'],
    bypassPolicy: !!args['bypass-policy'],
  };
  if (args['bypass-policy'] && args['bypass-reason']) {
    completionOptions.bypassReason = args['bypass-reason'];
  }

  console.log('Completion options:', completionOptions);
  if (args['dry-run']) {
    console.log('DRY RUN — no PATCH performed.');
    process.exit(3);
  }

  try {
    const result = await completePR(org, project, repoId, prId, {
      status: 'completed',
      lastMergeSourceCommit: { commitId: pr.lastMergeSourceCommit.commitId },
      completionOptions,
    }, auth);
    console.log(`OK status=${result.status}  mergeStatus=${result.mergeStatus}`);
    if (result.lastMergeCommit) {
      console.log(`Merge commit: ${result.lastMergeCommit.commitId}`);
    }
  } catch (e) {
    if (e.statusCode === 403) {
      const cause = diagnosePolicyError(e.body);
      console.error(`Policy gate rejected (${cause}):`);
      console.error('  ' + (e.body && e.body.message || JSON.stringify(e.body).slice(0, 300)));
      console.error('');
      switch (cause) {
        case 'unresolved-threads':
          console.error('  → Pass --close-threads-i-own, or manually close threads in the UI.');
          break;
        case 'reviewer-rejected':
          console.error('  → Inspect reviewers; ask blockers to vote or update --vote.');
          break;
        case 'ci-policy-stale':
          console.error('  → Re-queue the policy build from the PR UI, or add --bypass-policy');
          console.error('     (requires PAT "Code: manage" scope AND repo-level "Bypass policies" permission).');
          break;
        default:
          console.error('  → See SKILL.md for diagnosis steps.');
      }
    } else {
      console.error('Unexpected error:', e.message);
      if (e.body) console.error(JSON.stringify(e.body).slice(0, 500));
    }
    process.exit(2);
  }
})();
