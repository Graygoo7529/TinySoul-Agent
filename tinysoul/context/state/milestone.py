"""
Milestone component for Query State.

Provides MilestoneManager for milestone list operations.
"""



class MilestoneManager:
    """Manages milestone list for query state."""

    def __init__(self):
        self._milestone_list: list[str] = []

    @property
    def milestone_list(self) -> list[str]:
        """Return a copy of the milestone list."""
        return self._milestone_list.copy()

    def add(self, description: str) -> str:
        """Add a completed milestone description to the list."""
        self._milestone_list.append(description)
        return description

    def get_all(self) -> list[str]:
        """Get list of all milestone descriptions."""
        return self._milestone_list.copy()
