from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from scripts.fdb3_local_reproduce import wait_ready


class ReadinessTests(unittest.TestCase):
    def test_open_socket_with_loading_503_is_not_model_readiness(self):
        class Handler(BaseHTTPRequestHandler):
            attempts=0
            def do_GET(self):
                Handler.attempts+=1
                self.send_response(503 if Handler.attempts==1 else 200)
                self.end_headers()
            def log_message(self,*args): pass
        class Process:
            def poll(self): return None
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            wait_ready(server.server_port,Process(),seconds=2,http_path='/health')
            self.assertEqual(Handler.attempts,2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
