# -*- coding: utf-8 -*-
import json
import os
import re
import shlex
import signal
import subprocess
import threading
import time
import uuid

import octoprint.plugin
from flask import jsonify, make_response
from octoprint.filemanager import FileDestinations
from octoprint.util import RepeatedTimer


__plugin_name__ = "FACTOR Plugin"
__plugin_pythoncompat__ = ">=3.8,<4"
__plugin_version__ = "2.8.2"
__plugin_identifier__ = "octoprint_factor"


class InstanceIdRequiredError(Exception):
    """Raised when instance_id is required but not available."""
    pass


def _parse_mqtt_result_code(result_code):
    """Parse MQTT result code from various formats."""
    try:
        value = getattr(result_code, "value", None)
        if isinstance(value, int):
            return value
        return int(result_code)
    except Exception:
        text = (str(result_code) if result_code is not None else "").strip().lower()
        if text in ("success", "normal disconnection"):
            return 0
        match = re.search(r"(\d+)", text)
        return int(match.group(1)) if match else -1


class FactorPlugin(
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.ShutdownPlugin,
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.BlueprintPlugin,
    octoprint.plugin.WizardPlugin
):

    def __init__(self):
        super().__init__()
        self.mqtt_client = None
        self.is_connected = False
        self._snapshot_timer = None
        self._snapshot_timer_lock = threading.Lock()
        self._gcode_jobs = {}
        self._camera_proc = None
        self._camera_started_at = None
        self._camera_last_error = None
        self._temp_instance_id = None
        self._current_position = {"x": None, "y": None, "z": None, "e": None}
        self._target_position = {"x": None, "y": None, "z": None, "e": None}
        self._position_offset = {"x": None, "y": None, "z": None, "e": None}
        self._position_lock = threading.Lock()
        self._is_absolute_positioning = True
        self._path_history = []
        self._path_history_max = 10000
        self._last_recorded_position = {"x": 0, "y": 0, "z": 0, "e": 0}
        self._feed_rate = 100  # M220 S value (percentage)
        self._flow_rate = 100  # M221 S value (percentage)

    def get_settings_defaults(self):
        return dict(
            broker_host="factor.io.kr",
            broker_port=8883,
            broker_username="",
            broker_password="",
            broker_use_tls=True,
            broker_tls_insecure=False,
            broker_tls_ca_cert="",
            topic_prefix="octoprint",
            qos_level=0,
            retain_messages=False,
            publish_status=True,
            publish_progress=True,
            publish_temperature=True,
            publish_gcode=False,
            periodic_interval=1.0,
            instance_id="",
            registered=False,
            receive_gcode_enabled=True,
            receive_topic_suffix="gcode_in",
            receive_target_default="local_print",
            receive_timeout_sec=300,
            camera=dict(stream_url="")
        )

    def get_settings_version(self):
        return 1

    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self._disconnect_mqtt()
        self._connect_mqtt()

    def get_assets(self):
        return dict(
            js=["js/i18n.js", "js/factor.js"],
            css=["css/factor.css"]
        )

    def on_startup(self, host, port):
        self._connect_mqtt()
        try:
            self._log_api_endpoints(host, port)
        except Exception as e:
            self._logger.warning("Error logging endpoints: %s", e)

    def on_after_startup(self):
        pass

    def _log_api_endpoints(self, host, port):
        base_url = self._settings.global_get(["server", "baseUrl"]) or ""
        base_url = base_url.rstrip("/")
        internal_base = f"http://{host}:{port}{base_url}"
        plugin_id = __plugin_identifier__
        self._logger.info("[FACTOR] REST endpoints ready:")
        self._logger.info(" - GET  %s/api/plugin/%s/status", internal_base, plugin_id)
        self._logger.info(" - POST %s/api/plugin/%s/test", internal_base, plugin_id)

    def get_template_configs(self):
        return [
            dict(type="settings", name="FACTOR", template="factor_settings.jinja2", custom_bindings=True),
            dict(type="wizard", template="factor_wizard.jinja2", custom_bindings=True)
        ]

    def is_wizard_required(self):
        return not self._settings.get_boolean(["registered"])

    def get_wizard_version(self):
        return 1

    def get_wizard_details(self):
        return dict()

    def on_shutdown(self):
        self._disconnect_mqtt()

    def on_event(self, event, payload):
        if not self.is_connected:
            return

        if event == "PrintStarted":
            self._capture_position_offset()
            self._clear_path_history()
        elif event in ("PrintDone", "PrintFailed", "PrintCancelled"):
            self._reset_position_offset()

        topic_prefix = self._settings.get(["topic_prefix"])

        if event == "PrinterStateChanged":
            self._publish_status(payload, topic_prefix)
        elif event == "PrintProgress":
            self._publish_progress(payload, topic_prefix)
        elif event == "TemperatureUpdate":
            self._publish_temperature(payload, topic_prefix)
        elif event == "GcodeReceived":
            self._publish_gcode(payload, topic_prefix)

    def _connect_mqtt(self):
        try:
            import paho.mqtt.client as mqtt
            import ssl

            self.mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

            username = self._settings.get(["broker_username"])
            password = self._settings.get(["broker_password"])
            if username:
                self.mqtt_client.username_pw_set(username, password)

            use_tls = self._settings.get(["broker_use_tls"])
            if use_tls:
                tls_insecure = self._settings.get(["broker_tls_insecure"])
                ca_cert = self._settings.get(["broker_tls_ca_cert"])

                tls_context = ssl.create_default_context()
                if tls_insecure:
                    tls_context.check_hostname = False
                    tls_context.verify_mode = ssl.CERT_NONE
                    self._logger.warning("MQTT TLS certificate verification disabled")
                elif ca_cert:
                    tls_context.load_verify_locations(cafile=ca_cert)

                self.mqtt_client.tls_set_context(tls_context)
                self._logger.info("MQTT TLS/SSL enabled")

            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self.mqtt_client.on_publish = self._on_mqtt_publish
            self.mqtt_client.on_log = self._on_mqtt_log
            self.mqtt_client.on_message = self._on_mqtt_message

            self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=120)

            host = self._settings.get(["broker_host"])
            port = int(self._settings.get(["broker_port"]))
            protocol = "mqtts" if use_tls else "mqtt"
            self._logger.info(f"MQTT connecting: {protocol}://{host}:{port}")

            self.mqtt_client.connect_async(host, port, 60)
            self.mqtt_client.loop_start()

        except Exception as e:
            self._logger.error(f"MQTT connection failed: {e}")

    def _disconnect_mqtt(self):
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            self.mqtt_client = None
            self.is_connected = False
            self._logger.info("MQTT client disconnected")

    def _subscribe_mqtt_topics(self):
        """Subscribe to MQTT topics using current instance_id."""
        if not self.is_connected or not self.mqtt_client:
            self._logger.warning("Cannot subscribe: MQTT not connected")
            return

        try:
            qos = int(self._settings.get(["qos_level"]) or 1)
            instance_id = self._get_required_instance_id(context="MQTT topic subscription")

            if hasattr(self, '_current_subscribed_id') and self._current_subscribed_id != instance_id:
                old_id = self._current_subscribed_id
                old_topics = [
                    f"control/{old_id}",
                    f"octoprint/gcode_in/{old_id}",
                    f"camera/{old_id}/cmd",
                    f"device/{old_id}/registration"
                ]
                for topic in old_topics:
                    self.mqtt_client.unsubscribe(topic)
                self._logger.info(f"[FACTOR] Unsubscribed from old topics: {old_id}")

            topics = [
                f"control/{instance_id}",
                f"octoprint/gcode_in/{instance_id}",
                f"camera/{instance_id}/cmd",
                f"device/{instance_id}/registration"
            ]

            for topic in topics:
                self.mqtt_client.subscribe(topic, qos=qos)

            self._current_subscribed_id = instance_id
            self._logger.info(f"[FACTOR] Subscribed to topics: {instance_id}")
        except Exception as e:
            self._logger.warning(f"[FACTOR] Subscribe failed: {e}")

    def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None, *args, **kwargs):
        result_code = _parse_mqtt_result_code(rc)
        self.is_connected = (result_code == 0)
        if self.is_connected:
            instance_id = self._temp_instance_id or self._settings.get(["instance_id"])
            self._logger.info(f"[FACTOR] MQTT connected - Instance: {instance_id or '(none)'}")
            self._start_snapshot_timer()
            if instance_id:
                self._subscribe_mqtt_topics()
            else:
                self._logger.warning("[FACTOR] No instance ID, skipping subscription")
        else:
            self._logger.error(f"[FACTOR] MQTT connection failed: {rc}")

    def _on_mqtt_disconnect(self, client, userdata, rc, properties=None, *args, **kwargs):
        self.is_connected = False
        self._logger.warning(f"MQTT disconnected: {rc}")

    def _on_mqtt_publish(self, client, userdata, mid, *args, **kwargs):
        self._logger.debug(f"MQTT publish: mid={mid}")

    def _on_mqtt_log(self, client, userdata, level, buf):
        if level == 1:
            self._logger.debug(f"MQTT: {buf}")
        elif level == 2:
            self._logger.info(f"MQTT: {buf}")
        elif level == 4:
            self._logger.warning(f"MQTT: {buf}")
        elif level == 8:
            self._logger.error(f"MQTT: {buf}")

    def _on_mqtt_message(self, client, userdata, msg):
        try:
            topic = msg.topic or ""
            instance_id = self._temp_instance_id or self._settings.get(["instance_id"])
            if not instance_id:
                self._logger.warning(f"[FACTOR] No instance ID, ignoring: {topic}")
                return

            payload_preview = str(msg.payload[:100]) if msg.payload else ""
            self._logger.debug(f"[FACTOR] Message: {topic}, preview: {payload_preview}")

            if topic == f"control/{instance_id}":
                payload = msg.payload.decode("utf-8", errors="ignore") if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload or "")
                try:
                    data = json.loads(payload or "{}")
                except Exception:
                    data = {}
                self._handle_control_message(data)
                return

            if topic == f"octoprint/gcode_in/{instance_id}":
                if not bool(self._settings.get(["receive_gcode_enabled"])):
                    return
                payload = msg.payload.decode("utf-8", errors="ignore") if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload or "")
                data = json.loads(payload or "{}")
                self._handle_gcode_message(data)
                return

            if topic == f"camera/{instance_id}/cmd":
                payload = msg.payload.decode("utf-8", errors="ignore") if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload or "")
                try:
                    data = json.loads(payload or "{}")
                except Exception:
                    data = {}
                if isinstance(data, dict):
                    data = {"type": "camera", **data}
                else:
                    data = {"type": "camera"}
                self._handle_control_message(data)
                return

            registration_topic = f"device/{instance_id}/registration"
            if self._temp_instance_id:
                temp_topic = f"device/{self._temp_instance_id}/registration"
                if topic == registration_topic or topic == temp_topic:
                    payload = msg.payload.decode("utf-8", errors="ignore") if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload or "")
                    self._logger.info(f"[FACTOR] Registration message: {payload}")
                    try:
                        data = json.loads(payload or "{}")
                        status = data.get("status")

                        if status in ("registered", "registration_confirmed"):
                            final_id = self._temp_instance_id or instance_id
                            self._settings.set(["instance_id"], final_id)
                            self._settings.set(["registered"], True)
                            self._settings.save()

                            self._logger.info(f"[FACTOR] Registration confirmed: {final_id}")

                            confirmation = {
                                "status": "confirmed",
                                "instance_id": final_id,
                                "confirmed_at": data.get("registered_at")
                            }
                            try:
                                self.mqtt_client.publish(
                                    f"device/{final_id}/registration/ack",
                                    json.dumps(confirmation),
                                    qos=1
                                )
                            except Exception as e:
                                self._logger.error(f"Registration ack failed: {e}")

                            self._temp_instance_id = None
                            self.mqtt_client.unsubscribe(topic)

                            self._plugin_manager.send_plugin_message(
                                self._identifier,
                                dict(
                                    type="registration_confirmed",
                                    device_name=data.get("device_name"),
                                    registered_at=data.get("registered_at")
                                )
                            )

                        elif status in ("timeout", "failed"):
                            error_msg = data.get("error", f"Registration {status}")
                            error_code = data.get("error_code")
                            self._logger.warning(f"[FACTOR] Registration {status}: {error_msg}")

                            self.mqtt_client.unsubscribe(topic)
                            self._temp_instance_id = None

                            self._plugin_manager.send_plugin_message(
                                self._identifier,
                                dict(
                                    type="registration_failed",
                                    status=status,
                                    error=error_msg,
                                    error_code=error_code,
                                    attempted_at=data.get("attempted_at")
                                )
                            )
                    except Exception as e:
                        self._logger.error(f"Registration processing failed: {e}")
                    return
        except Exception as e:
            self._logger.exception(f"[FACTOR] Message processing error: {e}")

    def _handle_gcode_message(self, data):
        try:
            from .mqtt_gcode import handle_gcode_message
            handle_gcode_message(self, data)
        except Exception as e:
            self._logger.exception(f"GCODE handler error: {e}")

    def _handle_control_message(self, data):
        cmd_type = (data.get("type") or "").lower()
        try:
            from .control import (
                pause_print, resume_print, cancel_print,
                home_axes, move_axes, set_temperature,
                set_feed_rate, set_fan_speed
            )
        except Exception:
            pause_print = resume_print = cancel_print = None
            home_axes = move_axes = set_temperature = None
            set_feed_rate = set_fan_speed = None

        if cmd_type == "camera":
            action = (data.get("action") or "").lower()
            opts = data.get("options") or {}
            if action == "start":
                result = self._camera_start(opts)
                self._publish_camera_state()
                self._logger.info(f"[CONTROL] camera start: {result}")
            elif action == "stop":
                result = self._camera_stop(opts)
                self._publish_camera_state()
                self._logger.info(f"[CONTROL] camera stop: {result}")
            elif action == "restart":
                self._camera_stop(opts)
                time.sleep(0.4)
                result = self._camera_start(opts)
                self._publish_camera_state()
                self._logger.info(f"[CONTROL] camera restart: {result}")
            elif action == "state":
                self._publish_camera_state()
            return

        if cmd_type == "pause":
            result = pause_print(self) if pause_print else {"error": "unavailable"}
            self._logger.info(f"[CONTROL] pause: {result}")
        elif cmd_type == "resume":
            result = resume_print(self) if resume_print else {"error": "unavailable"}
            self._logger.info(f"[CONTROL] resume: {result}")
        elif cmd_type == "cancel":
            result = cancel_print(self) if cancel_print else {"error": "unavailable"}
            self._logger.info(f"[CONTROL] cancel: {result}")
        elif cmd_type == "home":
            axes_str = data.get("axes") or "XYZ"
            axes_str = axes_str if isinstance(axes_str, str) else "".join(axes_str)
            axes = []
            s = (axes_str or "").lower()
            if "x" in s:
                axes.append("x")
            if "y" in s:
                axes.append("y")
            if "z" in s:
                axes.append("z")
            if not axes:
                axes = ["x", "y", "z"]
            result = home_axes(self, axes) if home_axes else {"error": "unavailable"}
            self._logger.info(f"[CONTROL] home {axes}: {result}")
        elif cmd_type == "move":
            mode = (data.get("mode") or "relative").lower()
            x = data.get("x")
            y = data.get("y")
            z = data.get("z")
            e = data.get("e")
            feedrate = data.get("feedrate") or 1000
            result = move_axes(self, mode, x, y, z, e, feedrate) if move_axes else {"error": "unavailable"}
            self._logger.info(f"[CONTROL] move: {result}")
        elif cmd_type == "set_temperature":
            tool = int(data.get("tool", 0))
            temperature = float(data.get("temperature", 0))
            wait = bool(data.get("wait", False))
            result = set_temperature(self, tool, temperature, wait) if set_temperature else {"error": "unavailable"}
            self._logger.info(f"[CONTROL] set_temperature: {result}")
        elif cmd_type in ("set_feed_rate", "feed_rate"):
            factor = float(data.get("factor") or data.get("speed") or 100)
            result = set_feed_rate(self, factor) if set_feed_rate else {"error": "unavailable"}
            self._logger.info(f"[CONTROL] set_feed_rate: {result}")
        elif cmd_type in ("set_fan_speed", "fan_speed"):
            speed = int(data.get("speed") or 0)
            result = set_fan_speed(self, speed) if set_fan_speed else {"error": "unavailable"}
            self._logger.info(f"[CONTROL] set_fan_speed: {result}")
        else:
            self._logger.warning(f"[CONTROL] unknown type: {cmd_type}")

    def _gc_expired_jobs(self, now=None):
        try:
            if now is None:
                now = time.time()
            timeout = int(self._settings.get(["receive_timeout_sec"]) or 300)
            expired = []
            for job_id, state in self._gcode_jobs.items():
                if now - (state.get("last_ts") or state.get("created_ts") or now) > timeout:
                    expired.append(job_id)
            for job_id in expired:
                self._gcode_jobs.pop(job_id, None)
            if expired:
                self._logger.warning(f"[FACTOR] Cleared expired jobs: {expired}")
        except Exception as e:
            self._logger.error(f"[FACTOR] Job cleanup error: {e}")

    def _check_mqtt_connection_status(self):
        if not self.mqtt_client:
            return False
        try:
            if self.mqtt_client.is_connected():
                return True
            self._logger.debug("MQTT connection is down")
            return False
        except Exception as e:
            self._logger.error(f"MQTT status check error: {e}")
            return False

    def _publish_status(self, payload, topic_prefix):
        if not self._settings.get(["publish_status"]):
            return
        try:
            instance_id = self._get_required_instance_id(context="status publish")
        except InstanceIdRequiredError:
            return
        topic = f"{topic_prefix}/status/{instance_id}"
        self._publish_message(topic, json.dumps(payload))

    def _publish_progress(self, payload, topic_prefix):
        if not self._settings.get(["publish_progress"]):
            return
        topic = f"{topic_prefix}/progress"
        self._publish_message(topic, json.dumps(payload))

    def _publish_temperature(self, payload, topic_prefix):
        if not self._settings.get(["publish_temperature"]):
            return
        topic = f"{topic_prefix}/temperature"
        self._publish_message(topic, json.dumps(payload))

    def _publish_gcode(self, payload, topic_prefix):
        if not self._settings.get(["publish_gcode"]):
            return
        topic = f"{topic_prefix}/gcode"
        self._publish_message(topic, json.dumps(payload))

    def _publish_message(self, topic, message):
        if not self.is_connected or not self.mqtt_client:
            return
        try:
            import paho.mqtt.client as mqtt
            qos = self._settings.get(["qos_level"])
            retain = self._settings.get(["retain_messages"])
            result = self.mqtt_client.publish(topic, message, qos=qos, retain=retain)

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self._logger.debug(f"Published: {topic}")
            else:
                self._logger.error(f"Publish failed: {topic}, rc={result.rc}")
        except Exception as e:
            self._logger.error(f"Publish error: {e}")

    @staticmethod
    def _safe_int(value, default=0):
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _safe_bool(value, default=False):
        try:
            return bool(value)
        except Exception:
            return default

    def _pick_encoder(self, encoder_opt):
        enc = (encoder_opt or "").lower()
        if enc in ("v4l2m2m", "h264_v4l2m2m", "v4l2"):
            return ["-c:v", "h264_v4l2m2m"]
        if enc in ("omx", "h264_omx"):
            return ["-c:v", "h264_omx"]
        return ["-c:v", "libx264", "-tune", "zerolatency"]

    def _validate_url(self, url):
        """Validate URL to prevent command injection."""
        if not url:
            return False
        if not re.match(r'^(http://|https://|rtsp://|/dev/video\d+)', url):
            return False
        dangerous_chars = [';', '&', '|', '`', '$', '(', ')', '<', '>', '\n', '\r']
        for char in dangerous_chars:
            if char in url:
                return False
        if len(url) > 2048:
            return False
        return True

    def _build_webrtc_mediatx_cmd(self, opts):
        input_url = (opts.get("input") or opts.get("input_url") or
                     self._settings.get(["camera", "stream_url"]) or "").strip()
        if not input_url:
            raise ValueError("missing input url")

        if not self._validate_url(input_url):
            raise ValueError("invalid or dangerous input URL")

        name = (opts.get("name") or "cam").strip()
        if not re.match(r'^[a-zA-Z0-9_-]+$', name) or len(name) > 50:
            raise ValueError("invalid stream name")

        rtsp_base = (opts.get("rtsp_base") or
                     os.environ.get("MEDIAMTX_RTSP_BASE") or
                     "rtsp://factor.io.kr:8554").rstrip("/")
        webrtc_base = (opts.get("webrtc_base") or
                       os.environ.get("MEDIAMTX_WEBRTC_BASE") or
                       "https://factor.io.kr/webrtc").rstrip("/")

        if not self._validate_url(rtsp_base):
            raise ValueError("invalid rtsp_base URL")
        if not self._validate_url(webrtc_base):
            raise ValueError("invalid webrtc_base URL")

        rtsp_url = f"{rtsp_base}/{name}"

        fps = max(0, min(60, self._safe_int(opts.get("fps", 0))))
        width = max(0, min(3840, self._safe_int(opts.get("width", 0))))
        height = max(0, min(2160, self._safe_int(opts.get("height", 0))))
        bitrate_k = max(100, min(20000, self._safe_int(opts.get("bitrateKbps", 2000))))
        encoder = opts.get("encoder") or "v4l2m2m"
        allowed_encoders = ["v4l2m2m", "h264_v4l2m2m", "v4l2", "omx", "h264_omx", "libx264"]
        if encoder not in allowed_encoders:
            encoder = "v4l2m2m"
        low_lat = self._safe_bool(opts.get("lowLatency", True))
        force_mj = self._safe_bool(opts.get("forceMjpeg", False))

        cmd = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "info",
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "2",
            "-fflags", "nobuffer",
            "-use_wallclock_as_timestamps", "1",
            "-analyzeduration", "0", "-probesize", "32k",
        ]
        if low_lat:
            cmd += ["-flags", "low_delay"]

        if input_url.startswith("/dev/video"):
            cmd += ["-f", "v4l2"]
        elif input_url.startswith("rtsp://"):
            cmd += ["-rtsp_transport", "tcp"]

        if force_mj and input_url.startswith(("http://", "https://")):
            cmd += ["-f", "mjpeg"]

        cmd += ["-i", input_url]

        vf_chain = []
        if fps > 0:
            vf_chain.append(f"fps={fps}")
        if width > 0 and height > 0:
            vf_chain.append(f"scale={width}:{height}")
        vf_chain.append("format=yuv420p")
        cmd += ["-vf", ",".join(vf_chain)]

        cmd += self._pick_encoder(encoder)

        gop = (fps * 2) if fps > 0 else 50

        cmd += [
            "-preset", "veryfast",
            "-profile:v", "baseline",
            "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
            "-b:v", f"{bitrate_k}k",
            "-maxrate", f"{int(bitrate_k * 11 / 10)}k",
            "-bufsize", f"{bitrate_k}k",
            "-an",
        ]

        cmd += ["-f", "rtsp", "-rtsp_transport", "tcp", rtsp_url]

        extra = {
            "play_url_webrtc": f"{webrtc_base}/{name}/",
            "publish_url_rtsp": rtsp_url,
            "name": name,
        }
        return cmd, extra

    def _build_camera_cmd(self, opts):
        return self._build_webrtc_mediatx_cmd(opts)

    def _camera_status(self):
        running = bool(self._camera_proc and (self._camera_proc.poll() is None))
        pid = self._camera_proc.pid if running and self._camera_proc else None
        out = {
            "running": running,
            "pid": pid,
            "started_at": self._camera_started_at,
            "last_error": self._camera_last_error
        }
        if getattr(self, "_webrtc_last", None):
            out["webrtc"] = self._webrtc_last
        return out

    def _start_ffmpeg_subprocess(self, opts):
        if self._camera_proc and self._camera_proc.poll() is None:
            built = self._build_camera_cmd(opts)
            if isinstance(built, tuple):
                _, extra = built
                self._webrtc_last = extra or {}
            return {"success": True, "already_running": True, **self._camera_status()}

        try:
            built = self._build_camera_cmd(opts)
            if isinstance(built, tuple):
                cmd, extra = built
            else:
                cmd, extra = built, {}

            import sys
            popen_kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.STDOUT
            }

            if sys.platform != "win32" and hasattr(os, "setsid"):
                popen_kwargs["preexec_fn"] = os.setsid
            elif sys.platform == "win32":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

            self._camera_proc = subprocess.Popen(cmd, **popen_kwargs)
            self._webrtc_last = extra or {}
            self._camera_started_at = time.time()
            self._camera_last_error = None
            self._logger.info("[CAMERA] started pid=%s cmd=%s",
                              self._camera_proc.pid, " ".join(shlex.quote(c) for c in cmd))
            return {"success": True, **self._camera_status()}
        except Exception as e:
            self._camera_last_error = str(e)
            self._logger.exception("[CAMERA] start failed")
            return {"success": False, "error": str(e), **self._camera_status()}

    def _stop_ffmpeg_subprocess(self, timeout_sec=5.0):
        try:
            if not (self._camera_proc and self._camera_proc.poll() is None):
                return {"success": True, "already_stopped": True, **self._camera_status()}

            import sys

            if sys.platform == "win32":
                try:
                    self._camera_proc.send_signal(signal.CTRL_BREAK_EVENT)
                except AttributeError:
                    self._camera_proc.terminate()

                t0 = time.time()
                while (time.time() - t0) < timeout_sec:
                    if self._camera_proc.poll() is not None:
                        break
                    time.sleep(0.1)
                if self._camera_proc.poll() is None:
                    self._camera_proc.kill()
            else:
                try:
                    pgid = os.getpgid(self._camera_proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
                except (OSError, AttributeError):
                    self._camera_proc.terminate()

                t0 = time.time()
                while (time.time() - t0) < timeout_sec:
                    if self._camera_proc.poll() is not None:
                        break
                    time.sleep(0.1)
                if self._camera_proc.poll() is None:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except (OSError, AttributeError):
                        self._camera_proc.kill()

            self._logger.info("[CAMERA] stopped")
            return {"success": True, **self._camera_status()}
        except Exception as e:
            self._camera_last_error = str(e)
            self._logger.exception("[CAMERA] stop failed")
            return {"success": False, "error": str(e), **self._camera_status()}

    def _systemctl(self, unit, action):
        try:
            r = subprocess.run(["systemctl", action, unit],
                               capture_output=True, text=True, timeout=8)
            ok = (r.returncode == 0)
            if not ok:
                self._logger.warning("[CAMERA] systemctl %s %s rc=%s",
                                     action, unit, r.returncode)
            return {"success": ok, "stdout": r.stdout, "stderr": r.stderr, "rc": r.returncode}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _camera_start(self, opts):
        unit = (opts.get("systemd_unit") or "").strip()
        if unit:
            return self._systemctl(unit, "start")
        return self._start_ffmpeg_subprocess(opts)

    def _camera_stop(self, opts):
        unit = (opts.get("systemd_unit") or "").strip()
        if unit:
            return self._systemctl(unit, "stop")
        return self._stop_ffmpeg_subprocess()

    def _publish_camera_state(self):
        try:
            instance_id = self._get_required_instance_id(context="camera state publish")
            topic = f"camera/{instance_id}/state"
            payload = json.dumps(self._camera_status())
            self._publish_message(topic, payload)
        except InstanceIdRequiredError:
            pass
        except Exception as e:
            self._logger.debug(f"Camera state publish error: {e}")

    def _get_sd_tree(self, force_refresh=False, timeout=0.0):
        try:
            local_files = self._file_manager.list_files(FileDestinations.LOCAL)
            files_list = list(local_files.get("local", {}).values())
            sd_files = self._printer.get_sd_files()

            return {
                "local": files_list,
                "sdcard": sd_files
            }
        except Exception as e:
            self._logger.debug(f"SD tree retrieval failed: {e}")
            return {}

    def _get_printer_summary(self):
        try:
            conn = self._printer.get_current_connection() or {}
            state = None
            port = None
            baud = None
            profile = None
            if isinstance(conn, (list, tuple)) and len(conn) >= 4:
                state, port, baud, profile = conn[0], conn[1], conn[2], conn[3]
            elif isinstance(conn, dict):
                state = conn.get("state")
                port = conn.get("port")
                baud = conn.get("baudrate")
                profile = conn.get("profile") or {}
            else:
                profile = {}

            prof_id = None
            prof_name = None
            prof_model = None
            heated_bed = None
            volume = {}
            if isinstance(profile, dict):
                prof_id = profile.get("id")
                prof_name = profile.get("name")
                prof_model = profile.get("model")
                heated_bed = profile.get("heatedBed")
                volume = profile.get("volume") or {}

            return {
                "connection": {
                    "state": state,
                    "port": port,
                    "baudrate": baud,
                    "profile": {
                        "id": prof_id,
                        "name": prof_name,
                        "model": prof_model,
                        "heatedBed": heated_bed,
                        "volume": volume,
                    },
                },
                "size": {
                    "width": volume.get("width"),
                    "depth": volume.get("depth"),
                    "height": volume.get("height"),
                },
            }
        except Exception as e:
            self._logger.debug(f"Printer summary failed: {e}")
            return {}

    def _ensure_instance_id(self, force_new=False):
        saved_id = self._settings.get(["instance_id"])
        if saved_id and not force_new:
            return saved_id

        if force_new or not self._temp_instance_id:
            self._temp_instance_id = str(uuid.uuid4())
            self._logger.info(f"Generated temp instance ID: {self._temp_instance_id}")

        return self._temp_instance_id

    def _get_required_instance_id(self, context="operation"):
        """Get instance_id or raise InstanceIdRequiredError."""
        instance_id = self._temp_instance_id or self._settings.get(["instance_id"])
        if not instance_id:
            error_msg = f"Instance ID required for {context} but not available"
            self._logger.error(f"[FACTOR] {error_msg}")
            raise InstanceIdRequiredError(error_msg)
        return instance_id

    @octoprint.plugin.BlueprintPlugin.route("/setup-url", methods=["GET"])
    def get_setup_url(self):
        try:
            instance_id = self._ensure_instance_id(force_new=False)

            if self.is_connected and self.mqtt_client:
                self._subscribe_mqtt_topics()

            setup_url = f"https://factor.io.kr/setup/{instance_id}"

            return make_response(jsonify({
                "success": True,
                "instance_id": instance_id,
                "setup_url": setup_url
            }), 200)
        except Exception as e:
            self._logger.error(f"Setup URL error: {e}")
            return make_response(jsonify({"error": str(e)}), 500)

    @octoprint.plugin.BlueprintPlugin.route("/start-setup", methods=["POST"])
    def start_setup(self):
        try:
            self._subscribe_mqtt_topics()

            return make_response(jsonify({
                "success": True,
                "message": "Subscribed to registration topic"
            }), 200)
        except Exception as e:
            self._logger.error(f"Start setup error: {e}")
            return make_response(jsonify({"error": str(e)}), 500)

    @octoprint.plugin.BlueprintPlugin.route("/connection-status", methods=["GET"])
    def get_connection_status(self):
        try:
            instance_id = self._temp_instance_id or self._settings.get(["instance_id"])
            registered = self._settings.get_boolean(["registered"])
            subscribed_id = getattr(self, '_current_subscribed_id', None)

            status = {
                "mqtt_connected": self.is_connected,
                "instance_id": instance_id,
                "instance_id_available": bool(instance_id),
                "registered": registered,
                "subscribed": bool(subscribed_id),
                "subscribed_id": subscribed_id,
                "can_receive_commands": bool(self.is_connected and subscribed_id),
            }

            if not self.is_connected:
                status["status"] = "disconnected"
                status["message"] = "MQTT broker not connected"
            elif not instance_id:
                status["status"] = "no_instance_id"
                status["message"] = "No instance ID"
            elif not subscribed_id:
                status["status"] = "not_subscribed"
                status["message"] = "Connected but not subscribed"
            elif not registered:
                status["status"] = "pending_registration"
                status["message"] = "Waiting for registration"
            else:
                status["status"] = "ready"
                status["message"] = "Connected and ready"

            return make_response(jsonify(status), 200)
        except Exception as e:
            self._logger.error(f"Connection status error: {e}")
            return make_response(jsonify({"error": str(e)}), 500)

    @octoprint.plugin.BlueprintPlugin.route("/retry-connection", methods=["POST"])
    def retry_connection(self):
        try:
            result = {"actions": []}

            if not self.is_connected:
                self._disconnect_mqtt()
                self._connect_mqtt()
                result["actions"].append("mqtt_reconnect_initiated")

            instance_id = self._temp_instance_id or self._settings.get(["instance_id"])
            if instance_id and self.is_connected:
                self._subscribe_mqtt_topics()
                result["actions"].append("subscription_attempted")

            result["success"] = True
            return make_response(jsonify(result), 200)
        except Exception as e:
            self._logger.error(f"Retry connection error: {e}")
            return make_response(jsonify({"success": False, "error": str(e)}), 500)

    def get_update_information(self):
        return {
            "octoprint_factor": {
                "displayName": "FACTOR Plugin",
                "displayVersion": __plugin_version__,
                "type": "github_release",
                "user": "kangbyounggwan",
                "repo": "octoprint-factor-plugin",
                "current": __plugin_version__,
                "pip": "https://github.com/kangbyounggwan/octoprint-factor-plugin/archive/{target_version}.zip",
            }
        }

    def _make_snapshot(self):
        data = self._printer.get_current_data() or {}
        temps = self._printer.get_current_temperatures() or {}
        conn = self._printer.get_current_connection() or {}

        progress = data.get("progress") or {}
        job = data.get("job") or {}
        fileinfo = job.get("file") or {}
        filament = job.get("filament") or {}
        flags = (data.get("state") or {}).get("flags", {})

        size = fileinfo.get("size") or 0
        filepos = progress.get("filepos") or 0
        file_pct = round((filepos / size * 100.0), 2) if size else None

        return {
            "ts": time.time(),
            "state": {
                "text": (data.get("state") or {}).get("text"),
                "flags": {
                    "operational": bool(flags.get("operational")),
                    "printing": bool(flags.get("printing")),
                    "paused": bool(flags.get("paused")),
                    "error": bool(flags.get("error")),
                    "ready": bool(flags.get("ready")),
                }
            },
            "progress": {
                "completion": progress.get("completion"),
                "filepos": filepos,
                "file_size": size,
                "file_pct": file_pct,
                "print_time": progress.get("printTime"),
                "time_left": progress.get("printTimeLeft"),
                "time_left_origin": progress.get("printTimeLeftOrigin"),
            },
            "job": {
                "file": {
                    "name": fileinfo.get("name"),
                    "origin": fileinfo.get("origin"),
                    "date": fileinfo.get("date"),
                },
                "estimated_time": job.get("estimatedPrintTime"),
                "last_time": job.get("lastPrintTime"),
                "filament": filament,
            },
            "axes": {
                "current": self._get_job_coordinates(),
                "target": {
                    "x": self._target_position.get("x"),
                    "y": self._target_position.get("y"),
                    "z": self._target_position.get("z"),
                    "e": self._target_position.get("e")
                },
                "machine": {
                    "x": self._current_position.get("x"),
                    "y": self._current_position.get("y"),
                    "z": self._current_position.get("z"),
                    "e": self._current_position.get("e")
                }
            },
            "path": self._get_path_summary(),
            "temperatures": temps,
            "connection": conn,
            "sd": self._get_sd_tree(),
            "overrides": {
                "feedrate": self._feed_rate,
                "flowrate": self._flow_rate,
            },
        }

    def _start_snapshot_timer(self):
        with self._snapshot_timer_lock:
            if self._snapshot_timer:
                return
            interval = float(self._settings.get(["periodic_interval"]) or 1.0)
            self._snapshot_timer = RepeatedTimer(interval, self._snapshot_tick, run_first=True)
            self._snapshot_timer.start()
            self._logger.info(f"[FACTOR] Snapshot timer started: {interval}s")

    def _stop_snapshot_timer(self):
        with self._snapshot_timer_lock:
            if self._snapshot_timer:
                self._snapshot_timer.cancel()
                self._snapshot_timer = None
                self._logger.info("[FACTOR] Snapshot timer stopped")

    def _parse_m114_response(self, line):
        try:
            x_match = re.search(r'X:([-\d.]+)', line)
            y_match = re.search(r'Y:([-\d.]+)', line)
            z_match = re.search(r'Z:([-\d.]+)', line)
            e_match = re.search(r'E:([-\d.]+)', line)

            with self._position_lock:
                if x_match:
                    self._current_position["x"] = float(x_match.group(1))
                if y_match:
                    self._current_position["y"] = float(y_match.group(1))
                if z_match:
                    self._current_position["z"] = float(z_match.group(1))
                if e_match:
                    self._current_position["e"] = float(e_match.group(1))
        except Exception as e:
            self._logger.debug(f"M114 parse error: {e}")

    def _capture_position_offset(self):
        try:
            with self._position_lock:
                self._position_offset["x"] = self._current_position.get("x")
                self._position_offset["y"] = self._current_position.get("y")
                self._position_offset["z"] = self._current_position.get("z")
                self._position_offset["e"] = self._current_position.get("e")
                self._logger.info(f"[POSITION] Offset captured: {self._position_offset}")
        except Exception as e:
            self._logger.error(f"Position offset capture error: {e}")

    def _reset_position_offset(self):
        with self._position_lock:
            self._position_offset = {"x": None, "y": None, "z": None, "e": None}
            self._logger.info("[POSITION] Offset reset")

    def _clear_path_history(self):
        with self._position_lock:
            self._path_history = []
            self._last_recorded_position = {"x": 0, "y": 0, "z": 0, "e": 0}
            self._logger.info("[PATH] History cleared")

    def _add_path_segment(self, prev_x, prev_y, x, y, z, extrude=False, retract=0, tool=0):
        with self._position_lock:
            if prev_x == x and prev_y == y:
                return

            segment = {
                "prevX": prev_x,
                "prevY": prev_y,
                "x": x,
                "y": y,
                "z": z,
                "extrude": extrude,
                "retract": retract,
                "tool": tool,
                "move": not extrude and retract == 0
            }

            self._path_history.append(segment)

            if len(self._path_history) > self._path_history_max:
                remove_count = self._path_history_max // 10
                self._path_history = self._path_history[remove_count:]

    def _get_path_history(self, limit=None, offset=0):
        with self._position_lock:
            if limit is None:
                return self._path_history[offset:]
            return self._path_history[offset:offset + limit]

    def _get_path_summary(self):
        with self._position_lock:
            total_segments = len(self._path_history)
            extrude_count = sum(1 for s in self._path_history if s.get("extrude"))
            move_count = sum(1 for s in self._path_history if s.get("move"))
            retract_count = sum(1 for s in self._path_history if s.get("retract") == -1)

            if total_segments > 0:
                min_x = min(min(s["prevX"], s["x"]) for s in self._path_history)
                max_x = max(max(s["prevX"], s["x"]) for s in self._path_history)
                min_y = min(min(s["prevY"], s["y"]) for s in self._path_history)
                max_y = max(max(s["prevY"], s["y"]) for s in self._path_history)
                bounding_box = {"minX": min_x, "maxX": max_x, "minY": min_y, "maxY": max_y}
            else:
                bounding_box = None

            return {
                "total_segments": total_segments,
                "extrude_count": extrude_count,
                "move_count": move_count,
                "retract_count": retract_count,
                "bounding_box": bounding_box
            }

    def _get_job_coordinates(self):
        with self._position_lock:
            result = {"x": None, "y": None, "z": None, "e": None}

            for axis in ["x", "y", "z", "e"]:
                machine = self._current_position.get(axis)
                offset = self._position_offset.get(axis)

                if machine is not None and offset is not None:
                    result[axis] = machine - offset
                elif machine is not None:
                    result[axis] = machine

            return result

    def _request_position_update(self):
        try:
            if self._printer.is_operational():
                self._printer.commands("M114")
        except Exception as e:
            self._logger.debug(f"Position request error: {e}")

    def on_gcode_received(self, comm_instance, line, *args, **kwargs):
        if line:
            line_upper = line.upper().strip()
            # Parse M220 (feed rate) response: "FR:100%" or "echo:FR:100%"
            fr_match = re.search(r'FR[:\s]*(\d+)\s*%?', line_upper)
            if fr_match:
                self._feed_rate = int(fr_match.group(1))
            # Parse M221 (flow rate) response: "Flow: 100%" or "echo:E0 Flow: 100%"
            flow_match = re.search(r'FLOW[:\s]*(\d+)\s*%?', line_upper)
            if flow_match:
                self._flow_rate = int(flow_match.group(1))
            # Parse M114 position response
            if "X:" in line:
                if not (line_upper.startswith("SEND:") or
                        line_upper.startswith("G0 ") or line_upper.startswith("G1 ") or
                        line_upper.startswith("G28") or line_upper.startswith("G29") or
                        "G0 " in line_upper or "G1 " in line_upper):
                    self._parse_m114_response(line)
        return line

    def _parse_gcode_for_target_position(self, gcode, cmd):
        try:
            if gcode == "G90":
                self._is_absolute_positioning = True
                return
            elif gcode == "G91":
                self._is_absolute_positioning = False
                return

            if gcode not in ["G0", "G1"]:
                return

            x_match = re.search(r'X([-\d.]+)', cmd, re.IGNORECASE)
            y_match = re.search(r'Y([-\d.]+)', cmd, re.IGNORECASE)
            z_match = re.search(r'Z([-\d.]+)', cmd, re.IGNORECASE)
            e_match = re.search(r'E([-\d.]+)', cmd, re.IGNORECASE)

            new_x = None
            new_y = None
            new_z = None
            new_e = None
            extrude = False
            retract = 0

            with self._position_lock:
                prev_x = self._last_recorded_position.get("x", 0) or 0
                prev_y = self._last_recorded_position.get("y", 0) or 0
                prev_z = self._last_recorded_position.get("z", 0) or 0
                prev_e = self._last_recorded_position.get("e", 0) or 0

                if self._is_absolute_positioning:
                    if x_match:
                        new_x = float(x_match.group(1))
                        self._target_position["x"] = new_x
                    else:
                        new_x = prev_x

                    if y_match:
                        new_y = float(y_match.group(1))
                        self._target_position["y"] = new_y
                    else:
                        new_y = prev_y

                    if z_match:
                        new_z = float(z_match.group(1))
                        self._target_position["z"] = new_z
                    else:
                        new_z = prev_z

                    if e_match:
                        new_e = float(e_match.group(1))
                        self._target_position["e"] = new_e
                        e_delta = new_e - prev_e
                        if e_delta > 0:
                            extrude = True
                        elif e_delta < 0:
                            retract = -1
                    else:
                        new_e = prev_e
                else:
                    if x_match:
                        delta_x = float(x_match.group(1))
                        new_x = prev_x + delta_x
                        self._target_position["x"] = new_x
                    else:
                        new_x = prev_x

                    if y_match:
                        delta_y = float(y_match.group(1))
                        new_y = prev_y + delta_y
                        self._target_position["y"] = new_y
                    else:
                        new_y = prev_y

                    if z_match:
                        delta_z = float(z_match.group(1))
                        new_z = prev_z + delta_z
                        self._target_position["z"] = new_z
                    else:
                        new_z = prev_z

                    if e_match:
                        delta_e = float(e_match.group(1))
                        new_e = prev_e + delta_e
                        self._target_position["e"] = new_e
                        if delta_e > 0:
                            extrude = True
                        elif delta_e < 0:
                            retract = -1
                    else:
                        new_e = prev_e

                self._last_recorded_position["x"] = new_x
                self._last_recorded_position["y"] = new_y
                self._last_recorded_position["z"] = new_z
                self._last_recorded_position["e"] = new_e

            if x_match or y_match:
                self._add_path_segment(
                    prev_x=prev_x,
                    prev_y=prev_y,
                    x=new_x,
                    y=new_y,
                    z=new_z,
                    extrude=extrude,
                    retract=retract,
                    tool=0
                )

        except Exception as e:
            self._logger.debug(f"G-code parse error: {e}")

    def on_gcode_sent(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        if gcode:
            self._parse_gcode_for_target_position(gcode, cmd)
        return None

    def _snapshot_tick(self):
        if not (self.is_connected and self.mqtt_client):
            return
        self._request_position_update()
        try:
            instance_id = self._get_required_instance_id(context="snapshot publish")
            payload = self._make_snapshot()
            topic = f"{self._settings.get(['topic_prefix']) or 'octoprint'}/status/{instance_id}"
            self._publish_message(topic, json.dumps(payload))
            self._gc_expired_jobs()
        except InstanceIdRequiredError:
            pass
        except Exception as e:
            self._logger.debug(f"Snapshot tick error: {e}")


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = FactorPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config":
            __plugin_implementation__.get_update_information,
        "octoprint.comm.protocol.gcode.received":
            __plugin_implementation__.on_gcode_received,
        "octoprint.comm.protocol.gcode.sent":
            __plugin_implementation__.on_gcode_sent
    }
