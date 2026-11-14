from types import SimpleNamespace
from nexus_launcher.instance_diagnostics import Finding
from nexus_launcher.diagnostic_fixes import suggest_fixes


def test_duplicate_candidates_are_bound_to_scanned_filenames():
    report=SimpleNamespace(mods=[SimpleNamespace(filename='a.jar'),SimpleNamespace(filename='b.jar')],findings=[Finding('error','DUPLICATE_ID','Duplicate','',('a.jar','b.jar','../foreign.jar'))])
    assert [s.filename for s in suggest_fixes(report)]==['a.jar','b.jar']


def test_ambiguous_findings_do_not_offer_automatic_fixes():
    report=SimpleNamespace(mods=[],findings=[Finding('warning','UNRESOLVED_DEPENDENCY','Unknown','',(), 'source.jar'),Finding('info','LIMITATIONS','Limits','')])
    suggestions=suggest_fixes(report)
    assert len(suggestions)==1 and not suggestions[0].filename
