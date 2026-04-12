"""Practice session window for ACCA Study Plan App using GTK4."""

from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib, GObject, Pango

from studyplan.contracts import TutorPracticeItem, TutorAssessmentSubmission, TutorAssessmentResult
from studyplan.performance_monitor import PerformanceMonitor


@Gtk.Template(filename=str(Path(__file__).with_name("templates") / "practice_session.ui"))
class PracticeSessionWindow(Gtk.Box):
    """Main practice session interface with intelligent tutoring."""
    
    __gtype_name__ = "PracticeSessionWindow"
    
    # Template widgets
    session_header = Gtk.Template.Child()
    question_display = Gtk.Template.Child()
    answer_input = Gtk.Template.Child()
    submit_button = Gtk.Template.Child()
    hint_button = Gtk.Template.Child()
    feedback_display = Gtk.Template.Child()
    progress_bar = Gtk.Template.Child()
    confidence_slider = Gtk.Template.Child()
    session_stats = Gtk.Template.Child()
    
    def __init__(self, main_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        
        self.main_window = main_window
        self.practice_controller = main_window.get_practice_controller()
        self.cognitive_state = main_window.get_cognitive_state()
        
        # Session state
        self.current_item = None
        self.current_result = None
        self.session_items = []
        self.item_index = 0
        self.correct_count = 0
        self.total_attempts = 0
        self.loop_state = None
        
        # Performance monitoring
        self.performance_monitor = main_window.get_performance_monitor()
        
        # Connect signals
        self._setup_signals()
        
    def _setup_signals(self):
        """Connect UI signals."""
        self.submit_button.connect("clicked", self._on_submit_clicked)
        self.hint_button.connect("clicked", self._on_hint_clicked)
        # GtkTextView does not emit "activate"; submission happens via the button.
        
    def start_session(self):
        """Start a new practice session."""
        with self.performance_monitor.context("session_start"):
            # Build practice items
            self.loop_state = self._create_loop_state()
            self.session_items = self.practice_controller.build_practice_items(self.loop_state, max_items=5)
            
            if not self.session_items:
                self._show_error("No practice items available")
                return
                
            self.item_index = 0
            self.correct_count = 0
            self.total_attempts = 0
            
            # Update UI
            self._update_session_header()
            self._display_current_item()
            self._update_progress()
            
    def _create_loop_state(self):
        """Create practice loop state for item generation."""
        from studyplan.practice_loop_controller import PracticeLoopSessionState
        from studyplan.contracts import TutorSessionState, TutorLearnerProfileSnapshot, AppStateSnapshot
        
        session_state = TutorSessionState(
            session_id="practice_session",
            module="ACCA",
            topic="General",
            mode="guided_practice",
            loop_phase="practice"
        )
        
        learner_profile = TutorLearnerProfileSnapshot(
            learner_id="user",
            module="ACCA"
        )
        
        app_snapshot = AppStateSnapshot(
            module="ACCA",
            current_topic="General",
            coach_pick="auto",
            days_to_exam=90,
            must_review_due=0,
            overdue_srs_count=0
        )
        
        return PracticeLoopSessionState(
            cognitive_state=self.cognitive_state,
            session_state=session_state,
            learner_profile=learner_profile,
            app_snapshot=app_snapshot
        )
        
    def _display_current_item(self):
        """Display the current practice item."""
        if not self.session_items or self.item_index >= len(self.session_items):
            self._end_session()
            return
            
        self.current_item = self.session_items[self.item_index]
        if self.loop_state is not None:
            self.practice_controller.present_practice_item(
                self.loop_state,
                self.current_item,
                restart=self.item_index == 0,
                source="gtk_practice_session_display",
            )

        # Update question display
        question_text = f"<b>Question {self.item_index + 1}:</b>\n\n{self.current_item.prompt}"
        self.question_display.set_markup(question_text)
        
        # Clear previous input and feedback
        self._set_answer_text("")
        self.feedback_display.set_markup("")
        
        # Update hint button state
        self.hint_button.set_sensitive(True)
        
        # Update confidence slider
        self.confidence_slider.set_value(3.0)  # Default to neutral
        
        # Update hint level display
        self._update_hint_level_display()
        
    def _on_submit_clicked(self, button):
        """Handle answer submission."""
        if not self.current_item:
            return
            
        with self.performance_monitor.context("assessment"):
            # Get user input
            answer_text = self._get_answer_text()
            confidence = int(self.confidence_slider.get_value())
            
            if not answer_text:
                self._show_feedback("Please enter an answer before submitting.", "warning")
                return
                
            # Create submission
            submission = TutorAssessmentSubmission(
                item_id=self.current_item.item_id,
                answer_text=answer_text,
                confidence=confidence,
                response_time_seconds=30.0  # Mock timing
            )
            
            # Submit attempt
            if self.loop_state is None:
                self.loop_state = self._create_loop_state()
            result = self.practice_controller.submit_attempt(self.loop_state, self.current_item, submission)
            
            self.current_result = result
            self.total_attempts += 1
            
            # Update cognitive state
            self._update_cognitive_state(result)
            
            # Display feedback
            self._display_feedback(result)
            
            # Update statistics
            self._update_session_stats()
            self._update_progress()
            
            # Check if session should continue
            if result.outcome == "correct":
                self.correct_count += 1
                # Auto-advance after correct answer
                GLib.timeout_add(2000, self._advance_to_next_item)
            else:
                # Stay on current item for incorrect answers
                self.hint_button.set_sensitive(True)
                
    def _on_hint_clicked(self, button):
        """Handle hint request."""
        if not self.current_item:
            return
            
        with self.performance_monitor.context("hint_request"):
            loop_state = self.loop_state if self.loop_state is not None else self._create_loop_state()
            if self.loop_state is None:
                self.loop_state = loop_state
            
            # Get progressive hint
            hint = self.practice_controller.get_next_hint(
                loop_state,
                self.current_item,
                has_attempted=True,
                error_tags=self.current_result.error_tags if self.current_result else ()
            )
            
            # Display hint
            hint_text = f"<b>Hint Level {hint.level + 1}:</b>\n{hint.text}"
            self._show_feedback(hint_text, "info")
            
            # Update hint level display
            self._update_hint_level_display()
            
    def _update_cognitive_state(self, result: TutorAssessmentResult):
        """Update cognitive state based on assessment result."""
        if self.current_item is None:
            return
        # Update posterior for the topic
        topic = self.current_item.topic
        if topic not in self.cognitive_state.posteriors:
            self.cognitive_state.posteriors[topic] = self.cognitive_state.get_posterior(topic)
            
        posterior = self.cognitive_state.posteriors[topic]
        
        # Update based on outcome
        if result.outcome == "correct":
            posterior.alpha += 1.0
        elif result.outcome == "incorrect":
            posterior.beta += 1.0
        # partial outcome updates both slightly
            
        # Update confidence tracking
        predicted_confidence = int(self.confidence_slider.get_value())
        was_correct = result.outcome == "correct"
        
        self.practice_controller.track_confidence_and_calibrate(
            loop_state=self.loop_state or self._create_loop_state(),
            predicted_confidence=predicted_confidence,
            was_correct=was_correct,
            topic=topic
        )
        
    def _display_feedback(self, result: TutorAssessmentResult):
        """Display assessment feedback."""
        if result.outcome == "correct":
            feedback = f"<span foreground='green'><b>✓ Correct!</b></span>\n\n{result.feedback}"
        elif result.outcome == "partial":
            feedback = f"<span foreground='orange'><b>⚠ Partial Credit</b></span>\n\n{result.feedback}"
        else:
            feedback = f"<span foreground='red'><b>✗ Incorrect</b></span>\n\n{result.feedback}"
            
        # Add error analysis if available
        if result.error_tags:
            error_text = "Error tags: " + ", ".join(result.error_tags)
            feedback += f"\n\n{error_text}"
            
        self.feedback_display.set_markup(feedback)
        
    def _update_hint_level_display(self):
        """Update hint level indicator."""
        # This would update a visual hint level indicator
        pass
        
    def _advance_to_next_item(self):
        """Advance to the next practice item."""
        self.item_index += 1
        if self.item_index < len(self.session_items):
            self._display_current_item()
        else:
            self._end_session()
        return False
            
    def _end_session(self):
        """End the practice session and show summary."""
        if self.loop_state is not None:
            self.practice_controller.complete_practice_session(self.loop_state, source="gtk_practice_session_end")
        accuracy = (self.correct_count / self.total_attempts * 100) if self.total_attempts > 0 else 0
        
        summary = f"""
        <b>Session Complete!</b>
        
        <b>Results:</b>
        • Correct: {self.correct_count}/{self.total_attempts}
        • Accuracy: {accuracy:.1f}%
        
        <b>Next Steps:</b>
        • Review incorrect answers
        • Check cognitive dashboard for progress
        • Try transfer tasks for deeper learning
        """

        self.feedback_display.set_markup(summary)
        self.submit_button.set_sensitive(False)
        self.hint_button.set_sensitive(False)
        return False
        
    def _update_session_header(self):
        """Update session header with current information."""
        topic = self.current_item.topic if self.current_item else "General"
        header_text = f"Practice Session - {topic} ({len(self.session_items)} items)"
        self.session_header.set_text(header_text)
        
    def _update_progress(self):
        """Update progress bar."""
        if not self.session_items:
            progress = 0.0
        else:
            progress = (self.item_index + 1) / len(self.session_items)
        self.progress_bar.set_fraction(progress)
        
    def _update_session_stats(self):
        """Update session statistics display."""
        stats_text = f"Correct: {self.correct_count} | Total: {self.total_attempts}"
        self.session_stats.set_text(stats_text)

    def _get_answer_text(self) -> str:
        """Read the current answer from the GtkTextView buffer."""
        buffer = self.answer_input.get_buffer()
        start_iter = buffer.get_start_iter()
        end_iter = buffer.get_end_iter()
        return buffer.get_text(start_iter, end_iter, True).strip()

    def _set_answer_text(self, text: str) -> None:
        """Replace the current answer text."""
        buffer = self.answer_input.get_buffer()
        buffer.set_text(text, -1)
        
    def _show_feedback(self, message: str, message_type: str = "info"):
        """Show feedback message with appropriate styling."""
        color_map = {
            "info": "#3498db",
            "warning": "#f1c40f", 
            "error": "#e74c3c",
            "success": "#2ecc71"
        }
        color = color_map.get(message_type, "#3498db")
        
        markup = f"<span foreground='{color}'><b>{message}</b></span>"
        self.feedback_display.set_markup(markup)
        
    def _show_error(self, message: str):
        """Show error message."""
        self._show_feedback(message, "error")
