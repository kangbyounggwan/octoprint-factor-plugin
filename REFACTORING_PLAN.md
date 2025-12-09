# FACTOR Plugin Refactoring Plan

## Overview

This document outlines the comprehensive refactoring plan for the FACTOR OctoPrint plugin to improve code quality, security, and maintainability.

---

## 1. Code Structure Analysis

### Current File Structure
```
octoprint_factor/
├── __init__.py          # Main plugin (1690 lines)
├── control.py           # Printer control functions (173 lines)
├── mqtt_gcode.py        # G-code handling via MQTT (348 lines)
├── static/
│   ├── css/factor.css   # Styles (355 lines)
│   ├── js/
│   │   ├── factor.js    # Main JS (291 lines)
│   │   └── i18n.js      # Internationalization (144 lines)
│   └── translations/
│       ├── en.json
│       └── ko.json
└── templates/
    ├── factor_settings.jinja2
    └── factor_wizard.jinja2
```

---

## 2. Refactoring Tasks

### 2.1 Remove Unused Code

#### Python Files

| File | Location | Issue | Action |
|------|----------|-------|--------|
| `__init__.py` | Line 132-143 | `on_after_startup` empty method | Remove or add meaningful logic |
| `__init__.py` | Line 617 | Comment "finalize function moved to module" | Remove orphan comment |
| `__init__.py` | Lines 352-372 | `_on_mqtt_publish` verbose logging | Simplify |

#### JavaScript Files

| File | Function | Issue | Action |
|------|----------|-------|--------|
| `factor.js` | `MqttWizardViewModel.onWizardFinish` | Empty function | Remove |

### 2.2 Comment Cleanup

#### Remove Unnecessary Comments

| File | Line | Current | Action |
|------|------|---------|--------|
| `__init__.py` | 83 | `##~~ SettingsPlugin mixin` | Remove section markers |
| `__init__.py` | 123 | `##~~ AssetPlugin mixin` | Remove |
| `__init__.py` | 182 | `##~~ WizardPlugin mixin` | Remove |
| `__init__.py` | 194 | `##~~ ShutdownPlugin mixin` | Remove |
| `__init__.py` | 199 | `##~~ EventHandlerPlugin mixin` | Remove |
| `__init__.py` | 223 | `##~~ Private methods` | Remove |
| `__init__.py` | 349-350 | Timer comment | Remove |
| `__init__.py` | 425-426 | Korean comment `# camera 명령은...` | Remove |
| `__init__.py` | 617 | `# finalize function moved to module` | Remove |
| `__init__.py` | 1006 | `# ==== END Camera helpers ====` | Remove |
| `__init__.py` | 1137 | `##~~ BlueprintPlugin mixin` | Remove |
| `__init__.py` | 1645 | `# TODO: Track tool changes` | Remove TODO comment |
| `control.py` | 44-46 | Docstring excessive | Simplify |
| `control.py` | 115-118 | Docstring excessive | Simplify |
| `control.py` | 140-144 | Docstring excessive | Simplify |
| `mqtt_gcode.py` | 43-48 | Commented code block | Remove |

### 2.3 Emoji Removal

| File | Line | Current | Replacement |
|------|------|---------|-------------|
| `__init__.py` | 452 | `✅ Device registration confirmed` | `Device registration confirmed` |
| `__init__.py` | 491 | `❌ Device registration {status}` | `Device registration {status}` |
| `factor.js` | 24-30 | Status icons with emojis | Use CSS classes or icon fonts |
| `factor_settings.jinja2` | 7-11 | Flag emojis in buttons | Remove or use text only |
| `factor_wizard.jinja2` | 6-11 | Flag emojis in buttons | Remove or use text only |

### 2.4 Security Review

#### Current Security Measures (Documented)

| Feature | Location | Implementation |
|---------|----------|----------------|
| URL Validation | `__init__.py:739-754` | `_validate_url()` prevents command injection |
| Stream Name Validation | `__init__.py:769-771` | Regex whitelist for alphanumeric |
| Encoder Whitelist | `__init__.py:794-797` | Only allowed encoders accepted |
| Filename Validation | `mqtt_gcode.py:13-31` | `_validate_filename()` prevents path traversal |
| G-code Content Validation | `mqtt_gcode.py:34-49` | `_validate_gcode_content()` size limits |
| Instance ID Security | `__init__.py:1109-1135` | `_get_required_instance_id()` prevents generic topic sharing |
| Print Authorization | `mqtt_gcode.py:78-83` | Whitelist check before printing |

#### Potential Improvements

| Area | Issue | Recommendation |
|------|-------|----------------|
| MQTT Topics | Topic injection possible if instance_id compromised | Add topic validation |
| TLS | `tls_insecure` option exists | Add warning in UI, consider removing |
| Error Messages | Some expose internal details | Sanitize error responses |
| Input Validation | Integer parameters trust input | Add range validation consistently |

### 2.5 Code Quality Improvements

#### Naming Conventions

| File | Current | Proposed |
|------|---------|----------|
| `__init__.py` | `_as_code` | `_parse_mqtt_result_code` |
| `__init__.py` | `inst` (variable) | `instance_id` (full name) |
| `__init__.py` | `t` (variable) | `msg_type` or `command_type` |
| `mqtt_gcode.py` | `wl` (variable) | `whitelist` |
| `mqtt_gcode.py` | `b64` (variable) | `base64_data` |

