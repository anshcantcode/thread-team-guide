import base64
import io
import unittest
import wave

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from thread_agent.protocol import InputEvent
from thread_agent.server import app, validate_media, get_session


class BoundaryTests(unittest.TestCase):
    def test_artifact_download_uses_an_attachment_and_keeps_provenance(self):
        with TestClient(app) as client:
            sid=client.post('/api/sessions',json={}).json()['session_id']
            get_session(sid).workspace['document:checklist']={'id':'result-checklist','domain':'document','source':'Composed by THREAD','provenance':'draft',
                'items':[{'title':'Rainy-day packing','document':{'kind':'checklist','title':'Rainy-day packing','blocks':[{'heading':'Essentials','items':['Rain jacket','Camera']}]}}]}
            response=client.get(f'/api/sessions/{sid}/artifacts/result-checklist')
            self.assertEqual(response.status_code,200)
            self.assertIn('attachment;',response.headers['content-disposition'])
            self.assertIn('text/markdown',response.headers['content-type'])
            self.assertIn('Status: DRAFT',response.text)
            self.assertIn('- [ ] Rain jacket',response.text)
            self.assertEqual(client.get(f'/api/sessions/{sid}/artifacts/unpublished').status_code,404)

    def test_credential_file_is_not_served(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/.env').status_code,404)
            self.assertEqual(client.get('/static/../.env').status_code,404)
            self.assertNotIn('key',client.get('/api/config').json())

    def test_cross_origin_input_is_rejected(self):
        with TestClient(app) as client:
            response=client.post('/api/sessions',json={},headers={'Origin':'https://example.com'})
            self.assertEqual(response.status_code,403)

    def test_png_and_wav_validation(self):
        with self.assertRaises(ValueError):
            validate_media(InputEvent(id='bad',type='frame',data={'base64':'not base64','mime':'image/png'}))
        stream=io.BytesIO()
        with wave.open(stream,'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(b'\0\0'*16000)
        event=InputEvent(id='wav',type='audio',data={'mime':'audio/wav','base64':base64.b64encode(stream.getvalue()).decode()})
        validate_media(event)
        self.assertEqual(event.data['mime'],'audio/wav')

    def test_schema_validation_rejects_undeclared_event_fields(self):
        with self.assertRaises(ValueError): InputEvent(id='input',type='text',text='Hi',allow_arbitrary_tools=True)

    def test_session_handover_has_one_event_consumer(self):
        with TestClient(app) as client:
            sid=client.post('/api/sessions',json={}).json()['session_id']
            with client.websocket_connect('/ws/'+sid) as first:
                self.assertEqual(first.receive_json()['type'],'history')
                with client.websocket_connect('/ws/'+sid) as second:
                    self.assertEqual(second.receive_json()['type'],'history')
                    with self.assertRaises(WebSocketDisconnect) as stopped:
                        first.receive_json()
                    self.assertEqual(stopped.exception.code,4001)
                    second.send_json({'id':'status','type':'control','data':{'action':'status'}})
                    self.assertEqual(second.receive_json()['type'],'final')
                    self.assertFalse(client.get('/api/sessions/'+sid).json()['floor_held'])


if __name__=='__main__': unittest.main()
