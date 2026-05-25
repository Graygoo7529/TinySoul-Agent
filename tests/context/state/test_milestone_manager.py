"""Unit tests for MilestoneManager — append-only history."""

from tinysoul.context.state import QueryState


class TestMilestoneManager:
    def test_add_appends_description(self):
        state = QueryState()
        result = state.add_milestone("Completed phase 1")
        assert result == "Completed phase 1"
        assert "Completed phase 1" in state.milestone_list

    def test_get_all_returns_list(self):
        state = QueryState()
        state.add_milestone("Milestone 1")
        state.add_milestone("Milestone 2")
        milestones = state.get_milestones()
        assert isinstance(milestones, list)
        assert len(milestones) == 2
        assert "Milestone 1" in milestones
        assert "Milestone 2" in milestones

    def test_returns_copy(self):
        state = QueryState()
        state.add_milestone("Milestone")
        milestones = state.get_milestones()
        milestones.append("New")
        assert len(state.milestone_list) == 1

    def test_monotonic_growth(self):
        state = QueryState()
        state.add_milestone("A")
        state.add_milestone("B")
        state.add_milestone("C")
        assert state.milestone_list == ["A", "B", "C"]
