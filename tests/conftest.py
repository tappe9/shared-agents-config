from dataclasses import dataclass
from pathlib import Path
import os
import subprocess

import pytest

from harness.paths import Layout, resolve_layout


def git(repo, *args):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True,
                          env=env).stdout.decode('utf-8').strip()


@dataclass
class Sandbox:
    repo: Path
    layout: Layout

    def commit(self):
        git(self.repo, 'add', '.')
        git(self.repo, '-c', 'user.name=Harness Test', '-c', 'user.email=harness@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'fixture')
        return git(self.repo, 'rev-parse', 'HEAD')

    def write(self, name, text):
        p = self.repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode() if isinstance(text, str) else text)


@pytest.fixture
def sandbox(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    layout = resolve_layout(repo, home=tmp_path / 'home', codex_home=tmp_path / 'home/.codex', env={})
    result = Sandbox(repo, layout)
    schema = Path(__file__).resolve().parents[1] / 'config/codex-config.schema.json'
    result.write('config/codex-config.schema.json', schema.read_bytes())
    for relative, text in {
        'AGENTS.md': '# Common\n\nAllowed `agent_type`: `explorer`\n',
        'agents/explorer.toml': 'name="explorer"\ndescription="test"\ndeveloper_instructions="test"\n',
        'skills/sample/SKILL.md': '---\nname: sample\ndescription: Test skill\n---\n# Sample\n',
        'config/skills-policy.toml': 'schema_version=1\n[skills]\ndisabled_user_dirs=["brainstorming"]\n',
        'config/dependencies.toml': 'schema_version=1\nrequired_skills=[]\n',
    }.items():
        result.write(relative, text)
    result.commit()
    return result
