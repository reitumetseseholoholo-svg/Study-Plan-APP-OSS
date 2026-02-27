"""Professional UI styling system for StudyPlan application.

This module provides:
- CSS class constants for consistent styling
- Responsive breakpoints and layout utilities
- Accessibility helpers
- Theme and color system guidelines
- Typography scale
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ──────────────────────────────────────────────────────────────────────────────
# CSS CLASS CONSTANTS - Use these instead of hardcoded strings
# ──────────────────────────────────────────────────────────────────────────────

class CSSClasses:
    """Standard CSS class names for consistent styling across the UI."""
    
    # CARD & CONTAINER CLASSES
    CARD = "card"
    CARD_TIGHT = "card-tight"
    CARD_HERO = "hero-card"
    CARD_FEATURE = "feature-card"
    CARD_CHART = "chart-card"
    
    # TYPOGRAPHY CLASSES
    TITLE = "title"
    SECTION_TITLE = "section-title"
    COACH_TITLE = "coach-title"
    SUBTITLE = "subtitle"
    MUTED = "muted"
    SMALL = "small"
    WRAPPED = "allow-wrap"
    SINGLE_LINE = "single-line-lock"
    
    # STATUS BADGE CLASSES
    BADGE = "badge"
    BADGE_SUCCESS = "nudge-good"
    BADGE_WARNING = "nudge-warn"
    BADGE_INFO = "nudge-info"
    
    # LAYOUT CLASSES
    PANEL = "panel"
    PANEL_LEFT = "panel-left"
    PANEL_RIGHT = "panel-right"
    PANEL_SCROLL = "panel-scroll"
    INLINE_TOOLBAR = "inline-toolbar"
    
    # FORM CLASSES
    FORM_LABEL = "form-label"
    FORM_HELP = "form-help"
    FORM_SECTION = "form-section"
    REQUIRED_INDICATOR = "required-indicator"
    
    # STATE CLASSES
    STATE_ERROR = "state-error"
    STATE_LOADING = "state-loading"
    STATE_EMPTY = "state-empty"
    STATE_SUCCESS = "state-success"
    
    # BUTTON CLASSES
    BUTTON_FLAT = "flat"
    BUTTON_ACTION = "coach-action"
    BUTTON_SUGGESTED = "suggested-action"
    BUTTON_DANGEROUS = "destructive-action"
    
    # STATUS INDICATOR CLASSES
    STATUS_INDICATOR = "status-indicator"
    STATUS_LINE = "status-line"
    STATUS_INFO = "status-info"
    STATUS_SUCCESS = "status-success"
    STATUS_WARNING = "status-warning"
    STATUS_ERROR = "status-error"
    
    # BANNER CLASSES
    BANNER = "info-banner"
    BANNER_INFO = "banner-info"
    BANNER_SUCCESS = "banner-success"
    BANNER_WARNING = "banner-warning"
    BANNER_ERROR = "banner-error"
    
    # INTERACTIVE CLASSES
    SWITCH_ROW = "switch-row"
    SCROLLED = "scrolled"
    LIST_CARD = "list-card"
    
    # VISIBILITY
    COMPACT = "compact"
    EXPANDED = "expanded"
    HIDDEN = "hidden"
    DIMMED = "dimmed"


# ──────────────────────────────────────────────────────────────────────────────
# RESPONSIVE LAYOUT SYSTEM
# ──────────────────────────────────────────────────────────────────────────────

class ResponsiveBreakpoint(int):
    """Named responsive breakpoints for layout decisions."""
    
    # Standard breakpoints (pixels)
    MOBILE = 480
    TABLET = 768
    DESKTOP = 1024
    WIDE = 1440
    ULTRAWIDE = 1920
    
    @classmethod
    def is_mobile(cls, width: int) -> bool:
        """Check if layout is mobile (< 480px)."""
        return width < cls.MOBILE
    
    @classmethod
    def is_tablet(cls, width: int) -> bool:
        """Check if layout is tablet (480px - 768px)."""
        return cls.MOBILE <= width < cls.TABLET
    
    @classmethod
    def is_desktop(cls, width: int) -> bool:
        """Check if layout is desktop (768px - 1024px)."""
        return cls.TABLET <= width < cls.DESKTOP
    
    @classmethod
    def is_wide(cls, width: int) -> bool:
        """Check if layout is wide (1024px - 1440px)."""
        return cls.DESKTOP <= width < cls.WIDE
    
    @classmethod
    def is_ultrawide(cls, width: int) -> bool:
        """Check if layout is ultrawide (>= 1440px)."""
        return width >= cls.WIDE
    
    @classmethod
    def get_density_mode(cls, width: int) -> str:
        """Get recommended density mode based on width.
        
        Returns:
            One of: 'compact', 'comfortable', 'spacious'
        """
        if cls.is_mobile(width) or cls.is_tablet(width):
            return "compact"
        elif cls.is_desktop(width):
            return "comfortable"
        else:
            return "spacious"
    
    @classmethod
    def columns_per_row(cls, width: int) -> int:
        """Get recommended number of card columns based on width."""
        if cls.is_mobile(width):
            return 1
        elif cls.is_tablet(width):
            return 2
        elif cls.is_desktop(width):
            return 2
        else:
            return 3


@dataclass(frozen=True)
class ResponsiveLayoutConfig:
    """Configuration for responsive UI layout."""
    
    width: int
    height: int
    is_mobile: bool
    is_tablet: bool
    is_desktop: bool
    is_wide: bool
    density_mode: str
    columns_per_row: int
    sidebar_visible: bool = True
    compact_toolbar: bool = False
    
    @classmethod
    def from_size(cls, width: int, height: int, sidebar_visible: bool = True) -> "ResponsiveLayoutConfig":
        """Create config from dimensions."""
        return cls(
            width=width,
            height=height,
            is_mobile=ResponsiveBreakpoint.is_mobile(width),
            is_tablet=ResponsiveBreakpoint.is_tablet(width),
            is_desktop=ResponsiveBreakpoint.is_desktop(width),
            is_wide=ResponsiveBreakpoint.is_wide(width),
            density_mode=ResponsiveBreakpoint.get_density_mode(width),
            columns_per_row=ResponsiveBreakpoint.columns_per_row(width),
            sidebar_visible=sidebar_visible,
            compact_toolbar=ResponsiveBreakpoint.is_mobile(width) or ResponsiveBreakpoint.is_tablet(width),
        )


# ──────────────────────────────────────────────────────────────────────────────
# SPACING & SIZING SCALE
# ──────────────────────────────────────────────────────────────────────────────

class Spacing:
    """Standard spacing scale (in pixels)."""
    
    XS = 2  # Extra small - micro spacing
    SM = 4  # Small - tight grouping
    MD = 8  # Medium - standard spacing
    LG = 12  # Large - section spacing
    XL = 16  # Extra large - major spacing
    XXL = 24  # 2x Large - page spacing
    
    @staticmethod
    def get_list_spacing(is_compact: bool = False) -> int:
        """Get spacing for list items."""
        return Spacing.SM if is_compact else Spacing.MD
    
    @staticmethod
    def get_section_spacing(is_compact: bool = False) -> int:
        """Get spacing for sections."""
        return Spacing.MD if is_compact else Spacing.LG
    
    @staticmethod
    def get_card_padding(is_compact: bool = False) -> int:
        """Get padding for cards."""
        return 7 if is_compact else 11  # Matches CSS


class FontSize:
    """Standard font sizes (in pixels)."""
    
    TINY = 10
    SMALL = 12
    NORMAL = 14
    LARGE = 16
    XLARGE = 18
    TITLE = 22
    HEADING = 28


# ──────────────────────────────────────────────────────────────────────────────
# ACCESSIBILITY GUIDELINES
# ──────────────────────────────────────────────────────────────────────────────

class A11y:
    """Accessibility (a11y) guidelines and helpers."""
    
    # WCAG 2.1 Compliance helpers
    MIN_TOUCH_TARGET = 48  # Minimum touch target size (pixels)
    MIN_CONTRAST_RATIO = 4.5  # Minimum contrast ratio (normal text)
    MIN_CONTRAST_RATIO_LARGE = 3  # For large text (>= 18pt)
    
    @staticmethod
    def describe_widget(description: str) -> dict[str, str]:
        """Return accessibility attributes for a widget."""
        return {
            "accessible_description": description,
        }
    
    @staticmethod
    def requires_attention_message(high_priority: bool = False) -> str:
        """Return message for screen readers about urgent content."""
        return (
            "Requires immediate attention"
            if high_priority
            else "Please review this content"
        )
    
    # Common accessible patterns
    REQUIRED_FIELD_LABEL = "*"
    ERROR_PREFIX = "Error:"
    WARNING_PREFIX = "Warning:"
    INFO_PREFIX = "Note:"


# ──────────────────────────────────────────────────────────────────────────────
# COLOR & STATUS SYSTEM
# ──────────────────────────────────────────────────────────────────────────────

class StatusColor(str):
    """Named status colors with semantic meaning."""
    
    SUCCESS = "nudge-good"
    WARNING = "nudge-warn"
    ERROR = "nudge-error"
    INFO = "nudge-info"
    NEUTRAL = "muted"


class StatusType(str):
    """Status types for consistent semantic styling."""
    
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"


# ──────────────────────────────────────────────────────────────────────────────
# MOTION & ANIMATION PREFERENCES
# ──────────────────────────────────────────────────────────────────────────────

class MotionPreference:
    """Handle motion/animation preferences for accessibility."""
    
    @staticmethod
    def should_reduce_motion(reduce_motion: bool = False) -> bool:
        """Check if motion should be reduced (accessibility)."""
        return reduce_motion
    
    @staticmethod
    def get_transition_duration(reduce_motion: bool = False) -> int:
        """Get transition duration in milliseconds."""
        return 0 if reduce_motion else 250
    
    @staticmethod
    def get_animation_delay(reduce_motion: bool = False) -> int:
        """Get animation delay in milliseconds."""
        return 0 if reduce_motion else 100


# ──────────────────────────────────────────────────────────────────────────────
# PROFESSIONAL UI PATTERNS
# ──────────────────────────────────────────────────────────────────────────────

class UIPattern:
    """Common professional UI patterns and their standard configurations."""
    
    @staticmethod
    def get_error_flash_duration() -> int:
        """Duration to show error messages (ms)."""
        return 4000
    
    @staticmethod
    def get_success_flash_duration() -> int:
        """Duration to show success messages (ms)."""
        return 2000
    
    @staticmethod
    def get_warning_flash_duration() -> int:
        """Duration to show warning messages (ms)."""
        return 3000
    
    @staticmethod
    def get_debounce_delay() -> int:
        """Debounce delay for search/input (ms)."""
        return 300
    
    @staticmethod
    def get_auto_hide_duration() -> int:
        """Auto-hide duration for transient dialogs (ms)."""
        return 5000
    
    @staticmethod
    def get_tooltip_delay() -> int:
        """Delay before showing tooltip (ms)."""
        return 500


# ──────────────────────────────────────────────────────────────────────────────
# GRID & LAYOUT HELPERS
# ──────────────────────────────────────────────────────────────────────────────

class GridLayout:
    """Standard grid layout configurations."""
    
    # Column spacing
    COLUMN_SPACING = 12
    ROW_SPACING = 4
    
    # Common grid dimensions
    TWO_COLUMN = 2
    THREE_COLUMN = 3
    FOUR_COLUMN = 4
    
    @staticmethod
    def get_columns_for_width(width: int) -> int:
        """Get recommended number of grid columns for given width."""
        if ResponsiveBreakpoint.is_mobile(width):
            return 1
        elif ResponsiveBreakpoint.is_tablet(width):
            return 2
        elif ResponsiveBreakpoint.is_desktop(width):
            return 2
        else:
            return 3


# ──────────────────────────────────────────────────────────────────────────────
# VALIDATION & ERROR HANDLING SYSTEM
# ──────────────────────────────────────────────────────────────────────────────

class ValidationStatus(str):
    """Standard validation status values."""
    
    VALID = "valid"
    INVALID = "invalid"
    VALIDATING = "validating"
    PENDING = "pending"
    EMPTY = "empty"


class ErrorSeverity(str):
    """Error severity levels."""
    
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
