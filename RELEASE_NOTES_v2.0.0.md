# FACTOR Plugin v2.0.0 🚀

**Major Release: Workflow Redesign & Plugin Rename**

---

##  What's New

###  Plugin Rebranding
- **New Name**: "FACTOR Plugin" (previously "MQTT-Plugin from FACTOR")
- Clean, professional branding aligned with FACTOR platform
- Updated all UI elements and documentation

###  Simplified 3-Step Setup Flow
We've completely redesigned the registration process to make it faster and easier:

**Old Flow** (4 steps):
1. Login → 2. Register → 3. MQTT Settings → 4. Connection Test

**New Flow** (3 steps):
1. **Login** - Authenticate with FACTOR account
2. **Device Registration** - Generate Device UUID & configure camera
3. **Go to Web** - Complete setup on FACTOR website

**Why the change?**
- ✅ Faster setup (1 less step)
- ✅ No complex MQTT configuration needed
- ✅ Better user experience
- ✅ Web-based configuration is more flexible

###  Full Internationalization
- **Korean (한국어)** and **English** support
- Automatic language detection based on browser settings
- All UI elements, messages, and tooltips translated
- Easy to add more languages in the future

###  Improved Camera Setup
- Better camera URL validation
- Live preview testing
- Support for multiple stream formats (MJPEG, WebRTC, RTSP, HLS)
- Enhanced error messages

---

##  Technical Improvements

### Code Quality
- Refactored JavaScript for better maintainability
- Improved error handling and user feedback
- Fixed web navigation button binding issues
- Better separation of concerns

### Documentation
- Added comprehensive PyPI publishing guide ([PUBLISHING.md](PUBLISHING.md))
- Updated README with new 5-step user guide
- Added LICENSE file (AGPLv3)
- Modern Python packaging with `pyproject.toml`

### Project Structure
```
octoprint-factor-plugin/
├── .github/
│   └── FUNDING.yml          # Sponsorship configuration
├── docs/
│   └── logo.png             # Official FACTOR logo
├── octoprint_mqtt/
│   ├── static/
│   │   ├── translations/    # Moved from root
│   │   │   ├── ko.json
│   │   │   └── en.json
│   │   └── js/
│   │       └── i18n.js      # New i18n helper
├── LICENSE                  # AGPLv3
├── pyproject.toml          # Modern packaging
└── PUBLISHING.md           # PyPI guide
```

---

##  Breaking Changes

###  Migration Required
If you're upgrading from v1.x:

1. **Uninstall old version**:
   ```bash
   pip uninstall octoprint-mqtt-factor
   ```

2. **Install new version**:
   - From OctoPrint Plugin Manager: Search "FACTOR"
   - From URL: `https://github.com/kangbyounggwan/octoprint-factor-plugin/archive/v2.0.0.zip`

3. **Re-register your device**:
   - Old settings won't carry over
   - Use the new 3-step process
   - Your printer data remains safe on FACTOR platform

### Changed Settings
- MQTT configuration moved to web platform
- Camera settings now in Device Registration step
- Removed manual MQTT broker configuration from UI

---

##  Installation

### Method 1: OctoPrint Plugin Manager (Recommended)
1. Open OctoPrint Settings
2. Go to Plugin Manager
3. Click "Get More..."
4. Search for "FACTOR"
5. Click "Install"

### Method 2: URL
1. Open OctoPrint Settings
2. Go to Plugin Manager
3. Click "Get More..."
4. Enter URL:
   ```
   https://github.com/kangbyounggwan/octoprint-factor-plugin/archive/v2.0.0.zip
   ```
5. Click "Install"

### Method 3: PyPI (Coming Soon)
```bash
pip install octoprint-factor-plugin
```

---

## Bug Fixes

- Fixed web navigation button not binding on initial load
- Fixed button binding when navigating via tabs
- Fixed translation loading race condition
- Fixed camera section initialization timing issues

---

##  Documentation Updates

- ✅ [README.md](README.md) - Korean documentation (5-step guide)
- ✅ [README_EN.md](README_EN.md) - English documentation
- ✅ [PUBLISHING.md](PUBLISHING.md) - PyPI publishing guide
- ✅ Added inline code documentation

---

##  Acknowledgments

Special thanks to:
- FACTOR Team for the redesigned workflow
- OctoPrint community for feedback
- Early testers who helped identify issues

---

##  Stats

- **14 files changed**
- **481 additions**
- **327 deletions**
- **3 new features**
- **4 bug fixes**
- **2 languages supported**

---

##  Links

-  **FACTOR Platform**: [https://factor.io.kr](https://factor.io.kr)
-  **Documentation**: [GitHub Repository](https://github.com/kangbyounggwan/octoprint-factor-plugin)
-  **Report Issues**: [GitHub Issues](https://github.com/kangbyounggwan/octoprint-factor-plugin/issues)
-  **Support**: Contact via FACTOR website

---

## ⬇ Download

- **Source Code**: [v2.0.0.zip](https://github.com/kangbyounggwan/octoprint-factor-plugin/archive/v2.0.0.zip)
- **Source Code**: [v2.0.0.tar.gz](https://github.com/kangbyounggwan/octoprint-factor-plugin/archive/v2.0.0.tar.gz)

---

##  What's Next?

Coming in future versions:
- [ ] PyPI package publication
- [ ] OctoPrint Plugin Repository registration
- [ ] More language support (Japanese, Chinese, etc.)
- [ ] Advanced camera configuration options
- [ ] Enhanced monitoring features

---

**Full Changelog**: [v1.0.9...v2.0.0](https://github.com/kangbyounggwan/octoprint-factor-plugin/compare/v1.0.9...v2.0.0)

---

<div align="center">

**Made with ❤️ by FACTOR Team**

[Website](https://factor.io.kr) • [GitHub](https://github.com/kangbyounggwan/octoprint-factor-plugin) • [Issues](https://github.com/kangbyounggwan/octoproject-factor-plugin/issues)

</div>
