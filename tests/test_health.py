# Test health endpoint for strands-demo
import pytest
from yourapp import app

def test_health_endpoint(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert 'ok' in response.text
