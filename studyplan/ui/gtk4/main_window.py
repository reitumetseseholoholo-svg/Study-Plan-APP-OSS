"""Main application window for ACCA Study Plan App using GTK4."""

import logging
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib, GObject

from studyplan.config import Config
from studyplan.contracts import TutorLearnerProfileSnapshot, TutorSessionState
from studyplan.practice_loop_controller import PracticeLoopController
from studyplan.cognitive_state import CognitiveState
from studyplan.services import InMemoryTutorSessionController, InMemoryTutorLearnerModelStore
from studyplan_ui_state_store import (
    GTK4WindowStateSnapshot,
    default_gtk4_window_state_path,
    load_gtk4_window_state,
    save_gtk4_window_state,
)
from .practice_session import PracticeSessionWindow
from .cognitive_dashboard import CognitiveDashboard
from .hint_system import HintSystemWidget
from .confidence_calibrator import ConfidenceCalibratorWidget
from .transfer_analyzer import TransferAnalyzerWidget
from .user_profile import UserProfileWidget
from studyplan.performance_monitor import PerformanceMonitor


@Gtk.Template(filename=str(Path(__file__).with_name("templates") / "main_window.ui"))
class StudyPlanMainWindow(Gtk.ApplicationWindow):
    """Main application window with tabbed interface."""
    
    __gtype_name__ = "StudyPlanMainWindow"
    
    # Template widgets
    stack = Gtk.Template.Child()
    header_bar = Gtk.Template.Child()
    practice_button = Gtk.Template.Child()
    dashboard_button = Gtk.Template.Child()
    hints_button = Gtk.Template.Child()
    confidence_button = Gtk.Template.Child()
    transfer_button = Gtk.Template.Child()
    profile_button = Gtk.Template.Child()

    def __init__(self, application):
        super().__init__(application=application)

        self._logger = logging.getLogger(__name__)
        self._state_store_path = default_gtk4_window_state_path(str(getattr(Config, "CONFIG_HOME", "") or ""))
        self._restored_state = load_gtk4_window_state(self._state_store_path)

        # Initialize core services
        self.performance_monitor = PerformanceMonitor(enabled=True)
        self.practice_controller = PracticeLoopController(self.performance_monitor)
        self.session_controller = InMemoryTutorSessionController()
        self.learner_store = InMemoryTutorLearnerModelStore()

        # Initialize cognitive state
        self.cognitive_state = self._restored_state.cognitive_state or CognitiveState()

        # Initialize UI components
        self.practice_session = PracticeSessionWindow(self)
        self.cognitive_dashboard = CognitiveDashboard(self)
        self.hint_system = HintSystemWidget(self)
        self.confidence_calibrator = ConfidenceCalibratorWidget(self)
        self.transfer_analyzer = TransferAnalyzerWidget(self)
        self.user_profile = UserProfileWidget(self)

        # Register stack pages so navigation actually works.
        self.stack.add_named(self.practice_session, "practice_session")
        self.stack.add_named(self.cognitive_dashboard, "cognitive_dashboard")
        self.stack.add_named(self.hint_system, "hint_system")
        self.stack.add_named(self.confidence_calibrator, "confidence_calibrator")
        self.stack.add_named(self.transfer_analyzer, "transfer_analyzer")
        self.stack.add_named(self.user_profile, "user_profile")
        self.stack.set_visible_child(self.practice_session)

        self._restore_application_state()

        # Connect signals
        self._setup_signals()

        # Initial state
        self._update_ui_state()

    def _setup_signals(self):
        """Connect all UI signals."""
        # Navigation buttons
        self.practice_button.connect("clicked", self._on_practice_clicked)
        self.dashboard_button.connect("clicked", self._on_dashboard_clicked)
        self.hints_button.connect("clicked", self._on_hints_clicked)
        self.confidence_button.connect("clicked", self._on_confidence_clicked)
        self.transfer_button.connect("clicked", self._on_transfer_clicked)
        self.profile_button.connect("clicked", self._on_profile_clicked)
        
        # Window signals
        self.connect("close-request", self._on_close_request)
        
    def _on_practice_clicked(self, button):
        """Switch to practice session view."""
        self.stack.set_visible_child(self.practice_session)
        self._update_active_button(self.practice_button)
        self.practice_session.start_session()
        
    def _on_dashboard_clicked(self, button):
        """Switch to cognitive dashboard view."""
        self.stack.set_visible_child(self.cognitive_dashboard)
        self._update_active_button(self.dashboard_button)
        self.cognitive_dashboard.update_display()
        
    def _on_hints_clicked(self, button):
        """Switch to hint system view."""
        self.stack.set_visible_child(self.hint_system)
        self._update_active_button(self.hints_button)
        self.hint_system.update_display()
        
    def _on_confidence_clicked(self, button):
        """Switch to confidence calibrator view."""
        self.stack.set_visible_child(self.confidence_calibrator)
        self._update_active_button(self.confidence_button)
        self.confidence_calibrator.update_display()
        
    def _on_transfer_clicked(self, button):
        """Switch to transfer analyzer view."""
        self.stack.set_visible_child(self.transfer_analyzer)
        self._update_active_button(self.transfer_button)
        self.transfer_analyzer.update_display()
        
    def _on_profile_clicked(self, button):
        """Switch to user profile view."""
        self.stack.set_visible_child(self.user_profile)
        self._update_active_button(self.profile_button)
        self.user_profile.update_display()
        
    def _on_close_request(self, window):
        """Handle window close request."""
        # Save state before closing
        self._save_application_state()
        return False  # Allow close

    def _update_active_button(self, active_button):
        """Update which navigation button appears active."""
        buttons = [
            self.practice_button, self.dashboard_button, 
            self.hints_button, self.confidence_button,
            self.transfer_button, self.profile_button,
        ]
        for button in buttons:
            if button == active_button:
                button.add_css_class("active")
            else:
                button.remove_css_class("active")

    def _update_ui_state(self):
        """Update UI based on current application state."""
        # Update header with current session info
        session = self.session_controller.get_or_create_session(
            session_id="main", module="ACCA", topic="General"
        )
        self.header_bar.set_title_widget(Gtk.Label(label=f"ACCA Study Plan - {session.topic}"))

    def _restore_application_state(self):
        """Restore persisted state for the secondary GTK4 shell."""
        restored = self._restored_state
        if restored.session_state is not None:
            self.session_controller.save_session(restored.session_state)
        if restored.learner_profile is not None:
            self.learner_store.save_profile(restored.learner_profile)
        page_to_activate = str(restored.visible_page or "").strip()
        if page_to_activate == "cognitive_dashboard":
            self.stack.set_visible_child(self.cognitive_dashboard)
            self._update_active_button(self.dashboard_button)
        elif page_to_activate == "hint_system":
            self.stack.set_visible_child(self.hint_system)
            self._update_active_button(self.hints_button)
        elif page_to_activate == "confidence_calibrator":
            self.stack.set_visible_child(self.confidence_calibrator)
            self._update_active_button(self.confidence_button)
        elif page_to_activate == "transfer_analyzer":
            self.stack.set_visible_child(self.transfer_analyzer)
            self._update_active_button(self.transfer_button)
        elif page_to_activate == "user_profile":
            self.stack.set_visible_child(self.user_profile)
            self._update_active_button(self.profile_button)
        else:
            self._update_active_button(self.practice_button)

    def _save_application_state(self):
        """Save application state to persistence layer."""
        try:
            session = self.session_controller.get_or_create_session(
                session_id="main",
                module="ACCA",
                topic=str(self.cognitive_state.working_memory.active_chapter or "General"),
            )
            learner_profile = self.learner_store.get_or_create_profile("user", session.module or "ACCA")
            visible_page = ""
            get_visible_child_name = getattr(self.stack, "get_visible_child_name", None)
            if callable(get_visible_child_name):
                visible_page = str(get_visible_child_name() or "").strip()
            save_gtk4_window_state(
                GTK4WindowStateSnapshot(
                    cognitive_state=self.cognitive_state,
                    session_state=session if isinstance(session, TutorSessionState) else None,
                    learner_profile=(
                        learner_profile if isinstance(learner_profile, TutorLearnerProfileSnapshot) else None
                    ),
                    visible_page=visible_page,
                ),
                self._state_store_path,
            )
        except Exception as exc:
            self._logger.warning("Failed to persist GTK4 shell state: %s", exc)

    def get_cognitive_state(self) -> CognitiveState:
        """Get current cognitive state."""
        return self.cognitive_state

    def get_practice_controller(self) -> PracticeLoopController:
        """Get practice loop controller."""
        return self.practice_controller

    def get_session_controller(self):
        """Get session controller."""
        return self.session_controller

    def get_learner_store(self):
        """Get learner model store."""
        return self.learner_store

    def get_performance_monitor(self) -> PerformanceMonitor:
        """Get performance monitor."""
        return self.performance_monitor


class StudyPlanApplication(Gtk.Application):
    """Main application class."""

    def __init__(self):
        super().__init__(application_id="com.acca.studyplan")
        self.window = None

    def do_activate(self):
        """Activate the application."""
        if not self.window:
            self.window = StudyPlanMainWindow(self)
            self.window.present()

        self.window.present()


def run_application():
    """Run the GTK4 application."""
    app = StudyPlanApplication()
    return app.run(None)
