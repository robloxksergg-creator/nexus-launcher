"""Deterministic Markdown node/Qt resource/link acceptance."""
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextCursor
from nexus_launcher.nexus_platform.project_content import ProjectBody, safe_link
from nexus_launcher.nexus_platform.markdown_content import render_content
from tests.test_mod_media import png, URL
from tests.test_next_shell import candidate  # noqa: F401

@pytest.fixture
def body(candidate, monkeypatch):  # noqa: F811
    app, _, _ = candidate
    widget = ProjectBody()
    widget.resize(800, 600)
    widget.show()
    app.processEvents()
    submitted = []
    class Future:
        def cancel(self):
            pass
    monkeypatch.setattr(widget._pool, 'submit', lambda *args: submitted.append(args) or Future())
    yield widget, submitted, app
    widget.cancel_media()
    widget.close()

@pytest.mark.parametrize('source', [f'![Screenshot]({URL})', f'![]({URL})', f'![alt text](<{URL}>)', f'<img src="{URL}" alt="Screenshot">'])
def test_valid_image_nodes_with_and_without_alt(body, source):
    widget, submitted, _ = body
    widget.setMarkdown(source)
    assert [call[-1] for call in submitted] == [URL]
    assert widget.toPlainText() == 'Загрузка изображения…'
    widget._media_received(widget.generation, URL, png())
    assert widget.images[URL]
    assert widget.document().begin().begin().fragment().charFormat().isImageFormat()

@pytest.mark.parametrize('label,url', [('Discord', 'https://discord.gg/test'), ('GitHub', 'https://github.com/test/repo'), ('Modrinth', 'https://modrinth.com/mod/test'), ('CurseForge', 'https://www.curseforge.com/minecraft/mc-mods/test'), ('Other', 'https://example.com/a?q=(x)')])
def test_plain_links_are_anchors_never_images(body, label, url):
    widget, submitted, _ = body
    widget.setMarkdown(f'[{label}](<{url}>)')
    cursor = widget.document().find(label)
    assert cursor.charFormat().isAnchor()
    assert cursor.charFormat().anchorHref() == url
    assert not submitted
    assert 'Изображение' not in widget.toPlainText()

@pytest.mark.parametrize('label,url', [('Discord', 'https://discord.gg/test'), ('GitHub', 'https://github.com/test'), ('Modrinth', 'https://modrinth.com/mod/test'), ('CurseForge', 'https://www.curseforge.com/test')])
def test_external_html_badges_remain_readable_links(body, label, url):
    widget, submitted, _ = body
    widget.setMarkdown(f'<a href="{url}"><img src="https://tr7zw.github.io/button.png" alt="GitHub"></a>')
    assert widget.toPlainText() == label
    assert widget.document().find(label).charFormat().anchorHref() == url
    assert not submitted

@pytest.mark.parametrize('source', [f'[![Discord]({URL})](https://discord.gg/test)', f'<a href="https://discord.gg/test"><img src="{URL}" alt="Discord"></a>'])
def test_linked_image_keeps_anchor_while_loading_success_and_failure(body, source):
    widget, submitted, _ = body
    widget.setMarkdown(source)
    pending = widget.document().find('Загрузка изображения…')
    assert pending.charFormat().anchorHref() == 'https://discord.gg/test'
    assert len(submitted) == 1
    widget._media_received(widget.generation, URL, png())
    fmt = widget.document().begin().begin().fragment().charFormat()
    assert fmt.isImageFormat() and fmt.anchorHref() == 'https://discord.gg/test'
    widget.setMarkdown(source)
    widget._media_received(widget.generation, URL, b'corrupt')
    cursor = widget.document().find('Discord')
    assert cursor.charFormat().anchorHref() == 'https://discord.gg/test'
    assert 'Изображение недоступно.' in widget.toPlainText()

@pytest.mark.parametrize('url', ['https://evil.test/a.png', 'http://cdn.modrinth.com/a.png', 'file:///C:/private.png', 'javascript:alert(1)', 'data:image/png,secret', ''])
def test_forbidden_or_missing_image_never_queues_or_loads(body, url):
    widget, submitted, _ = body
    widget.setMarkdown(f'![image](<{url}>)')
    assert not submitted
    assert 'Изображение недоступно.' in widget.toPlainText()
    assert widget.loadResource(2, QUrl(url)) is None

def test_rich_markdown_nodes_and_literal_code(body):
    widget, submitted, _ = body
    widget.setMarkdown('''## Heading

Paragraph **bold** and *italic*, `inline`.

- First
- Second

1. Ordered one
2. Ordered two

> Quoted

---

~~~html
<img src="file:///private"> <script>literal code</script>
~~~

```text
[code](https://github.com/test) ![sample](https://cdn.modrinth.com/code.png)
```

    <img src="file:///indented-code">
''')
    text = widget.toPlainText()
    assert '##' not in text and '**' not in text and '~~~' not in text
    assert widget.document().find('bold').charFormat().fontWeight() >= 600
    assert widget.document().find('italic').charFormat().fontItalic()
    assert widget.document().find('First').block().textList()
    assert widget.document().find('Ordered one').block().textList()
    assert '<script>literal code</script>' in text
    assert '![sample]' in text
    assert '<img src="file:///indented-code">' in text
    assert not widget.document().find('[code]').charFormat().isAnchor()
    assert not submitted
    assert widget.document().find('Heading').block().blockFormat().headingLevel() == 2
    assert widget.document().find('Quoted').block().blockFormat().leftMargin() > 0
    assert '<hr' in widget.document().toHtml()

