"""Bounded, temporary document extraction; no uploaded originals are saved."""
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import zipfile
from collections import OrderedDict

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 60000
MAX_PAGES = 100
MAX_XML_BYTES = 20 * 1024 * 1024
CONTEXT_TTL = 8 * 60 * 60


class DocumentError(ValueError):
    pass


def extract_upload(upload):
    name = (upload.filename or '').replace('\\', '/').split('/')[-1][:200]
    suffix = Path(name).suffix.lower()
    if suffix not in {'.pdf', '.docx'}:
        raise DocumentError('只支持 PDF、DOCX 文件（不支持旧版 DOC）。Only PDF and DOCX are supported.')
    raw = upload.stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise DocumentError('文件大小不能超过 8 MB。Maximum file size: 8 MB.')
    if not raw:
        raise DocumentError('文件为空，请重新选择。The file is empty.')
    if not raw.startswith(b'%PDF-' if suffix == '.pdf' else b'PK\x03\x04'):
        raise DocumentError('文件内容与扩展名不匹配。File content does not match its extension.')
    # A separate process bounds CPU time and prevents parser failures blocking Flask.
    # Do not pass application credentials to the parser process.
    try:
        result = subprocess.run(
            [sys.executable, '-B', str(Path(__file__).resolve()), suffix],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=15, env={key: os.environ[key] for key in ('PATH', 'SYSTEMROOT') if key in os.environ},
        )
        if result.returncode:
            raise DocumentError('文件损坏或解析资源超限，请上传较小的有效文件。File is damaged or too complex.')
        data = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise DocumentError('文件解析超时，请拆分文件后重试。Parsing timed out; please split the file.') from None
    if 'error' in data:
        raise DocumentError(data['error'])
    return {'name': name, 'text': data['text'], 'warning': data['warning']}


class DocumentContexts:
    """Short-lived, bounded in-memory text, addressed by an unguessable token."""
    def __init__(self, capacity=32):
        self.items = OrderedDict()
        self.lock = threading.Lock()
        self.capacity = capacity
        threading.Thread(target=self._cleanup, daemon=True).start()

    def _cleanup(self):
        while True:
            time.sleep(60)
            with self.lock:
                self._expire()

    def _expire(self):
        now = time.monotonic()
        for token, item in list(self.items.items()):
            if item[0] <= now:
                del self.items[token]

    def put(self, document, owner='', conversation='legacy'):
        with self.lock:
            self._expire()
            if owner:
                for token, item in list(self.items.items()):
                    if item[2:] == (owner, conversation):
                        del self.items[token]
            while len(self.items) >= self.capacity:
                self.items.popitem(last=False)
            token = secrets.token_urlsafe(32)
            self.items[token] = (time.monotonic() + CONTEXT_TTL, document, owner, conversation)
            return token

    def get(self, token, owner='', conversation='legacy'):
        with self.lock:
            self._expire()
            item = self.items.get(token)
            if not item or item[2:] != (owner, conversation):
                raise DocumentError('文件上下文已过期或服务已重启，请重新上传文件。Document expired; please upload it again.')
            return item[1]

    def delete(self, owner, conversation=None):
        with self.lock:
            for token, item in list(self.items.items()):
                if item[2] == owner and (conversation is None or item[3] == conversation):
                    del self.items[token]

    def expires_at(self, token):
        with self.lock:
            item = self.items.get(token)
            return int((time.time() + max(0, item[0] - time.monotonic())) * 1000) if item else 0


