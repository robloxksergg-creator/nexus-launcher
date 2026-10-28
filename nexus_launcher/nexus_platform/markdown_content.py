"""CommonMark tokens -> inert Qt markup; images never emit an external src."""
from html import escape
from uuid import uuid4
from urllib.parse import urlsplit
import re

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML

from .mod_media import safe_image


def link_label(url, caption):
    names = {'discord.gg': 'Discord', 'discord.com': 'Discord',
             'github.com': 'GitHub', 'modrinth.com': 'Modrinth',
             'www.curseforge.com': 'CurseForge', 'curseforge.com': 'CurseForge',
             'ko-fi.com': 'Ko-fi'}
    return names.get(urlsplit(url).hostname, caption or 'Ссылка')


class InertRenderer(RendererHTML):
    def html_inline(self, tokens, idx, options, env):
        return escape(tokens[idx].content)

    def html_block(self, tokens, idx, options, env):
        return escape(tokens[idx].content)

    def link_open(self, tokens, idx, options, env):
        href = tokens[idx].attrGet('href') or ''
        allowed = env['link_allowed'](href)
        env['anchors'].append(href if allowed else '')
        return '<a href="' + escape(href, quote=True) + '">' if allowed else ''

    def link_close(self, tokens, idx, options, env):
        return '</a>' if env['anchors'].pop() else ''

    def image(self, tokens, idx, options, env):
        token = tokens[idx]
        url = token.attrGet('src') or ''
        caption = self.renderInlineAsText(token.children or [], options, env)[:160]
        if not safe_image(url) or (url not in env['urls'] and len(env['urls']) >= 12):
            href = env['anchors'][-1] if env['anchors'] else ''
            # A rejected badge still names its link, rather than breaking it
            # into Markdown brackets and an unrelated image error paragraph.
            if href:
                return escape(link_label(href, caption))
            marker = f"\ue000NEXUSREJECT{env['nonce']}:{len(env['rejected'])}\ue001"
            env['rejected'].append((marker, caption))
            return marker
        env['urls'].add(url)
        marker = f"\ue000NEXUS{env['nonce']}:{len(env['images'])}\ue001"
        env['images'].append((marker, url, caption))
        return marker


def render_content(markdown, link_allowed):
    parser = MarkdownIt('commonmark', {'html': False, 'maxNesting': 20}, renderer_cls=InertRenderer)
    parser.enable(['table', 'strikethrough'])
    # Parse all destinations as nodes; the renderer enforces our stricter policy
    # for every link/image. Parsing a URL is never permission to load it.
    parser.validateLink = lambda url: True
    env = {'link_allowed': link_allowed, 'anchors': [], 'urls': set(), 'rejected': [],
           'images': [], 'nonce': uuid4().hex}
    html = parser.render(markdown, env).strip()
    grouped = len(env['rejected']) > 2
    for marker, caption in env['rejected']:
        if grouped:
            label = '' if caption.lower() in {'', 'alt text', 'divider', 'изображение'} else caption
        else:
            label = 'Изображение недоступно.' + (' ' + caption if caption else '')
        html = html.replace(marker, escape(label))
    if grouped:
        html = re.sub(r'<p>\s*</p>', '', html)
        html = '<p>Часть изображений автора недоступна: адреса вне разрешённого CDN или превышен лимит.</p>' + html
    return html, env['images']
