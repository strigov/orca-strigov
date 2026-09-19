// Claude exec-form hook adapter: native PowerShell on Windows, Python on POSIX.
// Never launches an agent, changes settings or interprets paths through a shell.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

function invocation(platform = process.platform, root = __dirname) {
  return platform === 'win32'
    ? ['powershell.exe', ['-NoProfile', '-NonInteractive', '-File',
        path.join(root, 'coordinator-session.ps1'), 'hook', '--host', 'claude']]
    : ['python3', [path.join(root, 'lib', 'coordinator_session.py'), 'hook', '--host', 'claude']];
}

function hasBinding(payload) {
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(payload.session_id || '')
      || typeof payload.cwd !== 'string' || !path.isAbsolute(payload.cwd)) return false;
  let directory = path.resolve(payload.cwd);
  // Stop at the nearest Git boundary; never borrow a parent worktree's binding.
  for (let depth = 0; depth < 128; depth++) {
    if (fs.existsSync(path.join(directory, '.git'))) {
      try {
        fs.lstatSync(path.join(directory, '.superpowers', 'sdd', '.sessions', 'claude', payload.session_id + '.json'));
        return true; // A corrupt/linked binding still needs recovery, not a bypass.
      } catch (error) {
        return error.code !== 'ENOENT';
      }
    }
    const parent = path.dirname(directory);
    if (parent === directory) return false;
    directory = parent;
  }
  return false;
}

function failure(event, bound = false, tool = '', detail = 'native runtime failed') {
  const message = 'Orca coordinator guard unavailable (' + detail + '). Check the native runtime; do not claim coordinator completion.';
  if (bound && event === 'Stop') return {decision: 'block', reason: message};
  if (bound && event === 'PreToolUse' && ['apply_patch', 'Edit', 'Write', 'NotebookEdit'].includes(tool)) return {hookSpecificOutput: {
    hookEventName: event, permissionDecision: 'deny', permissionDecisionReason: message}};
  return {systemMessage: message};
}

function main() {
  const input = fs.readFileSync(0);
  let payload = {};
  try {
    payload = JSON.parse(input);
    if (process.env.ORCA_STRIGOV_WORKER === '1' || payload.agent_id
        || ['SubagentStart', 'SubagentStop'].includes(payload.hook_event_name)) {
      process.stdout.write('{}\n');
      return;
    }
    const [command, args] = invocation();
    const result = spawnSync(command, args, {input, timeout: 25000, maxBuffer: 1024 * 1024,
      windowsHide: true, shell: false});
    if (result.error) throw new Error(result.error.code || 'native launch failed');
    if (result.status !== 0) throw new Error('native exit ' + result.status);
    const output = JSON.parse(result.stdout.toString('utf8').replace(/^\uFEFF/, ''));
    process.stdout.write(JSON.stringify(output) + '\n');
  } catch (error) {
    payload = payload && typeof payload === 'object' ? payload : {};
    process.stdout.write(JSON.stringify(failure(payload.hook_event_name, hasBinding(payload),
      payload.tool_name, String(error.message).slice(0, 160))) + '\n');
  }
}

module.exports = {invocation, failure, hasBinding};
if (require.main === module) main();
