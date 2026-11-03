#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""
Behavior tests for cc-probe.py

Run: uv run test_cc_probe.py
"""

import http.server
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('cc_probe', HERE / 'cc-probe.py')
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)


# A stand-in for claude: logs its argv and a few env vars, builds a request shaped like
# Claude Code 2.1.311's first request from its flags and env, and POSTs it to
# $ANTHROPIC_BASE_URL. Like the real CLI, only the last --settings counts.
FAKE_CLAUDE = """\
#!{python}
import json, os, sys, urllib.error, urllib.request

args = sys.argv[1:]
env = os.environ
watched = ['ANTHROPIC_BASE_URL', 'CLAUDE_CODE_ARTIFACT', 'CLAUDE_CODE_DISABLE_ARTIFACT', 'HERDR_PANE_ID', 'FOO_VIA']
with open(env['FAKE_CLAUDE_LOG'], 'a') as f:
    f.write(json.dumps({{'args': args, 'cwd': os.getcwd(), 'env': {{k: env.get(k) for k in watched}}}}) + '\\n')
if env.get('FAKE_NO_REQUEST'):
    print('Not logged in · Please run /login', file=sys.stderr)
    sys.exit(1)

settings = {{}}
for i, a in enumerate(args):
    if a == '--settings':
        settings = json.loads(args[i + 1])
strict = '--strict-mcp-config' in args
artifact = env.get('CLAUDE_CODE_DISABLE_ARTIFACT', '') in ('', '0')
ai_skills = settings.get('syncClaudeAiSkills') is not False
git = settings.get('includeGitInstructions') is not False

def tool(name, desc='A tool.'):
    return {{'name': name, 'description': desc, 'input_schema': {{'type': 'object', 'properties': {{}}}}}}

tools = [tool('Agent'), tool('Bash', 'Run shell commands. ' * 20), tool('Read'), tool('Skill'), tool('ToolSearch')]
if artifact:
    tools.append(tool('Artifact', 'Publish a page. ' * 200))
if not strict:
    tools.append(tool('mcp__ctx__query', 'Query docs.'))

instructions = (
    '<system-reminder>\\nCodebase and user instructions are shown below. Be sure to adhere to these instructions.\\n\\n'
    "Contents of /home/u/.claude/CLAUDE.md (user's private global instructions for all projects):\\n\\n# Rules\\nBe nice.\\n\\n"
    'Contents of /proj/AGENTS.md (project instructions, checked into the codebase):\\n\\n# Proj\\nStuff.\\n</system-reminder>'
)
context = "<system-reminder>\\nAs you answer the user's questions, you can use the following context:\\n# userEmail\\nme@example.com\\n"
if git:
    context += '# gitStatus\\nCurrent branch: master\\n\\nStatus:\\nM a.txt\\n'
context += '</system-reminder>'
blocks = [instructions, context]
if git:
    blocks.append('<system-reminder>\\nAttribution for git commits you create:\\n- End git commit messages with:\\nCo-Authored-By: Claude\\n</system-reminder>')
blocks.append('say ok')

deferred = ['CronCreate', 'WebFetch'] + ([] if strict else ['mcp__ctx__resolve'])
skills = ['- loop: Run a prompt on an interval.', '- kb: Manage the kb.', '- feature-dev:feature-dev: Guided feature dev.']
if ai_skills:
    skills.append('- anthropic-skills:docx: Word documents. ' + 'x' * 300)
# Same order as 2.1.311: environment, deferred names, agents, MCP instructions, skills, loose paragraphs
listing = (
    '# Environment\\nYou have been invoked in the following environment:\\n - Platform: darwin\\n\\n'
    'The following deferred tools are now available via ToolSearch. Use ToolSearch to load them:\\n' + '\\n'.join(deferred) + '\\n\\n'
    'Available agent types for the Agent tool:\\n- Explore: Read-only search agent. (Tools: Read)\\n'
    '- feature-dev:code-architect: Designs features. (Tools: Read)\\n\\n'
)
if not strict:
    listing += '# MCP Server Instructions\\n\\nThe following MCP servers have provided instructions:\\n\\n## ctx\\nUse ctx for docs.\\n\\nMore about ctx.\\n\\n'
