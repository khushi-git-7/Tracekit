// Runs each command form the way Qwen Code's hook runner does: spawn(ComSpec, ['/d','/s','/c',cmd], {shell:false}).
const { spawnSync } = require('node:child_process');
const py = process.argv[2];
const caret = py.replace(/ /g, '^ ');
const forms = {
  'quoted path, -m': `"${py}" -I -m platform`,
  'quoted path, quoted -c': `"${py}" -I -c "print('ok')"`,
  'caret, -m': `${caret} -I -m platform`,
  'caret, quoted -c': `${caret} -I -c "print('ok')"`,
  'call quoted, -m': `call "${py}" -I -m platform`,
  'PowerShell ampersand, -m': `& "${py}" -I -m platform`,
};
for (const [name, cmd] of Object.entries(forms)) {
  const r = spawnSync(process.env.ComSpec || 'cmd.exe', ['/d', '/s', '/c', cmd], { input: '', encoding: 'utf8' });
  console.log(`[${name}] exit=${r.status}\n  cmd: ${cmd}\n  out: ${r.stdout.trim().slice(0, 120)}\n  err: ${r.stderr.trim().slice(0, 200)}`);
}
