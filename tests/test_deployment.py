import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.deployment import dependency_issues, record_runtime

ROOT=Path(__file__).resolve().parents[1]


def test_deployment_flags_version_mismatch_and_missing_torch(tmp_path,monkeypatch):
    requirements=tmp_path/'requirements.txt'
    requirements.write_text('numpy==2.3.1\npydantic==2.13.5\n',encoding='utf-8')
    def version(name):
        if name=='torch':raise importlib.metadata.PackageNotFoundError(name)
        return {'numpy':'2.3.1','pydantic':'1.10.0'}[name]
    monkeypatch.setattr(importlib.metadata,'version',version)
    problems=dependency_issues(requirements)
    assert len(problems)==2 and any('pydantic' in p for p in problems) and any('torch' in p for p in problems)


def test_runtime_record_belongs_to_current_location(tmp_path):
    root=tmp_path/'同事 项目(迁移)';root.mkdir()
    record_runtime(root)
    record=json.loads((root/'.runtime/current.json').read_text(encoding='utf-8'))
    assert record['root']==str(root.resolve())
    assert record['python']==sys.executable
    assert (root/'.runtime/installed-packages.txt').stat().st_size>0


@pytest.mark.skipif(sys.platform!='win32',reason='Windows launcher')
def test_check_only_in_relocated_folder_does_not_install(tmp_path):
    root=tmp_path/'同事 项目(迁移)';root.mkdir()
    for name in ['一键部署.ps1','config.example.json','requirements-lock.txt']:
        shutil.copy2(ROOT/name,root/name)
    for name in ['rag_app/__main__.py','scripts/deployment.py','scripts/conda-common.ps1','作业一/文献.pdf']:
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
    result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'一键部署.ps1'),'-CheckOnly'],capture_output=True,timeout=60)
    assert result.returncode==0,result.stderr
    assert not (root/'.runtime').exists() and not (root/'logs').exists()
    (root/'config.json').write_text('{"generation_model":"qwen3:1.7b"}',encoding='utf-8')
    partial=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'一键部署.ps1'),'-CheckOnly'],capture_output=True,timeout=60)
    assert partial.returncode==0 and b'qwen3:1.7b' in partial.stdout
    (root/'作业一/文献.pdf').unlink()
    missing=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'一键部署.ps1'),'-CheckOnly'],capture_output=True,timeout=60)
    assert missing.returncode==1
    assert not (root/'.runtime').exists()

@pytest.mark.skipif(sys.platform!='win32',reason='Windows launcher')
def test_base_cannot_be_selected_for_deployment():
    result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'一键部署.ps1'),'-EnvName','base','-CheckOnly'],capture_output=True,timeout=30)
    assert result.returncode==1


@pytest.mark.skipif(sys.platform!='win32',reason='Windows launcher')
def test_launcher_rejects_legacy_venv_record(tmp_path):
    root=tmp_path/'新项目';root.mkdir();(root/'scripts').mkdir();(root/'.runtime').mkdir()
    shutil.copy2(ROOT/'启动.ps1',root/'启动.ps1')
    shutil.copy2(ROOT/'scripts/conda-common.ps1',root/'scripts/conda-common.ps1')
    (root/'.runtime/current.json').write_text(json.dumps({'root':str(root),'python':sys.executable,'environment_kind':'legacy'}),encoding='utf-8')
    result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'启动.ps1'),'-NoBrowser'],capture_output=True,timeout=30)
    assert result.returncode==1


@pytest.mark.skipif(sys.platform!='win32',reason='Windows launcher')
def test_environment_guard_rejects_root_before_running_python(tmp_path):
    root=tmp_path/'base';root.mkdir()
    command=". '"+str(ROOT/'scripts/conda-common.ps1').replace("'","''")+"'; try { Assert-ProjectEnvironment '"+str(root)+"' '"+str(root)+"'; exit 0 } catch { exit 1 }"
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,timeout=30)
    assert result.returncode==1
