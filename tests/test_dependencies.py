import pytest

from harness.content import read_dependencies


def test_repository_dependency_manifest_contains_only_required_skill_declarations():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    data = read_dependencies(root)

    assert set(data) == {'schema_version', 'required_skills'}
    assert data['schema_version'] == 1
    assert 'git-commit' in data['required_skills']
    assert any(name.startswith('superpowers:') for name in data['required_skills'])


def test_dependency_manifest_rejects_inventory_metadata(sandbox):
    sandbox.write(
        'config/dependencies.toml',
        'schema_version=1\n'
        'required_skills=[]\n'
        '[providers.superpowers]\n'
        'last_documented_version="6.4.1"\n',
    )
    with pytest.raises(ValueError, match='invalid-dependency-manifest'):
        read_dependencies(sandbox.repo)
