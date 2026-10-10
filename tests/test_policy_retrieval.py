import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from src.policy import (
    load_policy_chunks,
    parse_effective_date,
    retrieve_policy,
    select_cancellation_version,
)


class PolicyRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chunks = load_policy_chunks()

    def test_all_five_documents_produce_metadata_rich_chunks(self) -> None:
        self.assertEqual(len({chunk.doc_name for chunk in self.chunks}), 5)
        self.assertTrue(all(chunk.text for chunk in self.chunks))
        self.assertTrue(all(chunk.section_title for chunk in self.chunks))
        self.assertTrue(all(chunk.page >= 1 for chunk in self.chunks))
        self.assertTrue(all(chunk.version for chunk in self.chunks))
        self.assertTrue(
            all(
                chunk.effective_date
                for chunk in self.chunks
                if "Cancellation_and_Refund" in chunk.doc_name
            )
        )
        citation = self.chunks[0].citation()
        self.assertEqual(
            set(citation),
            {"doc", "version", "section", "page", "effective_date"},
        )

    def test_effective_date_parses_date_and_india_local_time(self) -> None:
        self.assertEqual(
            parse_effective_date("Document policy · Effective 1 January 2025"),
            "2025-01-01",
        )
        self.assertEqual(
            parse_effective_date(
                "Effective 1 July 2026, 00:00 IST"
            ),
            "2026-07-01T00:00:00+05:30",
        )
        self.assertIsNone(parse_effective_date("No effective date stated."))

    def test_cancellation_policy_is_selected_by_booking_time(self) -> None:
        before_cutoff = datetime(2026, 6, 30, 18, 29, 59, tzinfo=timezone.utc)
        at_cutoff = datetime(2026, 6, 30, 18, 30, tzinfo=timezone.utc)
        self.assertEqual(
            select_cancellation_version(self.chunks, before_cutoff), "1"
        )
        self.assertEqual(select_cancellation_version(self.chunks, at_cutoff), "2")

    def test_bm25_retrieves_chunks_and_cites_metadata(self) -> None:
        with patch("src.llm.client.get_embedding_model", return_value=None):
            hits = retrieve_policy(
                "What happens if I return an EV with low battery?",
                chunks=self.chunks,
                top_k=3,
            )
        self.assertTrue(hits)
        self.assertTrue(any("battery" in hit.text.casefold() for hit in hits))
        self.assertTrue(all(hit.citation()["page"] >= 1 for hit in hits))

    def test_cancellation_retrieval_requires_booking_time_and_uses_one_version(
        self,
    ) -> None:
        with patch("src.llm.client.get_embedding_model", return_value=None):
            with self.assertRaisesRegex(ValueError, "booking date"):
                retrieve_policy(
                    "What is the cancellation refund?", chunks=self.chunks
                )

            hits = retrieve_policy(
                "What is the cancellation refund?",
                chunks=self.chunks,
                booking_date="2026-06-30T18:30:00Z",
            )
        cancellation_hits = [
            hit
            for hit in hits
            if "cancellation_and_refund" in hit.doc_name.casefold()
        ]
        self.assertTrue(cancellation_hits)
        self.assertEqual({hit.version for hit in cancellation_hits}, {"2"})

    def test_scanned_policy_page_tables_are_transcribed_as_chunks(self) -> None:
        expected = (
            (
                "03_Cancellation_and_Refund_Policy_v2.pdf",
                2,
                "transcribed from scanned annexure",
                ("48 hours or more | 100%", "12 hours or more, but less than 48 hours | 75%",
                 "2 hours or more, but less than 12 hours | 25%", "Less than 2 hours"),
            ),
            (
                "04_Late_Return_and_Damage_Penalty_Schedule.pdf",
                3,
                "transcribed from scanned annexure",
                ("STANDARD | None", "SILVER | None", "GOLD | 30 minutes"),
            ),
            (
                "05_EV_User_Guide_and_FAQ.pdf",
                2,
                "transcribed from scanned figure",
                ("below 10%", "Exactly 10%", "20% and above"),
            ),
        )
        for doc_name, page, note, fragments in expected:
            with self.subTest(doc_name=doc_name):
                matches = [
                    chunk
                    for chunk in self.chunks
                    if chunk.doc_name == doc_name
                    and chunk.page == page
                    and chunk.transcription_note == note
                ]
                self.assertEqual(len(matches), 1)
                for fragment in fragments:
                    self.assertIn(fragment.casefold(), matches[0].text.casefold())


if __name__ == "__main__":
    unittest.main()
