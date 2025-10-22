# FACTOR × OctoPrint — Remote Monitoring & Camera Integration

<div align="center">

![FACTOR Logo](https://via.placeholder.com/150x150.png?text=FACTOR)

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
  - [Step 3: Login & Register Device](#step-3-login--register-device)
  - [Step 4: Configure MQTT](#step-4-configure-mqtt)
- [Configuration](#-configuration)
- [Security](#-security)
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

### Step 3: Login & Register Device

<div align="center">

<img src="docs/3단계.png" alt="Login" width="600"/>

</div>

1. **Launch Plugin**:
   - Click **FACTOR MQTT** in the left menu
   - Enter your **email/password** from Step 1
   - Click **Login** button

<div align="center">

<img src="docs/3-1단계.png" alt="Device Registration" width="600"/>

</div>

2. **Register Printer**:
   - Select **New Registration** option (default)
   - Click **Create** button
   - Confirm auto-generated Instance ID

3. **Camera Setup** (Optional):
   - Enter stream URL (e.g., `http://192.168.1.100:8080/stream`)
   - Test connection with **Test** button
   - Click **Save**

> 💡 **Supported Formats**: MJPEG, WebRTC, RTSP, HLS

---

### Step 4: Configure MQTT

<div align="center">

<img src="docs/3-2단계.png" alt="MQTT Configuration" width="600"/>

</div>

1. **MQTT Broker Settings**:
   ```
   Broker Host: factor.io.kr
   Port: 1883 (plain) or 8883 (TLS)
   ```

2. **Security Settings** (Recommended):
   - ✅ Check **Use TLS/SSL**
   - Change port to **8883**

3. **Test Connection**:
   - Click **Connection Test** button
   - Verify "Connected" message

4. **Save Settings**:
   - Click **Save** button
   - Finalize with **Register** button

<div align="center">

<img src="docs/결과.png" alt="Complete" width="600"/>

**🎉 Setup Complete! Now monitor your printer from the website.**

</div>

---

## ⚙️ Configuration

### Advanced MQTT Settings

```yaml
# TLS/SSL Encryption (Recommended)
broker_use_tls: true
broker_port: 8883

# Certificate Verification (Production)
broker_tls_insecure: false
broker_tls_ca_cert: /path/to/ca.crt

# QoS Level
qos_level: 1  # 0: At most once, 1: At least once, 2: Exactly once

# Periodic Status Interval (seconds)
periodic_interval: 1.0
```

### Camera Stream URL Examples

| Type | Example URL |
|------|-------------|
| **MJPEG** | `http://192.168.1.100:8080/stream` |
| **WebRTC** | `https://factor.io.kr/webrtc/cam1/` |
| **RTSP** | `rtsp://192.168.1.100:8554/stream` |
| **USB Camera** | `/dev/video0` (Linux) |

---

## 🔐 Security

### 1. Enable MQTT TLS/SSL

```bash
# Broker Host
factor.io.kr

# Use TLS Port
8883

# Enable TLS checkbox in settings
✅ Use TLS/SSL
```

### 2. Firewall Configuration

```bash
# Open MQTT ports (Linux)
sudo ufw allow 1883/tcp  # Plain
sudo ufw allow 8883/tcp  # TLS

# Or allow specific IP only
sudo ufw allow from 192.168.1.0/24 to any port 1883
```

### 3. Network Security

- ✅ Access website via HTTPS
- ✅ Use strong passwords
- ✅ Keep plugin updated regularly
- ⚠️ TLS is mandatory on public networks

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
