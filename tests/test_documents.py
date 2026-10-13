"""Real parser fixtures and isolated API contract tests (not live AI validation)."""
import io
import json
import subprocess
import unittest
import zipfile
from datetime import datetime, timezone
from unittest.mock import patch
from xml.sax.saxutils import escape

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject
from werkzeug.datastructures import FileStorage

from document_uploads import DocumentContexts, DocumentError, extract_upload
import test_app


def pdf_bytes(text='BIO204 Assignment: Write a 900-word report. Deadline: 23 October 2026 at 17:00 Sydney time.', blank=False, encrypted=False, pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        if not blank:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
            stream = DecodedStreamObject()
            literal = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            stream.set_data(f'BT /F1 12 Tf 40 700 Td ({literal}) Tj ET'.encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
        else:
            # A real image-only PDF, rather than a renamed file or empty byte string.
            image = DecodedStreamObject()
            image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'), NameObject('/Width'): NumberObject(10), NameObject('/Height'): NumberObject(10), NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): NumberObject(8)})
            image.set_data(b'\x88\x88\x88' * 100)
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/Scan'): writer._add_object(image)})})
            stream = DecodedStreamObject()
            stream.set_data(b'q 100 0 0 100 40 500 cm /Scan Do Q')
            page[NameObject('/Contents')] = writer._add_object(stream)
    if encrypted:
        writer.encrypt('test-password')
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def docx_bytes(text='HIST321: Compare two primary sources. Write 750 words. First, select the two sources.', table='Submission code: MAPLE-72', extra_xml=''):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>' + escape(table) + '</w:t></w:r></w:p></w:tc></w:tr></w:tbl>' + extra_xml + '</w:body></w:document>')
    return output.getvalue()


class ParserTests(unittest.TestCase):
    def extract(self, raw, name):
        return extract_upload(FileStorage(stream=io.BytesIO(raw), filename=name))

    def test_real_pdf_and_docx_paragraphs_tables_unicode(self):
        self.assertIn('23 October 2026', self.extract(pdf_bytes(), 'brief.PDF')['text'])
        result = self.extract(docx_bytes('作业要求：分析两个案例。'), 'brief.docx')
        self.assertIn('两个案例', result['text'])
        self.assertIn('MAPLE-72', result['text'])

    def test_extraction_preserves_verifiable_source_locations(self):
        result = self.extract(docx_bytes('Write 750 words.', 'Due: 10 October 2026.'), 'brief.docx')
        self.assertIn('[DOCX 正文 段落 1]\nWrite 750 words.', result['text'])
        self.assertIn('[DOCX 正文 表格 1 行 1 列 1 段落 2]\nDue: 10 October 2026.', result['text'])
        self.assertNotIn('page', result['text'])
        pdf = self.extract(pdf_bytes(pages=2), 'brief.pdf')
        self.assertIn('[PDF page 1]', pdf['text'])
        self.assertIn('[PDF page 2]', pdf['text'])

    def test_source_locations_distinguish_body_header_and_footnotes(self):
        buffer = io.BytesIO(docx_bytes())
        with zipfile.ZipFile(buffer, 'a') as archive:
            for name, tag, text in [('header1.xml', 'hdr', 'Header reference'), ('footnotes.xml', 'footnotes', 'Footnote reference')]:
                archive.writestr('word/' + name, f'<w:{tag} xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:{tag}>')
        result = self.extract(buffer.getvalue(), 'brief.docx')
        self.assertIn('[DOCX 页眉（header1.xml） 段落 1]\nHeader reference', result['text'])
        self.assertIn('[DOCX 脚注（footnotes.xml） 段落 1]\nFootnote reference', result['text'])

    def test_empty_scan_encrypted_corrupt_and_unsupported(self):
        for raw, name, message in [
            (pdf_bytes(blank=True), 'scan.pdf', '无法从 PDF 提取文字'),
            (pdf_bytes(encrypted=True), 'secret.pdf', '加密 PDF'),
            (b'%PDF-1.7\nbroken', 'broken.pdf', '无法解析'),
            (b'PK\x03\x04broken', 'broken.docx', '无法解析'),
            (b'not pdf', 'fake.pdf', '不匹配'),
            (b'', 'empty.docx', '文件为空'),
            (b'text', 'old.doc', '只支持 PDF'),
            (docx_bytes('', ''), 'image.docx', '没有可提取'),
        ]:
            with self.subTest(name=name), self.assertRaisesRegex(DocumentError, message):
                self.extract(raw, name)

    def test_limits_and_timeout(self):
        for raw, name, message in [
            (b'%PDF-' + b'x' * (8 * 1024 * 1024), 'large.pdf', '8 MB'),
            (pdf_bytes(pages=101), 'long.pdf', '100 页'),
            (docx_bytes('x' * 60001), 'long.docx', '60,000'),
            (docx_bytes('x' * (21 * 1024 * 1024)), 'bomb.docx', '解压大小超限'),
        ]:
            with self.subTest(name=name), self.assertRaisesRegex(DocumentError, message):
                self.extract(raw, name)
        with patch('document_uploads.subprocess.run', side_effect=subprocess.TimeoutExpired('parser', 15)):
            with self.assertRaisesRegex(DocumentError, '超时'):
                self.extract(pdf_bytes(), 'slow.pdf')

    def test_partial_pdf_has_explicit_unread_page_warning(self):
        writer = PdfWriter()
        from pypdf import PdfReader
        writer.append(PdfReader(io.BytesIO(pdf_bytes())))
        writer.add_blank_page(width=612, height=792)
        buffer = io.BytesIO(); writer.write(buffer)
        result = self.extract(buffer.getvalue(), 'mixed.pdf')
        self.assertIn('不能视为已阅读：2', result['warning'])

    def test_zip_xml_entities_rejected(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            archive.writestr('[Content_Types].xml', '<!DOCTYPE x [<!ENTITY attack SYSTEM "file:///etc/passwd">]><Types>&attack;</Types>')
            archive.writestr('word/document.xml', '<doc/>')
        with self.assertRaisesRegex(DocumentError, '无法解析'):
            self.extract(raw.getvalue(), 'entities.docx')

    def test_context_expiry_capacity_and_unknown_id(self):
        contexts = DocumentContexts()
        token = contexts.put({'text': 'document'})
        self.assertEqual(contexts.get(token)['text'], 'document')
        with patch('document_uploads.time.monotonic', return_value=10**12):
            with self.assertRaisesRegex(DocumentError, '过期'):
                contexts.get(token)
        for number in range(33):
            contexts.put({'text': str(number)})
        self.assertEqual(len(contexts.items), 32)
        with self.assertRaises(DocumentError):
            contexts.get('guessed-token')


class DocumentRouteTests(unittest.TestCase):
    setUpClass = classmethod(test_app.AnalysisRegressionTests.setUpClass.__func__)
    setUp = test_app.AnalysisRegressionTests.setUp

    def test_accuracy_clock_uses_sydney_date_and_explicit_utc_across_midnight(self):
        instruction = self.app.view_functions['analyze'].__globals__['document_accuracy_instruction']
        before = instruction(datetime(2026, 10, 11, 12, 59, tzinfo=timezone.utc))
        after = instruction(datetime(2026, 10, 11, 13, 1, tzinfo=timezone.utc))
        self.assertIn('2026-10-11T23:59:00+11:00', before)
        self.assertIn('2026-10-12T00:01:00+11:00', after)
        self.assertIn('UTC：2026-10-11T13:01:00+00:00', after)

    def test_followup_refreshes_clock_and_keeps_original_sources_and_contract(self):
        namespace = self.app.view_functions['analyze'].__globals__
        instruction = namespace['document_accuracy_instruction']
        moments = iter([datetime(2026, 10, 11, 12, 59, tzinfo=timezone.utc), datetime(2026, 10, 11, 13, 1, tzinfo=timezone.utc)])
        with patch.dict(namespace, {'document_accuracy_instruction': lambda: instruction(next(moments))}):
            first = self.client.post('/analyze', data={'document': (io.BytesIO(docx_bytes()), 'brief.docx')})
            first_payload = self.post.call_args.kwargs['json']
            second = self.client.post('/analyze', data={'text': '然后呢？', 'document_context': first.json['_document']['id']})
            second_payload = self.post.call_args.kwargs['json']
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual({key: value for key, value in second.json.items() if key != '_document'}, self.result)
        self.assertIn('2026-10-11T23:59', first_payload['messages'][0]['content'])
        self.assertIn('2026-10-12T00:01', second_payload['messages'][0]['content'])
        self.assertEqual(first_payload['messages'][-1]['content'][1], second_payload['messages'][-1]['content'][1])
        self.assertIn('[DOCX 正文 段落 1]', second_payload['messages'][-1]['content'][1]['text'])
        prompt = second_payload['messages'][0]['content']
        for phrase in ['已过期', '今天截止，具体时间未注明', '缺少年份', '多个截止时间须逐项判断', '建议（非文件要求）', '不得虚构页码', '不能推断用户未交']:
            self.assertIn(phrase, prompt)

    def test_file_question_followup_and_image_together(self):
        response = self.client.post('/analyze', data={'text': '这份作业要求我做什么？', 'document': (io.BytesIO(pdf_bytes()), 'brief.pdf')})
        self.assertEqual(response.status_code, 200)
        token = response.json['_document']['id']
        content = self.post.call_args.kwargs['json']['messages'][-1]['content']
        self.assertIn('900-word', content[1]['text'])
        system = self.post.call_args.kwargs['json']['messages'][0]['content']
        self.assertIn('文件中未找到明确截止时间', system)
        history = [{'role': 'user', 'content': '这份作业要求我做什么？'}, {'role': 'assistant', 'content': '先读要求。'}]
        response = self.client.post('/analyze', data={'text': '然后呢？', 'document_context': token, 'history': json.dumps(history), 'image': (io.BytesIO(b'\x89PNG\r\n\x1a\nfixture'), 'image.png')})
        self.assertEqual(response.status_code, 200)
        messages = self.post.call_args.kwargs['json']['messages']
        self.assertEqual(messages[1:3], history)
        self.assertIn('900-word', messages[-1]['content'][1]['text'])
        self.assertEqual(messages[-1]['content'][2]['type'], 'image_url')

    def test_docx_only_and_replacement(self):
        response = self.client.post('/analyze', data={'document': (io.BytesIO(docx_bytes()), 'brief.docx')})
        self.assertEqual(response.status_code, 200)
        token = response.json['_document']['id']
        response = self.client.post('/analyze', data={'document_context': token, 'document': (io.BytesIO(pdf_bytes()), 'new.pdf')})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json['_document']['id'], token)
        text = self.post.call_args.kwargs['json']['messages'][-1]['content'][1]['text']
        self.assertIn('BIO204', text)
        self.assertNotIn('HIST321', text)

    def test_invalid_files_context_and_request_limit_do_not_call_ai(self):
        for data in [{'document_context': 'unknown', 'text': '然后呢'}, {'document': (io.BytesIO(pdf_bytes(blank=True)), 'scan.pdf')}, {'document': (io.BytesIO(b'old'), 'old.doc')}]:
            self.assertEqual(self.client.post('/analyze', data=data).status_code, 400)
        response = self.client.post('/analyze', data=b'x' * (18 * 1024 * 1024 + 1), content_type='application/octet-stream')
        self.assertEqual(response.status_code, 413)
        self.assertIn('8 MB', response.json['error'])
        self.post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
