"""Widget refresh is a closed public lookup boundary, independent of the language model."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from thread_agent.server import app


class WidgetRefreshTests(unittest.TestCase):
    def test_refresh_keeps_real_tool_provenance_and_module_identity(self):
        with TestClient(app) as client:
            result = client.post('/api/widgets/refresh', json={'modules': [
                {'id': 'calculation-original', 'domain': 'calculate', 'arguments': {'expression': '12*13'}},
                {'id': 'conversion-original', 'domain': 'convert', 'arguments': {'value': 1, 'from_unit': 'km', 'to_unit': 'm'}}]} )
            self.assertEqual(result.status_code, 200)
            rows = result.json()['results']
            self.assertEqual([r['id'] for r in rows], ['calculation-original', 'conversion-original'])
            self.assertEqual(rows[0]['items'][0]['value'], '156')
            self.assertEqual(rows[0]['provenance'], 'computed')
            self.assertIn('retrieved_at', rows[0])
            self.assertEqual(rows[0]['arguments'], {'expression': '12*13'})
            self.assertEqual(rows[1]['status'], 'completed')

    def test_rejects_write_demo_and_arbitrary_capabilities_before_execution(self):
        with TestClient(app) as client, patch('thread_agent.server.safe_execute', new_callable=AsyncMock) as execute:
            for domain in ['phone_set_alarm', 'phone', 'note', 'notebook', 'document', 'flights', 'rooms', 'device', 'shell', 'https://example.com']:
                with self.subTest(domain=domain):
                    self.assertEqual(client.post('/api/widgets/refresh', json={'modules': [{'domain': domain, 'arguments': {}}]}).status_code, 400)
            execute.assert_not_called()

    def test_schema_is_closed_and_entire_request_validated_before_any_lookup(self):
        with TestClient(app) as client, patch('thread_agent.server.safe_execute', new_callable=AsyncMock) as execute:
            valid = {'domain': 'calculate', 'arguments': {'expression': '1+1'}}
            for invalid in [None, [], {'expression': '2+2', 'url': 'http://localhost/private'}, {'expression': 12}, {}]:
                with self.subTest(arguments=invalid):
                    response = client.post('/api/widgets/refresh', json={'modules': [valid, {'domain': 'calculate', 'arguments': invalid}]})
                    self.assertEqual(response.status_code, 400)
            execute.assert_not_called()

    def test_rejects_empty_oversize_and_malformed_configurations(self):
        with TestClient(app) as client:
            for body in [None, [], {}, {'modules': []}, {'modules': [None]}, {'modules': [{}, {}, {}]}]:
                with self.subTest(body=body):
                    self.assertEqual(client.post('/api/widgets/refresh', json=body).status_code, 400)
            self.assertEqual(client.post('/api/widgets/refresh', content='{broken', headers={'Content-Type': 'application/json'}).status_code, 400)

    def test_timeout_is_explicit_with_no_invented_replacement(self):
        with TestClient(app) as client, patch('thread_agent.server.safe_execute', new_callable=AsyncMock, side_effect=asyncio.TimeoutError):
            row = client.post('/api/widgets/refresh', json={'modules': [{'id': 'saved-id', 'domain': 'calculate', 'arguments': {'expression': '1+1'}}]}).json()['results'][0]
            self.assertEqual(row['status'], 'failed')
            self.assertEqual(row['id'], 'saved-id')
            self.assertIn('Previous data remains', row['error'])
            self.assertNotIn('items', row)


if __name__ == '__main__':
    unittest.main()
