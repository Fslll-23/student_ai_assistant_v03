'use strict';
(() => {
  const MAX_CHATS = 20, MAX_MESSAGES = 40, MAX_TEXT = 60000;
  const newChat = (mode = 'chat') => ({id: crypto.randomUUID(), title: '', mode, messages: [], draft: '', input: '', document: null, image: null, assignment: false, updated: Date.now()});
  function historyFor(chat) {
    const pairs = [];
    for (let i = 0; i < chat.messages.length - 1; i++) {
      const user = chat.messages[i], assistant = chat.messages[i + 1];
      if (user.role === 'user' && user.status === 'done' && assistant.role === 'assistant') {
        const data = safeResult(assistant.data);
        // The complete current draft is sent separately, not truncated into history.
        delete data.draft;
        pairs.push([{role:'user', content:(user.text || '[Attachment uploaded]').slice(0,20000)},
          {role:'assistant', content:JSON.stringify(data).slice(0,20000)}]);
        i++;
      }
    }
    const recent=[];let size=0;
    for(const pair of pairs.slice(-6).reverse()){
      const length=pair[0].content.length+pair[1].content.length;
      if(size+length>100000)break;
      recent.unshift(pair);size+=length;
    }
    return recent.flat();
  }
  function safeResult(data) {
    const out = {};
    for (const key of ['title','answer','meaning','deadline','risk','reply_draft','uncertainty','draft','importance','answer_type']) {
      if (typeof data[key] === 'string') out[key] = data[key].slice(0,MAX_TEXT);
    }
    out.actions = Array.isArray(data.actions) ? data.actions.filter(x => typeof x === 'string').slice(0,30).map(x => x.slice(0,6000)) : [];
    out.assignment = data.assignment === true;
    out.reply_needed = data.reply_needed === true;
    return out;
  }
  class ChatDatabase {
    constructor(owner) { this.owner = owner; }
    async open() {
      this.db = await new Promise((resolve, reject) => {
        const req = indexedDB.open('baobao_chats_v1',1);
        req.onupgradeneeded = () => { const store=req.result.createObjectStore('chats',{keyPath:'key'}); store.createIndex('owner','owner'); };
        req.onsuccess=()=>resolve(req.result); req.onerror=()=>reject(req.error); req.onblocked=()=>reject(new Error('Storage blocked'));
      });
      return this;
    }
    transact(mode, operation) {
      return new Promise((resolve,reject)=>{
        const tx=this.db.transaction('chats',mode), req=operation(tx.objectStore('chats'));
        tx.oncomplete=()=>resolve(req?.result); tx.onerror=()=>reject(tx.error); tx.onabort=()=>reject(tx.error || new Error('Storage aborted'));
      });
    }
    async all() { return (await this.transact('readonly',store=>store.index('owner').getAll(this.owner))).map(x=>x.value); }
    put(chat) { return this.transact('readwrite',store=>store.put({key:`${this.owner}:${chat.id}`,owner:this.owner,value:structuredClone(chat)})); }
    remove(id) { return this.transact('readwrite',store=>store.delete(`${this.owner}:${id}`)); }
    clear() { return this.transact('readwrite',store=>store.clear()); }
  }
  const api={MAX_CHATS,MAX_MESSAGES,MAX_TEXT,newChat,historyFor,safeResult,ChatDatabase};
  if (typeof module !== 'undefined') module.exports=api;
  else window.BaoBaoChatStore=api;
})();
