# Test run endpoint for strands-demo
import pytest
from yourapp import app

def test_run_endpoint(client):
    data = {'input': {'input_type': 'json', 'data': '{"key":"value"}'}}
    response = client.post('/run', json=data)
    assert response.status_code == 200
    assert 'output' in response.json
