import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_gateway_is_independent_and_restricted():
    path = ROOT / 'deploy/gateway'
    resources = yaml.safe_load((path / 'kustomization.yaml').read_text())['resources']
    docs = [yaml.safe_load((path / r).read_text()) for r in resources]
    assert {d['kind'] for d in docs} == {'Deployment', 'ConfigMap'}
    assert 'echo' not in json.dumps(docs).lower()
    deployment = next(d for d in docs if d['kind'] == 'Deployment')
    assert deployment['spec']['replicas'] == 1
    assert deployment['spec']['strategy']['type'] == 'Recreate'
    pod = deployment['spec']['template']['spec']
    assert pod['automountServiceAccountToken'] is False
    assert pod['securityContext']['runAsNonRoot'] is True
    assert pod['terminationGracePeriodSeconds'] == 60
    config = next(d for d in docs if d['kind'] == 'ConfigMap')['data']
    assert all(isinstance(value, str) for value in config.values())
    assert json.loads(config['TELEGRAM_ALLOWED_USERS']) == []
    assert 'TELEGRAM_BOT_TOKEN' not in config
    assert not any(key.startswith('LLM_') for key in config)


def test_echo_has_no_gateway_secret_or_shared_resources():
    path = ROOT / 'examples/echo/deploy'
    resources = yaml.safe_load((path / 'kustomization.yaml').read_text())['resources']
    docs = [yaml.safe_load((path / r).read_text()) for r in resources]
    assert {d['kind'] for d in docs} == {'Deployment', 'ConfigMap'}
    assert 'agent-gateway-credentials' not in json.dumps(docs)
