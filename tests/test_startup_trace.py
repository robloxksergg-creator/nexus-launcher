from nexus_launcher.startup_trace import StartupTrace


def test_trace_ready_cancels_warning_and_records_static_stages(tmp_path):
    warnings=[]
    trace=StartupTrace(root=tmp_path,delay=300,notify=lambda *args:warnings.append(args))
    trace.stage('services-create')
    trace.ready()
    trace._timeout()
    assert not warnings
    assert 'renderer-ready' in trace.path.read_text()


def test_stalled_start_names_last_stage_without_exception_or_account_data(tmp_path):
    warnings=[]
    trace=StartupTrace(root=tmp_path,delay=300,notify=lambda *args:warnings.append(args))
    try:
        trace.stage('window-create')
        trace._timeout()
        assert warnings==[('window-create',trace.path)]
        assert 'startup-deadline' in trace.path.read_text()
    finally:trace.close()


def test_renderer_failure_is_visible_even_after_readiness(tmp_path):
    warnings=[]
    trace=StartupTrace(root=tmp_path,delay=300,notify=lambda *args:warnings.append(args))
    trace.ready()
    trace.fail('renderer-terminated')
    assert warnings==[('renderer-terminated',trace.path)]
    assert trace.finished.is_set()