#### Function Organization

| Current Location | Function | Proposed Module |
|------------------|----------|-----------------|
| `__init__.py` | Camera methods (711-1005) | `camera.py` |
| `__init__.py` | Position tracking (1344-1655) | `position.py` |
| `__init__.py` | Snapshot methods (1255-1340) | `status.py` |

### 2.6 Duplicate Import Cleanup

| File | Line | Issue |
|------|------|-------|
| `__init__.py` | 2, 656, 1257 | `import json` appears multiple times |
| `__init__.py` | 8, 1257 | `import time` appears multiple times |

### 2.7 f-string Consistency

Convert `.format()` and `%` formatting to f-strings for consistency:

| File | Line | Current Style |
|------|------|---------------|
| `__init__.py` | Multiple | Mixed usage |

---

## 3. Architecture Documentation

### 3.1 MQTT Communication Flow

```
OctoPrint Plugin                    MQTT Broker                    FACTOR Server
      |                                  |                               |
      |-- connect(TLS) ----------------->|                               |
      |<--- connected --------------------|                               |
      |                                  |                               |
      |-- subscribe(control/{id}) ------>|                               |
      |-- subscribe(gcode_in/{id}) ----->|                               |
      |-- subscribe(camera/{id}/cmd) --->|                               |
      |                                  |                               |
      |<---- control message ------------|<----- user command -----------|
      |-- execute command                |                               |
      |-- publish(status/{id}) --------->|-----> status update --------->|
      |                                  |                               |
```

### 3.2 Security Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Input Layer                               │
├─────────────────────────────────────────────────────────────────┤
│  _validate_url()        - URL injection prevention              │
│  _validate_filename()   - Path traversal prevention             │
│  _validate_gcode_content() - Size/content validation            │
│  Instance ID validation - Topic isolation                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Processing Layer                              │
├─────────────────────────────────────────────────────────────────┤
│  MQTT message handlers with type checking                        │
│  Whitelist-based print authorization                            │
│  Rate limiting via job expiration                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Output Layer                                │
├─────────────────────────────────────────────────────────────────┤
│  OctoPrint API calls with tags                                   │
│  Subprocess execution with validated parameters                  │
│  MQTT publish to instance-specific topics only                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| `__init__.py` | Plugin lifecycle, MQTT connection, event routing |
| `control.py` | Printer control commands (pause, resume, move, etc.) |
| `mqtt_gcode.py` | G-code file transfer via MQTT chunks |
| `factor.js` | Settings UI, connection status display |
| `i18n.js` | Multi-language support |

---

## 4. Implementation Phases

### Phase 1: Cleanup (Low Risk) - COMPLETED
1. ~~Remove all unused code and empty functions~~
2. ~~Remove unnecessary comments and section markers~~
3. ~~Remove emoji characters from logs~~
4. ~~Consolidate duplicate imports~~

### Phase 2: Standardization (Low Risk) - COMPLETED
1. ~~Apply consistent naming conventions~~
2. ~~Convert all string formatting to f-strings~~
3. ~~Standardize error message format~~

### Phase 3: Restructuring (Medium Risk) - OPTIONAL
1. Extract camera functions to `camera.py`
2. Extract position tracking to `position.py`
3. Extract status/snapshot to `status.py`
4. Update imports and references

### Phase 4: Security Hardening (Medium Risk) - OPTIONAL
1. Add MQTT topic validation
2. Improve error message sanitization
3. Add comprehensive input validation
4. Consider removing `tls_insecure` option

### Phase 5: Documentation - OPTIONAL
1. Add module-level docstrings
2. Document public API functions
3. Create developer documentation

---

## 5. Testing Requirements

### Unit Tests Required
- [ ] `_validate_url()` - test injection patterns
- [ ] `_validate_filename()` - test path traversal
- [ ] `_validate_gcode_content()` - test size limits
- [ ] `_get_required_instance_id()` - test error cases
- [ ] Control functions - test printer state checks

### Integration Tests Required
- [ ] MQTT connection/reconnection
- [ ] G-code chunk transfer
- [ ] Camera pipeline start/stop
- [ ] Event handling flow

---

## 6. Version Strategy

- Current: 2.7.6
- After Phase 1-2: 2.8.0 (Recommended next release)
- After Phase 3: 3.0.0 (breaking change potential)
- After Phase 4-5: 3.1.0

---

## 7. Files to Modify

### High Priority
1. `octoprint_factor/__init__.py` - Main cleanup and restructuring
2. `octoprint_factor/mqtt_gcode.py` - Comment removal
3. `octoprint_factor/control.py` - Docstring simplification
4. `octoprint_factor/static/js/factor.js` - Emoji removal

### Medium Priority
1. `octoprint_factor/templates/factor_settings.jinja2` - Emoji removal
2. `octoprint_factor/templates/factor_wizard.jinja2` - Emoji removal

### Low Priority
1. `octoprint_factor/static/css/factor.css` - No changes needed
2. `octoprint_factor/static/js/i18n.js` - No changes needed
3. Translation JSON files - No changes needed
