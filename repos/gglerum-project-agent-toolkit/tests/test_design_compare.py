import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'design-compare' / 'compare.py'


def load():
    spec = importlib.util.spec_from_file_location('design_compare_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.configure(None)
    return module


class PureFunctionTest(unittest.TestCase):
    def setUp(self):
        self.m = load()

    def test_colour_helpers(self):
        self.assertEqual((255, 0, 128, 1.0), self.m.parse_rgb('rgb(255, 0, 128)'))
        self.assertEqual((1, 2, 3, 0.5), self.m.parse_rgb('rgba(1, 2, 3, 0.5)'))
        self.assertIsNone(self.m.parse_rgb('transparent'))
        self.assertTrue(self.m.close((10, 10, 10), (14, 12, 10)))
        self.assertFalse(self.m.close((10, 10, 10), (30, 10, 10)))
        self.assertEqual('#0a0b0c', self.m.hexc((10, 11, 12)))

    def test_target_urls(self):
        self.assertEqual('http://127.0.0.1:8001/prototypes/x.html', self.m.url_of('/prototypes/x.html'))
        self.assertEqual('http://127.0.0.1:8001/auth/home', self.m.url_of('auth:/home'))
        self.assertEqual('http://127.0.0.1:8001/anon/login', self.m.url_of('anon:login'))
        self.assertEqual('https://example.test/a', self.m.url_of('https://example.test/a'))

    def test_text_rows_ok_diff_missing_and_wording(self):
        spec = {'lines': [
            {'text': 'Sign in', 'x': 20, 'y': 100, 'w': 60, 'h': 20},
            {'text': 'Forgot password', 'x': 20, 'y': 200, 'w': 100, 'h': 20},
            {'text': 'Create account', 'x': 20, 'y': 300, 'w': 100, 'h': 20},
            {'text': 'Welcome back', 'x': 20, 'y': 50, 'w': 100, 'h': 20},
        ], 'rects': []}
        line = lambda x, y: [{'x': x, 'y': y, 'w': 60, 'h': 20}]
        meas = {'els': [], 'texts': [
            {'t': 'Sign in', 'ff': 'Sans', 'fs': '16px', 'lines': line(22, 102)},
            {'t': 'Forgot password', 'ff': 'Sans', 'fs': '16px', 'lines': line(20, 230)},
            {'t': 'Welcome back, friend of the shop', 'ff': 'Sans', 'fs': '16px', 'lines': line(300, 400)},
        ]}
        rows = {r[2]: r for r in self.m.compare_data(spec, meas)}
        self.assertEqual('OK', rows['Sign in'][1])
        self.assertEqual('DIFF', rows['Forgot password'][1])
        self.assertIn('dy=+30', rows['Forgot password'][3])
        self.assertEqual('MISSING', rows['Create account'][1])
        self.assertEqual('DIFF', rows['Welcome back'][1])

    def test_box_rows(self):
        spec = {'lines': [], 'rects': [
            {'x': 20, 'y': 400, 'w': 350, 'h': 48, 'fill': (255, 0, 0)},
            {'x': 20, 'y': 600, 'w': 350, 'h': 48, 'fill': (0, 255, 0)},
        ]}
        meas = {'texts': [], 'els': [
            {'tag': 'button', 'cls': 'primary', 'id': '', 'type': '', 'x': 20, 'y': 402, 'w': 350, 'h': 48, 'bg': 'rgb(255, 0, 0)'},
        ]}
        rows = self.m.compare_data(spec, meas)
        by_label = {r[2]: r for r in rows}
        self.assertEqual('OK', by_label['box #ff0000 350x48'][1])
        self.assertEqual('MISSING', by_label['box #00ff00 350x48'][1])

    def test_words_are_grouped_into_lines_and_background_rect_is_skipped(self):
        words = [(10, 100, 40, 112, 'Hello'), (44, 100, 80, 112, 'world'), (10, 160, 50, 172, 'Next')]
        lines = self.m.group_lines(words)
        self.assertEqual(['Hello world', 'Next'], [l['text'] for l in lines])
        svg = ('<defs></defs><path d="M 0 0 L 393 0 L 393 852 L 0 852 Z" style="fill:rgb(100%,100%,100%)"/>'
               '<path d="M 20 400 L 370 400 L 370 448 L 20 448 Z" style="fill:rgb(100%,0%,0%)"/>')
        rects = self.m.svg_rects(svg)
        self.assertEqual(1, len(rects))
        self.assertEqual((255, 0, 0), rects[0]['fill'])


class BaselineTest(unittest.TestCase):
    def test_all_check_fails_only_when_worse_than_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'design').mkdir()
            (root / 'design/screens.json').write_text(json.dumps([{'name': 'login', 'design_page': 4, 'url': 'anon:/login', 'kind': 'app'}]))
            (root / 'design/baseline.json').write_text(json.dumps({'login': {'differ': 2, 'missing': 1}}))
            (root / 'c.json').write_text('{}')
            m = load()
            m.configure(str(root / 'c.json'))
            outcomes = iter([({'OK': 5, 'DIFF': 2, 'MISSING': 1, 'warn': ''}, root / 'r'), ({'OK': 5, 'DIFF': 3, 'MISSING': 1, 'warn': ''}, root / 'r'),
                             ({'OK': 5, 'DIFF': 0, 'MISSING': 0, 'warn': 'asked for /login but ended on /home'}, root / 'r')])
            m.compare_one = lambda name, page, target: next(outcomes)
            args = type('A', (), {'only': None, 'check': True, 'save_baseline': False, 'strict': False})()
            m.cmd_all(args)  # equal to baseline: passes
            with self.assertRaises(SystemExit) as worse:
                m.cmd_all(args)
            self.assertEqual(1, worse.exception.code)
            with self.assertRaises(SystemExit) as redirected:
                m.cmd_all(args)
            self.assertEqual(1, redirected.exception.code)

    def test_save_baseline_writes_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'design').mkdir()
            (root / 'design/screens.json').write_text(json.dumps([{'name': 'a', 'design_page': 1, 'url': '/a.html'}]))
            (root / 'c.json').write_text('{}')
            m = load()
            m.configure(str(root / 'c.json'))
            m.compare_one = lambda name, page, target: ({'OK': 1, 'DIFF': 4, 'MISSING': 2, 'warn': ''}, root / 'r')
            m.cmd_all(type('A', (), {'only': None, 'check': False, 'save_baseline': True, 'strict': False})())
            self.assertEqual({'a': {'differ': 4, 'missing': 2}}, json.loads((root / 'design/baseline.json').read_text()))


class CommandLineTest(unittest.TestCase):
    def test_help_and_missing_tools_report_exit_2(self):
        self.assertEqual(0, subprocess.run([sys.executable, '-B', '-I', str(SCRIPT), '--help'], capture_output=True).returncode)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'c.json').write_text(json.dumps({'poppler_prefix': ['no-such-poppler-wrapper']}))
            result = subprocess.run([sys.executable, '-B', '-I', str(SCRIPT), '--config', str(Path(tmp) / 'c.json'), 'render', '1'],
                                    capture_output=True, text=True)
            self.assertEqual(2, result.returncode)
            self.assertIn('not found', result.stderr)


if __name__ == '__main__':
    unittest.main()
