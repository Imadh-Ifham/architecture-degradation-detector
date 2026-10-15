"""Decision log storage tests.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    The file half of the decision history: appending a batch, replaying it
    back, and the three ways a log can be unusable.

    What is *not* here is any rule about what may be appended. Closing an
    interval rather than editing one, and a re-run appending nothing, are
    properties of the component and are tested there, against a list. This
    file only has to be a faithful append-only file.
"""

import json

import pytest

from app.infrastructure.decision_log import DecisionLogError, JsonlDecisionStore


def event(sequence: int, decision_id: str = "np-deny-all") -> dict:
    return {"seq": sequence, "event": "DECISION_RECORDED", "decision_id": decision_id}


class TestAppendingAndReplaying:
    def test_a_repository_with_no_log_yet_has_no_decisions(self):
        """The first scan is what creates the file, so its absence is a state
        rather than a fault."""

        assert JsonlDecisionStore("/nowhere").replay("never-ingested") == []

    def test_events_replay_in_the_order_they_were_appended(self, tmp_path):
        store = JsonlDecisionStore(tmp_path)

        store.append("online-boutique", [event(1), event(2, "rule-a-b")])
        store.append("online-boutique", [event(3, "rule-b-c")])

        assert [e["seq"] for e in store.replay("online-boutique")] == [1, 2, 3]

    def test_each_repository_keeps_its_own_history(self):
        """One log per repository: the thing it accumulates is one system's
        decisions across its releases."""

        import tempfile

        with tempfile.TemporaryDirectory() as root:
            store = JsonlDecisionStore(root)
            store.append("one", [event(1)])
            store.append("two", [event(1, "other")])

            assert len(store.replay("one")) == 1
            assert store.replay("two")[0]["decision_id"] == "other"

    def test_appending_nothing_leaves_no_file_behind(self, tmp_path):
        store = JsonlDecisionStore(tmp_path)

        store.append("online-boutique", [])

        assert list(tmp_path.iterdir()) == []

    def test_a_line_is_one_event_and_keys_are_ordered(self, tmp_path):
        """Ordered keys so that re-recording an unchanged history produces an
        unchanged file, which is what makes the committed corpus diffable."""

        store = JsonlDecisionStore(tmp_path)
        store.append("r", [{"b": 2, "a": 1}])

        line = (tmp_path / "r.jsonl").read_text(encoding="utf-8").strip()

        assert line == json.dumps({"a": 1, "b": 2})


class TestWhenTheLogCannotBeRead:
    def test_a_line_that_will_not_parse_raises_and_names_the_line(self, tmp_path):
        """A history that cannot be read in full cannot be replayed at all,
        and replaying half of one would answer with a past that never was."""

        (tmp_path / "r.jsonl").write_text('{"seq": 1}\nnot json\n', encoding="utf-8")

        with pytest.raises(DecisionLogError, match="line 2"):
            JsonlDecisionStore(tmp_path).replay("r")

    def test_blank_lines_are_not_events(self, tmp_path):
        (tmp_path / "r.jsonl").write_text('{"seq": 1}\n\n', encoding="utf-8")

        assert len(JsonlDecisionStore(tmp_path).replay("r")) == 1

    def test_a_repository_id_cannot_escape_the_log_directory(self, tmp_path):
        """The identifier arrives in a request body, so it is reduced to one
        path component here rather than trusted to be one."""

        logs = tmp_path / "logs"
        JsonlDecisionStore(logs).append("../../etc/passwd", [event(1)])

        written = list(logs.iterdir())
        assert len(written) == 1
        assert written[0].parent == logs
        assert "/" not in written[0].name and "\\" not in written[0].name

    def test_an_identifier_with_no_usable_characters_is_refused(self, tmp_path):
        with pytest.raises(DecisionLogError):
            JsonlDecisionStore(tmp_path).append("...", [event(1)])
