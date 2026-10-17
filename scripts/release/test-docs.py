#!/usr/bin/env python3
"""Verify the published technical manual: self-contained HTML, embedded PDF fonts, version and commit."""
import argparse
import base64
import binascii
import html.parser
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree

ALLOWED_PREFIXES = ('data:', '#')
GRAPHVIZ_BLOCK = re.compile(r'^~~~~\{\.graphviz', re.M)
IMAGE_REF = re.compile(r'!\[[^\]]*\]\(([^)\s]+)')
FONT_LINE = re.compile(r'^(?P<name>.+?)\s+(?P<type>\S+)\s+(?P<encoding>\S+)\s+(?P<emb>yes|no)\s+(?P<sub>yes|no)\s+(?P<uni>yes|no)\s+\d+\s+\d+\s*$')

class Scan(html.parser.HTMLParser):
    """Collect every attribute that makes a browser fetch a resource, plus the document facts we check."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.resources = []   # (tag, attribute, value)
        self.images = []      # img src values
        self.objects = 0
        self.charsets = []
        self.lang = None
        self.title = ''
        self._in_title = False
        self._in_style = False
        self.css = []         # style text and style attributes, scanned for url()/@import

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'html':
            self.lang = values.get('lang')
        if tag == 'meta' and 'charset' in values:
            self.charsets.append(values['charset'].lower())
        if tag == 'title':
            self._in_title = True
        if tag == 'style':
            self._in_style = True
        if tag == 'object':
            self.objects += 1
        if tag == 'img':
            self.images.append(values.get('src', ''))
        if 'style' in values:
            self.css.append(values['style'])
        for attribute, value in attrs:
            if value is None:
                continue
            if attribute in ('src', 'poster', 'data') or attribute == 'xlink:href' or \
               (attribute == 'href' and tag in ('link', 'use', 'image')):
                self.resources.append((tag, attribute, value))
            elif attribute == 'srcset':
                self.resources.extend((tag, attribute, part.strip().split(' ')[0]) for part in value.split(',') if part.strip())

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False
        if tag == 'style':
            self._in_style = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_style:
            self.css.append(data)

def css_violations(texts):
    problems = []
    for text in texts:
        if '@import' in text:
            problems.append('CSS @import is an external dependency')
        for url in re.findall(r'url\(\s*[\'"]?([^\'")\s]+)', text):
            if not url.startswith(ALLOWED_PREFIXES):
                problems.append('CSS url() is an external dependency: ' + url)
    return problems

def check_html(path, version, commit, source, build_docs):
    problems = []
    text = path.read_text(encoding='utf-8')
    scan = Scan()
    scan.feed(text)
    for tag, attribute, value in scan.resources:
        if not value.startswith(ALLOWED_PREFIXES):
            problems.append(f'<{tag} {attribute}="{value[:60]}"> is not embedded (not a data: or # reference)')
    problems.extend(css_violations(scan.css))
    if scan.objects:
        problems.append(f'{scan.objects} <object> element(s) remain; SVG must be an embedded image')
    if 'utf-8' not in scan.charsets:
        problems.append('missing <meta charset="utf-8">')
    if not scan.lang:
        problems.append('missing lang attribute on <html>')
    if scan.title != f'audiowmark {version}':
        problems.append(f'title {scan.title!r} does not match audiowmark {version}')
    if f'commit {commit}' not in text:
        problems.append('commit ' + commit + ' is not stated in the document')

    source_text = source.read_text(encoding='utf-8')
    markdown_images = [ref for ref in IMAGE_REF.findall(source_text)]
    expected_count = len(GRAPHVIZ_BLOCK.findall(source_text)) + len(markdown_images)
    if len(scan.images) != expected_count:
        problems.append(f'{len(scan.images)} <img> elements, expected {expected_count} (graphviz blocks + image references)')
    # Every embedded payload must be byte-identical to a file the build produced: graphviz diagrams and referenced images.
    produced = [p.read_bytes() for p in sorted((build_docs / 'graphviz-images').glob('*.svg'))]
    produced += [(build_docs / ref).read_bytes() for ref in markdown_images if not ref.startswith('graphviz-images/')]
    decoded = {'image/svg+xml': [], 'image/png': []}
    for source_uri in scan.images:
        match = re.fullmatch(r'data:(image/svg\+xml|image/png);base64,(.+)', source_uri, re.S)
        if not match:
            problems.append('image is not an embedded SVG or PNG data URI: ' + source_uri[:60])
            continue
        try:
            decoded[match[1]].append(base64.b64decode(match[2], validate=True))
        except binascii.Error:
            problems.append('image data is not valid base64')
    payloads = decoded['image/svg+xml'] + decoded['image/png']
    if sorted(payloads) != sorted(produced):
        problems.append('embedded image payloads differ from the build output')
    for payload in decoded['image/svg+xml']:
        try:
            if ElementTree.fromstring(payload).tag.split('}')[-1] != 'svg':
                problems.append('embedded SVG has no svg root element')
        except ElementTree.ParseError as error:
            problems.append(f'embedded SVG is not well-formed XML: {error}')
    return problems, len(scan.images)

def check_pdf(path, version, commit, minimum_pages):
    problems = []
    for tool in ('pdfinfo', 'pdffonts', 'pdftotext'):
        if not shutil.which(tool):
            raise SystemExit(f'required tool missing: {tool} (poppler-utils)')
    if not path.read_bytes().startswith(b'%PDF-'):
        return ['PDF header is missing']
    info = subprocess.run(['pdfinfo', str(path)], check=True, capture_output=True, text=True).stdout
    pages = int(re.search(r'^Pages:\s+(\d+)', info, re.M)[1])
    if pages < minimum_pages:
        problems.append(f'PDF has {pages} pages, expected at least {minimum_pages}')
    fonts = subprocess.run(['pdffonts', str(path)], check=True, capture_output=True, text=True).stdout.splitlines()[2:]
    font_rows = [FONT_LINE.match(line) for line in fonts if line.strip()]
    if not font_rows or any(row is None for row in font_rows):
        problems.append('pdffonts output is not parseable or lists no fonts')
    else:
        for row in font_rows:
            if row['emb'] != 'yes':
                problems.append('font is not embedded: ' + row['name'])
    text = ' '.join(subprocess.run(['pdftotext', str(path), '-'], check=True, capture_output=True, text=True).stdout.split())
    if f'audiowmark {version}' not in text:
        problems.append(f'PDF text does not carry audiowmark {version}')
    if f'commit {commit}' not in text:
        problems.append('PDF text does not carry commit ' + commit)
    if 'Audio Watermarking' not in text:
        problems.append('PDF text lacks the manual heading "Audio Watermarking"')
    return problems

def check_browser(browser, path, expected_images):
    """Load the HTML alone in a headless browser and count images that decoded successfully."""
    script = ('<script>window.addEventListener("load",function(){var n=0;for(var i=0;i<document.images.length;i++)'
              'if(document.images[i].complete&&document.images[i].naturalWidth>0)n++;'
              'document.documentElement.setAttribute("data-loaded",n+"/"+document.images.length);});</script>')
    with tempfile.TemporaryDirectory(prefix='audiowmark-docs-alone-') as directory:
        alone = pathlib.Path(directory) / 'index.html'
        content = path.read_text(encoding='utf-8')
        alone.write_text(content.replace('</body>', script + '</body>') if '</body>' in content else content + script, encoding='utf-8')
        # Acceptance: the standalone file renders with no network. Every host fails to resolve and background traffic is off.
        result = subprocess.run([browser, '--headless', '--no-sandbox', '--disable-gpu', '--dump-dom',
                                 '--host-resolver-rules=MAP * ~NOTFOUND', '--disable-background-networking',
                                 '--virtual-time-budget=10000', alone.as_uri()],
                                capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        return [f'browser exited with status {result.returncode}']
    match = re.search(r'data-loaded="(\d+)/(\d+)"', result.stdout)
    if not match:
        return ['browser did not report image loading (script did not run)']
    loaded, total = int(match[1]), int(match[2])
    if loaded != total or total != expected_images:
        return [f'browser decoded {loaded}/{total} images from the standalone file, expected {expected_images}/{expected_images}']
    return []

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=pathlib.Path, required=True)
    parser.add_argument('--html', type=pathlib.Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--commit', required=True, help='full or 12-character source commit shown in the manual')
    parser.add_argument('--source', type=pathlib.Path, required=True, help='docs/audiowmark.md of the built revision')
    parser.add_argument('--build-docs', type=pathlib.Path, required=True, help='build directory holding graphviz-images/ and rendered PNGs')
    parser.add_argument('--minimum-pages', type=int, default=2)
    parser.add_argument('--browser', help='headless Chrome/Chromium used to render the standalone HTML')
    args = parser.parse_args()
    commit = args.commit[:12]
    problems, image_count = check_html(args.html, args.version, commit, args.source, args.build_docs)
    problems += check_pdf(args.pdf, args.version, commit, args.minimum_pages)
    if args.browser:
        problems += check_browser(args.browser, args.html, image_count)
    if problems:
        for problem in problems:
            print('error: ' + problem, file=sys.stderr)
        sys.exit(1)
    print(f'documentation verified: PDF and standalone HTML ({image_count} embedded images)')

if __name__ == '__main__':
    main()
