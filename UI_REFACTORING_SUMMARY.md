# UI Refactoring Summary

## Problem Identified

The `studyplan_app.py` file contains extensive repetitive GTK widget creation code:

### Before: Verbose Label Creation
```python
# 6 lines for each warning label
self.exam_warning_label = Gtk.Label(label="Set an exam date to unlock accurate planning.")
self.exam_warning_label.set_halign(Gtk.Align.START)
self.exam_warning_label.set_wrap(False)
self.exam_warning_label.set_ellipsize(Pango.EllipsizeMode.END)
self.exam_warning_label.set_max_width_chars(96)
self.exam_warning_label.add_css_class("single-line-lock")
self.exam_warning_label.add_css_class("nudge-warn")
left_panel.append(self.exam_warning_label)

# Repeated 3+ times in the codebase for similar patterns
self.availability_warning_label = Gtk.Label(label="Set weekday/weekend minutes...")
self.availability_warning_label.set_halign(Gtk.Align.START)
# ... same 5 more lines
```

### After: Concise Builder Pattern
```python
# 1 line with the UIBuilder
self.exam_warning_label = ui.warning_label("Set an exam date to unlock accurate planning.")
left_panel.append(self.exam_warning_label)

# Or inline
left_panel.append(ui.warning_label("Set weekday/weekend minutes..."))
```

## What Was Created

### 1. `studyplan/ui_builder.py`
A fluent builder class that provides:

- **Labels**: `label()`, `section_title()`, `muted_label()`, `warning_label()`, `kpi_line()`, `badge()`
- **Containers**: `card()`, `hero_card()`, `feature_card()`, `box()`, `hbox()`, `vbox()`
- **Navigation**: `scrolled_window()`, `list_scroller()`, `panel_scroller()`
- **Actions**: `button()`, `flat_button()`, `action_button()`
- **Input/Display**: `progress_bar()`, `spinner()`, `separator()`, `stack()`, `image()`
- **Complex**: `metric_card()`, `quest_row()`, `flow_box()`, `expander()`, `reveal()`

### 2. `studyplan/ui/__init__.py`
Exports UIBuilder for easy imports.

## Usage

### Basic Setup
```python
from studyplan.ui import UIBuilder

# In your window class __init__
self._ui = UIBuilder(self)
ui = self._ui  # local alias for brevity
```

### Common Patterns

#### Section Title
```python
# Before
title = Gtk.Label(label="Badges")
title.set_halign(Gtk.Align.START)
title.add_css_class("section-title")

# After
title = ui.section_title("Badges")
```

#### Warning Label
```python
# Before
warning = Gtk.Label(label="Set an exam date...")
warning.set_halign(Gtk.Align.START)
warning.set_wrap(False)
warning.set_ellipsize(Pango.EllipsizeMode.END)
warning.set_max_width_chars(96)
warning.add_css_class("single-line-lock")
warning.add_css_class("nudge-warn")

# After
warning = ui.warning_label("Set an exam date...")
```

#### Card Container
```python
# Before
card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
card.add_css_class("card")
card.add_css_class("hero-card")
card.add_css_class("feature-card")

# After
card = ui.feature_card()
```

#### Scrolled List
```python
# Before
scroll = Gtk.ScrolledWindow()
scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
scroll.add_css_class("card")
scroll.add_css_class("list-card")

# After
scroll = ui.list_scroller()
```

#### Button with Handler
```python
# Before
btn = Gtk.Button(label="Save Availability")
btn.connect("clicked", self.on_save_availability)

# After
btn = ui.button("Save Availability", on_click=self.on_save_availability)
```

## Benefits

1. **Reduced Line Count**: ~60% fewer lines for common widget patterns
2. **Consistency**: All widgets get the same default configuration
3. **Maintainability**: Changes to default styling happen in one place
4. **Readability**: Intent is clearer with semantic method names
5. **Type Safety**: Full type hints for IDE autocomplete
6. **Testability**: Builder can be mocked for UI tests

## Integration Path

### Phase 1: Gradual Migration (Recommended)
1. Import UIBuilder in StudyPlanGUI.__init__
2. Use for NEW code
3. Refactor EXISTING code when touching it for other reasons

### Phase 2: Bulk Refactoring (Optional)
- Target repetitive sections like label creation
- Focus on patterns with 3+ occurrences
- Keep semantic behavior identical

## Example: Refactoring StudyPlanGUI.__init__

### Before (lines ~1700-1730)
```python
# Exam date warning banner
self.exam_warning_label = Gtk.Label(label="Set an exam date to unlock accurate planning.")
self.exam_warning_label.set_halign(Gtk.Align.START)
self.exam_warning_label.set_wrap(False)
self.exam_warning_label.set_ellipsize(Pango.EllipsizeMode.END)
self.exam_warning_label.set_max_width_chars(96)
self.exam_warning_label.add_css_class("single-line-lock")
self.exam_warning_label.add_css_class("nudge-warn")
left_panel.append(self.exam_warning_label)

self.availability_warning_label = Gtk.Label(label="Set weekday/weekend minutes...")
# ... 6 more lines identical pattern
```

### After
```python
# Exam date warning banner
self.exam_warning_label = ui.warning_label(
    "Set an exam date to unlock accurate planning."
)
left_panel.append(self.exam_warning_label)

self.availability_warning_label = ui.warning_label(
    "Set weekday/weekend minutes to personalize your plan."
)
```

## Count of Repetitive Patterns (estimates)

From analysis of studyplan_app.py:

| Pattern | Occurrences | Lines Saved (est) |
|---------|-------------|-------------------|
| Warning labels | ~6 | ~30 lines |
| Section titles | ~15 | ~30 lines |
| Muted labels | ~20 | ~40 lines |
| Card containers | ~10 | ~20 lines |
| Scrolled windows | ~8 | ~16 lines |
| Progress bars | ~5 | ~10 lines |
| Simple buttons | ~25 | ~25 lines |

**Total potential savings: ~170 lines from ~2200 line __init__**

## Next Steps

1. ✅ Create UIBuilder class
2. ✅ Export from studyplan.ui
3. ⏭️ Import in StudyPlanGUI
4. ⏭️ Use in new features (like Transfer Insights)
5. ⏭️ Gradually refactor existing code

## Files Modified

- `studyplan/ui_builder.py` - NEW: Builder class with 30+ widget methods
- `studyplan/ui/__init__.py` - MODIFIED: Export UIBuilder

## Files to Consider for Refactoring

- `studyplan_app.py` - Main UI file with 2200+ lines of widget setup
- `studyplan_ui_runtime.py` - View models (already clean)
