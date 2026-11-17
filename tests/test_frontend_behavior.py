"""前端行为测试：用 Node vm 真实执行 shared.js / demo-data.js，验证交互逻辑。

这些是行为断言（输入 -> 输出），补充 test_core.py 里大量脆弱的源码文本断言。
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FE = ROOT / 'custom_components' / 'workday_maintenance' / 'frontend'


def node_available() -> bool:
    return shutil.which('node') is not None


@unittest.skipUnless(node_available(), 'node 不可用')
class TestFrontendBehavior(unittest.TestCase):
    def run_node(self, script: str) -> str:
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                         encoding='utf-8') as f:
            f.write(script)
            path = f.name
        try:
            r = subprocess.run([shutil.which('node'), path],
                               capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                self.fail('node 执行失败：' + r.stderr[:500])
            return r.stdout
        finally:
            pathlib.Path(path).unlink(missing_ok=True)

    def _env_setup(self, pathname='C:/preview/workday.html'):
        tpl = '''
            const fs=require('fs'),vm=require('vm');
            const DIR=__DIR__;
            const shared=fs.readFileSync(DIR+'/shared.js','utf8');
            const demo=fs.readFileSync(DIR+'/demo-data.js','utf8');
            const el={hidden:true,textContent:'',className:'msg',style:{},value:'',
                        addEventListener:()=>{},getBoundingClientRect:()=>({left:0,top:0,bottom:0,right:0})};
            const doc={getElementById:()=>el,addEventListener:()=>{},
                        querySelectorAll:()=>[],querySelector:()=>null,
                        createElement:()=>({click:()=>{},style:{}}),
                        body:{appendChild:()=>{},removeChild:()=>{}}};
            const w={};w.window=w;w.location={protocol:'file:',pathname:__PATH__};
            w.localStorage={getItem:()=>null};w.document=doc;w.addEventListener=()=>{};
            w.fetch=()=>Promise.reject(new Error('no fetch'));
            const sb={Promise,Date,Math,JSON,Number,String,Array,Object,
                        setTimeout:(f)=>f(),clearTimeout:()=>{},console};
            sb.window=w;sb.location=w.location;sb.localStorage=w.localStorage;sb.document=doc;
            vm.createContext(sb);vm.runInContext(shared,sb);vm.runInContext(demo,sb);
        '''
        tpl = tpl.replace('__DIR__', repr(str(FE).replace(chr(92), '/')))
        tpl = tpl.replace('__PATH__', repr(pathname))
        return textwrap.dedent(tpl)

    def test_shared_helpers_exist(self):
        script = self._env_setup() + '''
            const M=w.MW;
            console.log(['bindDateFields','createLoader','createArmDel'].every(k=>typeof M[k]==='function')?'OK':'FAIL');
        '''
        self.assertIn('OK', self.run_node(script))

    def test_create_loader_loads_demo_data(self):
        """createLoader 真实走 demo 覆盖层取数并触发 render。"""
        script = self._env_setup() + '''
            (async()=>{
              const M=w.MW;
              const ld=M.createLoader({
                validate:d=>!!(d&&d.workday),
                onData:d=>{sb.GOT=d.today;},
                render:()=>{sb.RENDERED=true;}
              });
              await ld.load();
              console.log(sb.GOT&&sb.RENDERED?'OK':'FAIL');
            })().catch(e=>console.log('ERR '+e.message));
        '''
        out = self.run_node(script)
        self.assertIn('OK', out)

    def test_create_arm_del_two_step_confirm(self):
        script = self._env_setup() + '''
            const g=w.MW.createArmDel();
            const r1=g.arm('x')===false && g.peek('x');
            const r2=g.arm('x')===true && !g.peek('x');
            g.arm('y');g.reset();
            console.log(r1&&r2&&!g.peek('y')?'OK':'FAIL');
        '''
        self.assertIn('OK', self.run_node(script))

    def test_demo_snapshot_has_full_data(self):
        script = self._env_setup() + '''
            (async()=>{
              const s=await w.MW.snapshot();
              console.log(s.today&&s.workday&&s.maintenance&&s.maintenance.projects?'OK':'FAIL');
            })().catch(e=>console.log('ERR '+e.message));
        '''
        self.assertIn('OK', self.run_node(script))

    def test_import_export_roundtrip(self):
        """导出 -> 导入 -> 数据一致（含小项 id 与 history）。"""
        script = self._env_setup() + '''
            (async()=>{
              const M=w.MW;
              const seed='[{"name":"测试车","slug":"test_car","counter":100,'+
                '"items":[{"id":"i_oil","name":"机油","interval_days":365,'+
                '"last_date":"2026-11-01","last_counter":0}],'+
                '"history":[{"id":"r_oil","date":"2026-11-01","counter":0,'+
                '"entries":[{"item_id":"i_oil","note":"4S店"}]}]}]';
              await M.call('import_projects',{json:seed},true);
              const exp=(await M.call('export_all',{},true)).service_response.json;
              const parsed=JSON.parse(exp);
              const projects = parsed.maintenance ? parsed.maintenance.projects : parsed.projects;
              const p=projects.find(x=>x.slug==='test_car');
              const ok=p&&p.items[0].id==='i_oil'&&p.history[0].id==='r_oil'&&
                       p.history[0].entries[0].note==='4S店'&&p.counter===100;
              console.log(ok?'OK':'FAIL');
            })().catch(e=>console.log('ERR '+e.message));
        '''
        self.assertIn('OK', self.run_node(script))

    def test_zero_counter_not_due(self):
        """里程基准 0 不误报到期（与后端行为一致）。"""
        script = self._env_setup() + '''
            (async()=>{
              const M=w.MW;
              const seed='[{"name":"车","slug":"z","counter":43000,'+
                '"items":[{"id":"i1","name":"机油","interval_days":365,'+
                '"interval_counter":10000,"last_date":"2026-11-01","last_counter":0}]}]';
              await M.call('import_projects',{json:seed},true);
              const s=await M.snapshot();
              const sm=s.maintenance.summaries.find(x=>x.slug==='z');
              console.log(sm.items[0].status==='ok'?'OK':'FAIL '+sm.items[0].status);
            })().catch(e=>console.log('ERR '+e.message));
        '''
        self.assertIn('OK', self.run_node(script))

    def test_full_archive_v2_roundtrip(self):
        """v2 完整存档：导出含 workday+maintenance+说明，改后导入完整恢复。"""
        script = self._env_setup() + '''
            (async()=>{
              const M=w.MW;
              const d=JSON.parse((await M.call('export_all',{},true)).service_response.json);
              const shape = d.version===2 && d._说明 && d.workday && d.maintenance &&
                            Array.isArray(d.workday.todos) && Array.isArray(d.maintenance.projects);
              if(!shape){console.log('FAIL shape');return;}
              d.workday.todos[0].text='【AI改】测试待办';
              d.maintenance.projects[0].counter=99999;
              const slug=d.maintenance.projects[0].slug;
              await M.call('delete_project',{slug},true);
              const r=(await M.call('import_projects',{json:JSON.stringify(d)},true)).service_response||{};
              const s=await M.snapshot();
              const p=s.maintenance.projects.find(x=>x.slug===slug);
              const ok = r.workday_restored && s.workday.todos[0].text==='【AI改】测试待办' &&
                         p && p.counter===99999 && p.items.length>0 && p.history.length>0;
              console.log(ok?'OK':'FAIL');
            })().catch(e=>console.log('ERR '+e.message));
        '''
        self.assertIn('OK', self.run_node(script))


if __name__ == '__main__':
    unittest.main()
