# FACTOR × OctoPrint — Remote Monitoring & Camera Integration

<div align="center">

<img src="docs/logo.png" alt="FACTOR Logo" width="150"/>

**Monitor Your 3D Printer from Anywhere**

Have you ever come home after a long print to find **spaghetti or a clogged extruder**?
That's why we created **FACTOR** - an external monitoring platform that integrates with OctoPrint.

[![status](https://img.shields.io/badge/status-beta-blue)](https://github.com/kangbyounggwan/octoprint-factor-plugin)
[![platform](https://img.shields.io/badge/OctoPrint-plugin-green)](https://plugins.octoprint.org)
[![license](https://img.shields.io/badge/license-AGPLv3-lightgrey)](LICENSE)
[![language](https://img.shields.io/badge/language-한국어-red)](README.md)
[![language](https://img.shields.io/badge/language-English-blue)](README_EN.md)

**[🌐 Website](https://factor.io.kr)** •
**[📦 Download](https://github.com/kangbyounggwan/octoprint-factor-plugin/archive/main.zip)** •
**[📖 Documentation](https://factor.io.kr/docs)** •
**[💬 Report Issues](https://github.com/kangbyounggwan/octoprint-factor-plugin/issues)**

</div>

---

## 📋 Table of Contents

- [Features](#-features)
- [Quick Start](#-quick-start)
  - [Step 1: Sign Up](#step-1-sign-up)
  - [Step 2: Install Plugin](#step-2-install-plugin)
  - [Step 3: Login in Plugin](#step-3-login-in-plugin)
  - [Step 4: Register Device](#step-4-register-device)
  - [Step 5: Complete Setup on Web](#step-5-complete-setup-on-web)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)
- [License](#-license)

---

## ✨ Features

<table>
<tr>
<td width="50%">

### 🖥️ Real-time Monitoring
- Track print progress and status
- Monitor temperature and print time
- Manage multiple printers simultaneously

</td>
<td width="50%">

### 📹 Camera Integration
- Supports MJPEG/WebRTC/RTSP/HLS
- Use existing stream URLs as-is
- Real-time video streaming

</td>
</tr>
<tr>
<td width="50%">

### 🔒 Enhanced Security
- MQTT TLS/SSL encryption support
- Rate limiting and input validation
- Secure command execution

</td>
<td width="50%">

### ⚡ Easy Setup
- Complete setup in 5-10 minutes
- Automatic plugin updates
- Intuitive user interface

</td>
</tr>
</table>

---

## 🚀 Quick Start

### 📝 Prerequisites

- OctoPrint 1.4.0 or higher
- Python 3.8 or higher
- Internet connection

### Step 1: Sign Up

<div align="center">

<img src="docs/1단계.png" alt="Sign Up" width="600"/>

</div>

1. **Visit Website**: [https://factor.io.kr](https://factor.io.kr)
2. **Create Account**:
   - Click **Login** in the top right
   - Select **Sign Up** tab
   - Enter email, username, and password
   - Click **Sign Up** button
3. **Email Verification**: Click the verification link in your inbox

> 💡 **Tip**: Check your spam folder if you don't receive the email.

---

### Step 2: Install Plugin

<div align="center">

<img src="docs/2단계.png" alt="Plugin Manager" width="600"/>

</div>

1. **Open OctoPrint Settings**:
   - Click the **🔧 wrench icon** in the top right
   - Select **Plugin Manager**

<div align="center">

<img src="docs/2-1단계.png" alt="Install from URL" width="600"/>

</div>

2. **Install from URL**:
   - Click **Get More…** button
   - Select **…from URL**
   - Paste the following URL:
   ```
   https://github.com/kangbyounggwan/octoprint-factor-plugin/archive/main.zip
   ```
   - Click **Install**
3. **Restart OctoPrint**: Follow the prompt to restart after installation

> ⚠️ **Warning**: The plugin won't activate until you restart.

---

### Step 3: Login in Plugin

<div align="center">

<img src="docs/3단계.png" alt="Login" width="600"/>

</div>

1. **Launch Plugin**:
   - Click **FACTOR MQTT** in the left menu
   - Enter your **email/password** from Step 1
   - Click **Login** button

---

### Step 4: Register Device

<div align="center">

<img src="docs/3-1단계.png" alt="Device Registration" width="600"/>

</div>

1. **Generate Device UUID**:
   - Click **Create** button
   - Copy the auto-generated Device UUID

2. **Camera Setup** (Optional):
   - Enter stream URL (e.g., `http://192.168.1.100:8080/stream`)
   - Test connection with **Test** button
   - Click **Save**

3. **Complete Registration**:
   - Click **Register** button

> 💡 **Supported Camera Formats**: MJPEG, WebRTC, RTSP, HLS

---

### Step 5: Complete Setup on Web

1. **Go to Website**:
   - Click **Go to FACTOR Website** button in plugin
   - Or visit [https://factor.io.kr](https://factor.io.kr) directly

2. **Register Printer**:
   - Enter the **Device UUID** from Step 4
   - Configure printer name, description, etc.
   - Click **Complete Registration**

3. **Start Monitoring**:
   - View real-time printer status on dashboard
   - MQTT automatically connects and starts sending data

<div align="center">

<img src="docs/결과.png" alt="Complete" width="600"/>

**🎉 Setup Complete! Now monitor your printer from the website.**

</div>

---

## 🛠️ Troubleshooting

### MQTT Connection Failed

**Symptom**: "Connection Test" fails

**Solutions**:
1. Check network connection
2. Verify broker host/port
3. Check firewall settings
4. Review OctoPrint logs: `Settings > Logging > octoprint.plugins.factor_mqtt`

### Camera Stream Not Showing

**Symptom**: No camera feed on website

**Solutions**:
1. Verify stream URL is correct
2. HTTP streams may be blocked on HTTPS sites (Mixed Content)
3. Check browser console for errors (F12)
4. Verify ffmpeg process status

### View Logs

```bash
# OctoPrint log location
~/.octoprint/logs/octoprint.log

# Real-time log monitoring
tail -f ~/.octoprint/logs/octoprint.log | grep MQTT
```

### Common Error Codes

| Code | Meaning | Solution |
|------|---------|----------|
| `rc=1` | Invalid protocol version | Check broker settings |
| `rc=2` | Client ID rejected | Regenerate Instance ID |
| `rc=3` | Server unavailable | Check broker status |
| `rc=4` | Bad username/password | Verify credentials |
| `rc=5` | Not authorized | Check account permissions |

---

## 🤝 Contributing

Bug reports, feature requests, and pull requests are welcome!

1. Fork this repository
2. Create a Feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Create a Pull Request

### Development Setup

```bash
# Clone repository
git clone https://github.com/kangbyounggwan/octoprint-factor-plugin.git
cd octoprint-factor-plugin

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install in development mode
pip install -e .
```

---

## 📄 License

This project is distributed under the [AGPLv3 License](LICENSE).

---

## 🙏 Acknowledgments

- [OctoPrint](https://octoprint.org/) - Amazing 3D printer control software
- [Paho MQTT](https://www.eclipse.org/paho/) - MQTT client library
- Thanks to all beta testers!

---

<div align="center">

**[⬆ Back to Top](#factor--octoprint--remote-monitoring--camera-integration)**

Made with ❤️ by FACTOR Team

</div>
