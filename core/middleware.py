from html import escape, unescape
from html.parser import HTMLParser

from django.utils.cache import patch_vary_headers

from .translations import translate_ui


class _HindiHTML(HTMLParser):
    """Translate exact interface text/labels and annotate it for language toggles."""
    translatable_attrs = {'placeholder', 'title', 'aria-label', 'alt'}
    raw_tags = {'script', 'style', 'textarea', 'pre', 'code'}
    void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []
        self.raw_depth = 0
        self.protected_tags = []

    def handle_starttag(self, tag, attrs):
        rendered_attrs = []
        for name, value in attrs:
            if value is not None and name in self.translatable_attrs:
                original = unescape(value)
                translated = translate_ui(original, 'hi')
                if translated != original:
                    value = translated
                    rendered_attrs.append(('data-i18n-attr-' + name, original))
            if value is None:
                rendered_attrs.append((name, None))
            else:
                rendered_attrs.append((name, value))
        attrs_text = ''.join(f' {name}' if value is None else f' {name}="{escape(value, quote=True)}"' for name, value in rendered_attrs)
        self.parts.append(f'<{tag}{attrs_text}>')
        if tag in self.raw_tags:
            self.raw_depth += 1
        if tag not in self.void_tags and any(name == 'data-no-translate' for name, _ in attrs):
            self.protected_tags.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        self.parts.append(f'</{tag}>')
        if tag in self.raw_tags and self.raw_depth:
            self.raw_depth -= 1
        if tag in self.protected_tags:
            protected_index = len(self.protected_tags) - 1 - self.protected_tags[::-1].index(tag)
            self.protected_tags.pop(protected_index)

    def handle_data(self, data):
        if self.raw_depth or self.protected_tags:
            self.parts.append(data)
            return
        key = data.strip()
        translated = translate_ui(key, 'hi')
        if translated == key:
            self.parts.append(data)
            return
        prefix = data[:len(data) - len(data.lstrip())]
        suffix = data[len(data.rstrip()):]
        self.parts.append(f'{prefix}<span data-i18n-key="{escape(key, quote=True)}">{escape(translated)}</span>{suffix}')

    def handle_entityref(self, name):
        self.parts.append(f'&{name};')

    def handle_charref(self, name):
        self.parts.append(f'&#{name};')

    def handle_comment(self, data):
        self.parts.append(f'<!--{data}-->')

    def handle_decl(self, decl):
        self.parts.append(f'<!{decl}>')

    def unknown_decl(self, data):
        self.parts.append(f'<![{data}]>')


class HindiMarkupMiddleware:
    """Server-render exact catalogue translations while retaining English keys."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        language = getattr(request, 'LANGUAGE_CODE', '')
        if language != 'hi' or response.streaming or not response.get('Content-Type', '').startswith('text/html'):
            return response
        parser = _HindiHTML()
        parser.feed(response.content.decode(response.charset or 'utf-8'))
        parser.close()
        response.content = ''.join(parser.parts).encode(response.charset or 'utf-8')
        response['Content-Length'] = str(len(response.content))
        patch_vary_headers(response, ('Cookie',))
        return response
