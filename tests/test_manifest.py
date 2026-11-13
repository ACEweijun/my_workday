"""仓库静态一致性检查（不依赖 HA）。"""
from __future__ import annotations

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CODE = ROOT if (ROOT / 'core.py').exists() else ROOT / 'custom_components' / 'my_workday'
WEB = CODE / 'frontend' / 'workday.html'


class TestRepo(unittest.TestCase):
    def test_manifest_required_fields(self):
        m = json.loads((CODE / 'manifest.json').read_text(encoding='utf-8'))
        for key in ('domain', 'name', 'version', 'config_flow', 'documentation',
                    'issue_tracker', 'codeowners', 'requirements', 'iot_class'):
            self.assertIn(key, m)
        self.assertEqual(m['domain'], 'my_workday')
        self.assertRegex(m['version'], r'^\d+\.\d+\.\d+$')
        self.assertTrue(m['config_flow'])

    def test_hacs_json(self):
        h = json.loads((ROOT / 'hacs.json').read_text(encoding='utf-8'))
        self.assertEqual(h['name'], 'my_workday')
        self.assertIn('homeassistant', h)

    def test_translations_are_valid_json(self):
        for f in (CODE / 'translations').glob('*.json'):
            json.loads(f.read_text(encoding='utf-8'))
        json.loads((CODE / 'strings.json').read_text(encoding='utf-8'))

    def test_services_match_const(self):
        const = (CODE / 'const.py').read_text(encoding='utf-8')
        declared = set(re.findall(r'SERVICE_[A-Z_]+\s*=\s*"([^"]+)"', const))
        services_yaml = (CODE / 'services.yaml').read_text(encoding='utf-8')
        defined = set(re.findall(r'^([a-z_]+):\s*$', services_yaml, re.M))
        self.assertEqual(declared, defined, f'服务不一致: {declared ^ defined}')

    def test_entity_ids_match_const(self):
        const = (CODE / 'const.py').read_text(encoding='utf-8')
        left = re.search(r'ENTITY_LEFT\s*=\s*"([^"]+)"', const).group(1)
        html = WEB.read_text(encoding='utf-8')
        self.assertIn(left, html)
        self.assertIn("/api/services/my_workday/", html)

    def test_no_old_project_names(self):
        for f in CODE.rglob('*'):
            if not f.is_file() or f.suffix not in {'.py', '.json', '.yaml', '.html'}:
                continue
            rel = f.relative_to(CODE)
            if rel.parts[0] in ('.github', 'tests') or rel.name in (
                    'README.md', 'hacs.json', 'LICENSE'):
                continue
            text = f.read_text(encoding='utf-8')
            for old in ('cn_workday', 'ha-cn-workday', '中国工作日', 'Chinese Workday'):
                self.assertNotIn(old, text, f'{f.name} 仍含旧名称 {old}')

    def test_frontend_has_no_debug_text_in_prod_path(self):
        html = WEB.read_text(encoding='utf-8')
        self.assertIn("var LOCAL = location.protocol === 'file:'", html)
        self.assertIn("LOCAL && P.get('demo')", html)
        self.assertNotIn('dataLine', html)
        self.assertNotIn("id=\"sub\"", html)


if __name__ == '__main__':
    unittest.main()
