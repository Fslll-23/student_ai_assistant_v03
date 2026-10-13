'use strict';
// Keep document attachments separate from the existing conversation history.
let documentContext = null;
function storeDocumentContext(value) {
  documentContext = value;
  window.BaoBaoChat?.documentChanged(value);
}
function showDocument() {
  const file = $('document').files[0];
  $('document-box').classList.toggle('hidden', !file && !documentContext);
  $('document-name').textContent = file ? translate('待分析文件：', 'Selected file: ') + file.name :
    documentContext ? (documentContext.expiresAt<Date.now() ? translate('文件需要重新上传：', 'Re-upload this file: ') : translate('追问将继续参考：', 'Follow-ups will refer to: ')) + documentContext.name : '';
  $('document-warning').textContent = file ? translate('最多 8 MB；只提取文字，不识别文件内图片。', 'Up to 8 MB; text extraction only, no embedded image recognition.') :
    documentContext ? documentContext.warning + '\n' + translate('文件上下文有效期最多 8 小时，服务重启或上下文失效后需重新上传。', 'Document context is valid for up to 8 hours. Re-upload after a restart or expiry.') : '';
}
function hasDocument() { return !!($('document').files[0] || documentContext); }
function appendDocument(form) {
  const file = $('document').files[0];
  if (file) form.append('document', file);
  else if (documentContext) form.append('document_context', documentContext.id);
}
function acceptDocumentResult(data) {
  if (data._document && typeof data._document.id === 'string') {
    storeDocumentContext(data._document);
    $('document').value = '';
    showDocument();
  }
  delete data._document;
}
$('upload-document').addEventListener('click', () => { if (!pending) $('document').click(); });
$('document').addEventListener('change', () => {
  const file = $('document').files[0];
  if (!file) { showDocument(); return; }
  if (!/\.(pdf|docx)$/i.test(file.name) || !file.size || file.size > 8 * 1024 * 1024) {
    $('document').value = '';
    $('err').textContent = translate('请选择非空 PDF 或 DOCX 文件，大小不能超过 8 MB。', 'Choose a non-empty PDF or DOCX file, up to 8 MB.');
    $('err').classList.remove('hidden');
  } else {
    storeDocumentContext(null);
    $('err').classList.add('hidden');
  }
  showDocument();
});
$('remove-document').addEventListener('click', () => {
  if (pending) return;
  $('document').value = '';
  storeDocumentContext(null);
  showDocument();
});
$('language').addEventListener('change', showDocument);
showDocument();
