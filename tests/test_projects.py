from nexus_launcher.projects import Project, ProjectCatalog, ServerProfile


def test_project_catalog_roundtrip(tmp_path):
    catalog = ProjectCatalog(tmp_path / "projects.json")
    expected = [
        Project(
            "sky",
            "Sky Project",
            (ServerProfile("main", "Main", "sky.example.org", "https://cdn.example.org/manifest.json"),),
        )
    ]
    catalog.save(expected)
    assert catalog.load() == expected


def test_retired_demo_entries_do_not_remove_custom_servers_or_saves(tmp_path):
    catalog = ProjectCatalog(tmp_path / 'projects.json')
    save = tmp_path / 'world-save.dat'
    save.write_bytes(b'preserve-user-world')
    retired = ServerProfile('pinewood', 'PINEWOOD', '', pack_id='nexus-pinewood')
    custom = ServerProfile('elderfall', 'My custom server', 'localhost', pack_id='custom')
    catalog.save([Project('nexusmc', 'NexusMC', (retired, custom))])
    loaded = catalog.load()[0].servers
    assert [item.id for item in loaded] == ['elderfall', 'main']
    assert loaded[0] == custom
    assert save.read_bytes() == b'preserve-user-world'


def test_old_project_format_gets_local_management_defaults(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text('{"nexus_launcher.projects":[{"id":"old","name":"Old","server":"localhost"}]}', encoding="utf-8")
    server = ProjectCatalog(path).load()[0].servers[0]
    assert server.management_type == "local"
    assert server.server_jar == "server.jar"
    assert server.max_memory_mb == 4096


def test_existing_nexus_catalog_keeps_only_gearmorph_defaults(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text('{"projects":[{"id":"nexusmc","name":"NexusMC","servers":[{"id":"main","name":"Main","address":"play.example.org"}]}]}', encoding="utf-8")
    servers = ProjectCatalog(path).load()[0].servers
    assert [server.id for server in servers] == ["main"]
    assert servers[0].name == "GEARMORPH • NeoForge"
    assert servers[0].artwork == "gearmorph-world-art.png"


def test_obsolete_official_manifest_and_local_archive_are_migrated(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(
        '{"nexus_launcher.projects":[{"id":"nexusmc","name":"NexusMC","servers":['
        '{"id":"nexus_launcher.main","name":"GEARMORPH","address":"old","manifest_url":"https://old.invalid/v2.json",'
        '"local_pack_path":"D:/packs/local.zip"}]}]}',
        encoding="utf-8",
    )
    main = ProjectCatalog(path).load()[0].servers[0]
    assert main.manifest_url.endswith("/api/launcher/modpacks/gearmorph")
    assert main.local_pack_path == ""
