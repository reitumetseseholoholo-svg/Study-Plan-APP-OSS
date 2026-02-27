"""Migration Guide: Upgrading UI Code to Professional Standards

This guide helps developers migrate existing UI code to use the improved
StudyPlan UI system with robust components, validation, and accessibility.

Last Updated: February 27, 2026
"""

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 1: Direct GTK Widget Calls → UIBuilder
# ──────────────────────────────────────────────────────────────────────────────

## BEFORE (Legacy Code)
```python
# Direct GTK widget creation scattered throughout codebase
label = Gtk.Label(label="Title")
label.set_halign(Gtk.Align.START)
label.add_css_class("section-title")

button = Gtk.Button(label="Click me")
button.connect("clicked", self.on_click)
button.set_sensitive(True)

box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
box.add_css_class("card")
```

## AFTER (Modern Code)
```python
# Use UIBuilder for all widget creation
from studyplan.ui_builder import UIBuilder

ui = UIBuilder()

label = ui.section_title("Title")

button = ui.button("Click me", on_click=self.on_click)

box = ui.card(spacing=8)
```

**Migration Steps**:
1. Import UIBuilder: `from studyplan.ui_builder import UIBuilder`
2. Initialize in __init__: `self._ui = UIBuilder(self)`  OR use `UIBuilderMixin`
3. Replace all `Gtk.Label()` with `ui.label()`
4. Replace all `Gtk.Button()` with `ui.button()`
5. Replace all `Gtk.Box()` with `ui.hbox()` or `ui.vbox()`
6. Run tests and verify styling

---

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 2: Hardcoded CSS Classes → Constants
# ──────────────────────────────────────────────────────────────────────────────

## BEFORE (Fragile)
```python
card.add_css_class("card")
card.add_css_class("card-tight")
label.add_css_class("section-title")
label.add_css_class("muted")
button.add_css_class("suggested-action")
```

## AFTER (Maintainable)
```python
from studyplan.ui_styles import CSSClasses

card.add_css_class(CSSClasses.CARD)
card.add_css_class(CSSClasses.CARD_TIGHT)
label.add_css_class(CSSClasses.SECTION_TITLE)
label.add_css_class(CSSClasses.MUTED)
button.add_css_class(CSSClasses.BUTTON_SUGGESTED)
```

**Migration Steps**:
1. Import CSS constants: `from studyplan.ui_styles import CSSClasses`
2. Search for `add_css_class("` in your module
3. Replace hardcoded strings with `CSSClasses.CONSTANT_NAME`
4. Use shell one-liner to find all:
   ```bash
   grep -rn "add_css_class(" . --include="*.py" | grep -v CSSClasses | head -20
   ```

---

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 3: Manual Layout → Responsive Patterns
# ──────────────────────────────────────────────────────────────────────────────

## BEFORE (Fixed Layout)
```python
def build_ui(self, width):
    # Same layout regardless of screen size
    container = self.hbox(spacing=8)
    for item in items:
        container.append(self.card())
```

## AFTER (Responsive)
```python
from studyplan.ui_styles import ResponsiveLayoutConfig

def build_ui(self, width, height):
    config = ResponsiveLayoutConfig.from_size(width, height)
    
    container = ui.vbox(spacing=Spacing.get_section_spacing(config.density_mode))
    
    if config.is_mobile:
        # Single column
        for item in items:
            container.append(self.build_item_card(item))
    else:
        # Multi-column flow
        flow = ui.flow_box(max_children_per_line=config.columns_per_row)
        for item in items:
            flow.append(self.build_item_card(item))
        container.append(flow)
```

**Migration Steps**:
1. Test current layout at different window sizes (375px, 768px, 1024px, 1440px)
2. Import responsive helpers: `from studyplan.ui_styles import ResponsiveBreakpoint`
3. Add responsive checks: `if ResponsiveBreakpoint.is_mobile(width):`
4. Adjust spacing based on density: `Spacing.get_section_spacing(is_compact)`
5. Test again at all breakpoints

---

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 4: No Validation → Form Validation System
# ──────────────────────────────────────────────────────────────────────────────

