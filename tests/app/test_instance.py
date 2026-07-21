from __future__ import annotations

import json
from pathlib import Path

import pytest

from tinysoul.app import AppInstanceError, ProjectInstanceLease, project_identity_for
from tinysoul.endpoint import EndpointReady


def test_project_instance_lease_publishes_and_cleans_connection_record(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    directory = tmp_path / "instances"
    lease = ProjectInstanceLease(root, directory=directory)

    with lease:
        assert lease.identity.project_identity == project_identity_for(root)
        lease.publish(
            EndpointReady(
                host="127.0.0.1",
                port=43123,
                token="x" * 32,
                instance_id=lease.identity.instance_id,
                project_identity=lease.identity.project_identity,
            )
        )
        record = json.loads(lease.record_path.read_text(encoding="utf-8"))
        assert record["instance_id"] == lease.identity.instance_id
        assert record["project_identity"] == lease.identity.project_identity
        assert record["project_root"] == str(root.resolve())

    assert lease.record_path.exists() is False


def test_project_instance_lease_rejects_second_owner(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    directory = tmp_path / "instances"

    with ProjectInstanceLease(root, directory=directory):
        with pytest.raises(AppInstanceError, match="already running"):
            with ProjectInstanceLease(root, directory=directory):
                pass
