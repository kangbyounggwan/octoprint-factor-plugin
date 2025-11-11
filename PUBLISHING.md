# Publishing FACTOR Plugin to PyPI

## Prerequisites

1. **Install build tools**:
   ```bash
   pip install --upgrade build twine
   ```

2. **Create PyPI account**:
   - Go to https://pypi.org/account/register/
   - Verify your email
   - Enable 2FA (recommended)

3. **Create API token**:
   - Go to https://pypi.org/manage/account/token/
   - Create a new API token with scope: "Entire account"
   - Save the token (it starts with `pypi-`)

## Building the Package

1. **Clean old builds**:
   ```bash
   rm -rf build/ dist/ *.egg-info
   ```

2. **Build the package**:
   ```bash
   python -m build
   ```

   This creates files in `dist/`:
   - `octoprint_factor_plugin-2.0.0-py3-none-any.whl`
   - `octoprint-factor-plugin-2.0.0.tar.gz`

## Uploading to PyPI

### Test PyPI (Optional - for testing)

```bash
python -m twine upload --repository testpypi dist/*
```

### Production PyPI

```bash
python -m twine upload dist/*
```

When prompted:
- Username: `__token__`
- Password: `pypi-...` (your API token)

## Verify Installation

After uploading, test installation:

```bash
pip install octoprint-factor-plugin
```

## Register with OctoPrint Plugin Repository

1. **Fork the plugin repository**:
   - Go to https://github.com/OctoPrint/plugins.octoprint.org
   - Click "Fork"

2. **Add your plugin**:
   - Create a new file in `_plugins/` directory
   - Name it: `octoprint_factor_plugin.md`
   - Content:

   ```yaml
   ---
   layout: plugin

   id: factor_mqtt
   title: FACTOR Plugin
   description: Remote monitoring and camera integration for OctoPrint
   authors:
   - FACTOR Team
   license: AGPLv3

   date: 2024-11-11

   homepage: https://factor.io.kr
   source: https://github.com/kangbyounggwan/octoprint-factor-plugin
   archive: https://github.com/kangbyounggwan/octoprint-factor-plugin/archive/{target_version}.zip

   tags:
   - monitoring
   - camera
   - mqtt
   - remote
   - 3dprinting

   screenshots:
   - url: /assets/img/plugins/factor_mqtt/screenshot.png
     alt: FACTOR Plugin Dashboard
     caption: Monitor your printer remotely

   featuredimage: /assets/img/plugins/factor_mqtt/featured.png

   compatibility:
     octoprint:
     - 1.4.0

     os:
     - linux
     - windows
     - macos

     python: ">=3.8,<4"

   ---

   # FACTOR Plugin

   Remote monitoring and camera integration for OctoPrint.

   ## Features

   - Real-time printer status monitoring
   - Camera streaming (MJPEG, WebRTC, RTSP)
   - MQTT integration
   - Remote control capabilities
   - Multi-language support (Korean, English)

   ## Setup

   1. Install the plugin via Plugin Manager
   2. Login with your FACTOR account
   3. Register your device
   4. Complete setup on https://factor.io.kr

   For detailed instructions, see the [GitHub repository](https://github.com/kangbyounggwan/octoprint-factor-plugin).
   ```

3. **Submit Pull Request**:
   - Commit your changes
   - Push to your fork
   - Create a Pull Request to the main repository

## After Registration

Once your PR is merged:
- Plugin will appear in OctoPrint's Plugin Manager
- Users can install directly from the UI
- Updates will be distributed automatically

## Versioning

When releasing new versions:

1. Update version in:
   - `setup.py`
   - `pyproject.toml`
   - `octoprint_mqtt/__init__.py` (`__plugin_version__`)

2. Create a git tag:
   ```bash
   git tag -a v2.0.0 -m "Release version 2.0.0"
   git push origin v2.0.0
   ```

3. Rebuild and upload:
   ```bash
   rm -rf dist/
   python -m build
   python -m twine upload dist/*
   ```

4. GitHub Release:
   - Go to https://github.com/kangbyounggwan/octoprint-factor-plugin/releases
   - Click "Create a new release"
   - Select the tag (v2.0.0)
   - Add release notes
   - Publish

## Troubleshooting

### "Package already exists"
- You can't re-upload the same version
- Increment version number

### "Invalid package name"
- Package name must be lowercase with hyphens
- Use: `octoprint-factor-plugin`

### "Authentication failed"
- Use `__token__` as username
- Use full token including `pypi-` prefix

## Resources

- [PyPI Guide](https://packaging.python.org/tutorials/packaging-projects/)
- [OctoPrint Plugin Tutorial](https://docs.octoprint.org/en/master/plugins/index.html)
- [OctoPrint Plugin Repository](https://plugins.octoprint.org/)
