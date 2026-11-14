from copy import deepcopy
import pytest
from nexus_launcher.modrinth_provider import ModrinthProvider,ProviderError


def test_diamond_dependency_fetches_shared_version_once_and_preserves_input(monkeypatch):
    p=ModrinthProvider();calls=[]
    shared={'id':'shared-v','project_id':'shared','loaders':['fabric'],'game_versions':['1.21.1'],'dependencies':[]}
    root={'id':'root-v','project_id':'root','dependencies':[{'dependency_type':'required','project_id':'shared','version_id':'shared-v'}]*3}
    original=deepcopy(root)
    monkeypatch.setattr(p,'versions',lambda *a:[root])
    monkeypatch.setattr(p,'version',lambda key:(calls.append(key) or shared))
    plan=p.resolve('root','1.21.1','fabric')
    assert calls==['shared-v'] and len(plan)==2
    assert root==original and 'required_by' not in shared


def test_resolver_caps_dependency_graph(monkeypatch):
    p=ModrinthProvider();calls=[]
    def versions(project,*a):
        calls.append(project)
        return [{'id':project,'project_id':project,'dependencies':[{'dependency_type':'required','project_id':project+'x'}]}]
    monkeypatch.setattr(p,'versions',versions)
    with pytest.raises(ProviderError,match='граф'):p.resolve('root','1.21.1','fabric')
    assert len(calls)==64
