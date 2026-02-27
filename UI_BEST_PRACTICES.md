# StudyPlan UI Best Practices & Style Guide

A comprehensive guide for building professional, robust, and accessible UIs in the StudyPlan application.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Component Library](#component-library)
3. [Styling & Theming](#styling--theming)
4. [Accessibility](#accessibility)
5. [Form Handling](#form-handling)
6. [Error Handling](#error-handling)
7. [State Management](#state-management)
8. [Responsive Layouts](#responsive-layouts)
9. [Common Patterns](#common-patterns)
10. [Testing & QA](#testing--qa)

---

## Architecture Overview

The StudyPlan UI system consists of several layers:

### Core Components
- **UIBuilder**: Fluent widget factory with 40+ pre-configured widgets
- **UIBuilderMixin**: Mixin class for GTK windows to access UIBuilder
- **ui_styles.py**: CSS class constants, spacing, and accessibility standards
- **ui_validation.py**: Comprehensive input validation and form state management
- **ui_mixin.py**: Advanced state utilities (ErrorHandler, LoadingManager, etc.)

### Widget Hierarchy
```
UIBuilder (factory pattern)
├── Labels (section_title, muted_label, warning_label, badge)
├── Containers (card, hero_card, feature_card, hbox, vbox)
├── Input (entry, check_button, combo_box_text, spin_button, scale)
├── Form (form_row, form_section)
├── State (error_state, loading_state, empty_state)
├── Buttons (button, flat_button, action_button, accessible_button)
├── Lists (flow_box, list_scroller, panel_scroller)
└── Advanced (status_indicator, info_banner, stack, expander)
```

---

## Component Library

### ✅ DO: Use UIBuilder for ALL widgets

```python
# ❌ WRONG - Direct GTK widget creation
label = Gtk.Label(label="Title")
button = Gtk.Button(label="Click me")

# ✅ CORRECT - Use UIBuilder
label = ui.section_title("Title")
button = ui.button("Click me", on_click=self.handle_click)
```

### Labels

**Section Titles** (use for section headers)
```python
ui.section_title("Dashboard")
```

**Muted Labels** (secondary text, help text)
```python
ui.muted_label("No data available")
ui.muted_label("This field is optional", halign=Gtk.Align.END)
```

**Warning Labels** (important notices)
```python
ui.warning_label("You have unsaved changes")
```

**Badges** (status indicators)
```python
ui.badge("Active", css_class="nudge-good")
ui.badge("Failed", css_class="nudge-warn")
```

### Buttons

**Standard Button**
```python
btn = ui.button("Save", on_click=self.on_save_clicked)
```

**Action Button** (primary action)
```python
btn = ui.action_button("Start Study", on_click=self.on_start)
```

**Flat Button** (secondary action)
```python
btn = ui.flat_button("Skip", on_click=self.on_skip)
```

**Accessible Button** (with keyboard support & a11y)
```python
btn = ui.accessible_button(
    "Open File",
    tooltip="Click to open file picker (Ctrl+O)",
    on_click=self.on_open_file
)
```

### Input Widgets

**Text Entry**
```python
entry = ui.entry(
    placeholder_text="Enter your name",
    max_length=100,
    on_changed=self.on_input_changed,
)
```

**Search Box**
```python
search = ui.search_entry(
    placeholder="Search topics...",
    on_search=self.on_search
)
```

**Checkbox**
```python
checkbox = ui.check_button(
    label="Remember me",
    active=True,
    on_toggled=self.on_remember_toggled,
)
```

**Toggle Switch**
```python
switch_box = ui.switch(
    label="Enable notifications",
    active=False,
    on_notify_active=self.on_notifications_toggled,
)
```

**Dropdown/Combo Box**
```python
combo = ui.combo_box_text(
    items=["Option 1", "Option 2", "Option 3"],
    on_changed=self.on_selection_changed,
)
```

**Numeric Input (Spin Button)**
```python
spinner = ui.spin_button(
    min_val=1,
    max_val=100,
    value=50,
    step=1,
    on_changed=self.on_value_changed,
)
```

**Slider/Scale**
```python
scale = ui.scale(
    min_val=0,
    max_val=100,
    value=75,
    marks={0: "0%", 25: "25%", 50: "50%", 75: "75%", 100: "100%"},
)
```

### Containers

**Card** (standard container)
```python
card = ui.card(spacing=8)
card.append(ui.section_title("Stats"))
card.append(ui.label("Your progress..."))
```

**Hero Card** (prominent container with accent styling)
```python
card = ui.hero_card()
card.append(ui.section_title("Welcome!"))
```

**Feature Card** (special highlighting for featured content)
```python
card = ui.feature_card()
```

**Horizontal Box** (layout)
```python
hbox = ui.hbox(spacing=8)
hbox.append(icon)
hbox.append(label)
hbox.append(button)
```

**Vertical Box** (layout)
```python
vbox = ui.vbox(spacing=12)
vbox.append(title)
vbox.append(content)
vbox.append(actions)
```

### State Indicators

**Error State** (user-friendly error display)
```python
error = ui.error_state(
    title="Unable to Load",
    message="Please check your connection",
    details="Network timeout after 30 seconds",
    on_retry=self.on_retry_clicked,
)
```

**Loading State** (shows spinner + message)
```python
loading = ui.loading_state("Loading your study plan...")
```

**Empty State** (nothing to show)
```python
empty = ui.empty_state(
    title="No courses yet",
    message="Add your first course to get started",
    icon_name="folder-open-symbolic",
    action_label="Add Course",
    on_action=self.on_add_course,
)
```

### Forms

**Form Row** (label + input + help text)
```python
row = ui.form_row(
    label_text="Email",
    widget=ui.entry(placeholder_text="your@email.com"),
    help_text="We'll never share your email",
    required=True,
)
```

**Form Section** (group related rows)
```python
section = ui.form_section(
    title="Account Settings",
    rows=[
        ui.form_row("Full Name", ui.entry(...), required=True),
        ui.form_row("Email", ui.entry(...), required=True),
        ui.form_row("Timezone", ui.combo_box_text(...)),
    ]
)
```

### Status Indicators

**Status Line** (icon + text status)
```python
indicator = ui.status_indicator(
    status="success",  # or "warning", "error", "info"
    text="All changes saved",
)
```

**Info Banner** (highlighted notification)
```python
banner = ui.info_banner(
    message="Your study session is about to expire",
    status="warning",  # or "error", "success", "info"
    closeable=True,
    on_close=self.on_banner_closed,
)
```

---

## Styling & Theming

### Using CSS Classes

Always use the constant class names from `CSSClasses`:

```python
from studyplan.ui_styles import CSSClasses

# ❌ WRONG - Hardcoded strings
card.add_css_class("my-custom-class")

# ✅ CORRECT - Use constants
card.add_css_class(CSSClasses.CARD)
card.add_css_class(CSSClasses.CARD_HERO)
```

### Common CSS Classes

- **Container**: `CSSClasses.CARD`, `CSSClasses.PANEL`
- **Typography**: `CSSClasses.SECTION_TITLE`, `CSSClasses.MUTED`
- **Status**: `CSSClasses.BADGE_SUCCESS`, `CSSClasses.BADGE_WARNING`, `CSSClasses.BADGE_ERROR`
- **Forms**: `CSSClasses.FORM_LABEL`, `CSSClasses.FORM_HELP`, `CSSClasses.REQUIRED_INDICATOR`
- **States**: `CSSClasses.STATE_ERROR`, `CSSClasses.STATE_LOADING`, `CSSClasses.STATE_EMPTY`

### Spacing Scale

Use the `Spacing` class for consistent spacing:

```python
from studyplan.ui_styles import Spacing

vbox = ui.vbox(spacing=Spacing.MD)  # 8px spacing
card = ui.card(spacing=Spacing.LG)  # 12px spacing
```

**Spacing Options**:
- `Spacing.XS` = 2px (micro)
- `Spacing.SM` = 4px (tight)
- `Spacing.MD` = 8px (standard)
- `Spacing.LG` = 12px (section)
- `Spacing.XL` = 16px (major)
- `Spacing.XXL` = 24px (page)

---

## Accessibility

### Keyboard Navigation

Always make interactive elements focusable and keyboard accessible:

```python
# ✅ DO: Use accessible_button for important controls
btn = ui.accessible_button(
    "Open Settings",
    tooltip="Open settings dialog (Ctrl+,)",
    on_click=self.on_settings,
)
```

### Screen Reader Support

Provide meaningful labels and descriptions:

```python
# For images
icon = ui.image("document-save-symbolic")
# Set accessible name through context
context = icon.get_accessible()
if context:
    context.set_accessible_name("Document has unsaved changes")
```

### Color Accessibility

Never rely on color alone; always use text labels or icons:

```python
# ❌ WRONG - Color only
status_box.add_css_class("nudge-good")  # Only shows green

# ✅ CORRECT - Text + color
indicator = ui.status_indicator(
    status="success",
    text="Saved successfully",
)
```

### Touch Targets

Ensure interactive elements are at least 48x48 pixels:

```python
btn = ui.button("Open")
# UIBuilder buttons already meet WCAG 2.1 touch target requirements
```

### Reduce Motion

Respect user's accessibility preferences:

```python
from studyplan.ui_styles import MotionPreference

reduce_motion = self.get_accessibility_preference()
duration = MotionPreference.get_transition_duration(reduce_motion)
```

---

## Form Handling

### Input Validation

Use the validation system for robust form handling:

```python
from studyplan.ui_validation import FieldValidator, FormState

# Validate a single field
validator = FieldValidator("user@example.com", field_name="Email")
result = (
    validator
    .required("Email is required")
    .email("Email format is invalid")
    .validate()
)

if result.is_valid:
    print("Valid email!")
else:
    print(f"Error: {result.first_error()}")
```

### Form State Management

Use `FormState` for managing multiple form fields:

```python
from studyplan.ui_validation import FormState, FieldValidator

form_state = FormState()

# Validate field on change
def on_email_changed(entry):
    value = entry.get_text()
    result = FieldValidator(value, "Email").email().validate()
    form_state.set_field_result("email", result)
    
    # Mark field as touched
    form_state.mark_touched("email")

entry = ui.entry(on_changed=on_email_changed)

# Before submit, check form validity
def on_submit():
    form_state.mark_submitted()
    if form_state.is_valid():
        print("Submit form!")
    else:
        for field, error in form_state.get_all_errors().items():
            print(f"{field}: {error}")
```

### Input Sanitization

Always sanitize user input:

```python
from studyplan.ui_validation import InputSanitizer

user_input = entry.get_text()
clean_text = InputSanitizer.sanitize_text(user_input)
```

### Common Validators

Use preset validators for common field types:

```python
from studyplan.ui_validation import CommonValidators

# Email validation
result = CommonValidators.create_email_validator(value)

# Password validation (min 8 chars)
result = CommonValidators.create_password_validator(value)

# Username validation (alphanumeric underscore dash)
result = CommonValidators.create_username_validator(value)

# URL validation
result = CommonValidators.create_url_validator(value)

# Numeric range validation
result = CommonValidators.create_number_validator(value, min_val=0, max_val=100)
```

---

## Error Handling

### Using ErrorHandler

Centralized error handling with callbacks:

```python
from studyplan.ui_mixin import ErrorHandler

error_handler = ErrorHandler(window)

# Register error callback
error_handler.on_error(self.on_application_error)

# Handle an error
try:
    load_data()
except Exception as e:
    error_handler.handle_error(
        title="Failed to Load Data",
        message="Could not fetch your study plan",
        details=str(e),
    )
```

### Error States

Use error state builder for user-friendly errors:

```python
# Show error in card
error_card = ui.error_state(
    title="Connection Failed",
    message="Check your internet connection",
    details="Please try again in a few moments",
    on_retry=self.on_retry,
)

# Replace content with error
main_container.set_child(error_card)
```

### Toast Notifications

Quick feedback to user:

```python
from studyplan.ui_mixin import ToastNotification

toast = ToastNotification(window)

# Show different types
toast.success("Profile updated successfully")
toast.warning("Some changes may not be saved")
toast.error("Failed to save changes", "Please try again")
toast.info("Tip: You can use keyboard shortcuts")
```

---

## State Management

### Loading States

Use `LoadingManager` for async operations:

```python
from studyplan.ui_mixin import LoadingManager

loading = LoadingManager()

# Register callback for when loading state changes
loading.on_loading_changed(self.on_loading_changed)

async def load_data():
    loading.start_loading()
    try:
        data = await fetch_data()
        self.update_ui(data)
    finally:
        loading.stop_loading()

def on_loading_changed(is_loading):
    if is_loading:
        main_container.set_child(ui.loading_state())
    else:
        main_container.set_child(content)
```

### Reactive Widgets

Automatically update when data changes:

```python
from studyplan.ui_mixin import ReactiveWidget

progress_label = ui.label("0/100")

def update_progress(widget, data):
    widget.set_text(f"{data['completed']}/{data['total']}")

reactive = ReactiveWidget(progress_label, update_progress)

# Update whenever data changes
reactive.update({"completed": 50, "total": 100})
```

### Widget Caching

Avoid recreating widgets:

```python
from studyplan.ui_mixin import WidgetCache

cache = WidgetCache()

def get_topic_card(topic_id):
    return cache.get_or_create(
        f"topic_{topic_id}",
        lambda: ui.card(spacing=8).append(ui.section_title(topic))
    )

# Clear cache when data changes
cache.invalidate("topic_5")  # Clear specific
cache.invalidate()  # Clear all
```

---

## Responsive Layouts

### Responsive Breakpoints

Adapt UI based on window size:

```python
from studyplan.ui_styles import ResponsiveBreakpoint, ResponsiveLayoutConfig

window_width = window.get_allocated_width()

config = ResponsiveLayoutConfig.from_size(window_width, window_height)

if config.is_mobile:
    # Show single column
    columns = 1
elif config.is_tablet:
    # Show 2 columns
    columns = 2
else:
    # Show 3 columns
    columns = 3
```

### Responsive Spacing

Adjust spacing based on density:

```python
from studyplan.ui_styles import Spacing, ResponsiveBreakpoint

width = window.get_allocated_width()
is_compact = ResponsiveBreakpoint.is_mobile(width)

spacing = Spacing.get_section_spacing(is_compact)
vbox = ui.vbox(spacing=spacing)
```

---

## Common Patterns

### Dialog Pattern

Use DialogBuilder for consistent dialogs:

```python
from studyplan.ui_mixin import DialogBuilder

def on_delete_clicked():
    dialog = (
        DialogBuilder(window, "Delete Item?")
        .with_message("This action cannot be undone")
        .with_secondary_message("Are you sure?")
        .with_ok_cancel()
        .build()
    )
    
    response = dialog.run()
    if response == Gtk.ResponseType.OK:
        delete_item()
    
    dialog.destroy()
```

### Section with Actions

Build reusable sections:

```python
from studyplan.ui_mixin import SectionBuilder

section = SectionBuilder(ui)
section \
    .with_title("Study Plan") \
    .with_card(lambda card: (
        card.append(ui.label("Your current topic")),
        card.append(progress_bar)
    )) \
    .with_action("Start", self.on_start_study) \
    .with_action("Pause", self.on_pause_study) \
    .build(main_container)
```

### Loading with Fallback

Show content or loading state:

```python
content_stack = ui.stack()

# Add content page
content_box = ui.vbox(spacing=8)
# ... populate content
content_stack.add_named(content_box, "content")

# Add loading page
loading = ui.loading_state("Loading your data...")
content_stack.add_named(loading, "loading")

# Add error page
error = ui.error_state(
    "Failed to load",
    on_retry=self.on_retry
)
content_stack.add_named(error, "error")

# Switch pages
content_stack.set_visible_child_name("loading")
# When done:
content_stack.set_visible_child_name("content")
```

---

## Testing & QA

### UI Testing Checklist

- [ ] All buttons are keyboard focusable
- [ ] All interactive elements have tooltips
- [ ] Loading states display properly
- [ ] Error messages are clear and actionable
- [ ] Forms validate on change and submit
- [ ] Empty states have action buttons
- [ ] Responsive layouts work at all breakpoints
- [ ] Colors meet WCAG contrast ratios
- [ ] Touch targets are 48x48 pixels minimum
- [ ] No hardcoded strings (use translation strings)

### Accessibility Testing

Run with accessibility tools:

```bash
# Test with screen reader (Linux)
accerciser  # GTK accessibility inspector

# Test keyboard navigation
# Use Tab to navigate, Enter/Space to activate
```

### Responsive Testing

Test at common breakpoints:

- Mobile: 375px - 480px
- Tablet: 768px - 1024px
- Desktop: 1024px - 1440px
- Wide: 1440px+

---

## Summary of Best Practices

1. ✅ **Always use UIBuilder** - Direct GTK calls are prohibited
2. ✅ **Use CSS class constants** - No hardcoded class names
3. ✅ **Validate all inputs** - Use FieldValidator for forms
4. ✅ **Show loading states** - Indicate async operations
5. ✅ **Provide error context** - Clear, actionable error messages
6. ✅ **Make forms accessible** - Required indicators, help text, labels
7. ✅ **Support keyboard navigation** - No mouse-only UIs
8. ✅ **Respect user preferences** - Reduce motion, high contrast, etc.
9. ✅ **Use standard spacing** - Spacing constants for consistency
10. ✅ **Test responsiveness** - Work at all viewport sizes

---

**Last Updated**: February 27, 2026  
**Version**: 1.0 - Professional Edition
