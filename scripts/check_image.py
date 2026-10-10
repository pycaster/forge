"""Run through stdin in a final container, without service credentials."""
import importlib
import os
import pathlib
import sys

assert os.getuid() == 10001
importlib.import_module('gateway.__main__')
importlib.import_module('sdk.lifecycle')
if sys.argv[1] == 'echo':
    importlib.import_module('examples.echo.worker')
else:
    assert not pathlib.Path('/app/examples').exists()
for path in pathlib.Path('/app').rglob('*'):
    assert path.name not in {'.git', '.venv', 'secrets', 'kubeconfig'}
    assert not path.name.startswith('.env')
print(f'{sys.argv[1]} image imports and contents verified')
