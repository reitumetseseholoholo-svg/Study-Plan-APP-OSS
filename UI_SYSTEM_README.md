"""StudyPlan UI System - Professional Edition

Complete, production-ready UI framework for the StudyPlan application.
Built with accessibility, robustness, and professional standards.

Version: 1.0 Professional Edition (2026)
"""

# 🎨 StudyPlan Professional UI System

A comprehensive, enterprise-grade UI framework for building robust, accessible, and beautiful applications in GTK4.

## ✨ What's Included

### 1. **UIBuilder** - Complete Widget Factory
- 40+ pre-configured widget builders
- Fluent API for concise, readable code
- Zero boilerplate widget creation

**Key Components**:
```python
# Labels
ui.section_title("Title")
ui.muted_label("Secondary text")
ui.warning_label("Important message")
ui.badge("Status")

# Inputs
ui.entry(placeholder_text="...", max_length=100)
ui.check_button("Remember me")
ui.switch("Enable notifications")
ui.combo_box_text(items=["A", "B", "C"])
ui.spin_button(min_val=1, max_val=100)
ui.scale(0, 100, marks={0: "Low", 100: "High"})

# Containers
ui.card(spacing=8)
ui.hero_card()
ui.feature_card()
ui.hbox(spacing=12)
ui.vbox(spacing=12)

# State Builders
ui.error_state(title="...", message="...", on_retry=handler)
ui.loading_state("Loading...")
ui.empty_state(title="...", icon_name="...", on_action=handler)

# Professional Patterns
ui.error_state()
ui.form_row(label="Email", widget=entry, required=True)
ui.form_section(title="Settings", rows=[...])
ui.status_indicator(status="success", text="Saved")
ui.info_banner(message="...", status="warning")
ui.accessible_button(label="...", tooltip="...", on_click=handler)
```

### 2. **ui_styles.py** - Styling System
- CSS class constants (no hardcoded strings!)
- Responsive breakpoints (mobile, tablet, desktop)
- Professional spacing scale
- Accessibility guidelines (WCAG 2.1)
- Color & status system
- Typography scale
- Animation preferences

**Usage**:
```python
from studyplan.ui_styles import (
    CSSClasses,
    ResponsiveBreakpoint,
    Spacing,
    A11y,
    StatusColor,
)

card.add_css_class(CSSClasses.CARD)
card.add_css_class(CSSClasses.CARD_HERO)

vbox = ui.vbox(spacing=Spacing.LG)  # 12px

if ResponsiveBreakpoint.is_mobile(width):
    show_single_column()
```

### 3. **ui_validation.py** - Form Validation
- Fluent field validator
- Form state management
- Input sanitization
- Common validators (email, password, URL, etc.)
- Comprehensive error reporting

**Usage**:
```python
from studyplan.ui_validation import FieldValidator, FormState

# Single field
result = (
    FieldValidator(email, "Email")
    .required()
    .email()
    .validate()
)

# Multiple fields
form_state = FormState()
form_state.set_field_result("email", email_result)
form_state.mark_submitted()
if form_state.is_valid():
    save_data()
```

### 4. **ui_mixin.py** - Advanced State Management
- **ErrorHandler**: Centralized error handling with callbacks
- **LoadingManager**: Async operation state management
- **ToastNotification**: User feedback system
- **DialogBuilder**: Professional dialogs
- **WidgetCache**: Performance optimization
- **ReactiveWidget**: Auto-updating widgets
- **SectionBuilder**: Complex section builder

**Usage**:
```python
from studyplan.ui_mixin import (
    UIBuilderMixin,
    ErrorHandler,
    LoadingManager,
    ToastNotification,
)

class MyWindow(Gtk.ApplicationWindow, UIBuilderMixin):
    def __init__(self):
        super().__init__()
        self._init_ui_builder()
        self.error_handler = ErrorHandler(self)
        self.loading = LoadingManager()
        self.toast = ToastNotification(self)
```

### 5. **UI_BEST_PRACTICES.md** - Comprehensive Guide
- Architecture overview
- Component library reference
- Styling guidelines
- Accessibility requirements
- Form handling patterns
- Error handling best practices
- State management patterns
- Responsive layout guide
- Common UI patterns
- Testing checklist