def _extract(raw, suffix):
    pieces = []
    total = 0

    def add(text):
        nonlocal total
        total += len(text) + 1
        if total > MAX_TEXT_CHARS:
            raise DocumentError('文件文字超过 60,000 字符，请拆分后上传；未截断分析。Text exceeds 60,000 characters; please split the file.')
        pieces.append(text)

    warning = '仅提取文字；文件内图片、图表和复杂排版未解析。Text only; embedded images, charts and complex layout are not read.'
    if suffix == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise DocumentError('不支持加密 PDF，请先解密再上传。Encrypted PDFs are not supported.')
        if len(reader.pages) > MAX_PAGES:
            raise DocumentError('PDF 不能超过 100 页，请拆分后上传。PDF limit: 100 pages.')
        empty = []
        for index, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or '').strip()
            if text:
                add(f'[PDF page {index}]\n{text}\n')
            else:
                empty.append(str(index))
        if not pieces:
            raise DocumentError('无法从 PDF 提取文字，可能是扫描件。尚未阅读成功；请上传清晰截图或带文字层的 PDF。No readable text: upload screenshots or a text-based PDF.')
        if empty:
            warning += '\n以下页未提取到文字（可能是扫描页或空白页），不能视为已阅读：' + ', '.join(empty) + '. Pages without readable text: ' + ', '.join(empty)
    else:
        from defusedxml.ElementTree import fromstring
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if (len(entries) > 1000 or sum(item.file_size for item in entries) > MAX_XML_BYTES
                    or any(item.flag_bits & 1 for item in entries)):
                raise DocumentError('DOCX 解压大小超限或已加密，请使用较小的未加密文件。DOCX is too large when unpacked or encrypted.')
            names = archive.namelist()
            if len(set(names)) != len(names) or 'word/document.xml' not in names or '[Content_Types].xml' not in names:
                raise DocumentError('不是有效的 DOCX 文件。Invalid DOCX file.')
            types = fromstring(archive.read('[Content_Types].xml'))
            if not any(item.attrib.get('ContentType') == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml' for item in types):
                raise DocumentError('只支持普通 DOCX，不支持宏文档或其他 Office 格式。Only standard DOCX is supported.')
            selected = ['word/document.xml'] + sorted(name for name in names if
                name.startswith(('word/header', 'word/footer', 'word/footnotes', 'word/endnotes')) and name.endswith('.xml'))
            namespace = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            for name in selected:
                root = fromstring(archive.read(name))
                # Preserve real XML locations without inventing Word page numbers.
                part = '正文' if name == 'word/document.xml' else (
                    '页眉' if name.startswith('word/header') else
                    '页脚' if name.startswith('word/footer') else
                    '脚注' if name.startswith('word/footnotes') else '尾注'
                ) + f'（{Path(name).name}）'
                parents = {child: parent for parent in root.iter() for child in parent}
                cells = {}
                for table_index, table in enumerate(root.iter(namespace + 'tbl'), 1):
                    for row_index, row in enumerate(table.findall(namespace + 'tr'), 1):
                        for cell_index, cell in enumerate(row.findall(namespace + 'tc'), 1):
                            cells[cell] = f' 表格 {table_index} 行 {row_index} 列 {cell_index}'
                for paragraph_index, paragraph in enumerate(root.iter(namespace + 'p'), 1):
                    text = ''.join(node.text or '' if node.tag == namespace + 't' else
                                   '\t' if node.tag == namespace + 'tab' else '\n' if node.tag == namespace + 'br' else ''
                                   for node in paragraph.iter()).strip()
                    if text:
                        ancestor = parents.get(paragraph)
                        while ancestor is not None and ancestor not in cells:
                            ancestor = parents.get(ancestor)
                        location = f'{part}{cells.get(ancestor, "")} 段落 {paragraph_index}'
                        add(f'[DOCX {location}]\n{text}\n')
        if not pieces:
            raise DocumentError('DOCX 中没有可提取的文字，可能只有图片；请上传截图。No readable DOCX text; upload screenshots instead.')
    return {'text': '\n'.join(pieces), 'warning': warning}


if __name__ == '__main__':
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
        if sys.platform == 'darwin':
            # macOS rejects address-space/data limits. Monitor this worker's RSS.
            def watch_memory():
                while True:
                    if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > 512 * 1024 * 1024:
                        os._exit(2)
                    time.sleep(0.05)
            threading.Thread(target=watch_memory, daemon=True).start()
        else:
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        raw = sys.stdin.buffer.read(MAX_DOCUMENT_BYTES + 1)
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise DocumentError('文件大小不能超过 8 MB。Maximum file size: 8 MB.')
        output = _extract(raw, sys.argv[1])
    except DocumentError as exc:
        output = {'error': str(exc)}
    except Exception:
        output = {'error': '无法解析文件，文件可能损坏或格式不受支持。Unable to parse this file; it may be damaged or unsupported.'}
    print(json.dumps(output, ensure_ascii=False))
