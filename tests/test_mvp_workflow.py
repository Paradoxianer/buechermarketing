import unittest
from datetime import datetime

from mvp_marketing.workflow import default_marketing_plan, schedule_followups


class TestMvpWorkflow(unittest.TestCase):
    def test_default_marketing_plan_has_priorities(self):
        plan = default_marketing_plan(
            {
                "region_land": "Deutschland",
                "kanaele": ["buchhandlung", "podcast"],
            }
        )
        self.assertEqual([p["prioritaet"] for p in plan], [1, 2, 3])

    def test_schedule_followups_only_for_due_sent_items(self):
        rows = [
            {
                "id": "dr_1",
                "contact_id": "ct_1",
                "status": "sent",
                "sent_at": "2026-01-01T12:00:00Z",
                "response_status": "none",
            },
            {
                "id": "dr_2",
                "contact_id": "ct_2",
                "status": "draft",
                "sent_at": "2026-01-01T12:00:00Z",
                "response_status": "none",
            },
            {
                "id": "dr_3",
                "contact_id": "ct_3",
                "status": "sent",
                "sent_at": "2026-01-03T12:00:00Z",
                "response_status": "responded",
            },
        ]
        due = schedule_followups(rows, days=5, now=datetime(2026, 1, 10, 12, 0, 0))
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["draft_id"], "dr_1")


if __name__ == "__main__":
    unittest.main()
