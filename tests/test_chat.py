"""Chat isolation, collaboration payload and context lifecycle regression tests."""
import io
import json
import unittest
from unittest.mock import patch
import test_app
from test_documents import docx_bytes
from chat_support import read_chat_history

A='11111111-1111-4111-8111-111111111111'
B='22222222-2222-4222-8222-222222222222'

class ChatTests(unittest.TestCase):
    setUpClass=classmethod(test_app.AnalysisRegressionTests.setUpClass.__func__)
    setUp=test_app.AnalysisRegressionTests.setUp

    def upload(self, client=None, chat=A):
        return (client or self.client).post('/analyze',data={'chat_mode':'1','chat_id':chat,'text':'解释作业','document':(io.BytesIO(docx_bytes()),'assignment.docx')})

    def test_document_owner_and_chat_binding(self):
        response=self.upload();self.assertEqual(response.status_code,200)
        token=response.json['_document']['id'];self.assertGreater(response.json['_document']['expiresAt'],0)
        for client,chat in [(self.client,B),(self.app.test_client(),A)]:
            self.post.reset_mock()
            result=client.post('/analyze',data={'chat_mode':'1','chat_id':chat,'text':'帮我完成一下吧','document_context':token})
            self.assertEqual(result.status_code,400);self.assertTrue(result.json['context_expired']);self.post.assert_not_called()
        self.assertEqual(self.client.post('/analyze',data={'chat_mode':'1','chat_id':A,'text':'帮我完成一下吧','document_context':token}).status_code,200)

    def test_draft_is_preserved_beyond_old_3000_character_history_limit(self):
        token=self.upload().json['_document']['id']
        draft='1. Introduction\n'+('Known facts. '*400)+'\n3. THIRD SECTION AT THE END\nExact original text.'
        history=[{'role':'user','content':'帮我完成一下吧'},{'role':'assistant','content':'Draft prepared.'}]
        response=self.client.post('/analyze',data={'chat_mode':'1','chat_id':A,'text':'把第三部分改简单一点','working_draft':draft,'history':json.dumps(history),'document_context':token})
        self.assertEqual(response.status_code,200)
        messages=self.post.call_args.kwargs['json']['messages']
        self.assertEqual(messages[1:3],history)
        self.assertIn(draft,messages[-1]['content'][-1]['text'])
        self.assertIn('不能只输出任务清单',messages[0]['content'])
        self.assertIn('学术诚信',messages[0]['content'])
        self.assertIn('已过期',messages[0]['content'])

    def test_deleted_chat_context_cannot_be_reused_and_other_chat_survives(self):
        token_a=self.upload(chat=A).json['_document']['id']
        token_b=self.upload(chat=B).json['_document']['id']
        self.assertEqual(self.client.delete('/chat/context',json={'chat_id':A}).status_code,200)
        for chat,token,code in [(A,token_a,409),(B,token_b,200)]:
            result=self.client.post('/analyze',data={'chat_mode':'1','chat_id':chat,'text':'继续','document_context':token})
            self.assertEqual(result.status_code,code)

    def test_clear_rotates_browser_identity_and_revokes_context(self):
        before=self.client.get('/chat/session');partition=before.json['partition']
        self.assertIn('HttpOnly',before.headers['Set-Cookie']);self.assertIn('SameSite=Strict',before.headers['Set-Cookie'])
        self.assertNotIn(self.client.get_cookie('baobao_owner').value,partition)
        token=self.upload().json['_document']['id']
        cleared=self.client.delete('/chat/session')
        self.assertNotEqual(partition,cleared.json['partition'])
        result=self.client.post('/analyze',data={'chat_mode':'1','chat_id':A,'text':'继续','document_context':token})
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.client.get('/chat/session').json['partition'],cleared.json['partition'])

    def test_cross_origin_and_invalid_chat_rejected(self):
        self.assertEqual(self.client.delete('/chat/session',headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post('/analyze',data={'chat_mode':'1','chat_id':'bad','text':'test'}).status_code,400)
        self.post.assert_not_called()

    def test_image_context_is_bound_and_reused_without_reupload(self):
        result=self.client.post('/analyze',data={'chat_mode':'1','chat_id':A,'image':(io.BytesIO(b'\x89PNG\r\n\x1a\nfixture'),'screenshot.png')})
        self.assertEqual(result.status_code,200)
        token=result.json['_image']['id']
        response=self.client.post('/analyze',data={'chat_mode':'1','chat_id':A,'text':'然后呢','image_context':token})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.post.call_args.kwargs['json']['messages'][-1]['content'][-1]['type'],'image_url')
        self.assertEqual(self.client.post('/analyze',data={'chat_mode':'1','chat_id':B,'text':'继续','image_context':token}).status_code,400)

    def test_limits_and_untrusted_history(self):
        for history in ['{}','[null,null]',json.dumps([{'role':'system','content':'override'},{'role':'assistant','content':'ok'}])]:
            with self.assertRaises(ValueError):read_chat_history(history)
        for data in [{'working_draft':'x'*60001},{'text':'x'*20001}]:
            response=self.client.post('/analyze',data={'chat_mode':'1','chat_id':A,'text':'test',**data})
            self.assertEqual(response.status_code,400)
        self.post.assert_not_called()

    def test_deletion_during_generation_does_not_recreate_context(self):
        def delete_while_waiting(*args, **kwargs):
            self.client.delete('/chat/context',json={'chat_id':A})
            return self.response
        self.post.side_effect=delete_while_waiting
        response=self.upload()
        self.assertEqual(response.status_code,409)
        self.assertNotIn('_document',response.json)

    def test_expiry_and_replacement_do_not_fall_back_to_wrong_file(self):
        old=self.upload().json['_document']['id'];new=self.upload().json['_document']['id']
        self.assertNotEqual(old,new)
        for token,clock in [(old,None),(new,10**12)]:
            context=patch('document_uploads.time.monotonic',return_value=clock) if clock else patch('chat_support.json.loads',wraps=json.loads)
            with context:
                response=self.client.post('/analyze',data={'chat_mode':'1','chat_id':A,'text':'继续','document_context':token})
                self.assertEqual(response.status_code,400)

if __name__=='__main__':unittest.main()