@pytest.mark.parametrize('value', ['[broken](', '![broken](', '[![nested]()](', '**unclosed', '<a href="https://github.com/test"><img', '![x](javascript:alert(1))'])
def test_malformed_markdown_is_bounded_inert_text(body, value):
    widget, submitted, _ = body
    widget.setMarkdown(value)
    assert len(widget.toPlainText()) < 300
    assert not submitted

def test_multiple_images_duplicate_urls_and_stale(body):
    widget, submitted, _ = body
    second = URL + '?second'
    widget.setMarkdown(f'![a]({URL}) ![]({second}) ![again]({URL})')
    assert [call[-1] for call in submitted] == [URL, second]
    widget._media_received(widget.generation, URL, png())
    assert widget.toPlainText().count('Загрузка изображения…') == 1
    widget._media_received(widget.generation - 1, second, png())
    assert second not in widget.images
    widget._media_received(widget.generation, second, png())
    assert 'Загрузка изображения…' not in widget.toPlainText()

def test_reference_links_images_autolinks_and_escaped_image(body):
    widget, submitted, _ = body
    widget.setMarkdown(f'[Discord][social]\n\n![Shot][picture]\n\n[social]: https://discord.gg/test\n[picture]: {URL}\n\n<https://github.com/test>\n\n\\![literal]({URL})')
    assert widget.document().find('Discord').charFormat().anchorHref() == 'https://discord.gg/test'
    assert widget.document().find('https://github.com/test').charFormat().isAnchor()
    assert [call[-1] for call in submitted] == [URL]
    assert widget.toPlainText().count('Загрузка изображения…') == 1

def test_quoted_image_fits_indented_reading_area_on_resize(body):
    widget, _, app = body
    widget.setMarkdown(f'> ![screenshot]({URL})')
    widget._media_received(widget.generation, URL, png(1200, 600))
    app.processEvents()
    assert widget.horizontalScrollBar().maximum() == 0
    widget.resize(500, 400)
    app.processEvents()
    assert widget.horizontalScrollBar().maximum() == 0

def test_many_rejected_images_have_one_compact_notice_and_alt_text(body):
    widget, submitted, _ = body
    widget.setMarkdown(' '.join(f'![Section {i}](https://evil.test/{i}.png)' for i in range(5)))
    text = widget.toPlainText()
    assert text.count('Часть изображений автора недоступна') == 1
    assert all(f'Section {i}' in text for i in range(5))
    assert 'Изображение недоступно.' not in text
    assert not submitted

def test_gallery_loading_success_failure_and_stale(body, candidate, monkeypatch):  # noqa: F811
    catalog = candidate[1].instances_page.mod_catalog
    class Future:
        def cancel(self):
            pass
    monkeypatch.setattr(catalog.media_pool, 'submit', lambda *args: Future())
    catalog._project_received(catalog.detail_generation, {'title': 'Fixture', 'body': 'Text', 'gallery': [{'url': URL, 'title': 'First', 'description': 'Caption', 'featured': True}, {'url': URL + '?bad', 'title': 'Broken', 'ordering': 1}]}, '')
    assert catalog.gallery_labels[0].text() == 'Загрузка изображения…'
    catalog._gallery_received(catalog.detail_generation - 1, 0, png())
    assert catalog.gallery_labels[0].text() == 'Загрузка изображения…'
    catalog._gallery_received(catalog.detail_generation, 0, png())
    assert not catalog.gallery_labels[0].pixmap().isNull()
    catalog._gallery_received(catalog.detail_generation, 1, b'corrupt')
    assert catalog.gallery_labels[1].text() == 'Изображение недоступно.'
    assert catalog.gallery_labels[1].height() == 40
    assert catalog.gallery_labels[0].accessibleName() == 'First'

def test_generated_markup_has_no_remote_resources_or_authored_active_html(body):
    widget, submitted, _ = body
    source = '<script>hidden</script><style>secret</style><iframe>frame</iframe><form>form</form><object>object</object><embed>embed</embed>'
    widget.setMarkdown(source + f'\n\n![safe]({URL})\n\n[text](javascript:alert(1))')
    text = widget.toPlainText()
    assert all(value not in text for value in ['hidden', 'secret', 'frame', 'form', 'object', 'embed'])
    assert not widget.document().find('text').charFormat().isAnchor()
    html, images = render_content(f'![safe]({URL}) [bad](javascript:alert(1))', safe_link)
    assert '<img' not in html and ' src=' not in html and 'javascript:' not in html
    assert images[0][1] == URL
    assert len(submitted) == 1

def test_normal_link_click_dispatch_only_safe_https(body, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtCore import Qt
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    widget, _, app = body
    calls = []
    monkeypatch.setattr(QDesktopServices, 'openUrl', lambda url: calls.append(url.toString()) or True)
    widget.setMarkdown('[Discord](https://discord.gg/test)')
    cursor = widget.document().find('Discord')
    cursor.clearSelection()
    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
    app.processEvents()
    QTest.mouseClick(widget.viewport(), Qt.MouseButton.LeftButton, pos=widget.cursorRect(cursor).center() + QPoint(12, 0))
    assert calls == ['https://discord.gg/test']
    widget._open_link(QUrl('javascript:alert(1)'))
    widget._open_link(QUrl('file:///private'))
    assert calls == ['https://discord.gg/test']
