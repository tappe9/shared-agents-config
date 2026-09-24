from pathlib import Path
import re

import yaml


def test_ci_runs_safe_cross_platform_checks():
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/validate.yml').read_text())
    assert workflow['permissions'] == {'contents': 'read'}
    job = workflow['jobs']['validate']
    assert set(job['strategy']['matrix']['os']) == {'windows-latest', 'macos-latest'}
    assert set(job['strategy']['matrix']['python']) == {'3.11', '3.14'}
    assert job['steps'][0]['with']['persist-credentials'] is False
    for step in job['steps']:
        if 'uses' in step:
            assert re.fullmatch(r'actions/[a-z-]+@[0-9a-f]{40}', step['uses'])
        if 'run' in step:
            assert 'harness apply' not in step['run']
    runs = [step['run'] for step in job['steps'] if 'run' in step]
    assert 'python -m harness validate' in runs
    assert 'python -m pytest -q' in runs
