from nexus_launcher.build_file_manifest import github_asset_name


def test_github_asset_name_matches_release_normalization():
    assert github_asset_name("a--Fresh Buckets 3D UI.zip") == "a--Fresh.Buckets.3D.UI.zip"
    assert github_asset_name("a--Bliss_(Shaders edit).zip") == "a--Bliss_.Shaders.edit.zip"
    assert github_asset_name("a--mod+name.jar") == "a--mod+name.jar"
    assert github_asset_name("a--mod%2Bname.jar") == "a--mod.2Bname.jar"
