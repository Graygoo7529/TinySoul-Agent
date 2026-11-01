from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.gateway.errors import ProjectInstanceError
from tinysoul.gateway.project.instance import ProjectInstanceLease
from tinysoul.gateway.project.instance import project_identity_for


def test_project_instance_lease_keeps_process_lock_and_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    directory = tmp_path / "instances"
    lease = ProjectInstanceLease(root, directory=directory)

    with lease:
        assert lease.identity.project_identity == project_identity_for(root)
        assert lease.identity.project_root == root.resolve()
        assert lease.identity.instance_id.startswith("instance_")
    assert not tuple(directory.glob("*.json"))


def test_project_instance_lease_rejects_second_owner(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    directory = tmp_path / "instances"

    with ProjectInstanceLease(root, directory=directory):
        with pytest.raises(ProjectInstanceError, match="already running"):
            with ProjectInstanceLease(root, directory=directory):
                pass
