"""Exercise the real Marketplace installer against a source-only repository."""

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

from aiogithubapi.models.git_tree import GitHubGitTreeEntryModel
from homeassistant.components.marketplace.base import MarketplaceManager
from homeassistant.components.marketplace.repositories.base import RepositoryManifest
from homeassistant.components.marketplace.repositories.integration import IntegrationRepository
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

ROOT = Path(__file__).resolve().parents[1]


async def test_main_installs_source_without_a_release(hass, tmp_path):
    assert await async_setup_component(hass, "lovelace", {"lovelace": {"mode": "storage"}})
    manager = MarketplaceManager(hass, MockConfigEntry(domain="marketplace", data={}))
    repository = IntegrationRepository(manager, "GalenaHu/deepseek-ha")
    repository.repository_manifest = RepositoryManifest.from_dict(
        json.loads((ROOT / "hacs.json").read_text())
    )
    repository.data.default_branch = repository.ref = "main"
    repository.tree = [
        GitHubGitTreeEntryModel({"path": "custom_components/deepseek_ai", "type": "tree"})
    ]
    repository.resolve_content()
    # Never write through the normal test config's source-directory symlink.
    installed = tmp_path / "installed" / "deepseek_ai"
    repository.content.path.local = str(installed)

    contents = io.BytesIO()
    with zipfile.ZipFile(contents, "w") as archive:
        for path in sorted((ROOT / "custom_components/deepseek_ai").rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.writestr(
                    "deepseek-ha-main/" + str(path.relative_to(ROOT)), path.read_bytes()
                )

    requests = []

    async def download(remote, **kwargs):
        requests.append(remote.path)
        if remote.path.endswith("/archive/refs/heads/main.zip"):
            return contents.getvalue()
        # No tags and no Release assets exist for this source-only repository.
        return None

    with patch.object(manager, "async_download_file", side_effect=download):
        await repository._async_download_version("main")

    assert not any("/releases/download/" in path for path in requests), requests
    assert requests[-1] == "GalenaHu/deepseek-ha/archive/refs/heads/main.zip"
    assert repository.validate.success
    assert json.loads((installed / "manifest.json").read_text())["domain"] == "deepseek_ai"
    assert 'MIN_HA = "2026.11.2"' in (installed / "const.py").read_text()
    assert (installed / "translations/zh-Hans.json").is_file()
