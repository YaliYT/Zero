"""Compact inference retains exact verification, permission gates and durable results."""
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qwen_coding import CodingWorkspace, TOOLS
spec = importlib.util.spec_from_file_location('agent_compact_test', ROOT / 'Qwen-Agent.py')
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

class CompactProtocol(unittest.TestCase):
    def test_verified_write_keeps_checkpoint_and_requested_independent_read(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            base = Path(folder)
            project, root = base / 'project', base / 'agent'
            project.mkdir(); root.mkdir()
            (root / 'qwen-agent-settings.json').write_text(json.dumps({'agent_compact_protocol_enabled': True}))
            ws = CodingWorkspace(root, project, mode='acceptEdits')
            agent.WORKSPACE, agent.MEMORY_GUARD = ws, None
            sent = []
            def call(name, arguments):
                return {'role':'assistant', 'content':'', 'tool_calls':[{'function':{'name':name, 'arguments':arguments}}]}
            replies = iter([call('write_file', {'path':'hello.txt','content':'hello\n'}),
                            call('read_file', {'path':'hello.txt'}), {'role':'assistant','content':'done'}])
            def chat(messages):
                sent.append(json.loads(json.dumps(messages)))
                return next(replies)
            agent.chat_request = chat
            result = agent.agent_turn('Create and separately read hello.txt.', interactive=False)
            self.assertEqual((project/'hello.txt').read_bytes(), b'hello\n')
            self.assertEqual([item['name'] for item in result['tools']], ['write_file','read_file'])
            full = result['tools'][0]['result']
            self.assertTrue(full['verified'])
            self.assertIn('checkpoint', full)
            self.assertEqual(full['path'], str(project/'hello.txt'))
            compact = json.loads(next(m['content'] for m in sent[-1] if m.get('tool_name') == 'write_file'))
            self.assertTrue(compact['verified'])
            self.assertEqual(compact['path'], 'hello.txt')
            self.assertNotIn('checkpoint', compact)
            durable = json.loads((ws.state/'sessions'/(ws.session['id']+'.json')).read_text(encoding='utf-8'))
            self.assertEqual(durable['history'][-1]['tools'][0]['result'], full)
            self.assertEqual([t['function']['parameters'] for t in ws.tools()], [t['function']['parameters'] for t in TOOLS])
            error = {'ok':False,'error':'human approval required','path':str(project/'hello.txt')}
            self.assertEqual(ws.model_result('write_file', error), error)
            ws.mode = 'plan'
            self.assertEqual({t['function']['name'] for t in ws.tools()}, {'read_file','list_directory','search_files','update_tasks'})
            agent.WORKSPACE = None

if __name__ == '__main__':
    unittest.main(verbosity=2)