## BEFORE (No Validation)
```python
def on_save_clicked(self):
    value = entry.get_text()
    # Hope the user entered something valid!
    save_data(value)
```

## AFTER (Robust Validation)
```python
from studyplan.ui_validation import FieldValidator, FormState

def __init__(self):
    self.form_state = FormState()

def on_email_changed(self, entry):
    value = entry.get_text()
    result = FieldValidator(value, "Email").email().validate()
    self.form_state.set_field_result("email", result)
    self.form_state.mark_touched("email")
    self.update_error_display("email")

def on_save_clicked(self):
    self.form_state.mark_submitted()
    
    if not self.form_state.is_valid():
        # Show errors
        for field, error in self.form_state.get_all_errors().items():
            show_error(field, error)
        return
    
    # Safe to save
    save_data(self.form_state.get_field_values())
```

**Migration Steps**:
1. Identify all form fields in your UI
2. Import validation: `from studyplan.ui_validation import FormState, FieldValidator`
3. Create FormState instance in __init__
4. Add validation to on_change handlers
5. Add validation to submit handler
6. Test with invalid inputs
7. Add error message display
8. Use InputSanitizer for unsafe user input

---

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 5: Silent Failures → Error Handling
# ──────────────────────────────────────────────────────────────────────────────

## BEFORE (Silent Failures)
```python
try:
    data = load_data()
except:
    pass  # What happened? User doesn't know
```

## AFTER (User-Friendly Errors)
```python
from studyplan.ui_mixin import ErrorHandler, ToastNotification

def __init__(self):
    self.error_handler = ErrorHandler(window)
    self.toast = ToastNotification(window)

async def load_data(self):
    loading_mgr = LoadingManager()
    loading_mgr.start_loading()
    
    try:
        data = await fetch_data()
        self.update_ui(data)
        self.toast.success("Data loaded successfully")
        return data
    except NetworkError as e:
        self.error_handler.handle_error(
            title="Connection Failed",
            message="Unable to fetch data",
            details=str(e),
        )
        # Show error UI
        error_card = self.ui.error_state(
            title="Connection Failed",
            message="Check your internet",
            on_retry=lambda *_: self.load_data()
        )
        self.show_error_card(error_card)
    except Exception as e:
        self.error_handler.show_error_dialog(
            title="Unexpected Error",
            message="Something went wrong",
            details=str(e),
        )
    finally:
        loading_mgr.stop_loading()
```

**Migration Steps**:
1. Audit all try/except blocks
2. Replace bare `except:` with specific exceptions
3. Add ErrorHandler callbacks for logging
4. Show loading states for async operations
5. Use appropriate error cards or dialogs
6. Show success feedback with toast notifications
7. Provide retry mechanisms for transient errors

---

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 6: No Accessibility → WCAG Compliant
# ──────────────────────────────────────────────────────────────────────────────

## BEFORE (Inaccessible)
```python
button = ui.button("→")  # What does this do?
icon.set_visible(danger)  # Color only - can't see if colorblind
```

## AFTER (Accessible)
```python
button = ui.accessible_button(
    "Next",  # Clear label
    tooltip="Go to next section (Ctrl+Right)",
    on_click=self.on_next,
)

indicator = ui.status_indicator(
    status="error" if danger else "success",
    text="There are errors in this form",  # Text + color
)
```

**Migration Steps**:
1. Review all buttons - ensure they have text labels
2. All images need accessible names
3. All color-based indicators need text labels
4. Use accessible_button for important controls
5. Add tooltips with keyboard shortcuts
6. Test with keyboard only (no mouse)
7. Run accessibility checker: `accerciser` (Linux)
8. Test with screen reader

---

# ──────────────────────────────────────────────────────────────────────────────
# MIGRATION CHECKLIST
# ──────────────────────────────────────────────────────────────────────────────

For each module you're migrating:

- [ ] Phase 1: Replace direct GTK calls with UIBuilder
  - [ ] Search for all `Gtk.Label(`, `Gtk.Button(`, `Gtk.Box(`
  - [ ] Replace with `ui.label()`, `ui.button()`, `ui.hbox()/vbox()`
  - [ ] Run unit tests

