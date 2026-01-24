"""Question Manager - Manage quarterly performance questions.

Handles:
- Loading/saving questions configuration
- Auto-evidence tagging from events
- Manual notes management
- LLM evaluation of questions
- Quarter-to-quarter template inheritance
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default questions file location
COMPETENCIES_FILE = Path.home() / ".config" / "aa-workflow" / "competencies.json"


class QuestionManager:
    """Manage quarterly performance questions."""

    def __init__(self, perf_dir: Path):
        self.perf_dir = perf_dir
        self.questions_file = perf_dir / "questions.json"
        self.questions_data = self._load_questions()

    def _load_questions(self) -> dict:
        """Load questions from file or create from template."""
        if self.questions_file.exists():
            try:
                with open(self.questions_file) as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load questions: {e}")

        # Create from default template
        return self._create_from_template()

    def _create_from_template(self) -> dict:
        """Create questions from default template."""
        # Load default questions from competencies config
        default_questions = []
        if COMPETENCIES_FILE.exists():
            try:
                with open(COMPETENCIES_FILE) as f:
                    config = json.load(f)
                    default_questions = config.get("quarterly_questions", {}).get("default_questions", [])
            except Exception as e:
                logger.warning(f"Failed to load default questions: {e}")

        if not default_questions:
            default_questions = [
                {
                    "id": "accomplishments",
                    "text": "What accomplishments are you most proud of last quarter?",
                    "subtext": "Reflect not only on WHAT but also HOW.",
                    "evidence_categories": ["technical_contribution", "creativity_innovation", "end_to_end_delivery"],
                },
                {
                    "id": "priorities",
                    "text": "What are your top priorities for this quarter?",
                    "subtext": None,
                    "evidence_categories": ["planning_execution", "opportunity_recognition"],
                },
                {
                    "id": "energy",
                    "text": "What is the most enjoyable/least enjoyable part of your job?",
                    "subtext": "What gives you energy / takes your energy away?",
                    "evidence_categories": ["all"],
                },
                {
                    "id": "support",
                    "text": "What support do you need to be successful?",
                    "subtext": "How can your manager help you?",
                    "evidence_categories": ["gaps", "blockers"],
                },
            ]

        # Initialize questions with empty evidence
        questions = []
        for q in default_questions:
            questions.append(
                {
                    **q,
                    "auto_evidence": [],
                    "manual_notes": [],
                    "llm_summary": None,
                    "last_evaluated": None,
                }
            )

        data = {
            "quarter": self._get_quarter_string(),
            "template_source": "default",
            "questions": questions,
            "custom_questions": [],
        }

        self._save_questions(data)
        return data

    def _get_quarter_string(self) -> str:
        """Get current quarter string like 'Q1 2026'."""
        now = datetime.now()
        quarter = (now.month - 1) // 3 + 1
        return f"Q{quarter} {now.year}"

    def _save_questions(self, data: dict | None = None):
        """Save questions to file."""
        if data is None:
            data = self.questions_data

        self.perf_dir.mkdir(parents=True, exist_ok=True)
        with open(self.questions_file, "w") as f:
            json.dump(data, f, indent=2)

    def get_questions(self) -> list[dict]:
        """Get all questions (default + custom)."""
        questions = self.questions_data.get("questions", [])
        custom = self.questions_data.get("custom_questions", [])
        return questions + custom

    def get_question(self, question_id: str) -> dict | None:
        """Get a specific question by ID."""
        for q in self.get_questions():
            if q.get("id") == question_id:
                return q
        return None

    def add_question(
        self,
        question_id: str,
        text: str,
        subtext: str | None = None,
        evidence_categories: list[str] | None = None,
    ) -> dict:
        """Add a custom question."""
        question = {
            "id": question_id,
            "text": text,
            "subtext": subtext,
            "evidence_categories": evidence_categories or ["all"],
            "auto_evidence": [],
            "manual_notes": [],
            "llm_summary": None,
            "last_evaluated": None,
        }

        if "custom_questions" not in self.questions_data:
            self.questions_data["custom_questions"] = []

        self.questions_data["custom_questions"].append(question)
        self._save_questions()
        return question

    def edit_question(
        self,
        question_id: str,
        text: str | None = None,
        subtext: str | None = None,
    ) -> dict | None:
        """Edit an existing question."""
        for q_list in [self.questions_data.get("questions", []), self.questions_data.get("custom_questions", [])]:
            for q in q_list:
                if q.get("id") == question_id:
                    if text is not None:
                        q["text"] = text
                    if subtext is not None:
                        q["subtext"] = subtext
                    self._save_questions()
                    return q
        return None

    def add_note(self, question_id: str, note: str) -> bool:
        """Add a manual note to a question."""
        for q_list in [self.questions_data.get("questions", []), self.questions_data.get("custom_questions", [])]:
            for q in q_list:
                if q.get("id") == question_id:
                    if "manual_notes" not in q:
                        q["manual_notes"] = []
                    q["manual_notes"].append(
                        {
                            "text": note,
                            "added_at": datetime.now().isoformat(),
                        }
                    )
                    self._save_questions()
                    return True
        return False

    def add_evidence(self, question_id: str, event_id: str) -> bool:
        """Add auto-evidence to a question."""
        for q_list in [self.questions_data.get("questions", []), self.questions_data.get("custom_questions", [])]:
            for q in q_list:
                if q.get("id") == question_id:
                    if "auto_evidence" not in q:
                        q["auto_evidence"] = []
                    if event_id not in q["auto_evidence"]:
                        q["auto_evidence"].append(event_id)
                        self._save_questions()
                    return True
        return False

    def tag_event_to_questions(self, event: dict) -> list[str]:
        """Tag an event to relevant questions based on competencies.

        Args:
            event: Event dict with competencies and points

        Returns:
            List of question IDs the event was tagged to
        """
        tagged = []
        event_id = event.get("id", "")
        competencies = list(event.get("points", {}).keys())
        total_points = sum(event.get("points", {}).values())

        for question in self.get_questions():
            q_id = question.get("id", "")
            q_categories = question.get("evidence_categories", [])

            # Check if event matches question's evidence categories
            should_tag = False

            if "all" in q_categories:
                should_tag = True
            elif "gaps" in q_categories:
                # Tag low-scoring events to support question
                if total_points < 2:
                    should_tag = True
            elif "blockers" in q_categories:
                # Tag events with blocker labels
                labels = event.get("labels", [])
                if any(l in ["blocked", "blocker", "needs-help"] for l in labels):
                    should_tag = True
            else:
                # Check if any competency matches
                for comp in competencies:
                    if comp in q_categories:
                        should_tag = True
                        break

            # For accomplishments, only tag high-value events
            if q_id == "accomplishments" and total_points < 3:
                should_tag = False

            if should_tag:
                self.add_evidence(q_id, event_id)
                tagged.append(q_id)

        return tagged

    def set_evaluation(self, question_id: str, summary: str) -> bool:
        """Set the LLM evaluation summary for a question."""
        for q_list in [self.questions_data.get("questions", []), self.questions_data.get("custom_questions", [])]:
            for q in q_list:
                if q.get("id") == question_id:
                    q["llm_summary"] = summary
                    q["last_evaluated"] = datetime.now().isoformat()
                    self._save_questions()
                    return True
        return False

    def get_evidence_details(self, question_id: str, daily_dir: Path) -> list[dict]:
        """Get full event details for a question's evidence.

        Args:
            question_id: Question ID
            daily_dir: Path to daily data directory

        Returns:
            List of event dicts
        """
        question = self.get_question(question_id)
        if not question:
            return []

        evidence_ids = set(question.get("auto_evidence", []))
        events = []

        # Load events from daily files
        for daily_file in daily_dir.glob("*.json"):
            try:
                with open(daily_file) as f:
                    data = json.load(f)
                    for event in data.get("events", []):
                        if event.get("id") in evidence_ids:
                            events.append(event)
            except Exception:
                pass

        return events

    def get_questions_summary(self) -> list[dict]:
        """Get summary of all questions for UI display."""
        summaries = []
        for q in self.get_questions():
            summaries.append(
                {
                    "id": q.get("id"),
                    "text": q.get("text"),
                    "evidence_count": len(q.get("auto_evidence", [])),
                    "notes_count": len(q.get("manual_notes", [])),
                    "has_summary": q.get("llm_summary") is not None,
                    "last_evaluated": q.get("last_evaluated"),
                }
            )
        return summaries


async def evaluate_question_with_llm(
    question: dict,
    evidence_events: list[dict],
    competency_summary: dict,
    llm_client: Any,
) -> str:
    """Evaluate a question using LLM.

    Args:
        question: Question dict
        evidence_events: List of evidence events
        competency_summary: Dict of competency scores
        llm_client: LLM client for completion

    Returns:
        Generated summary text
    """
    # Build evidence list
    evidence_text = "\n".join(
        f"- [{e.get('source', '')}] {e.get('title', '')} (Points: {sum(e.get('points', {}).values())})"
        for e in evidence_events[:20]  # Limit to 20 events
    )

    # Build competency summary
    comp_text = "\n".join(f"- {comp_id}: {data.get('percentage', 0)}%" for comp_id, data in competency_summary.items())

    # Include manual notes
    notes = question.get("manual_notes", [])
    notes_text = "\n".join(f"- {n.get('text', '')}" for n in notes) if notes else "None"

    prompt = f"""You are helping prepare a quarterly performance review.

QUESTION: {question.get('text', '')}
{question.get('subtext', '') or ''}

EVIDENCE FROM THIS QUARTER ({len(evidence_events)} items):
{evidence_text or 'No automatic evidence collected'}

MANUAL NOTES:
{notes_text}

COMPETENCY SCORES:
{comp_text}

Based on this evidence, write a 2-3 paragraph response that:
1. Highlights the most significant accomplishments/points
2. Provides specific examples with metrics where available
3. Frames the response in first person ("I accomplished...")

Focus on impact and the "how" not just the "what". Be specific and quantitative where possible.
"""

    try:
        response = await llm_client.complete(prompt)
        return response.strip()
    except Exception as e:
        logger.error(f"LLM evaluation failed: {e}")
        raise
