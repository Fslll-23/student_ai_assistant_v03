'use strict';
(() => {
  const S = window.BaoBaoChatStore;
  const composer = $('composer'), marker = document.createComment('home composer');
  composer.before(marker);
  let chats = [], current = null, database = null, partition = '', hydrated = false, saving = Promise.resolve();
  let refreshing = false, submitStarting = false, controller = null;
  let invalidated = false;
  let contextEpoch = '';
  const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('baobao-chat-updates') : null;
  const t = (zh,en) => translate(zh,en);
  const node = (tag,text,className) => {const el=document.createElement(tag); if(text!==undefined)el.textContent=text; if(className)el.className=className; return el;};
  function status(zh,en) { $('chat-storage-status').textContent=t(zh,en); $('chat-storage-status').hidden=false; }
  function error(message) { $('err').textContent=message; $('err').classList.remove('hidden'); }
  function apiError(data,code) { return [400,403,409,413,429,503].includes(code) && typeof data?.error === 'string' ? data.error : t('服务暂时未完成请求，请重试。','The service could not complete the request. Please retry.') + ` (${code})`; }
  function askConfirm(message) {
    const dialog=$('chat-confirm');
    if(dialog.open)return Promise.resolve(false);
    $('chat-confirm-copy').textContent=message;
    return new Promise(resolve=>{
      const finish=value=>{dialog.close();$('chat-confirm-accept').onclick=null;$('chat-confirm-cancel').onclick=null;dialog.oncancel=null;resolve(value);};
      $('chat-confirm-accept').onclick=()=>finish(true);
      $('chat-confirm-cancel').onclick=()=>finish(false);
      dialog.oncancel=event=>{event.preventDefault();finish(false);};
      dialog.showModal();$('chat-confirm-cancel').focus();
    });
  }
  async function session() {
    const response=await fetch('/chat/session',{cache:'no-store'});
    if(!response.ok) throw new Error('session');
    const identity=await response.json();contextEpoch=identity.context_epoch;return identity.partition;
  }
  function rememberActive() {
    if(!database)return;
    return database.put({id:'_state',active:current?.id,view:location.hash==='#chat'?'chat':'home',contextEpoch});
  }
  function save(notify=true) {
    if(!current)return Promise.resolve();
    current.updated=Date.now();
    const snapshot=structuredClone(current);
    saving=saving.catch(()=>{}).then(async()=>{
      if(invalidated)return;
      if(database){await database.put(snapshot); await rememberActive();}
      else throw new Error('Storage unavailable');
    }).then(()=>{if(notify)channel?.postMessage({partition,id:snapshot.id});}).catch(()=>{
      status('浏览器未能保存本次更改：当前可继续聊天，但刷新可能丢失内容。请复制重要初稿。','Changes could not be saved. You can continue, but refreshing may lose them. Copy important drafts.');
    });
    return saving;
  }
  function settings() { return {country:$('country').value,city:$('city').value,school:$('school').value,language:language(),category:$('category').value}; }
  function applySettings(chat) {
    if(chat.settings){
      $('country').value=chat.settings.country; updateCities(); $('city').value=chat.settings.city; updateSchools(); $('school').value=chat.settings.school;
      $('language').value=chat.settings.language; $('category').value=chat.settings.category;
    }
    activeMode=modes[chat.mode]?chat.mode:'chat'; replyMode=activeMode==='reply';
    $('composer-title').dataset.zh=modes[activeMode].zh; $('composer-title').dataset.en=modes[activeMode].en;
    applyLanguage(); $('chat-language').value=language();
  }
  function loadCurrent() {
    hydrated=false;
    documentContext=current.document || null;
    $('document').value=''; $('image').value=''; showPreview(); showDocument();
    $('text').value=current.input || ''; $('text').style.height='44px';
    applySettings(current); hydrated=true;
    $('err').classList.add('hidden');
    render();
  }
  function renderHistory() {
    $('chat-history').replaceChildren();
    for(const chat of [...chats].sort((a,b)=>b.updated-a.updated)) {
      const row=node('div',undefined,'chat-history-row');
      const select=node('button',chat.title || t('新聊天','New chat'),'chat-history-select'); select.type='button';
      select.setAttribute('aria-current',String(chat.id===current?.id)); select.title=chat.title || t('新聊天','New chat'); select.disabled=pending;
      select.addEventListener('click',()=>switchChat(chat.id));
      const remove=node('button',t('删除','Delete'),'chat-delete');remove.type='button';remove.disabled=pending;
      remove.setAttribute('aria-label',t('删除聊天：','Delete chat: ')+(chat.title || t('新聊天','New chat')));
      remove.addEventListener('click',()=>deleteChat(chat));row.append(select,remove);$('chat-history').append(row);
    }
  }
  function renderContext() {
    const box=$('chat-context-status');box.replaceChildren();
    for(const [kind,attachment] of [['document',current?.document],['image',current?.image]]) {
      if(!attachment)continue;
      if(attachment.expiresAt && attachment.expiresAt<=Date.now()) box.append(node('span',t('附件已到期，请重新上传：','Attachment expired; re-upload: ')+attachment.name+' '));
      else if(kind==='image')box.append(node('span',t('追问继续参考截图：','Screenshot context: ')+attachment.name+' '));
      if(kind==='image'){
        const remove=node('button',t('移除截图上下文','Remove screenshot context'));remove.type='button';remove.disabled=pending;
        remove.addEventListener('click',async()=>{await revoke(current.id,'image');current.image=null;save();renderContext();});box.append(remove);
      }
    }
    box.hidden=!box.childNodes.length;
  }
  function draftView(message,container) {
    if(!message.data.draft)return;
    const wrap=node('div',undefined,'chat-draft'), text=node('div',message.data.draft,'chat-draft-text');
    const controls=node('div',undefined,'chat-message-tools'), edit=node('button',t('编辑这份初稿','Edit this draft')), copy=node('button',t('复制初稿','Copy draft'));
    edit.type=copy.type='button';edit.disabled=pending;
    edit.addEventListener('click',()=>{
      if(pending)return;
      const editor=node('textarea',undefined,'chat-draft-editor');editor.value=message.data.draft;editor.maxLength=S.MAX_TEXT;
      editor.setAttribute('aria-label',t('可编辑初稿','Editable draft'));
      const commit=node('button',t('保存为当前初稿','Save as current draft')),cancel=node('button',t('取消','Cancel'));
      commit.type=cancel.type='button';
      text.replaceWith(editor);controls.replaceChildren(commit,cancel);
      commit.addEventListener('click',async()=>{
        if(!editor.value.trim()){error(t('初稿不能为空。','The draft cannot be empty.'));return;}
        current.draft=editor.value;message.data.draft=editor.value;message.edited=true;
        await save();render();
      });
      cancel.addEventListener('click',render);
      editor.focus({preventScroll:true});
    });
    copy.addEventListener('click',async()=>{
      try {await navigator.clipboard.writeText(message.data.draft);copy.textContent=t('已复制','Copied');}
      catch {copy.textContent=t('请点编辑后手动复制','Use Edit to copy manually');}
    });
    controls.append(edit,copy);wrap.append(node('h3',t('初稿（可编辑）','Editable draft')),text,controls);container.append(wrap);
  }
  function renderMessages() {
    const log=$('chat-messages'),oldScroll=log.scrollTop;
    log.replaceChildren();
    if(!current?.messages.length)log.append(node('p',t('把问题或作业发给 BaoBao，我们在这里接着聊。','Send a question or assignment, and we’ll work through it here.'),'chat-empty'));
    for(const message of current?.messages || []) {
      const item=node('article',undefined,'chat-message '+message.role);
      item.append(node('div',message.role==='user'?t('你','You'):'BaoBao','chat-speaker'));
      if(message.role==='user'){
        item.append(node('div',message.text || t('请分析附件','Please analyze the attachment')));
        for(const name of message.attachments || [])item.append(node('div','📎 '+name,'chat-attachment-name'));
        if(message.status==='error'){
          const box=node('div',message.error || t('请求未完成。','Request was interrupted.'),'chat-error');
          const retry=node('button',t('重试这条消息','Retry this message'));retry.type='button';retry.disabled=pending;
          retry.addEventListener('click',()=>submit(null,message));box.append(retry);item.append(box);
        }
      }else{
        const data=message.data;
        if(data.answer)item.append(node('div',data.answer,'chat-answer'));
        else{
          if(data.title)item.append(node('strong',data.title));
          if(usefulResultText(data.meaning))item.append(node('p',data.meaning));
          if(data.actions?.length){const list=node('ol');for(const text of data.actions)list.append(node('li',text));item.append(list);}
        }
        for(const [key,zh,en] of [['deadline','截止时间','Deadline'],['uncertainty','还需核实','Still to verify'],['risk','注意','Note']]){
          if(usefulResultText(data[key]) && !(data.answer || '').includes(data[key]))item.append(node('h3',t(zh,en)),node('p',data[key]));
        }
        if(data.reply_needed && data.reply_draft)item.append(node('h3',t('英文回复草稿','Reply draft')),node('p',data.reply_draft));
        draftView(message,item);
      }
      log.append(item);
    }
    if(pending)log.append(node('p',t('BaoBao 正在整理回答…','BaoBao is working on your answer…'),'chat-loading'));
    log.scrollTop=oldScroll;
  }
  function render() {
    $('chat-title').textContent=current?.title || t('和 BaoBao 聊聊','Chat with BaoBao');
    $('chat-quick').hidden=!current?.assignment;
    renderHistory();renderMessages();renderContext();
  }
  function bottom() {requestAnimationFrame(()=>{$('chat-messages').scrollTop=$('chat-messages').scrollHeight;});}
  function viewport() {
    const vv=window.visualViewport;
    $('chat-view').style.setProperty('--chat-height',`${vv?.height || window.innerHeight}px`);
    $('chat-view').style.setProperty('--chat-top',`${vv?.offsetTop || 0}px`);
  }
  function route() {
    const visible=location.hash==='#chat';
    $('chat-view').hidden=!visible;document.body.classList.toggle('chat-open',visible);
    if(visible){$('chat-composer-host').append(composer);viewport();bottom();}
    else marker.after(composer);
    rememberActive()?.catch(()=>{});
  }
  async function open(mode) {
    await ready;
    if(!current)return;
    if(mode && modes[mode]){current.mode=mode;current.settings=settings();save();}
    location.hash='chat';route();$('chat-language').value=language();
  }
  function closeHistory() { $('chat-view').classList.remove('history-open');$('chat-history-toggle').setAttribute('aria-expanded','false'); }
  async function switchChat(id) {
    if(pending || submitStarting)return;
    if(current?.id===id){closeHistory();return;}
    if(document.querySelector('.chat-draft-editor') && !await askConfirm(t('放弃未保存的初稿修改？','Discard unsaved draft edits?')))return;
    if(($('document').files.length || $('image').files.length) && !await askConfirm(t('切换聊天将移除尚未发送的附件，继续吗？','Switching chats removes unsent attachments. Continue?')))return;
    current.input=$('text').value;current.settings=settings();await save();
    current=chats.find(chat=>chat.id===id);loadCurrent();await rememberActive();closeHistory();bottom();
  }
  async function create() {
    await ready;
    if(pending || submitStarting)return;
    if(document.querySelector('.chat-draft-editor') && !await askConfirm(t('放弃未保存的初稿修改？','Discard unsaved draft edits?')))return;
    if(chats.length>=S.MAX_CHATS){status('已达到 20 个聊天，请先删除不需要的记录。','You have 20 chats. Delete one before creating another.');return;}
    if(($('document').files.length || $('image').files.length) && !await askConfirm(t('新聊天将移除尚未发送的附件，继续吗？','A new chat removes unsent attachments. Continue?')))return;
    if(current){current.input=$('text').value;current.settings=settings();await save();}
    current=S.newChat();current.settings={...settings(),category:modes.chat.category};chats.push(current);loadCurrent();await save();closeHistory();await open();
  }
  async function revoke(id,kind) {
    const response=await fetch('/chat/context',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({chat_id:id,kind})});
    if(!response.ok)throw new Error(t('未能清除附件上下文，请重试。','Could not clear attachment context. Please retry.'));
  }
  async function deleteChat(chat) {
    if(pending || !await askConfirm(t('删除这个聊天和它的附件上下文？此操作无法撤销。','Delete this chat and its attachment context? This cannot be undone.')))return;
    try{
      await saving;await revoke(chat.id);await database?.remove(chat.id);
      chats=chats.filter(x=>x.id!==chat.id);
      if(current.id===chat.id){current=chats[0] || S.newChat();if(!chats.length)chats.push(current);loadCurrent();await save(false);}
      render();channel?.postMessage({partition,deleted:chat.id});
    }catch(exc){status(exc.message,exc.message);}
  }
  async function clearAll() {
    if(pending || !await askConfirm(t('清除本机全部聊天、初稿和附件上下文？此操作无法撤销。共用设备交接前建议清除。','Clear all local chats, drafts and attachment context? This cannot be undone.')))return;
    try{
      await saving;const response=await fetch('/chat/session',{method:'DELETE'});if(!response.ok)throw new Error('clear');
      await database?.clear();
      localStorage.removeItem(HISTORY_KEY);sessionStorage.removeItem('baobao_document_v1');
      channel?.postMessage({reset:true});location.reload();
    }catch{status('清除未完成，请保持页面打开后重试。','Clearing did not finish. Please keep this page open and retry.');}
  }
  function lock(value) {
    pending=value;
    for(const element of [$('go'),$('language'),$('chat-language'),$('document'),$('image'),$('upload-document'),$('remove-document'),$('remove-image'),$('chat-new'),$('chat-clear'),$('chat-home'),...document.querySelectorAll('[data-mode],[data-chat-prompt]')])element.disabled=value;
    $('busy').classList.toggle('hidden',!value);$('question-form').setAttribute('aria-busy',String(value));render();
  }
  async function submit(event,retry) {
    event?.preventDefault();
    if(pending || submitStarting)return;
    if(document.querySelector('.chat-draft-editor')){error(t('请先保存或取消初稿编辑，再发送消息。','Save or cancel draft edits before sending.'));return;}
    submitStarting=true;
    await ready;
    if(!current){submitStarting=false;error(t('未能初始化聊天，请刷新重试。','Chat could not initialize. Please reload.'));return;}
    await open();
    const chat=current,text=retry?retry.text:$('text').value.trim();
    const image=$('image').files[0],documentFile=$('document').files[0];
    $('err').classList.add('hidden');
    if(!text && !image && !documentFile && !chat.document && !chat.image){submitStarting=false;error(t('请写下问题或上传附件。','Enter a question or upload an attachment.'));return;}
    if((!documentFile && chat.document?.expiresAt<Date.now()) || (!image && chat.image?.expiresAt<Date.now())){
      submitStarting=false;error(t('附件上下文已失效，请重新上传，或移除附件后继续。聊天和初稿仍已保留。','Attachment context expired. Re-upload or remove it to continue. Your chat and draft are preserved.'));return;
    }
    if(retry && ((retry.needsDocument && !documentFile && !chat.document) || (retry.needsImage && !image && !chat.image))){submitStarting=false;error(t('这条消息的原附件未保存在浏览器中，请重新选择附件后重试。','Please reselect the attachment for this interrupted message.'));return;}
    // Capture a complete, per-chat request before awaiting any network operation.
    const form=new FormData();
    chat.settings=settings();
    form.append('chat_mode','1');form.append('chat_id',chat.id);form.append('language',language());
    form.append('school',`${chat.settings.country} / ${chat.settings.city} / ${chat.settings.school}`);
    form.append('category',$('category').value);form.append('intent',replyMode?'reply':'analyze');
    form.append('text',modes[activeMode].prompt?`${modes[activeMode].prompt}\n\n用户当前问题：${text || '请分析附件'}`:text);
    form.append('history',JSON.stringify(S.historyFor(chat)));form.append('working_draft',chat.draft || '');
    if(documentFile)form.append('document',documentFile);else if(chat.document)form.append('document_context',chat.document.id);
    if(image)form.append('image',image);else if(chat.image)form.append('image_context',chat.image.id);
    let message=retry;
    if(!message){
      message={id:crypto.randomUUID(),role:'user',text,attachments:[documentFile?.name,image?.name].filter(Boolean),needsDocument:!!documentFile,needsImage:!!image,status:'pending'};
      chat.messages.push(message);
    }else{chat.messages=chat.messages.filter(x=>x.id!==message.id);chat.messages.push(message);message.status='pending';delete message.error;}
    if(!chat.title)chat.title=(text || documentFile?.name || image?.name || t('附件对话','Attachment chat')).slice(0,60);
    chat.input='';$('text').value='';$('text').style.height='44px';
    lock(true);submitStarting=false;await save();bottom();
    controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),110000);
    try{
      const response=await fetch('/analyze',{method:'POST',body:form,signal:controller.signal});
      let data;try{data=await response.json();}catch{throw new Error(t('服务返回格式异常，请重试。','Invalid response; please retry.'));}
      if(!response.ok)throw new Error(apiError(data,response.status));
      if(!data || typeof data!=='object' || Array.isArray(data))throw new Error(t('回答格式异常。','Invalid answer.'));
      chat.document=data._document || chat.document;chat.image=data._image || chat.image;
      if(documentFile || image)message.attachments=[documentFile?.name,image?.name].filter(Boolean);
      const answer=S.safeResult(data);chat.assignment=answer.assignment || chat.assignment;
      if(answer.draft)chat.draft=answer.draft;
      message.status='done';chat.messages.push({id:crypto.randomUUID(),role:'assistant',data:answer});
      if(chat.messages.length>S.MAX_MESSAGES){chat.messages=chat.messages.slice(-S.MAX_MESSAGES);while(chat.messages[0]?.role!=='user')chat.messages.shift();}
      hydrated=false;documentContext=chat.document;$('document').value='';$('image').value='';showDocument();showPreview();hydrated=true;
    }catch(exc){message.status='error';message.error=exc.name==='AbortError'?t('等待超时，可重试这条消息。','Timed out. You can retry this message.'):exc instanceof TypeError?t('连接中断，请检查网络后重试。','Connection interrupted. Check your network and retry.'):exc.message;}
    finally{clearTimeout(timeout);controller=null;if(!invalidated){lock(false);await save();bottom();}}
  }
  async function initialize() {
    try{
      partition=await session();
      try{database=await new S.ChatDatabase(partition).open();}catch{status('本地存储不可用，本次聊天仅在内存中，刷新会丢失。','Local storage is unavailable. This chat is temporary and will be lost on refresh.');}
      const records=database?await database.all():[],state=records.find(x=>x.id==='_state');
      chats=records.filter(x=>x.id!=='_state' && Array.isArray(x.messages));
      if(state && state.contextEpoch!==contextEpoch){
        for(const chat of chats){
          for(const kind of ['document','image'])if(chat[kind])chat[kind].expiresAt=Date.now()-1;
          await database.put(chat);
        }
      }
      for(const chat of chats)for(const msg of chat.messages)if(msg.status==='pending'){msg.status='error';msg.error=t('页面关闭时请求未完成，可以重试。','The request was interrupted when the page closed. Retry it.');}
      if(!chats.length){
        current=S.newChat();current.settings=settings();chats.push(current);
        // Migrate existing text history once; legacy attachment tokens have no chat binding.
        try{
          const old=boundedHistory(JSON.parse(localStorage.getItem(HISTORY_KEY)||'[]'));
          if(old.length){current.title=t('之前的对话','Previous conversation');
            for(const item of old){let data;try{data=JSON.parse(item.content);}catch{data={answer:item.content};}
              current.messages.push(item.role==='user'?{id:crypto.randomUUID(),role:'user',text:item.content,status:'done'}:{id:crypto.randomUUID(),role:'assistant',data:S.safeResult(data)});}
            status('已保留之前的文字对话；旧附件如需继续使用，请重新上传一次。','Previous text conversation restored. Re-upload old attachments once if needed.');
          }
          if(database){await database.put(current);localStorage.removeItem(HISTORY_KEY);sessionStorage.removeItem('baobao_document_v1');}
        }catch{/* Keep legacy history if migration could not be saved. */}
      }else current=chats.find(x=>x.id===state?.active)||chats.sort((a,b)=>b.updated-a.updated)[0];
      loadCurrent();
      if(state?.view==='chat' && (!location.hash || location.hash==='#chat'))location.hash='chat';
      route();await save(false);
    }catch{error(t('聊天服务暂时无法连接，请刷新页面重试。','Chat service is unavailable. Please reload to retry.'));}
  }
  const ready=initialize();
  window.BaoBaoChat={open,submit,ready,documentChanged(value){
    if(!hydrated || !current)return;
    if(!value && current.document)revoke(current.id,'document').catch(()=>status('文件已从当前聊天移除；服务器副本会在到期后清除。','File detached locally; the server copy will expire.'));
    current.document=value;save();renderContext();
  }};
  $('chat-home').addEventListener('click',()=>{if(!pending){current.input=$('text').value;save();location.hash='home';}});
  $('chat-new').addEventListener('click',create);$('chat-clear').addEventListener('click',clearAll);
  $('chat-history-toggle').addEventListener('click',()=>{const expanded=$('chat-view').classList.toggle('history-open');$('chat-history-toggle').setAttribute('aria-expanded',String(expanded));});
  $('chat-close-history').addEventListener('click',closeHistory);
  $('chat-language').addEventListener('change',()=>{$('language').value=$('chat-language').value;applyLanguage();showDocument();render();current.settings=settings();save();});
  $('language').addEventListener('change',()=>{if(current){$('chat-language').value=language();current.settings=settings();save();render();}});
  let inputTimer;
  $('text').addEventListener('input',()=>{if(!current)return;current.input=$('text').value;clearTimeout(inputTimer);inputTimer=setTimeout(()=>save(false),250);});
  $('text').addEventListener('keydown',event=>{if(event.key==='Enter' && !event.shiftKey && !event.isComposing && matchMedia('(min-width:701px)').matches){event.preventDefault();submit(event);}});
  for(const id of ['image','document'])$(id).addEventListener('change',()=>{if($(id).files.length)open();});
  document.querySelectorAll('[data-chat-prompt]').forEach(button=>button.addEventListener('click',()=>{
    const prompts={draft:t('帮我完成一下吧，请生成可编辑初稿。','Help me draft this assignment.'),steps:t('一步步带我做，先一起完成第一步的实际内容。','Guide me step by step, starting with the actual first step.'),review:t('帮我检查作业，按照原文件要求检查当前初稿。','Review my current draft against the assignment requirements.')};
    $('text').value=prompts[button.dataset.chatPrompt];submit();
  }));
  window.addEventListener('hashchange',route);window.addEventListener('resize',viewport);
  window.visualViewport?.addEventListener('resize',viewport);window.visualViewport?.addEventListener('scroll',viewport);
  channel?.addEventListener('message',async event=>{
    if(event.data.reset){invalidated=true;controller?.abort();location.reload();return;}
    if(event.data.partition!==partition || !database)return;
    if(event.data.deleted===current?.id){invalidated=true;controller?.abort();location.reload();return;}
    // Never overwrite unsent edits or an in-flight answer with another tab's version.
    if(pending || $('text').value || document.querySelector('.chat-draft-editor')){status('另一个标签页修改了聊天。请完成当前操作后刷新，避免同时编辑。','Another tab changed a chat. Finish your work, then refresh; avoid simultaneous editing.');return;}
    if(refreshing)return;refreshing=true;
    try{const records=await database.all();chats=records.filter(x=>x.id!=='_state');current=chats.find(x=>x.id===current?.id)||current;loadCurrent();}finally{refreshing=false;}
  });
})();
