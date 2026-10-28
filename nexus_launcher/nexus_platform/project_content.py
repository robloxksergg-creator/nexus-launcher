"""Bounded, inert rich descriptions. Authored markup never becomes active HTML."""
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit
from uuid import uuid4

from PySide6.QtCore import QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QTextCursor, QTextDocument, QTextBlockFormat, QTextCharFormat, QTextFormat, QTextImageFormat
from PySide6.QtWidgets import QTextBrowser

from .theme_tokens import TOKENS
from .mod_media import safe_image, fetch_media, decode_image
from .markdown_content import render_content

MEDIA_URL = int(QTextFormat.Property.UserProperty) + 20
MEDIA_LABEL = MEDIA_URL + 1


def safe_link(url):
    try:
        parts = urlsplit(url)
        return (parts.scheme == 'https' and bool(parts.hostname) and
                parts.username is None and parts.password is None and
                parts.port in (None, 443) and not any(ord(c) < 32 for c in url))
    except ValueError:
        return False



class DescriptionParser(HTMLParser):
    """Translate supported HTML into Markdown, discarding attributes and code."""
    BLOCKED = {'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'form', 'button'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.blocked = []
        self.links = []
        self.pre = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCKED:
            self.blocked.append(tag)
        if self.blocked:
            return
        attrs = dict(attrs)
        if tag in {'p', 'div', 'center', 'section', 'article', 'blockquote', 'ul', 'ol', 'table', 'tr'}:
            self.parts.append('\n\n')
        elif tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            self.parts.append('\n\n' + '#' * int(tag[1]) + ' ')
        elif tag == 'br':
            self.parts.append('  \n')
        elif tag == 'hr':
            self.parts.append('\n\n---\n\n')
        elif tag == 'li':
            self.parts.append('\n- ')
        elif tag in {'b', 'strong'}:
            self.parts.append('**')
        elif tag in {'i', 'em'}:
            self.parts.append('*')
        elif tag == 'pre':
            self.pre += 1
            self.parts.append('\n\n```\n')
        elif tag == 'code' and not self.pre:
            self.parts.append('`')
        elif tag == 'a':
            url = attrs.get('href', '')
            self.links.append(url if safe_link(url) else '')
            if self.links[-1]:
                self.parts.append('[')
        elif tag == 'img':
            url = attrs.get('src') or ''
            caption = re.sub(r'[\[\]\\\n]', '', (attrs.get('alt') or 'Изображение'))[:160]
            # Keep image nodes inline inside anchors. Origin checks belong to
            # the token renderer, before any image enters the loading queue.
            url = url.replace('<', '%3C').replace('>', '%3E')
            self.parts.append(f'![{caption}](<{url}>)')

    def handle_endtag(self, tag):
        if self.blocked:
            if tag == self.blocked[-1]:
                self.blocked.pop()
            return
        if tag in {'p', 'div', 'center', 'section', 'article', 'blockquote', 'ul', 'ol', 'table', 'tr',
                   'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            self.parts.append('\n\n')
        elif tag in {'b', 'strong'}:
            self.parts.append('**')
        elif tag in {'i', 'em'}:
            self.parts.append('*')
        elif tag == 'pre':
            self.pre = max(0, self.pre - 1)
            self.parts.append('\n```\n\n')
        elif tag == 'code' and not self.pre:
            self.parts.append('`')
        elif tag == 'a' and self.links:
            url = self.links.pop()
            if url:
                # Angle brackets prevent authored parentheses from breaking Markdown.
                self.parts.append('](<' + url.replace('>', '%3E').replace('<', '%3C') + '>)')

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


def description_markdown(value):
    value = str(value)[:200_000]
    # Code samples are text, so their literal tags are retained inside code only.
    samples = []
    nonce = uuid4().hex
    def protect(match):
        samples.append(match.group())
        return f'NEXUSCODESAMPLE{nonce}:{len(samples) - 1}TOKEN'
    value = re.sub(r'(?m)^[ \t]{0,3}(`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:^[ \t]{0,3}\1[ \t]*$|\Z)|(?:(?:^ {4}|^\t)[^\n]*(?:\n|$))+|`[^`\n]+`|<https://[^<>\s]+>', protect, value)
    parser = DescriptionParser()
    parser.feed(value)
    parser.close()
    result = ''.join(parser.parts)
    for index, sample in enumerate(samples):
        result = result.replace(f'NEXUSCODESAMPLE{nonce}:{index}TOKEN', sample)
    return result


class ProjectBody(QTextBrowser):
    media_ready = Signal(int, str, bytes)
    _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='description-media')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.generation = 0
        self.images = {}
        self._futures = []
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._open_link)
        self.media_ready.connect(self._media_received)
        self.document().setDefaultStyleSheet(f'''
            body {{ color:{TOKENS['text']}; font-family:'Segoe UI'; font-size:15px; }}
            h1 {{ font-size:30px; margin-top:24px; margin-bottom:16px; }}
            h2 {{ font-size:24px; margin-top:24px; }}
            h3 {{ font-size:19px; margin-top:20px; }}
            p, li {{ margin-top:8px; margin-bottom:12px; }}
            a {{ color:{TOKENS['accent']}; }}
            pre, code {{ background:{TOKENS['surface']}; font-family:Consolas; }}
            blockquote {{ margin-left:20px; color:{TOKENS['muted']}; }}
        ''')
        self.document().setDocumentMargin(24)

    def setPlainText(self, value):
        self.cancel_media()
        super().setPlainText(value)

    def cancel_media(self):
        self.generation += 1
        self.images.clear()
        for future in self._futures:
            future.cancel()
        self._futures.clear()

    def setMarkdown(self, value):
        self.cancel_media()
        token = self.generation
        self.images.clear()
        html, entries = render_content(description_markdown(value), safe_link)
        # Generated inert formatting only: authored HTML is sanitized first;
        # the token renderer never produces img/src, script or external style.
        self.document().setHtml(html)
        images = []
        for marker, url, caption in entries:
            cursor = self.document().find(marker)
            if cursor.isNull():
                continue
            fmt = QTextCharFormat(cursor.charFormat())
            fmt.setProperty(MEDIA_URL, url)
            fmt.setProperty(MEDIA_LABEL, caption)
            cursor.insertText('Загрузка изображения…', fmt)
            if url not in images:
                images.append(url)
        self._reading_layout()
        for url in images:
            self._futures.append(self._pool.submit(self._fetch, token, url))

    def _reading_layout(self):
        block = self.document().begin()
        while block.isValid():
            fmt = block.blockFormat()
            heading = fmt.headingLevel()
            fmt.setTopMargin(0 if block.blockNumber() == 0 else 24 if heading else 4)
            fmt.setBottomMargin(12 if heading else 6 if block.textList() else 12)
            fmt.setLineHeight(140, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            QTextCursor(block).setBlockFormat(fmt)
            block = block.next()
        self.document().setTextWidth(max(120, min(960, self.viewport().width() - 48)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.document().setTextWidth(max(120, min(960, self.viewport().width() - 48)))
        # Existing resources must shrink with the reading area too, rather than
        # retaining the width of the window where the download completed.
        block = self.document().begin()
        edits = []
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.charFormat().isImageFormat():
                    fmt = fragment.charFormat().toImageFormat()
                    image = self.images.get(fmt.name())
                    if image is not None:
                        width = self._image_width(block, image)
                        fmt.setWidth(width)
                        fmt.setHeight(width * image.height() / image.width())
                        edits.append((fragment.position(), fragment.length(), fmt))
                iterator += 1
            block = block.next()
        for position, length, fmt in edits:
            cursor = QTextCursor(self.document())
            cursor.setPosition(position)
            cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(fmt)

    def _image_width(self, block, image):
        fmt = block.blockFormat()
        available = min(self.document().textWidth(), self.viewport().width()) - 2 * self.document().documentMargin()
        available -= fmt.leftMargin() + fmt.rightMargin() + max(0, fmt.textIndent())
        if block.textList():
            available -= block.textList().format().indent() * self.document().indentWidth()
        return max(1, min(image.width(), available))

    def loadResource(self, _kind, url):
        # Qt cannot fetch remote URLs or local files; only our bounded cache exists.
        return self.images.get(url.toString()) if isinstance(url, QUrl) else None

    def _open_link(self, url):
        if safe_link(url.toString()):
            QDesktopServices.openUrl(url)

    def _fetch(self, token, url):
        if token != self.generation:
            return
        data = fetch_media(url, cancelled=lambda: token != self.generation)
        try:
            self.media_ready.emit(token, url, data)
        except RuntimeError:
            pass

    @Slot(int, str, bytes)
    def _media_received(self, token, url, data):
        if token != self.generation or not safe_image(url):
            return
        image = decode_image(data, width=max(120, min(960, self.viewport().width() - 64)))
        valid = not image.isNull()
        if valid:
            self.images[url] = image
            self.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), image)
        block = self.document().begin()
        edits = []
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                fmt = fragment.charFormat()
                if fmt.property(MEDIA_URL) == url:
                    edits.append((fragment.position(), fragment.length(), fmt, self._image_width(block, image) if valid else 0))
                iterator += 1
            block = block.next()
        for position, length, original, width in reversed(edits):
            cursor = QTextCursor(self.document())
            cursor.setPosition(position)
            cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
            if valid:
                fmt = QTextImageFormat()
                fmt.setAnchor(original.isAnchor())
                fmt.setAnchorHref(original.anchorHref())
                fmt.setName(url)
                fmt.setWidth(width)
                fmt.setHeight(width * image.height() / image.width())
                cursor.insertImage(fmt)
            else:
                fmt = QTextCharFormat(original)
                fmt.clearProperty(MEDIA_URL)
                label = original.property(MEDIA_LABEL) if original.isAnchor() else ''
                cursor.insertText((str(label) + ' — ' if label else '') + 'Изображение недоступно.', fmt)
        self.document().markContentsDirty(0, self.document().characterCount())