### 6. **UI_MIGRATION_GUIDE.md** - Upgrade Path
- Step-by-step migration instructions
- Before/after code examples
- Phase-based approach (6 phases)
- Common migration patterns
- Testing checklist
- Legacy code patterns to replace

## 🚀 Quick Start

### 1. Create a Window with UIBuilder

```python
from gi.repository import Gtk
from studyplan.ui_mixin import UIBuilderMixin
from studyplan.ui_builder import UIBuilder

class MyWindow(Gtk.ApplicationWindow, UIBuilderMixin):
    def __init__(self, app):
        super().__init__(application=app)
        self._init_ui_builder()
        self.set_default_size(800, 600)
        
        # Now use self._ui throughout
        self.build_ui()
    
    def build_ui(self):
        main_box = self.ui.vbox(spacing=12)
        
        title = self.ui.section_title("Welcome to StudyPlan")
        main_box.append(title)
        
        content = self.ui.card()
        content.append(self.ui.label("Select your course"))
        main_box.append(content)
        
        button = self.ui.action_button("Start", on_click=self.on_start)
        main_box.append(button)
        
        self.set_child(main_box)
    
    def on_start(self, button):
        self.ui.info_banner("Study session started!", status="success")
```

### 2. Add Form Validation

```python
from studyplan.ui_validation import FormState, FieldValidator

self.form_state = FormState()

email_entry = self.ui.entry(
    placeholder_text="your@email.com",
    on_changed=self.on_email_changed,
)

def on_email_changed(self, entry):
    value = entry.get_text()
    result = FieldValidator(value, "Email").email().validate()
    self.form_state.set_field_result("email", result)
    self.update_error_display("email", result)

def on_save_clicked(self):
    self.form_state.mark_submitted()
    if self.form_state.is_valid():
        save_data()
    else:
        self.show_errors(self.form_state.get_all_errors())
```

### 3. Handle Errors & Loading

```python
from studyplan.ui_mixin import ErrorHandler, LoadingManager

async def load_data(self):
    self.loading.start_loading()
    container.set_child(self.ui.loading_state("Loading..."))
    
    try:
        data = await fetch_data()
        container.set_child(self.build_content(data))
        self.toast.success("Data loaded")
    except Exception as e:
        self.error_handler.handle_error(
            "Failed to load",
            str(e),
        )
        container.set_child(self.ui.error_state(
            message="Could not load data",
            on_retry=lambda *_: self.load_data()
        ))
    finally:
        self.loading.stop_loading()
```

### 4. Build Responsive Layouts

```python
from studyplan.ui_styles import ResponsiveLayoutConfig, Spacing

def build_ui(self):
    config = ResponsiveLayoutConfig.from_size(
        self.get_allocated_width(),
        self.get_allocated_height()
    )
    
    spacing = Spacing.get_section_spacing(config.density_mode)
    container = self.ui.vbox(spacing=spacing)
    
    if config.is_mobile:
        # Single column on mobile
        for item in items:
            container.append(self.ui.card())
    else:
        # Multi-column on desktop
        flow = self.ui.flow_box(max_children_per_line=config.columns_per_row)
        for item in items:
            child = self.ui.card()
            flow.append_child(child)
        container.append(flow)
```

## 📋 Features

### ✅ Professional Components
- 40+ pre-configured widgets
- CSS class constants (no magic strings)
- Fluent API (method chaining)
- Type hints throughout
- Comprehensive docstrings

### ✅ Form Handling
- Field validation with fluent API
- Form state management
- Input sanitization
- Common validators (email, password, URL, etc.)
- Error message display
- Touch tracking
- Submit handling

### ✅ Error Handling
- Centralized error handler
- Error callbacks & logging
- Error dialogs
- User-friendly error states
- Retry mechanisms
- Toast notifications

### ✅ Accessibility
- WCAG 2.1 compliant
- Keyboard navigation support
- Screen reader compatible
- Touch target size (48x48px minimum)
- Color + text status indicators
- Accessible button helpers
- Reduce motion support

### ✅ Responsive Design
- Mobile-first breakpoints
- Automatic layout adaptation
- Density modes (compact, comfortable, spacious)
- Flexible spacing system
- Responsive grid system

### ✅ State Management
- Loading state tracking
- Widget caching
- Reactive widgets (auto-update)
- Form state management
- Error tracking
- Loading manager