listing += 'The following skills are available for use with the Skill tool:\\n\\n' + '\\n'.join(skills) + '\\n\\n'
listing += 'While bypass permissions mode is active:\\n\\nYou can do work through Bash.\\n\\nToday is 2026-11-03.'

req = {{
    'model': 'claude-opus-5-5',
    'max_tokens': 128000,
    'thinking': {{'type': 'adaptive', 'display': 'omitted'}},
    'output_config': {{'effort': 'xhigh'}},
    'metadata': {{'user_id': json.dumps({{'device_id': 'dev-123', 'account_uuid': 'acct-456'}})}},
    # bypass mode sends no permission_mode; only the "While ... mode is active" paragraph tells
    'safeguards': [] if '--dangerously-skip-permissions' in args else [{{'type': 'dangerous_tool_use', 'classifier_context': {{'permission_mode': 'auto'}}}}],
    'system': [
        {{'type': 'text', 'text': 'x-anthropic-billing-header: cc_version=9.9.9.abc; cc_entrypoint=sdk-cli;'}},
        {{'type': 'text', 'text': 'You are a Claude agent.'}},
        {{'type': 'text', 'text': '# Harness\\nFollow the rules.\\n\\n# Context management\\nSummaries happen.'}},
    ],
    'tools': tools,
    'messages': [
        {{'role': 'user', 'content': [{{'type': 'text', 'text': b}} for b in blocks]}},
        {{'role': 'system', 'content': [{{'type': 'text', 'text': listing}}]}},
    ],
    'stream': True,
}}
if settings.get('fastMode'):
    req['speed'] = 'fast'
headers = {{
    'content-type': 'application/json',
    'authorization': env.get('FAKE_AUTH', 'Bearer sk-ant-oat01-fake'),
    'anthropic-version': '2023-06-01',
    'user-agent': 'claude-cli/9.9.9 (external, sdk-cli)',
}}
url = env['ANTHROPIC_BASE_URL'] + '/v1/messages?beta=true'
try:
    urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(req).encode(), headers=headers))
except urllib.error.HTTPError:
    pass
