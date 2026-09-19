"""Capacity belongs to the shared Job owner, independently of its backends."""

from collections.abc import Mapping
from dataclasses import dataclass

from tinysoul.infra.config import ConfigError, reject_unknown_keys


@dataclass(frozen=True)
class JobSettings:
    retained_capacity: int = 16
    per_turn_live_capacity: int = 1

    def __post_init__(self) -> None:
        for name in ("retained_capacity", "per_turn_live_capacity"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ConfigError(
                    "Job capacity must be a positive integer", key=f"jobs.{name}"
                )
        if self.per_turn_live_capacity > self.retained_capacity:
            raise ConfigError(
                "Live Job capacity exceeds retained capacity",
                key="jobs.per_turn_live_capacity",
            )


def parse_job_settings(tree: Mapping[str, object]) -> JobSettings:
    reject_unknown_keys(
        tree, {"retained_capacity", "per_turn_live_capacity"}, key="jobs"
    )
    retained = tree.get("retained_capacity", 16)
    live = tree.get("per_turn_live_capacity", 1)
    if type(retained) is not int or type(live) is not int:
        raise ConfigError("Job capacities must be integers", key="jobs")
    return JobSettings(retained, live)