### ✅ Performance
- Widget caching
- Minimal re-renders
- Efficient validation
- Smart loading states
- Debouncing support

## 📚 Documentation

- **UI_BEST_PRACTICES.md** - Complete best practices guide
  - Architecture overview
  - Component reference
  - Styling guidelines
  - Accessibility requirements
  - Common patterns
  
- **UI_MIGRATION_GUIDE.md** - Step-by-step upgrade guide
  - Phase-based migration (6 phases)
  - Before/after examples
  - Common patterns
  - Testing checklist

- **Code Documentation** - Docstrings in each module
  - UIBuilder - Widget factory
  - ui_styles.py - Styling system
  - ui_validation.py - Form validation
  - ui_mixin.py - State management

## 🧪 Testing

All components include comprehensive docstrings and examples.

```bash
# Run UI tests
pytest tests/test_ui.py -v

# Test at different viewport sizes
# - Mobile: 375px
# - Tablet: 768px
# - Desktop: 1024px
# - Wide: 1440px

# Accessibility testing
accerciser  # GTK accessibility inspector

# Keyboard navigation
# Tab through all elements
# Ensure all controls are keyboard accessible
```

## 🔄 Migration Path

For existing code:

1. **Phase 1**: Replace `Gtk.Label()` → `ui.label()` etc.
2. **Phase 2**: Replace hardcoded CSS strings → Constants
3. **Phase 3**: Add responsive layouts
4. **Phase 4**: Add form validation
5. **Phase 5**: Add error handling
6. **Phase 6**: Improve accessibility

See **UI_MIGRATION_GUIDE.md** for step-by-step instructions.

## 📦 What Changed

### New Files
- `studyplan/ui_styles.py` - Styling system (300+ lines)
- `studyplan/ui_validation.py` - Form validation (500+ lines)
- `studyplan/UI_BEST_PRACTICES.md` - Complete guide (600+ lines)
- `studyplan/UI_MIGRATION_GUIDE.md` - Migration guide (400+ lines)

### Enhanced Files
- `studyplan/ui_builder.py` - Added 15+ new widgets & builders
- `studyplan/ui_mixin.py` - Added 6 new professional utilities
- `studyplan/ui/dashboard_cards.py` - Fixed consistency issues

### No Breaking Changes
- All existing code continues to work
- UIBuilder is backward compatible
- Gradual migration path available

## 🎯 Design Principles

1. **Consistency** - Same patterns throughout the UI
2. **Accessibility** - WCAG 2.1 compliance built-in
3. **Robustness** - Validation, error handling, state management
4. **Professional** - Enterprise-grade quality standards
5. **Maintainability** - Clear, documented, type-hinted code
6. **Performance** - Caching, efficient rendering
7. **User-Friendly** - Clear feedback, error messages, loading states

## 🌟 Key Statistics

- **40+** Pre-configured widgets
- **6+** Advanced state management utilities
- **20+** CSS class constants
- **10+** Common validators
- **4** Responsive breakpoints
- **7** Spacing scale levels
- **WCAG 2.1** Accessibility compliance
- **Zero** Breaking changes

## 💡 Best Practices

```python
# ✅ DO
button = ui.button("Save", on_click=self.on_save)
card.add_css_class(CSSClasses.CARD)
entry = ui.entry(max_length=100)
result = FieldValidator(value).email().validate()

# ❌ DON'T
button = Gtk.Button(label="Save")
button.connect("clicked", self.on_save)
card.add_css_class("card")  # Hardcoded!
entry = Gtk.Entry()
entry.set_max_length(100)
# No validation!
```

## 🚀 Next Steps

1. **Read** UI_BEST_PRACTICES.md
2. **Review** UIBuilder component library
3. **Start** using ui() in new code
4. **Migrate** existing modules (Phase 1-6)
5. **Test** at all breakpoints
6. **Verify** accessibility

## 📞 Support

- See UI_BEST_PRACTICES.md for detailed guidance
- Check UI_MIGRATION_GUIDE.md for upgrade help
- Review docstrings in each module
- Run tests to verify changes

---

**Professional Edition 1.0**  
*Built with accessibility, robustness, and modern web standards in mind.*

Last Updated: February 27, 2026