print('API Error: 400 probe', file=sys.stderr)
sys.exit(1)
"""


class CountServer:
    """Fake count_tokens endpoint: one token per 4 characters of the request body."""

    def __init__(self):
        self.calls = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers['content-length']))
                server.calls.append({'path': self.path, 'headers': {k.lower(): v for k, v in self.headers.items()}})
                out = json.dumps({'input_tokens': len(body) // 4}).encode()
                self.send_response(200)
                self.send_header('content-type', 'application/json')
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}'

    def close(self):
        self.httpd.shutdown()


class ProbeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        bindir = self.tmp / 'bin'
        bindir.mkdir()
        fake = bindir / 'claude'
        fake.write_text(FAKE_CLAUDE.format(python=sys.executable))
        fake.chmod(0o755)
        self.log = self.tmp / 'claude.log'
        self.config = self.tmp / 'config'
        (self.config / 'skills' / 'kb').mkdir(parents=True)
        (self.config / 'skills' / 'kb' / 'SKILL.md').write_text('---\nname: kb\n---\n')
        (self.config / 'settings.json').write_text(
            json.dumps(
                {
                    'syncClaudeAiPlugins': False,
                    'includeGitInstructions': False,
                    'skillOverrides': {'loop': 'user-invocable-only'},
                    'env': {'SECRET_TOKEN': 'sk-should-never-print', 'CLAUDE_CODE_DISABLE_ARTIFACT': '1'},
                }
            )
        )
        self.count = CountServer()
        env = {
            'PATH': f'{bindir}{os.pathsep}{os.environ["PATH"]}',
            'FAKE_CLAUDE_LOG': str(self.log),
            'CLAUDE_CONFIG_DIR': str(self.config),
            'CC_PROBE_API_BASE': self.count.url,
            'HERDR_PANE_ID': 'pane-1',
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for k in ('CLAUDE_CODE_DISABLE_ARTIFACT', 'CLAUDE_CODE_ARTIFACT', 'FAKE_AUTH', 'FAKE_NO_REQUEST'):
            os.environ.pop(k, None)
        self.addCleanup(self.count.close)

    def run_probe(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cp.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def report(self, *argv):
        argv = list(argv)
        cut = argv.index('--') if '--' in argv else len(argv)
        code, out, err = self.run_probe(*argv[:cut], '--json', *argv[cut:])
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def claude_calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def item(self, report, kind, name):
        hits = [i for i in report['items'] if i['kind'] == kind and i['name'] == name]
        self.assertEqual(len(hits), 1, f'{kind} {name!r} in {[(i["kind"], i["name"]) for i in report["items"]]}')
        return hits[0]


class TestCapture(ProbeTestCase):
    def test_runs_claude_headless_against_a_local_server(self):
        report = self.report('--count', 'offline')
        call = self.claude_calls()[0]
        self.assertTrue(call['env']['ANTHROPIC_BASE_URL'].startswith('http://127.0.0.1:'))
        self.assertIn('-p', call['args'])
        self.assertIn('--no-session-persistence', call['args'])
        self.assertEqual(report['state']['version'], '9.9.9')
        self.assertEqual(report['state']['model'], 'claude-opus-5-5')

    def test_strips_herdr_env_and_loads_artifact_like_an_interactive_session(self):
        self.report('--count', 'offline')
        self.report('--count', 'offline', '--headless')
        default, headless = self.claude_calls()
        self.assertIsNone(default['env']['HERDR_PANE_ID'])
        self.assertEqual(default['env']['CLAUDE_CODE_ARTIFACT'], '1')
        self.assertIsNone(headless['env']['CLAUDE_CODE_ARTIFACT'])

    def test_env_unset_and_cwd_reach_claude(self):
        os.environ['CLAUDE_CODE_DISABLE_ARTIFACT'] = '1'
        workdir = self.tmp / 'work'
        workdir.mkdir()
        self.report(
            '--count', 'offline', '--unset', 'CLAUDE_CODE_DISABLE_ARTIFACT', '--env', 'FOO_VIA=x', '--cwd', str(workdir)
        )
        call = self.claude_calls()[0]
        self.assertIsNone(call['env']['CLAUDE_CODE_DISABLE_ARTIFACT'])
        self.assertEqual(call['env']['FOO_VIA'], 'x')
        self.assertEqual(Path(call['cwd']).resolve(), workdir.resolve())

    def test_reports_why_capture_failed(self):
        os.environ['FAKE_NO_REQUEST'] = '1'
        code, out, err = self.run_probe('--count', 'offline')
        self.assertEqual(code, 2)
        self.assertIn('Not logged in', err)


class TestBreakdown(ProbeTestCase):
    def test_splits_the_request_into_named_items(self):
        report = self.report('--count', 'offline')
        self.item(report, 'system', 'Harness')
        self.item(report, 'system', 'Context management')
        self.item(report, 'tool', 'Bash')
        self.item(report, 'tool', 'Artifact')
        self.item(report, 'tool-mcp', 'mcp__ctx__query')
        self.item(report, 'instructions', '/home/u/.claude/CLAUDE.md')
        self.item(report, 'instructions', '/proj/AGENTS.md')
        self.item(report, 'context', 'gitStatus')
        self.item(report, 'context', 'Environment')
        self.item(report, 'agent', 'feature-dev:code-architect')
        # an MCP server's instructions run over several paragraphs, up to the skill listing
        self.assertGreaterEqual(
            self.item(report, 'mcp', 'ctx')['chars'], len('## ctx\nUse ctx for docs.\n\nMore about ctx.')
        )
        self.assertEqual(report['deferred'], ['CronCreate', 'WebFetch', 'mcp__ctx__resolve'])

    def test_trailing_paragraphs_do_not_count_as_the_last_skill(self):
        report = self.report('--count', 'offline')
        docx = self.item(report, 'skill', 'anthropic-skills:docx')
        self.assertLess(docx['chars'], 400)
        self.item(report, 'context', 'While bypass permissions mode is active:')

    def test_labels_each_skill_by_where_it_comes_from(self):
        report = self.report('--count', 'offline')
        sources = {i['name']: i['source'] for i in report['items'] if i['kind'] == 'skill'}
        self.assertEqual(sources['loop'], 'bundled')
        self.assertEqual(sources['kb'], 'user')
        self.assertEqual(sources['feature-dev:feature-dev'], 'plugin')
        self.assertEqual(sources['anthropic-skills:docx'], 'claude.ai')

    def test_item_sizes_add_up_to_the_request_text(self):
        report = self.report('--count', 'offline')
        self.assertEqual(sum(i['chars'] for i in report['items']), report['totals']['chars'])


class TestState(ProbeTestCase):
    def test_default_state(self):
        state = self.report('--count', 'offline')['state']
        self.assertTrue(state['artifact'])
        self.assertEqual(state['claude_ai_skills'], 1)
        self.assertTrue(state['git_snapshot'])
        self.assertTrue(state['git_attribution'])
        self.assertEqual(state['mcp_servers'], ['ctx'])
        self.assertEqual(state['effort'], 'xhigh')
        self.assertEqual(state['thinking'], 'adaptive')
        self.assertEqual(state['permission_mode'], 'auto')
        self.assertFalse(state['fast'])

    def test_switches_turned_off_show_up(self):
        os.environ['CLAUDE_CODE_DISABLE_ARTIFACT'] = '1'
        state = self.report(
            '--count',
            'offline',
            '--no-mcp',
            '--settings',
            '{"syncClaudeAiSkills": false, "includeGitInstructions": false, "fastMode": true}',
        )['state']
        self.assertFalse(state['artifact'])
        self.assertEqual(state['claude_ai_skills'], 0)
        self.assertFalse(state['git_snapshot'])
        self.assertFalse(state['git_attribution'])
        self.assertEqual(state['mcp_servers'], [])
        self.assertTrue(state['fast'])
        self.assertIn('--strict-mcp-config', self.claude_calls()[0]['args'])

    def test_bypass_mode_is_read_from_the_mode_paragraph(self):
        state = self.report('--count', 'offline', '--', '--dangerously-skip-permissions')['state']
        self.assertEqual(state['permission_mode'], 'bypass permissions')
        self.assertIn('--dangerously-skip-permissions', self.claude_calls()[0]['args'])

    def test_no_hooks_is_merged_into_the_one_settings_flag(self):
        self.report('--count', 'offline', '--settings', '{"a": 1}', '--no-hooks')
        args = self.claude_calls()[0]['args']
        self.assertEqual(args.count('--settings'), 1)
        self.assertEqual(json.loads(args[args.index('--settings') + 1]), {'a': 1, 'disableAllHooks': True})

    def test_reads_switches_from_user_settings_without_printing_other_env(self):
        code, out, err = self.run_probe('--count', 'offline')
        self.assertEqual(code, 0, err)
        report = self.report('--count', 'offline')
        self.assertEqual(report['settings']['syncClaudeAiPlugins'], False)
        self.assertEqual(report['settings']['skillOverrides'], {'loop': 'user-invocable-only'})
        self.assertEqual(report['settings']['env'], {'CLAUDE_CODE_DISABLE_ARTIFACT': '1'})
        self.assertNotIn('sk-should-never-print', out + json.dumps(report))


class TestVia(ProbeTestCase):
    def test_runs_through_a_zsh_function(self):
        rc = self.tmp / 'rc.zsh'
        rc.write_text("""mycl() { FOO_VIA=1 claude --settings '{"syncClaudeAiSkills": false}' "$@" }\n""")
        report = self.report('--count', 'offline', '--via', 'mycl', '--rc', str(rc))
        call = self.claude_calls()[0]
        self.assertEqual(call['env']['FOO_VIA'], '1')
        self.assertEqual(report['state']['claude_ai_skills'], 0)
        self.assertEqual(report['meta']['via'], 'mycl')


class TestCounting(ProbeTestCase):
    def test_total_comes_from_count_tokens_with_the_captured_login(self):
        report = self.report()
        self.assertEqual(report['totals']['counting'], 'count_tokens')
        self.assertEqual(len(self.count.calls), 1)
        call = self.count.calls[0]
        self.assertIn('/v1/messages/count_tokens', call['path'])
        self.assertEqual(call['headers']['authorization'], 'Bearer sk-ant-oat01-fake')
        self.assertGreater(report['totals']['tokens'], 0)

    def test_exact_mode_counts_each_item_by_removing_it(self):
        report = self.report('--count', 'exact')
        self.assertEqual(report['totals']['counting'], 'count_tokens (per item)')
        self.assertEqual(len(self.count.calls), 1 + len(report['items']))
        artifact = self.item(report, 'tool', 'Artifact')
        self.assertGreater(artifact['tokens'], 700)

    def test_never_sends_a_non_anthropic_credential(self):
        os.environ['FAKE_AUTH'] = 'Bearer glm-secret'
        report = self.report()
        self.assertEqual(self.count.calls, [])
        self.assertTrue(report['totals']['counting'].startswith('estimate'))

    def test_offline_mode_never_calls_the_api(self):
        report = self.report('--count', 'offline')
        self.assertEqual(self.count.calls, [])
        self.assertTrue(report['totals']['counting'].startswith('estimate'))


class TestSaveAndDiff(ProbeTestCase):
    def test_saved_capture_has_no_credentials_or_account_ids(self):
        path = self.tmp / 'a.json'
        self.report('--save', str(path))
        text = path.read_text()
        self.assertNotIn('sk-ant', text)
        self.assertNotIn('acct-456', text)
        self.assertIn('request', json.loads(text))

    def test_diff_lists_what_changed_between_two_captures(self):
        a, b = self.tmp / 'a.json', self.tmp / 'b.json'
        self.report('--count', 'offline', '--save', str(a))
        os.environ['CLAUDE_CODE_DISABLE_ARTIFACT'] = '1'
        self.report('--count', 'offline', '--save', str(b), '--settings', '{"syncClaudeAiSkills": false}')
        code, out, err = self.run_probe('diff', str(a), str(b))
        self.assertEqual(code, 0, err)
        self.assertIn('- tool Artifact', out)
        self.assertIn('- skill anthropic-skills:docx', out)
        self.assertIn('artifact: on -> off', out)
        diff = json.loads(self.run_probe('diff', str(a), str(b), '--json')[1])
        self.assertLess(diff['tokens_delta'], 0)


class TestExpectations(ProbeTestCase):
    def test_failed_expectation_exits_1_and_says_which(self):
        code, out, err = self.run_probe('--count', 'offline', '--expect-absent', 'Artifact')
        self.assertEqual(code, 1)
        self.assertIn('Artifact', err)

    def test_met_expectations_exit_0(self):
        code, out, err = self.run_probe(
            '--count',
            'offline',
            '--expect-present',
            'anthropic-skills:*',
            '--expect-absent',
            'searchfit-seo:*',
        )
        self.assertEqual(code, 0, err)

    def test_token_budget(self):
        code, out, err = self.run_probe('--count', 'offline', '--max-tokens', '10')
        self.assertEqual(code, 1)
        self.assertIn('10', err)


class TestHumanReport(ProbeTestCase):
    def test_plain_report_shows_state_and_largest_items(self):
        code, out, err = self.run_probe('--count', 'offline')
        self.assertEqual(code, 0, err)
        for text in ('Claude Code 9.9.9', 'claude-opus-5-5', 'Artifact', 'By kind', 'Largest items', 'skill/claude.ai'):
            self.assertIn(text, out)


if __name__ == '__main__':
    unittest.main()
