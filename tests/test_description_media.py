import pytest
from nexus_launcher.nexus_platform.description_media import safe_description_image,DescriptionRedirects
from nexus_launcher.nexus_platform.markdown_content import render_content
from nexus_launcher.nexus_platform.project_content import safe_link


@pytest.mark.parametrize('url',[
    'https://tr7zw.dev/nea/eating.png',
    'https://tr7zw.github.io/uikit/banner/essential_1.png',
    'https://github.com/uBlockOrigin/uAssets/assets/5133936/banner',
    'https://github-production-user-asset-6210df.s3.amazonaws.com/5133936/banner.png',
    'https://raw.githubusercontent.com/author/repository/main/banner.png',
])
def test_known_static_author_sources(url):
    assert safe_description_image(url)
    DescriptionRedirects().validate(url)


@pytest.mark.parametrize('url',[
    'http://tr7zw.dev/nea/eating.png','https://tr7zw.dev.evil.test/nea/a.png',
    'https://127.0.0.1/nea/a.png','https://localhost/a.png','file:///private/a.png',
    'https://tr7zw.dev/admin','https://tr7zw.dev:444/nea/a.png',
    'https://user@tr7zw.dev/nea/a.png','https://arbitrary.s3.amazonaws.com/a.png',
    'https://github.com/owner/repo/settings','data:image/png;base64,a',
])
def test_unapproved_sources_and_redirects_rejected(url):
    assert not safe_description_image(url)
    with pytest.raises(ValueError):DescriptionRedirects().validate(url)


def test_description_can_render_author_banner_and_more_than_twelve_images():
    text='\n\n'.join(f'![Image {i}](https://tr7zw.dev/nea/{i}.png)' for i in range(30))
    html,images=render_content(text,safe_link)
    assert len(images)==24
    assert '<img' not in html and 'src=' not in html
