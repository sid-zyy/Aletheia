"""Customer tickets to the administrators (raise, answer, close, re-open; who sees what)."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_app import Base, aletheia, signed_in  # noqa: E402
import tickets  # noqa: E402


class Tickets(Base):
    def setUp(self):
        super().setUp()
        with aletheia.db() as c:
            for t in ("ticket_messages_no_update", "ticket_messages_no_delete"): c.execute(f"DROP TRIGGER IF EXISTS {t}")
            c.execute("DELETE FROM ticket_messages"); c.execute("DELETE FROM tickets"); c.execute("DELETE FROM notifications")
            tickets.init_db(c)

    def notes(self, username):
        with aletheia.db() as c:
            return [r[0] for r in c.execute("SELECT n.message FROM notifications n JOIN users u ON u.id=n.user_id WHERE u.username=? AND n.kind='ticket'", (username,))]

    def test_customer_raises_a_ticket_and_the_admin_answers_and_closes_it(self):
        i = self.job()
        bad = self.cust.post("/api/tickets", json=dict(category="Weather", subject="x", message="short")).json["error"]
        self.assertEqual(len(bad), 3)
        r = self.cust.post("/api/tickets", json=dict(category="Test report", job_id=i, subject="When is the report due?", message="Please tell us when the final report will be released."))
        self.assertEqual(r.status_code, 201, r.json); tid = r.json["id"]
        self.assertIn("New customer ticket", self.notes("admin")[0])
        self.assertEqual([t["id"] for t in self.admin.get("/api/my-work").json["tickets"]], [tid])
        self.assertEqual(self.admin.post(f"/api/tickets/{tid}/messages", json=dict(message="Expected on Friday, after verification.")).status_code, 200)
        t = self.cust.get(f"/api/tickets/{tid}").json
        self.assertEqual(t["status"], "answered"); self.assertEqual(t["messages"][1]["author"], "CPRI Short Circuit Laboratory")  # no staff names
        self.assertEqual(self.admin.get(f"/api/tickets/{tid}").json["messages"][1]["author"], "Lab Admin")
        self.assertIn("answered your ticket", self.notes("ap.portal")[0])
        self.cust.post(f"/api/tickets/{tid}/messages", json=dict(message="Thank you"))
        self.assertEqual(self.admin.get("/api/tickets?status=open").json["tickets"][0]["id"], tid)  # the customer's reply re-opens it
        self.assertEqual(self.admin.post(f"/api/tickets/{tid}/close").status_code, 200)
        self.assertEqual(self.admin.post(f"/api/tickets/{tid}/close").status_code, 409)
        self.assertEqual(self.cust.get(f"/api/tickets/{tid}").json["status"], "closed")
        self.assertEqual(self.admin.post(f"/api/tickets/{tid}/reopen").status_code, 200)
        with aletheia.db() as c: self.assertTrue(c.execute("SELECT 1 FROM audit WHERE kind='ticket' AND event LIKE 'Ticket % raised%'").fetchone())

    def test_only_customers_raise_only_admins_answer_and_customers_see_only_their_own(self):
        self.assertEqual(self.admin.post("/api/tickets", json=dict(category="Other", subject="Test ticket", message="Staff cannot raise these")).status_code, 403)
        self.assertEqual(self.c.get("/api/tickets").status_code, 403)  # testers do not handle tickets
        other = self.c.post("/api/demo").json["id"]  # not this customer's job
        self.assertIn("not one of your", " ".join(self.cust.post("/api/tickets", json=dict(category="Other", job_id=other, subject="Not mine", message="A job of someone else")).json["error"]))
        tid = self.cust.post("/api/tickets", json=dict(category="Other", subject="Our own question", message="Something about our account")).json["id"]
        from test_auth import RoutePolicy
        stranger = RoutePolicy.customer_client(self, "Other Transformers Ltd", "other.customer")
        self.assertEqual(stranger.get(f"/api/tickets/{tid}").status_code, 404)  # ids reveal nothing
        self.assertEqual(stranger.get("/api/tickets").json["tickets"], [])
        self.assertEqual(stranger.post(f"/api/tickets/{tid}/messages", json=dict(message="hello")).status_code, 404)
        with aletheia.db() as c:  # messages are kept as written
            with self.assertRaises(Exception): c.execute("UPDATE ticket_messages SET body='changed'")

    def test_admin_gets_an_ai_reply_draft_built_only_from_what_the_customer_may_see(self):
        i = self.job()
        tid = self.cust.post("/api/tickets", json=dict(category="Test report", job_id=i, subject="Report date?", message="When will our report be ready?")).json["id"]
        self.admin.post(f"/api/tickets/{tid}/messages", json=dict(message="We will check."))
        self.assertEqual(self.admin.post(f"/api/tickets/{tid}/draft").status_code, 404)  # off by default
        self.assertNotIn("draft", self.cust.get(f"/api/tickets/{tid}").json)
        aletheia.app.config["FEATURE_DRAFT"] = True; os.environ["GEMINI_API_KEY"] = "test"; sent = []
        try:
            self.assertTrue(self.admin.get(f"/api/tickets/{tid}").json["draft"])
            self.assertEqual(self.cust.post(f"/api/tickets/{tid}/draft").status_code, 403)
            def fake(model, key, body):
                sent.append(body["contents"][0]["parts"][0]["text"]); return {"candidates": [{"content": {"parts": [{"text": "```\nThank you. We will let you know.\n```"}]}}]}
            aletheia.app.config["VISION_TRANSPORT"] = fake
            r = self.admin.post(f"/api/tickets/{tid}/draft"); self.assertEqual(r.status_code, 200, r.json)
            self.assertEqual(r.json["draft"], "Thank you. We will let you know."); self.assertEqual(r.json["warnings"], [])
            p = sent[0]
            self.assertIn("When will our report be ready?", p); self.assertIn("[Laboratory,", p); self.assertIn("No report has been released yet", p)
            self.assertNotIn("Lab Admin", p)  # no staff names reach the model
            self.assertEqual(len(self.admin.get(f"/api/tickets/{tid}").json["messages"]), 2)  # a draft is never sent or saved
            for said, flagged in (("Ready within 3-5 business days.", ["within 3-5 business days"]), ("Expect it by the end of next week.", ["by the end of next week"]),
                                  ("It takes 2-3 weeks, by 20/10/2026.", ["2-3 weeks", "20/10/2026"]), ("We will reply in this ticket.", [])):
                aletheia.app.config["VISION_TRANSPORT"] = lambda *a, s=said: {"candidates": [{"content": {"parts": [{"text": s}]}}]}
                self.assertEqual([w.split('"')[1] for w in self.admin.post(f"/api/tickets/{tid}/draft").json["warnings"]], flagged, said)
            aletheia.app.config["VISION_TRANSPORT"] = lambda *a: {"candidates": []}
            self.assertEqual(self.admin.post(f"/api/tickets/{tid}/draft").status_code, 503)
        finally:
            aletheia.app.config.pop("FEATURE_DRAFT"); aletheia.app.config.pop("VISION_TRANSPORT", None); os.environ.pop("GEMINI_API_KEY")


if __name__ == "__main__":
    unittest.main()
