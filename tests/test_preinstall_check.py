"""Synthetic probes and owned files; no live server, JVM, account or game launch."""
import socket
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock
from nexus_launcher import preinstall_check as module

class Checks(unittest.TestCase):
    server = SimpleNamespace(name='Fixture', address='fixture.invalid:25565', minecraft_version='1.21.1', java_major=0, recommended_memory_mb=6016)
    def run_report(self, **kwargs):
        with patch.object(module,'read_memory',return_value=(16*1024**3,8*1024**3)), patch.object(module,'free_disk',return_value=20*1024**3), patch.object(module,'inspect_java',return_value=('ok','Java 21 fixture')), patch.object(module,'connection_time',return_value=42):
            return module.collect(self.server,Path('/unused'),**kwargs)
    def test_native_os_memory_adapter_reports_valid_bytes(self):
        total,available=module.read_memory()
        self.assertIsInstance(total,int);self.assertGreater(total,0)
        if available is not None:
            self.assertIsInstance(available,int);self.assertGreaterEqual(available,0);self.assertLessEqual(available,total)

    def test_unknown_disk_and_fps_never_become_success(self):
        report=self.run_report(allocated_mb=6144)
        self.assertEqual([x.key for x in report.checks],['ram','disk','java','network','fps'])
        by={x.key:x for x in report.checks}
        self.assertEqual(by['disk'].state,'unknown');self.assertIn('20.0',by['disk'].detail)
        self.assertEqual(by['fps'].state,'unknown');self.assertEqual(by['network'].state,'ok')
        self.assertIn('не игровой пинг',by['network'].detail);self.assertGreater(report.measured_at,0)
    def test_memory_choice_below_existing_recommendation_warns(self):
        self.assertEqual(self.run_report(allocated_mb=2048).checks[0].state,'warning')
    def test_low_available_memory_warns_without_reservation(self):
        with patch.object(module,'read_memory',return_value=(16*1024**3,1024**3)),patch.object(module,'free_disk',side_effect=OSError),patch.object(module,'inspect_java',return_value=('unknown','fixture')),patch.object(module,'connection_time',side_effect=socket.timeout):
            report=module.collect(self.server,Path('/unused'),allocated_mb=6144)
        self.assertEqual(report.checks[0].state,'warning');self.assertEqual(report.checks[1].state,'unknown');self.assertEqual(report.checks[3].state,'unknown')
        self.assertIn('причина не установлена',report.checks[3].detail)
    def test_memory_probe_timeout_remains_unknown_and_other_checks_continue(self):
        with patch.object(module,'read_memory',side_effect=module.subprocess.TimeoutExpired('synthetic-os-probe',2)),patch.object(module,'free_disk',return_value=1),patch.object(module,'inspect_java',return_value=('unknown','fixture')),patch.object(module,'connection_time',return_value=1):
            report=module.collect(self.server,Path('/unused'))
        self.assertEqual(report.checks[0].state,'unknown');self.assertEqual(len(report.checks),5)

    def test_cancel_before_probe_has_no_side_effect(self):
        with patch.object(module,'read_memory') as memory,patch.object(module,'connection_time') as network:
            r=module.collect(self.server,Path('/unused'),cancelled=lambda:True)
        self.assertTrue(r.cancelled);self.assertEqual(r.checks,());memory.assert_not_called();network.assert_not_called()
    def test_cancellation_after_ram_skips_other_probes(self):
        calls=iter([False,True])
        with patch.object(module,'read_memory',return_value=(1,None)),patch.object(module,'free_disk') as disk:
            r=module.collect(self.server,Path('/unused'),cancelled=lambda:next(calls))
        self.assertTrue(r.cancelled);self.assertEqual(len(r.checks),1);disk.assert_not_called()
    def test_disk_uses_existing_ancestor_without_creating_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing=Path(tmp)/'new'/'instance'
            with patch.object(module.shutil,'disk_usage',return_value=SimpleNamespace(free=123)) as disk:
                self.assertEqual(module.free_disk(missing),123)
            disk.assert_called_once_with(Path(tmp));self.assertFalse(missing.exists())
    def test_network_is_one_bounded_connection_and_not_a_game_packet(self):
        conn=MagicMock()
        with patch.object(module.socket,'create_connection',return_value=conn) as connect,patch.object(module.time,'monotonic',side_effect=[1,1.042]):
            self.assertAlmostEqual(module.connection_time('[::1]:25570'),42)
        connect.assert_called_once_with(('::1',25570),timeout=3);conn.__enter__.return_value.sendall.assert_not_called()
    def test_invalid_endpoints_never_connect(self):
        with patch.object(module.socket,'create_connection') as connect:
            for value in ['host:0','host:65536','https://host','user@host','host/path','host?x=1','host #x','']:
                with self.subTest(value=value),self.assertRaises(ValueError):module.connection_time(value)
        connect.assert_not_called()
    def test_java_uses_existing_version_probe_and_respects_explicit_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            java=Path(tmp)/'java';java.write_bytes(b'fixture; never execute')
            with patch.object(module,'java_major',return_value=17) as major:
                state,detail=module.inspect_java(str(java),21)
            self.assertEqual(state,'warning');self.assertIn('17',detail);major.assert_called_once_with(java)
            with patch.object(module,'java_major') as major:
                self.assertEqual(module.inspect_java(str(Path(tmp)/'missing/java'),21)[0],'unknown')
            major.assert_not_called()
    def test_unknown_minecraft_cannot_claim_java_compatibility(self):
        server=SimpleNamespace(**{**vars(self.server),'minecraft_version':'unknown'})
        with patch.object(module,'read_memory',return_value=(None,None)),patch.object(module,'free_disk',return_value=1),patch.object(module,'inspect_java') as java,patch.object(module,'connection_time',return_value=1):
            result=module.collect(server,Path('/unused'))
        self.assertEqual(result.checks[2].state,'unknown');java.assert_not_called()

if __name__=='__main__': unittest.main()