- [ ] Phase 2: Migrate to CSS constants
  - [ ] Replace hardcoded "card", "section-title", etc.
  - [ ] Use CSSClasses.CONSTANT_NAME
  - [ ] Verify styling is unchanged

- [ ] Phase 3: Add responsive layouts
  - [ ] Test at: 375px, 768px, 1024px, 1440px
  - [ ] Adjust spacing based on breakpoints
  - [ ] Verify no overflow on mobile

- [ ] Phase 4: Add form validation
  - [ ] Identify all input fields
  - [ ] Create FormState for multi-field forms
  - [ ] Add FieldValidator to on_change handlers
  - [ ] Add validation checks to submit
  - [ ] Display validation errors

- [ ] Phase 5: Add error handling
  - [ ] Try all error paths (network, invalid data, etc.)
  - [ ] Show ErrorHandler feedback
  - [ ] Provide retry mechanisms
  - [ ] Log errors properly

- [ ] Phase 6: Improve accessibility
  - [ ] All interactive elements keyboard accessible
  - [ ] All images have accessible names
  - [ ] Use accessible_button for important controls
  - [ ] All color indicators have text labels
  - [ ] Test with accessibility tools

- [ ] Documentation
  - [ ] Update module docstring with new patterns
  - [ ] Add usage examples
  - [ ] Link to UI_BEST_PRACTICES.md

---

# ──────────────────────────────────────────────────────────────────────────────
# COMMON MIGRATION PATTERNS
# ──────────────────────────────────────────────────────────────────────────────

### Pattern 1: Card with Title and Content

**Before**:
```python
card_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
card_box.add_css_class("card")
title = Gtk.Label(label="Title")
title.add_css_class("section-title")
card_box.append(title)
card_box.append(content)
```

**After**:
```python
card = ui.card(spacing=8)
card.append(ui.section_title("Title"))
card.append(content)
```

### Pattern 2: Button Row with Actions

**Before**:
```python
actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
save_btn = Gtk.Button(label="Save")
save_btn.connect("clicked", self.on_save)
actions.append(save_btn)
cancel_btn = Gtk.Button(label="Cancel")
cancel_btn.connect("clicked", self.on_cancel)
actions.append(cancel_btn)
```

**After**:
```python
actions = ui.hbox(spacing=6)
actions.append(ui.button("Save", on_click=self.on_save))
actions.append(ui.button("Cancel", on_click=self.on_cancel))
```

### Pattern 3: Loading within Container

**Before**:
```python
if is_loading:
    container.set_child(Gtk.Label(label="Loading..."))
else:
    container.set_child(content)
```

**After**:
```python
if is_loading:
    container.set_child(ui.loading_state("Loading your data..."))
else:
    container.set_child(content)
```

### Pattern 4: Error Display

**Before**:
```python
if error:
    error_label = Gtk.Label(label=f"Error: {error}")
    error_label.add_css_class("nudge-warn")
    container.append(error_label)
```

**After**:
```python
if error:
    container.append(ui.error_state(
        title="Error",
        message=error,
        on_retry=self.on_retry,
    ))
```

---

# ──────────────────────────────────────────────────────────────────────────────
# TESTING YOUR MIGRATION
# ──────────────────────────────────────────────────────────────────────────────

```bash
# 1. Unit tests
pytest tests/test_ui.py -v

# 2. Visual inspection at different sizes
# Run with different window sizes: 375px, 768px, 1024px

# 3. Accessibility check
accerciser  # Launch GTK accessibility inspector

# 4. Keyboard navigation
# Press Tab through all interactive elements
# Press Enter/Space to activate buttons

# 5. Error scenarios
# Test with network disabled
# Test with invalid inputs
# Test with large data sets

# 6. Search for remaining legacy patterns
grep -rn "Gtk\.Label\|Gtk\.Button\|Gtk\.Box" . --include="*.py" | \
    grep -v "ui\." | \
    grep -v "UIBuilder" | \
    head -20
```

---

**Questions?** See UI_BEST_PRACTICES.md for complete guidelines.
