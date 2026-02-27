"""Progressive hint system for productive struggle.

Provides escalating hints from minimal guidance to full explanation,
implementing Vygotsky's Zone of Proximal Development (ZPD).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .logging_config import get_logger


logger = get_logger(__name__)


@dataclass
class HintLevel:
    """Single hint at a specific level of scaffolding."""
    
    level: int  # 0=minimal, 1=light, 2=medium, 3=heavy, 4=solution
    text: str
    label: str  # "Nudge", "Hint", "Scaffold", "Explained", "Solution"
    context: str = ""  # e.g., "timing", "formula", "logic"


class HintBank:
    """Generate progressive hints for a practice item (minimal → full explanation)."""
    
    def __init__(
        self,
        topic: str,
        concept: str,
        item_type: str = "short_answer",
        expected_answer: str = "",
        error_tags: tuple[str, ...] = (),
    ):
        """
        Initialize hint bank for a specific item.
        
        Args:
            topic: Learning topic (e.g., "NPV calculation")
            concept: Core concept being tested
            item_type: "short_answer" | "numeric" | "mcq" | "essay"
            expected_answer: What correct answer should contain
            error_tags: Tags from previous attempt (e.g., "formula_error", "sign_error")
        """
        self.topic = topic
        self.concept = concept
        self.item_type = item_type
        self.expected_answer = expected_answer
        self.error_tags = error_tags
    
    def generate_hints(self) -> list[HintLevel]:
        """Generate all 5 hints levels for this item."""
        hints = []
        
        # Level 0: Nudge (minimal, just reorient attention)
        nudge = self._generate_nudge()
        hints.append(nudge)
        
        # Level 1: Light hint (direction, no specifics)
        light = self._generate_light_hint()
        hints.append(light)
        
        # Level 2: Medium hint (partial answer, key step)
        medium = self._generate_medium_hint()
        hints.append(medium)
        
        # Level 3: Heavy hint (nearly completed, fill-in-blank)
        heavy = self._generate_heavy_hint()
        hints.append(heavy)
        
        # Level 4: Solution (full explanation)
        solution = self._generate_solution()
        hints.append(solution)
        
        return hints
    
    def get_hint(self, level: int) -> HintLevel:
        """Get single hint at specified level (0-4)."""
        hints = self.generate_hints()
        level = max(0, min(4, level))  # Clamp to [0, 4]
        return hints[level]
    
    def _generate_nudge(self) -> HintLevel:
        """Level 0: Nudge them to re-read the question."""
        if self.error_tags and "misread" in str(self.error_tags):
            return HintLevel(
                level=0,
                label="Nudge",
                text="Read the question once more, slowly. What are you being asked for?",
                context="attention",
            )
        return HintLevel(
            level=0,
            label="Nudge",
            text=f"Think about what {self.concept} means. What are the key steps?",
            context="orientation",
        )
    
    def _generate_light_hint(self) -> HintLevel:
        """Level 1: Light directional hint."""
        if self.item_type == "numeric":
            if "formula_error" in self.error_tags:
                return HintLevel(
                    level=1,
                    label="Hint",
                    text=f"Check: did you use the right formula for {self.concept}? Try writing it down first.",
                    context="formula",
                )
            if "sign_error" in self.error_tags:
                return HintLevel(
                    level=1,
                    label="Hint",
                    text="Check your signs. Are all the + and − correct?",
                    context="arithmetic",
                )
            return HintLevel(
                level=1,
                label="Hint",
                text=f"Start by identifying which values go into the {self.concept} calculation.",
                context="setup",
            )
        
        if self.item_type == "short_answer":
            if self.expected_answer:
                key_words = self.expected_answer.split()[:3]
                return HintLevel(
                    level=1,
                    label="Hint",
                    text=f"Your answer should mention: {', '.join(key_words)}",
                    context="keywords",
                )
            return HintLevel(
                level=1,
                label="Hint",
                text=f"What are the two or three most important aspects of {self.concept}?",
                context="structure",
            )
        
        return HintLevel(
            level=1,
            label="Hint",
            text=f"Focus on understanding the core principle: {self.concept}.",
            context="concept",
        )
    
    def _generate_medium_hint(self) -> HintLevel:
        """Level 2: Medium hint with partial solution."""
        if self.item_type == "numeric":
            return HintLevel(
                level=2,
                label="Scaffold",
                text=(
                    f"Step 1: Write down the formula for {self.concept}.\n"
                    f"Step 2: Identify each input value.\n"
                    f"Step 3: Substitute and calculate. What do you get?"
                ),
                context="steps",
            )
        
        if self.item_type == "short_answer":
            return HintLevel(
                level=2,
                label="Scaffold",
                text=(
                    f"Structure your answer like this:\n"
                    f"1. State what {self.concept} is\n"
                    f"2. Explain why it matters\n"
                    f"3. Give one example"
                ),
                context="structure",
            )
        
        return HintLevel(
            level=2,
            label="Scaffold",
            text=f"Think through each part of {self.concept} separately, then combine them.",
            context="decomposition",
        )
    
    def _generate_heavy_hint(self) -> HintLevel:
        """Level 3: Heavy hint (mostly done, critical piece missing)."""
        if self.item_type == "numeric":
            return HintLevel(
                level=3,
                label="Nearly there",
                text=(
                    f"The formula is: [shown]\n"
                    f"Now substitute your values:\n"
                    f"[partial workings]\n"
                    f"Complete the calculation. What's your final answer?"
                ),
                context="completion",
            )
        
        if self.item_type == "short_answer":
            return HintLevel(
                level=3,
                label="Nearly there",
                text=(
                    f"{self.concept} is important because [key reason]. "
                    f"For example, [example setup]. "
                    f"This shows that [conclusion]. "
                    f"Now put this in your own words."
                ),
                context="template",
            )
        
        return HintLevel(
            level=3,
            label="Nearly there",
            text=f"You're close. The key insight is: [core idea about {self.concept}]. Apply it now.",
            context="insight",
        )
    
    def _generate_solution(self) -> HintLevel:
        """Level 4: Full solution (learning failure—explain fully)."""
        return HintLevel(
            level=4,
            label="Solution",
            text=self.expected_answer or (
                f"{self.concept} works like this: [full explanation]. "
                f"The key steps are: [complete walkthrough]. "
                f"Notice how [insight]. This is why we use {self.concept} in {self.topic}."
            ),
            context="full_explanation",
        )
    
    @staticmethod
    def recommend_next_level(
        current_level: int,
        has_attempted: bool,
        is_struggling: bool,
        time_since_hint_seconds: float = 30.0,
    ) -> int:
        """
        Recommend which hint level to show next.
        
        Args:
            current_level: What level was just shown (0-4)
            has_attempted: Did they try another time?
            is_struggling: Are they in struggle_mode?
            time_since_hint_seconds: How long since last hint?
        
        Returns:
            Next recommended hint level (0-4)
        """
        if not has_attempted:
            # If they haven't tried, show same level again
            return current_level
        
        if is_struggling and time_since_hint_seconds > 15:
            # In struggle mode, escalate faster
            return min(4, current_level + 2)
        
        # Normal: move to next level
        return min(4, current_level + 1)
