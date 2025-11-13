# -*- coding: utf-8 -*-
import json
import subprocess, shlex, os, signal
from flask import request  # Blueprint에서 사용
import octoprint.plugin
from octoprint.filemanager import FileDestinations

from octoprint.util import RepeatedTimer
from flask import jsonify, make_response
import flask
import requests
import re
import uuid
import tempfile
import base64
import io
import time
import hashlib



__plugin_name__ = "FACTOR Plugin"
__plugin_pythoncompat__ = ">=3.8,<4"
__plugin_version__ = "2.0.0"
__plugin_identifier__ = "factor_mqtt"

        
def _as_code(x):
    try:
        v = getattr(x, "value", None)
        if isinstance(v, int):
            return v
        return int(x)
    except Exception:
        s = (str(x) if x is not None else "").strip().lower()
        if s in ("success", "normal disconnection"):
            return 0
        import re
        m = re.search(r"(\d+)", s)
        return int(m.group(1)) if m else -1


class MqttPlugin(octoprint.plugin.SettingsPlugin,
                 octoprint.plugin.AssetPlugin,
                 octoprint.plugin.TemplatePlugin,
                 octoprint.plugin.StartupPlugin,
                 octoprint.plugin.ShutdownPlugin,
                 octoprint.plugin.EventHandlerPlugin,
                 octoprint.plugin.BlueprintPlugin,
                 octoprint.plugin.WizardPlugin):
    
    def __init__(self):
        super().__init__()
        self.mqtt_client = None
        self.is_connected = False
        self._snapshot_timer = None
        self._snapshot_timer_lock = __import__("threading").Lock()
        self._gcode_jobs = {}
        # camera process state
        self._camera_proc = None
        self._camera_started_at = None
        self._camera_last_error = None
        # Temporary instance ID (not saved until registration is complete)
        self._temp_instance_id = None
    
    ##~~ SettingsPlugin mixin
    
    def get_settings_defaults(self):
        return dict(
            broker_host="localhost",
            broker_port=1883,
            broker_username="",
            broker_password="",
            broker_use_tls=False,
            broker_tls_insecure=False,
            broker_tls_ca_cert="",
            topic_prefix="octoprint",   # JS와 일치!
            qos_level=0,
            retain_messages=False,
            publish_status=True,
            publish_progress=True,
            publish_temperature=True,
            publish_gcode=False,
            publish_snapshot=True,
            periodic_interval=1.0,
            auth_api_base="https://factor.io.kr",
            register_api_base="https://factor.io.kr",
            instance_id="",
            registered=False,
            receive_gcode_enabled=True,
            receive_topic_suffix="gcode_in",
            receive_target_default="local_print",
            receive_timeout_sec=300,
            camera=dict(
                stream_url=""
            )

        )
    
    def get_settings_version(self):
        return 1
    
    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self._disconnect_mqtt()
        self._connect_mqtt()
        # 타이머는 연결 성공 시 자동으로 시작됨
    
    ##~~ AssetPlugin mixin

    def get_assets(self):
        return dict(
            js=["js/i18n.js", "js/mqtt.js"],
            css=["css/mqtt.css"]
        )
    
    ##~~ TemplatePlugin mixin
    def on_startup(self, host, port):
        self._connect_mqtt()
        try:
            self._log_api_endpoints(host, port)
        except Exception as e:
            self._logger.warning("엔드포인트 로그 중 오류: %s", e)
    
    def on_after_startup(self):
        """시작 후 초기화 작업"""
        # 더 이상 busy-wait 금지. 필요하면 그냥 타이머를 미리 켜두고
        # tick에서 is_connected를 확인하게 해도 됩니다.
        pass


    # --- 여기부터 유틸 메서드 추가 ---
    def _log_api_endpoints(self, host: str, port: int):
        """
        플러그인 로드 시 접근 가능한 API 엔드포인트를 콘솔(octoprint.log)에 출력
        """
        # reverse proxy 등으로 baseUrl 이 설정된 경우 고려
        base_url = self._settings.global_get(["server", "baseUrl"]) or ""
        base_url = base_url.rstrip("/")

        # 실제로 바인딩된 내부 주소 기준 (OctoPrint 서비스 관점)
        internal_base = f"http://{host}:{port}{base_url}"
        pid = __plugin_identifier__

        status_url = f"{internal_base}/api/plugin/{pid}/status"
        test_url   = f"{internal_base}/api/plugin/{pid}/test"

        self._logger.info("[FACTOR] REST endpoints ready:")
        self._logger.info(" - GET  %s", status_url)
        self._logger.info(" - POST %s", test_url)
        self._logger.info("   (헤더 'X-Api-Key' 필요)")

    def get_template_configs(self):
        return [
            dict(
                type="settings",
                name="FACTOR",
                template="mqtt_settings.jinja2",
                custom_bindings=True
            ),
            dict(
                type="wizard",
                template="mqtt_wizard.jinja2",
                custom_bindings=True
            )
        ]

    ##~~ WizardPlugin mixin

    def is_wizard_required(self):
        # Show wizard if device is not registered yet
        return not self._settings.get_boolean(["registered"])

    def get_wizard_version(self):
        return 1

    def get_wizard_details(self):
        return dict()

    ##~~ ShutdownPlugin mixin
    
    def on_shutdown(self):
        self._disconnect_mqtt()
    
    ##~~ EventHandlerPlugin mixin
    
    def on_event(self, event, payload):
        if not self.is_connected:
            return
        
        topic_prefix = self._settings.get(["topic_prefix"])
        
        if event == "PrinterStateChanged":
            self._publish_status(payload, topic_prefix)
        elif event == "PrintProgress":
            self._publish_progress(payload, topic_prefix)
        elif event == "TemperatureUpdate":
            self._publish_temperature(payload, topic_prefix)
        elif event == "GcodeReceived":
            self._publish_gcode(payload, topic_prefix)
    
    ##~~ Private methods
    
    def _connect_mqtt(self):
        try:
            import paho.mqtt.client as mqtt
            import ssl

            self.mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

            # 인증 정보 설정
            username = self._settings.get(["broker_username"])
            password = self._settings.get(["broker_password"])
            if username:
                self.mqtt_client.username_pw_set(username, password)

            # TLS/SSL 설정
            use_tls = self._settings.get(["broker_use_tls"])
            if use_tls:
                tls_insecure = self._settings.get(["broker_tls_insecure"])
                ca_cert = self._settings.get(["broker_tls_ca_cert"])

                tls_context = ssl.create_default_context()
                if tls_insecure:
                    tls_context.check_hostname = False
                    tls_context.verify_mode = ssl.CERT_NONE
                    self._logger.warning("MQTT TLS 인증서 검증이 비활성화되었습니다. 프로덕션 환경에서는 권장하지 않습니다.")
                elif ca_cert:
                    tls_context.load_verify_locations(cafile=ca_cert)

                self.mqtt_client.tls_set_context(tls_context)
                self._logger.info("MQTT TLS/SSL이 활성화되었습니다.")

            # 콜백 함수 설정
            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self.mqtt_client.on_publish = self._on_mqtt_publish
            self.mqtt_client.on_log = self._on_mqtt_log
            self.mqtt_client.on_message = self._on_mqtt_message

            # 재연결 설정
            self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=120)

            # 비동기 연결
            host = self._settings.get(["broker_host"])
            port = int(self._settings.get(["broker_port"]))
            protocol = "mqtts" if use_tls else "mqtt"
            # 사용자명은 로그에 표시하지 않음 (보안)
            self._logger.info(f"MQTT 비동기 연결 시도: {protocol}://{host}:{port}")

            # connect_async로 비동기 연결 시작
            self.mqtt_client.connect_async(host, port, 60)
            self.mqtt_client.loop_start()

        except Exception as e:
            self._logger.error(f"MQTT 연결 실패: {e}")
    
    def _disconnect_mqtt(self):
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            self.mqtt_client = None
            self.is_connected = False
            self._logger.info("MQTT 클라이언트 연결이 종료되었습니다.")
    
    def _subscribe_mqtt_topics(self):
        """Subscribe to MQTT topics using current instance_id"""
        if not self.is_connected or not self.mqtt_client:
            self._logger.warning("Cannot subscribe: MQTT not connected")
            return

        try:
            qos = int(self._settings.get(["qos_level"]) or 1)
            # Use temporary ID first (for setup), then saved ID (for registered devices)
            inst = self._temp_instance_id or self._settings.get(["instance_id"]) or "unknown"

            # Unsubscribe from old topics if they exist
            if hasattr(self, '_current_subscribed_id') and self._current_subscribed_id != inst:
                old_inst = self._current_subscribed_id
                old_topics = [
                    f"control/{old_inst}",
                    f"octoprint/gcode_in/{old_inst}",
                    f"camera/{old_inst}/cmd",
                    f"device/{old_inst}/registration"
                ]
                for topic in old_topics:
                    self.mqtt_client.unsubscribe(topic)
                self._logger.info(f"[FACTOR] Unsubscribed from old topics with ID: {old_inst}")

            # Subscribe to new topics
            control_topic = f"control/{inst}"
            gcode_topic = f"octoprint/gcode_in/{inst}"
            camera_cmd = f"camera/{inst}/cmd"
            registration_topic = f"device/{inst}/registration"

            self.mqtt_client.subscribe(control_topic, qos=qos)
            self.mqtt_client.subscribe(gcode_topic, qos=qos)
            self.mqtt_client.subscribe(camera_cmd, qos=qos)
            self.mqtt_client.subscribe(registration_topic, qos=qos)

            self._current_subscribed_id = inst
            self._logger.info(f"[FACTOR] Subscribed to topics with ID: {inst}")
        except Exception as e:
            self._logger.warning(f"[FACTOR] Subscribe failed: {e}")

    def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None, *args, **kwargs):
        rc_i = _as_code(rc)
        self.is_connected = (rc_i == 0)
        if self.is_connected:
            self._logger.info("MQTT 브로커 연결 OK")
            self._start_snapshot_timer()     # ✅ 여기서 시작
            self._subscribe_mqtt_topics()
        else:
            self._logger.error(f"MQTT 연결 실패 rc={rc}")

    def _on_mqtt_disconnect(self, client, userdata, rc, properties=None, *args, **kwargs):
        rc_i = _as_code(rc)
        self.is_connected = False
        self._logger.warning(f"MQTT 연결 끊김 rc={rc}")
        # 타이머는 유지해도 되고 멈춰도 됨. 유지하면 재연결 후 자동 퍼블리시됨.
        # 멈추고 싶다면 아래 주석 해제:
        # self._stop_snapshot_timer()
    
    def _on_mqtt_publish(self, client, userdata, mid, *args, **kwargs):
        # paho 2.0: (mid, properties)
        # paho 2.1+: (mid, reasonCode, properties)
        reasonCode = None
        properties = None
        if len(args) == 1:
            properties = args[0]
        elif len(args) >= 2:
            reasonCode, properties = args[0], args[1]

        if reasonCode is not None:
            try:
                rc_i = _as_code(reasonCode)  # 이미 위에 정의됨
            except Exception:
                rc_i = None
            if rc_i is not None:
                self._logger.debug(f"MQTT publish mid={mid} rc={rc_i}")
            else:
                self._logger.debug(f"MQTT publish mid={mid} rc={reasonCode}")
        else:
            self._logger.debug(f"MQTT publish mid={mid}")
        
    def _on_mqtt_log(self, client, userdata, level, buf):
        """MQTT 로그 콜백 - 연결 상태 디버깅용"""
        if level == 1:  # DEBUG level
            self._logger.debug(f"MQTT: {buf}")
        elif level == 2:  # INFO level
            self._logger.info(f"MQTT: {buf}")
        elif level == 4:  # WARNING level
            self._logger.warning(f"MQTT: {buf}")
        elif level == 8:  # ERROR level
            self._logger.error(f"MQTT: {buf}")
    
    def _on_mqtt_message(self, client, userdata, msg):
        try:
            topic = msg.topic or ""
            # Use temporary ID first during setup, then saved ID for registered devices
            inst = self._temp_instance_id or self._settings.get(["instance_id"]) or "unknown"

            # 1) Control: control/<instance_id>
            if topic == f"control/{inst}":
                payload = msg.payload.decode("utf-8", errors="ignore") if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload or "")
                try:
                    data = json.loads(payload or "{}")
                except Exception:
                    data = {}
                self._handle_control_message(data)
                return

            # 2) G-code in: octoprint/gcode_in/<instance_id>
            if topic == f"octoprint/gcode_in/{inst}":
                if not bool(self._settings.get(["receive_gcode_enabled"])):
                    return
                payload = msg.payload.decode("utf-8", errors="ignore") if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload or "")
                data = json.loads(payload or "{}")
                self._handle_gcode_message(data)
                return

            # 3) Camera control: camera/<instance_id>/cmd
            if topic == f"camera/{inst}/cmd":
                payload = msg.payload.decode("utf-8", errors="ignore") if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload or "")
                try:
                    data = json.loads(payload or "{}")
                except Exception:
                    data = {}
                # camera 명령은 control 핸들러로 위임 (type=camera)
                if isinstance(data, dict):
                    data = {"type": "camera", **data}
                else:
                    data = {"type": "camera"}
                self._handle_control_message(data)
                return

            # 4) Registration confirmation: device/<instance_id>/registration
            registration_topic = f"device/{inst}/registration"
            if self._temp_instance_id:
                registration_topic_temp = f"device/{self._temp_instance_id}/registration"
                if topic == registration_topic or topic == registration_topic_temp:
                    payload = msg.payload.decode("utf-8", errors="ignore") if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload or "")
                    try:
                        data = json.loads(payload or "{}")
                        status = data.get("status")

                        if status == "registered":
                            # Save registration permanently
                            instance_id = self._temp_instance_id or inst
                            self._settings.set(["instance_id"], instance_id)
                            self._settings.set(["registered"], True)
                            self._settings.save()

                            self._logger.info(f"✅ Device registration confirmed via MQTT: {instance_id}")

                            # Send confirmation back to server via MQTT
                            confirmation_payload = {
                                "status": "confirmed",
                                "instance_id": instance_id,
                                "confirmed_at": data.get("registered_at")
                            }
                            confirmation_topic = f"device/{instance_id}/registration/ack"
                            try:
                                self.mqtt_client.publish(
                                    confirmation_topic,
                                    json.dumps(confirmation_payload),
                                    qos=1
                                )
                                self._logger.info(f"[FACTOR] Sent registration confirmation to server: {confirmation_topic}")
                            except Exception as e:
                                self._logger.error(f"Failed to send registration confirmation: {e}")

                            # Clear temporary instance ID
                            self._temp_instance_id = None

                            # Unsubscribe from registration topic
                            self.mqtt_client.unsubscribe(topic)

                            # Send plugin message to update UI
                            self._plugin_manager.send_plugin_message(
                                self._identifier,
                                dict(
                                    type="registration_confirmed",
                                    device_name=data.get("device_name"),
                                    registered_at=data.get("registered_at")
                                )
                            )

                        elif status == "timeout" or status == "failed":
                            # Handle failure/timeout
                            error_msg = data.get("error", f"Registration {status}")
                            error_code = data.get("error_code")
                            self._logger.warning(f"❌ Device registration {status}: {error_msg}" + (f" (code: {error_code})" if error_code else ""))

                            # Unsubscribe from registration topic
                            self.mqtt_client.unsubscribe(topic)

                            # Clear temporary instance ID - ready for new registration
                            self._temp_instance_id = None

                            # Send failure notification to UI
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
                        self._logger.error(f"Failed to process registration message: {e}")
                    return

            # 기타 토픽은 무시
            return
        except Exception as e:
            self._logger.exception(f"[FACTOR] on_message 처리 오류: {e}")

    def _handle_gcode_message(self, data: dict):
        # 위임: 모듈로 분리된 구현 사용
        try:
            from .mqtt_gcode import handle_gcode_message as _impl
            _impl(self, data)
        except Exception as e:
            self._logger.exception(f"GCODE 핸들러 오류: {e}")

    def _handle_control_message(self, data: dict):
        t = (data.get("type") or "").lower()
        try:
            from .control import pause_print as _pause, resume_print as _resume, cancel_print as _cancel, home_axes as _home, move_axes as _move, set_temperature as _set_temp
        except Exception:
            _pause = _resume = _cancel = _home = _move = _set_temp = None
        # ---- camera control via MQTT ----
        if t == "camera":
            action = (data.get("action") or "").lower()
            opts = data.get("options") or {}
            if action == "start":
                res = self._camera_start(opts)
                self._publish_camera_state()
                self._logger.info(f"[CONTROL] camera start -> {res}")
                return
            if action == "stop":
                res = self._camera_stop(opts)
                self._publish_camera_state()
                self._logger.info(f"[CONTROL] camera stop -> {res}")
                return
            if action == "restart":
                self._camera_stop(opts)
                time.sleep(0.4)
                res = self._camera_start(opts)
                self._publish_camera_state()
                self._logger.info(f"[CONTROL] camera restart -> {res}")
                return
            if action == "state":
                self._publish_camera_state()
                return
        if t == "pause":
            res = _pause(self) if _pause else {"error": "control module unavailable"}
            self._logger.info(f"[CONTROL] pause -> {res}")
            return
        if t == "resume":
            res = _resume(self) if _resume else {"error": "control module unavailable"}
            self._logger.info(f"[CONTROL] resume -> {res}")
            return
        if t == "cancel":
            res = _cancel(self) if _cancel else {"error": "control module unavailable"}
            self._logger.info(f"[CONTROL] cancel -> {res}")
            return
        if t == "home":
            axes_s = (data.get("axes") or "XYZ")
            axes_s = axes_s if isinstance(axes_s, str) else "".join(axes_s)
            axes = []
            s = (axes_s or "").lower()
            if "x" in s: axes.append("x")
            if "y" in s: axes.append("y")
            if "z" in s: axes.append("z")
            if not axes:
                axes = ["x", "y", "z"]
            res = _home(self, axes) if _home else {"error": "control module unavailable"}
            self._logger.info(f"[CONTROL] home {axes} -> {res}")
            return
        if t == "move":
            mode = (data.get("mode") or "relative").lower()
            x = data.get("x"); y = data.get("y"); z = data.get("z"); e = data.get("e")
            feedrate = data.get("feedrate") or 1000
            res = _move(self, mode, x, y, z, e, feedrate) if _move else {"error": "control module unavailable"}
            self._logger.info(f"[CONTROL] move mode={mode} x={x} y={y} z={z} e={e} F={feedrate} -> {res}")
            return
        if t == "set_temperature":
            tool = int(data.get("tool", 0))
            temperature = float(data.get("temperature", 0))
            wait = bool(data.get("wait", False))
            res = _set_temp(self, tool, temperature, wait) if _set_temp else {"error": "control module unavailable"}
            self._logger.info(f"[CONTROL] set_temperature tool={tool} temp={temperature} wait={wait} -> {res}")
            return
        self._logger.warning(f"[CONTROL] 알 수 없는 type={t}")

    # finalize 함수는 모듈 내로 이동

    def _gc_expired_jobs(self, now: float = None):
        try:
            if now is None:
                now = time.time()
            timeout = int(self._settings.get(["receive_timeout_sec"]) or 300)
            expired = []
            for job_id, st in self._gcode_jobs.items():
                if now - (st.get("last_ts") or st.get("created_ts") or now) > timeout:
                    expired.append(job_id)
            for job_id in expired:
                self._gcode_jobs.pop(job_id, None)
            if expired:
                self._logger.warning(f"[FACTOR] 만료된 job 정리: {expired}")
        except Exception as e:
            self._logger.error(f"[FACTOR] job 정리 중 오류: {e}")
    
    def _check_mqtt_connection_status(self):
        """MQTT 연결 상태를 확인합니다."""
        if not self.mqtt_client:
            return False
        
        try:
            # 연결 상태 확인
            if self.mqtt_client.is_connected():
                return True
            else:
                # 연결되지 않은 경우 로그만 출력 (재연결은 자동으로 처리됨)
                self._logger.debug("MQTT 연결이 끊어져 있습니다.")
                return False
        except Exception as e:
            self._logger.error(f"MQTT 연결 상태 확인 중 오류: {e}")
            return False
    
    def _publish_status(self, payload, topic_prefix):
        if not self._settings.get(["publish_status"]):
            return
        
        import json
        inst = self._settings.get(["instance_id"]) or "unknown"
        topic = f"{topic_prefix}/status/{inst}"
        message = json.dumps(payload)
        self._publish_message(topic, message)
    
    def _publish_progress(self, payload, topic_prefix):
        if not self._settings.get(["publish_progress"]):
            return
        
        import json
        topic = f"{topic_prefix}/progress"
        message = json.dumps(payload)
        self._publish_message(topic, message)
    
    def _publish_temperature(self, payload, topic_prefix):
        if not self._settings.get(["publish_temperature"]):
            return
        
        import json
        topic = f"{topic_prefix}/temperature"
        message = json.dumps(payload)
        self._publish_message(topic, message)
    
    def _publish_gcode(self, payload, topic_prefix):
        if not self._settings.get(["publish_gcode"]):
            return
        
        import json
        topic = f"{topic_prefix}/gcode"
        message = json.dumps(payload)
        self._publish_message(topic, message)
    
    def _publish_message(self, topic, message):
        if not self.is_connected or not self.mqtt_client:
            return
        
        try:
            import paho.mqtt.client as mqtt
            qos = self._settings.get(["qos_level"])
            retain = self._settings.get(["retain_messages"])
            result = self.mqtt_client.publish(topic, message, qos=qos, retain=retain)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self._logger.debug(f"메시지 발행 성공: {topic}")
            else:
                self._logger.error(f"메시지 발행 실패: {topic}, 오류 코드: {result.rc}")
                
        except Exception as e:
            self._logger.error(f"메시지 발행 중 오류 발생: {e}")
    
    # ---- Camera helpers ----
    # WebRTC(MediaMTX) 전용으로 카메라 파이프라인을 구성합니다.
    @staticmethod
    def _safe_int(x, default=0):
        try:
            return int(x)
        except Exception:
            return default

    @staticmethod
    def _safe_bool(x, default=False):
        try:
            return bool(x)
        except Exception:
            return default


    def _pick_encoder(self, encoder_opt: str) -> list:
        enc = (encoder_opt or "").lower()
        # Raspberry Pi (Bullseye 이후): v4l2m2m
        if enc in ("v4l2m2m", "h264_v4l2m2m", "v4l2"):
            return ["-c:v", "h264_v4l2m2m"]
        # 일부 구형/커스텀: omx
        if enc in ("omx", "h264_omx"):
            return ["-c:v", "h264_omx"]
        # 기본값: 소프트웨어 인코더
        return ["-c:v", "libx264", "-tune", "zerolatency"]

    def _validate_url(self, url: str) -> bool:
        """Validate URL to prevent command injection."""
        if not url:
            return False
        # Allow only safe protocols
        if not re.match(r'^(http://|https://|rtsp://|/dev/video\d+)', url):
            return False
        # Prevent command injection characters
        dangerous_chars = [';', '&', '|', '`', '$', '(', ')', '<', '>', '\n', '\r']
        for char in dangerous_chars:
            if char in url:
                return False
        # Reasonable length
        if len(url) > 2048:
            return False
        return True

    def _build_webrtc_mediatx_cmd(self, opts: dict):
        input_url = (opts.get("input") or opts.get("input_url") or
                     self._settings.get(["camera", "stream_url"]) or "").strip()
        if not input_url:
            raise ValueError("missing input url")

        # Validate input URL to prevent command injection
        if not self._validate_url(input_url):
            raise ValueError("invalid or potentially dangerous input URL")

        # 스트림 이름 & 서버 주소
        name = (opts.get("name") or "cam").strip()
        self._logger.info(f"[CAMERA] Stream name validation - name: '{name}', length: {len(name)}, opts.get('name'): '{opts.get('name')}'")
        # Validate stream name (alphanumeric + underscore only)
        if not re.match(r'^[a-zA-Z0-9_]+$', name) or len(name) > 50:
            self._logger.error(f"[CAMERA] Stream name validation failed - name: '{name}', length: {len(name)}")
            raise ValueError("invalid stream name")

        rtsp_base = (opts.get("rtsp_base")
                     or os.environ.get("MEDIAMTX_RTSP_BASE")
                     or "rtsp://factor.io.kr:8554").rstrip("/")
        webrtc_base = (opts.get("webrtc_base")
                       or os.environ.get("MEDIAMTX_WEBRTC_BASE")
                       or "https://factor.io.kr/webrtc").rstrip("/")

        # Validate server URLs
        if not self._validate_url(rtsp_base):
            raise ValueError("invalid rtsp_base URL")
        if not self._validate_url(webrtc_base):
            raise ValueError("invalid webrtc_base URL")

        rtsp_url = f"{rtsp_base}/{name}"

        # 화질/프레임/비트레이트 (범위 검증 추가)
        fps       = max(0, min(60, self._safe_int(opts.get("fps", 0))))  # 0-60
        width     = max(0, min(3840, self._safe_int(opts.get("width", 0))))  # 0-3840 (4K)
        height    = max(0, min(2160, self._safe_int(opts.get("height", 0))))  # 0-2160 (4K)
        bitrate_k = max(100, min(20000, self._safe_int(opts.get("bitrateKbps", 2000))))  # 100-20000 kbps
        encoder   = (opts.get("encoder") or "v4l2m2m")
        # Validate encoder option (whitelist)
        allowed_encoders = ["v4l2m2m", "h264_v4l2m2m", "v4l2", "omx", "h264_omx", "libx264"]
        if encoder not in allowed_encoders:
            encoder = "v4l2m2m"
        low_lat   = self._safe_bool(opts.get("lowLatency", True))
        force_mj  = self._safe_bool(opts.get("forceMjpeg", False))

        # 기본 저지연/네트워크 복구 옵션들(중복 제거)
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

        # 입력 프로토콜별 최적화
        if input_url.startswith("/dev/video"):
            cmd += ["-f", "v4l2"]
        elif input_url.startswith("rtsp://"):
            cmd += ["-rtsp_transport", "tcp"]

        # HTTP MJPEG일 때 명시
        if force_mj and input_url.startswith(("http://", "https://")):
            cmd += ["-f", "mjpeg"]

        cmd += ["-i", input_url]

        # 필터 체인: fps / 스케일 / 픽셀포맷
        vf_chain = []
        if fps > 0:
            vf_chain.append(f"fps={fps}")
        if width > 0 and height > 0:
            vf_chain.append(f"scale={width}:{height}")
        vf_chain.append("format=yuv420p")
        cmd += ["-vf", ",".join(vf_chain)]

        # 인코더
        cmd += self._pick_encoder(encoder)

        # 키프레임 길이(GOP): WebRTC용으로 2초 정도 권장
        gop = (fps * 2) if fps > 0 else 50

        # 레이트컨트롤/프로파일
        cmd += [
            "-preset", "veryfast",
            "-profile:v", "baseline",
            "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
            "-b:v", f"{bitrate_k}k",
            "-maxrate", f"{int(bitrate_k * 11 / 10)}k",
            "-bufsize", f"{bitrate_k}k",
            "-an",  # 오디오 제거
        ]

        # 출력: RTSP Publish → MediaMTX
        cmd += ["-f", "rtsp", "-rtsp_transport", "tcp", rtsp_url]

        # 프론트에서 바로 볼 수 있는 WebRTC URL 힌트(메시지에 실어 보냄)
        extra = {
            "play_url_webrtc": f"{webrtc_base}/{name}/",
            "publish_url_rtsp": rtsp_url,
            "name": name,
        }
        return cmd, extra

    def _build_camera_cmd(self, opts: dict):
        return self._build_webrtc_mediatx_cmd(opts)


    def _camera_status(self):
        running = bool(self._camera_proc and (self._camera_proc.poll() is None))
        pid = (self._camera_proc.pid if running and self._camera_proc else None)
        out = {
            "running": running,
            "pid": pid,
            "started_at": self._camera_started_at,
            "last_error": self._camera_last_error
        }
        if getattr(self, "_webrtc_last", None):
            out["webrtc"] = self._webrtc_last
        return out

    def _start_ffmpeg_subprocess(self, opts: dict):
        if self._camera_proc and self._camera_proc.poll() is None:
            # 이미 실행 중이면 최근 URL만 갱신해서 반환
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

            # 플랫폼별 프로세스 그룹 설정
            import sys
            popen_kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.STDOUT
            }

            # Unix/Linux: 프로세스 그룹 생성
            if sys.platform != "win32" and hasattr(os, "setsid"):
                popen_kwargs["preexec_fn"] = os.setsid
            # Windows: CREATE_NEW_PROCESS_GROUP 플래그 사용
            elif sys.platform == "win32":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

            self._camera_proc = subprocess.Popen(cmd, **popen_kwargs)
            self._webrtc_last = extra or {}
            self._camera_started_at = time.time()
            self._camera_last_error = None
            self._logger.info("[CAMERA] pipeline started pid=%s cmd=%s",
                              self._camera_proc.pid, " ".join(shlex.quote(c) for c in cmd))
            return {"success": True, **self._camera_status()}
        except Exception as e:
            self._camera_last_error = str(e)
            self._logger.exception("[CAMERA] start failed")
            return {"success": False, "error": str(e), **self._camera_status()}

    def _stop_ffmpeg_subprocess(self, timeout_sec: float = 5.0):
        try:
            if not (self._camera_proc and self._camera_proc.poll() is None):
                return {"success": True, "already_stopped": True, **self._camera_status()}

            import sys

            # 플랫폼별 프로세스 종료
            if sys.platform == "win32":
                # Windows: CTRL_BREAK_EVENT 시그널 전송
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
                # Unix/Linux: 프로세스 그룹에 시그널 전송
                try:
                    pgid = os.getpgid(self._camera_proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
                except (OSError, AttributeError):
                    # Fallback: 개별 프로세스 종료
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

            self._logger.info("[CAMERA] ffmpeg stopped")
            return {"success": True, **self._camera_status()}
        except Exception as e:
            self._camera_last_error = str(e)
            self._logger.exception("[CAMERA] stop failed")
            return {"success": False, "error": str(e), **self._camera_status()}
    # ---------------------------------------------------------
    # (그대로 사용해도 OK) systemd or subprocess 선택
    def _systemctl(self, unit: str, action: str):
        try:
            r = subprocess.run(["systemctl", action, unit],
                               capture_output=True, text=True, timeout=8)
            ok = (r.returncode == 0)
            if not ok:
                self._logger.warning("[CAMERA] systemctl %s %s rc=%s out=%s err=%s",
                                     action, unit, r.returncode, r.stdout, r.stderr)
            return {"success": ok, "stdout": r.stdout, "stderr": r.stderr, "rc": r.returncode}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _camera_start(self, opts: dict):
        unit = (opts.get("systemd_unit") or "").strip()
        if unit:
            return self._systemctl(unit, "start")
        return self._start_ffmpeg_subprocess(opts)

    def _camera_stop(self, opts: dict):
        unit = (opts.get("systemd_unit") or "").strip()
        if unit:
            return self._systemctl(unit, "stop")
        return self._stop_ffmpeg_subprocess()

    def _publish_camera_state(self):
        try:
            inst = self._settings.get(["instance_id"]) or "unknown"
            topic = f"camera/{inst}/state"
            payload = json.dumps(self._camera_status())
            self._publish_message(topic, payload)
        except Exception as e:
            self._logger.debug(f"publish camera state error: {e}")
            
# ==== END Camera helpers ====



    def _get_sd_tree(self, force_refresh=False, timeout=0.0):
        """
        /api/files?recursive=true 의 sdcard 트리와 최대한 동일하게 반환
        """
        try:
            # 방법 1: 리스트 형식으로 통일
            # 전체 파일 목록 (API 응답과 동일한 형식)
            local_files = self._file_manager.list_files(FileDestinations.LOCAL)
            files_list = list(local_files.get("local", {}).values())
            # SD카드 파일 목록 (리스트 형태)
            sd_files = self._printer.get_sd_files()

            all_files_payload = {}
            all_files_payload["local"] = files_list
            all_files_payload["sdcard"] = sd_files

            
            return all_files_payload

        except Exception as e:
            self._logger.debug(f"sd 트리 조회 실패: {e}")
            return {}




    def _get_printer_summary(self):
        try:
            conn = self._printer.get_current_connection() or {}
            # OctoPrint는 (state, port, baudrate, profile) 형태를 반환하는 경우가 많음
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

            size = {
                "width": volume.get("width"),
                "depth": volume.get("depth"),
                "height": volume.get("height"),
            }

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
                "size": size,
            }
        except Exception as e:
            self._logger.debug(f"summary 조회 실패: {e}")
            return {}

    def _ensure_instance_id(self, force_new=False):
        """
        Get or create instance ID.
        If force_new=True, always generate a new temporary ID.
        Temporary IDs are NOT saved until registration is confirmed.
        """
        # Check if already registered
        saved_id = self._settings.get(["instance_id"])
        if saved_id and not force_new:
            return saved_id

        # Generate new temporary ID or use existing temporary ID
        if force_new or not self._temp_instance_id:
            self._temp_instance_id = str(uuid.uuid4())
            self._logger.info(f"Generated new temporary instance ID: {self._temp_instance_id}")

        return self._temp_instance_id

    ##~~ BlueprintPlugin mixin

    @octoprint.plugin.BlueprintPlugin.route("/setup-url", methods=["GET"])
    def get_setup_url(self):
        """Get the setup URL for this device"""
        try:
            # Get existing temporary ID or create new one (not saved)
            # Only save after registration is confirmed
            instance_id = self._ensure_instance_id(force_new=False)

            # DO NOT subscribe here - subscribe only when button is clicked
            setup_url = f"https://factor.io.kr/setup/{instance_id}"

            return make_response(jsonify({
                "success": True,
                "instance_id": instance_id,
                "setup_url": setup_url
            }), 200)
        except Exception as e:
            self._logger.error(f"Setup URL generation error: {e}")
            return make_response(jsonify({"error": str(e)}), 500)

    @octoprint.plugin.BlueprintPlugin.route("/start-setup", methods=["POST"])
    def start_setup(self):
        """Called when user clicks 'Open Setup Page' button - subscribe to MQTT topics"""
        try:
            # Subscribe to MQTT topics with current temporary instance_id
            self._subscribe_mqtt_topics()

            return make_response(jsonify({
                "success": True,
                "message": "Subscribed to registration topic"
            }), 200)
        except Exception as e:
            self._logger.error(f"Start setup error: {e}")
            return make_response(jsonify({"error": str(e)}), 500)

    @octoprint.plugin.BlueprintPlugin.route("/refresh-qr", methods=["POST"])
    def refresh_qr_code(self):
        """Generate a new temporary instance ID and QR code"""
        try:
            # Force generate new temporary ID
            new_instance_id = self._ensure_instance_id(force_new=True)

            # DO NOT subscribe here - wait for button click
            setup_url = f"https://factor.io.kr/setup/{new_instance_id}"

            self._logger.info(f"QR code refreshed with new ID: {new_instance_id}")

            return make_response(jsonify({
                "success": True,
                "instance_id": new_instance_id,
                "setup_url": setup_url
            }), 200)
        except Exception as e:
            self._logger.error(f"QR refresh error: {e}")
            return make_response(jsonify({"error": str(e)}), 500)

    @octoprint.plugin.BlueprintPlugin.route("/confirm-registration", methods=["POST"])
    def confirm_registration(self):
        """Confirm registration and save the instance ID permanently"""
        try:
            data = request.get_json()
            instance_id = data.get("instance_id")

            if not instance_id:
                return make_response(jsonify({"error": "instance_id is required"}), 400)

            # Verify this is our temporary ID
            if instance_id != self._temp_instance_id:
                saved_id = self._settings.get(["instance_id"])
                if instance_id != saved_id:
                    return make_response(jsonify({"error": "Invalid instance_id"}), 400)

            # Save permanently
            self._settings.set(["instance_id"], instance_id)
            self._settings.set(["registered"], True)
            self._settings.save()

            # Clear temporary ID
            self._temp_instance_id = None

            self._logger.info(f"Registration confirmed for device: {instance_id}")

            return make_response(jsonify({
                "success": True,
                "message": "Registration confirmed"
            }), 200)
        except Exception as e:
            self._logger.error(f"Registration confirmation error: {e}")
            return make_response(jsonify({"error": str(e)}), 500)

    @octoprint.plugin.BlueprintPlugin.route("/camera", methods=["GET"])
    def get_camera_config(self):
        try:
            url = self._settings.get(["camera", "stream_url"]) or ""
            return make_response(jsonify({"success": True, "stream_url": url}), 200)
        except Exception as e:
            return make_response(jsonify({"success": False, "error": str(e)}), 500)

    @octoprint.plugin.BlueprintPlugin.route("/camera", methods=["POST"])
    def set_camera_config(self):
        try:
            data = request.get_json(force=True, silent=True) or {}
            url = (data.get("stream_url") or "").strip()
            # 빈 값도 허용(초기화)
            self._settings.set(["camera", "stream_url"], url)
            self._settings.save()
            return make_response(jsonify({"success": True, "stream_url": url}), 200)
        except Exception as e:
            return make_response(jsonify({"success": False, "error": str(e)}), 500)

    # ===== Blueprint API 엔드포인트 (당신의 코드) =====
    @octoprint.plugin.BlueprintPlugin.route("/upload/local", methods=["POST"])
    def upload_to_local(self):
        """로컬에 파일 업로드"""
        try:
            from octoprint.filemanager.util import DiskFileWrapper
            from octoprint.filemanager.destinations import FileDestinations as FD
        except Exception:
            from octoprint.filemanager.util import DiskFileWrapper
            from octoprint.filemanager import FileDestinations as FD

        if 'file' not in request.files:
            return make_response(jsonify({"error": "파일이 없습니다"}), 400)

        file = request.files['file']
        if file.filename == '':
            return make_response(jsonify({"error": "파일명이 없습니다"}), 400)

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.gcode') as tmp_file:
                file.save(tmp_file.name)
                tmp_path = tmp_file.name

            file_object = DiskFileWrapper(file.filename, tmp_path)
            username = None
            try:
                user = getattr(self, "_user_manager", None)
                if user:
                    cu = user.get_current_user()
                    if cu:
                        username = cu.get_name()
            except Exception:
                pass

            saved_path = self._file_manager.add_file(
                FD.LOCAL,
                file.filename,
                file_object,
                allow_overwrite=True,
                user=username
            )

            try:
                os.unlink(tmp_path)
            except Exception:
                pass

            return make_response(jsonify({
                "success": True,
                "path": saved_path,
                "message": f"파일이 로컬에 저장되었습니다: {saved_path}"
            }), 200)

        except Exception as e:
            try:
                if 'tmp_path' in locals() and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass
            return make_response(jsonify({"error": f"업로드 실패: {str(e)}"}), 500)

    @octoprint.plugin.BlueprintPlugin.route("/upload/sd", methods=["POST"])
    def upload_to_sd(self):
        """로컬 파일을 SD카드로 전송"""
        try:
            from octoprint.filemanager.destinations import FileDestinations as FD
        except Exception:
            from octoprint.filemanager import FileDestinations as FD

        data = request.get_json(force=True, silent=True) or {}
        local_filename = data.get('filename')

        if not local_filename:
            return make_response(jsonify({"error": "파일명이 필요합니다"}), 400)

        try:
            if not getattr(self._printer, "is_sd_ready", lambda: False)():
                return make_response(jsonify({"error": "SD카드가 준비되지 않았습니다"}), 409)

            if self._printer.is_printing():
                return make_response(jsonify({"error": "프린트 중에는 SD카드 업로드가 불가능합니다"}), 409)

            local_path = self._file_manager.path_on_disk(FD.LOCAL, local_filename)
            if not os.path.exists(local_path):
                return make_response(jsonify({"error": f"로컬 파일을 찾을 수 없습니다: {local_filename}"}), 404)

            def on_success(remote_filename):
                try:
                    self._logger.info(f"SD카드 업로드 성공: {remote_filename}")
                except Exception:
                    pass

            def on_failure(remote_filename):
                try:
                    self._logger.error(f"SD카드 업로드 실패: {remote_filename}")
                except Exception:
                    pass

            remote_filename = self._printer.add_sd_file(
                local_filename,
                local_path,
                on_success=on_success,
                on_failure=on_failure,
                tags={"source:plugin"}
            )

            return make_response(jsonify({
                "success": True,
                "remote_filename": remote_filename,
                "message": f"파일이 SD카드에 업로드되었습니다: {remote_filename}"
            }), 200)

        except Exception as e:
            return make_response(jsonify({"error": f"SD카드 업로드 실패: {str(e)}"}), 500)


    def get_update_information(self):
        return {
            "factor_mqtt": {
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
        """프린터 상태 스냅샷을 생성합니다."""
        import time, json
        
        data  = self._printer.get_current_data() or {}
        temps = self._printer.get_current_temperatures() or {}
        conn  = self._printer.get_current_connection() or {}

        progress = (data.get("progress") or {})
        job      = (data.get("job") or {})
        fileinfo = (job.get("file") or {})
        filament = (job.get("filament") or {})
        flags    = (data.get("state") or {}).get("flags", {})

        size    = fileinfo.get("size") or 0
        filepos = progress.get("filepos") or 0
        file_pct = round((filepos/size*100.0), 2) if size else None

        snapshot = {
            "ts":        time.time(),
            "state": {
                "text": (data.get("state") or {}).get("text"),
                "flags": {
                    "operational": bool(flags.get("operational")),
                    "printing":    bool(flags.get("printing")),
                    "paused":      bool(flags.get("paused")),
                    "error":       bool(flags.get("error")),
                    "ready":       bool(flags.get("ready")),
                }
            },
            "progress": {
                "completion": progress.get("completion"),      # %
                "filepos":    filepos,                         # bytes
                "file_size":  size,                            # bytes
                "file_pct":   file_pct,                        # %
                "print_time": progress.get("printTime"),       # sec
                "time_left":  progress.get("printTimeLeft"),   # sec
                "time_left_origin": progress.get("printTimeLeftOrigin"),
            },
            "job": {
                "file": {
                    "name":   fileinfo.get("name"),
                    "origin": fileinfo.get("origin"),   # local/sdcard
                    "date":   fileinfo.get("date"),
                },
                "estimated_time": job.get("estimatedPrintTime"),
                "last_time":      job.get("lastPrintTime"),
                "filament":       filament,            # tool0.length/volume 등 그대로 유지
            },
            "axes": {
                "currentZ": data.get("currentZ")
            },
            "temperatures": temps,                      # tool0/bed/chamber: actual/target/offset
            "connection": conn,                         # port/baudrate/printerProfile/state
            "sd": self._get_sd_tree(),                  # REST 스타일 { files: [...] }
        }
        return snapshot

    @octoprint.plugin.BlueprintPlugin.route("/snapshot", methods=["GET"])
    def get_snapshot(self):
        """REST API로 스냅샷을 반환합니다."""
        return self._make_snapshot()

    def _start_snapshot_timer(self):
        """스냅샷 전송 타이머를 시작합니다."""
        with self._snapshot_timer_lock:
            if self._snapshot_timer:  # 중복 방지
                return
            interval = float(self._settings.get(["periodic_interval"]) or 1.0)
            self._snapshot_timer = RepeatedTimer(interval, self._snapshot_tick, run_first=True)
            self._snapshot_timer.start()
            self._logger.info(f"[FACTOR] snapshot timer started every {interval}s")

    def _stop_snapshot_timer(self):
        """스냅샷 전송 타이머를 중지합니다."""
        with self._snapshot_timer_lock:
            if self._snapshot_timer:
                self._snapshot_timer.cancel()
                self._snapshot_timer = None
                self._logger.info("[FACTOR] snapshot timer stopped")

    def _snapshot_tick(self):
        """스냅샷 타이머 콜백 함수"""
        # 연결되어 있지 않으면 아무것도 안 함 (MQTT 재연결을 기다림)
        if not (self.is_connected and self.mqtt_client):
            return
        # 스냅샷 만들어 퍼블리시 (이미 만들었던 함수 재사용)
        try:
            payload = self._make_snapshot()
            # Use temporary ID first during setup, then saved ID for registered devices
            inst = self._temp_instance_id or self._settings.get(["instance_id"]) or "unknown"
            topic = f"{self._settings.get(['topic_prefix']) or 'octoprint'}/status/{inst}"
            self._publish_message(topic, json.dumps(payload))
            self._gc_expired_jobs()
        except Exception as e:
            self._logger.debug(f"snapshot tick error: {e}")


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = MqttPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config":
            __plugin_implementation__.get_update_information
    }