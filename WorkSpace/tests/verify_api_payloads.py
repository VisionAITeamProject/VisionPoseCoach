from fastapi.testclient import TestClient
from network.api_server import create_app

app = create_app()
client = TestClient(app)
health = client.get('/health')
session = client.get('/session/status')
print('health_ok', health.status_code, health.json()['type'], health.json()['app']['state'])
print('session_ok', session.status_code, session.json()['type'], session.json()['screen_hint'])
