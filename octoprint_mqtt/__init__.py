# -*- coding: utf-8 -*-
import json
import subprocess, shlex, os, signal
from flask import request  # Blueprint에서 사용
import octoprint.plugin
from octoprint.filemanager import FileDestinations

from octoprint.util import RepeatedTimer
from flask import jsonify, make_response
import requests
import re
import uuid
import tempfile
import base64
import io
import time
import hashlib



__plugin_name__ = "MQTT-Plugin from FACTOR"
__plugin_pythoncompat__ = ">=3.8,<4"
__plugin_version__ = "1.0.9"
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
                 octoprint.plugin.BlueprintPlugin):
    
    def __init__(self):
        super().__init__()
        self.mqtt_client = None
        self.is_connected = False
        self._snapshot_timer = None
        self._gcode_jobs = {}
        # camera process state
        self._camera_proc = None
        self._camera_started_at = None
        self._camera_last_error = None
    
    ##~~ SettingsPlugin mixin
    
    def get_settings_defaults(self):
        return dict(
            broker_host="localhost",
            broker_port=1883,
            broker_username="",
            broker_password="",
            topic_prefix="octoprint",   # JS와 일치!
            qos_level=0,
            retain_messages=False,
            publish_status=True,
            publish_progress=True,
            publish_temperature=True,
            publish_gcode=False,
            publish_snapshot=True,
            periodic_interval=1.0,
            auth_api_base="http://192.168.200.102:3000",
            register_api_base="http://192.168.200.102:3000",
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
            js=["js/mqtt.js"],
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

        self._logger.info("[FACTOR MQTT] REST endpoints ready:")
        self._logger.info(" - GET  %s", status_url)
        self._logger.info(" - POST %s", test_url)
        self._logger.info("   (헤더 'X-Api-Key' 필요)")

    def get_template_configs(self):
        return [dict(
            type="settings",
            name="FACTOR MQTT",
            template="mqtt_settings.jinja2",
            custom_bindings=True   # ← 여기 꼭 True
        )]
    
    
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
            
            self.mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
            
            # 인증 정보 설정
            username = self._settings.get(["broker_username"])
            password = self._settings.get(["broker_password"])
            if username:
                self.mqtt_client.username_pw_set(username, password)
            
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
            self._logger.info(f"MQTT 비동기 연결 시도: {host}:{port}")
            
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
    
    def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None, *args, **kwargs):
        rc_i = _as_code(rc)
        self.is_connected = (rc_i == 0)
        if self.is_connected:
            self._logger.info("MQTT 브로커 연결 OK")
            self._start_snapshot_timer()     # ✅ 여기서 시작
            try:
                qos = int(self._settings.get(["qos_level"]) or 1)
                inst = self._settings.get(["instance_id"]) or "unknown"

                # 고정 토픽만 구독
                control_topic = f"control/{inst}"
                gcode_topic = f"octoprint/gcode_in/{inst}"
                camera_cmd = f"camera/{inst}/cmd"
                self.mqtt_client.subscribe(control_topic, qos=qos)
                self.mqtt_client.subscribe(gcode_topic, qos=qos)
                self.mqtt_client.subscribe(camera_cmd, qos=qos)
                self._logger.info(f"[FACTOR MQTT] subscribe: {control_topic} | {gcode_topic} | {camera_cmd} (qos={qos})")
            except Exception as e:
                self._logger.warning(f"[FACTOR MQTT] subscribe 실패: {e}")
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
            inst = self._settings.get(["instance_id"]) or "unknown"

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

            # 기타 토픽은 무시
            return
        except Exception as e:
            self._logger.exception(f"[FACTOR MQTT] on_message 처리 오류: {e}")

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
                self._logger.warning(f"[FACTOR MQTT] 만료된 job 정리: {expired}")
        except Exception:
            pass
    
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

    def _build_webrtc_mediatx_cmd(self, opts: dict):
        input_url = (opts.get("input") or opts.get("input_url") or
                     self._settings.get(["camera", "stream_url"]) or "").strip()
        if not input_url:
            raise ValueError("missing input url")

        # 스트림 이름 & 서버 주소
        name = (opts.get("name") or "cam").strip()
        rtsp_base = (opts.get("rtsp_base")
                     or os.environ.get("MEDIAMTX_RTSP_BASE")
                     or "rtsp://192.168.200.102:8554").rstrip("/")
        webrtc_base = (opts.get("webrtc_base")
                       or os.environ.get("MEDIAMTX_WEBRTC_BASE")
                       or "http://192.168.200.102:8889").rstrip("/")

        rtsp_url = f"{rtsp_base}/{name}"

        # 화질/프레임/비트레이트
        fps       = self._safe_int(opts.get("fps", 0))
        width     = self._safe_int(opts.get("width", 0))
        height    = self._safe_int(opts.get("height", 0))
        bitrate_k = self._safe_int(opts.get("bitrateKbps", 2000))
        encoder   = (opts.get("encoder") or "v4l2m2m")
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
        if input_url.startswith("rtsp://"):
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
            "play_url_webrtc": f"{webrtc_base}/{name}",
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

            # 라즈베리(리눅스) 기준 프로세스 그룹 생성해서 종료 간편화
            self._camera_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid
            )
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
            pgid = os.getpgid(self._camera_proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            t0 = time.time()
            while (time.time() - t0) < timeout_sec:
                if self._camera_proc.poll() is not None:
                    break
                time.sleep(0.1)
            if self._camera_proc.poll() is None:
                os.killpg(pgid, signal.SIGKILL)
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

    def _ensure_instance_id(self):
        iid = self._settings.get(["instance_id"]) or ""
        if not iid:
            try:
                iid = str(uuid.uuid4())
                # 메모리에만 보관하고, 등록 성공 시에만 저장하도록 변경
                self._settings.set(["instance_id"], iid)
            except Exception:
                pass
        return iid

    ##~~ BlueprintPlugin mixin
    
    @octoprint.plugin.BlueprintPlugin.route("/auth/login", methods=["POST"])
    def auth_login(self):
        try:
            data = request.get_json(force=True) or {}
            email = (data.get("email") or "").strip()
            password = data.get("password") or ""
            if not email or not password:
                return make_response(jsonify({"error": "email and password required"}), 400)

            api_base = (self._settings.get(["auth_api_base"])).rstrip("/")
            if not re.match(r"^https?://", api_base):
                return make_response(jsonify({"error": "invalid auth_api_base"}), 500)

            url = f"{api_base}/api/auth/login"
            resp = requests.post(url, json={"email": email, "password": password}, timeout=8)
            try:
                is_json = (resp.headers.get("content-type", "").lower().startswith("application/json"))
            except Exception:
                is_json = False
            out = (resp.json() if is_json else {"raw": resp.text})
            return make_response(jsonify(out), resp.status_code)
        except Exception as e:
            return make_response(jsonify({"error": str(e)}), 500)

    @octoprint.plugin.BlueprintPlugin.route("/summary", methods=["GET"])
    def proxy_printers_summary(self):
        """사용자 ID에 등록된 프린터 요약을 외부 API로부터 안전하게 프록시"""
        try:
            base = (self._settings.get(["register_api_base"]) or self._settings.get(["auth_api_base"]) or "").rstrip("/")
            if not base or not re.match(r"^https?://", base):
                return make_response(jsonify({"error": "invalid register_api_base"}), 500)
            token = request.headers.get("Authorization") or ""
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = token
            url = f"{base}/api/printers/summary"
            resp = requests.get(url, headers=headers, timeout=8)
            try:
                out = resp.json()
            except Exception:
                out = {"raw": resp.text}
            return make_response(jsonify(out), resp.status_code)
        except Exception as e:
            return make_response(jsonify({"error": str(e)}), 500)

    @octoprint.plugin.BlueprintPlugin.route("/register", methods=["POST"])
    def proxy_register(self):
        try:
            data = request.get_json(force=True) or {}
            instance_id = (data.get("instance_id") or "").strip() or self._ensure_instance_id()
            user = data.get("user") or {}
            access_token = (data.get("access_token") or data.get("accessToken") or "").strip()
            # 헤더 우선: Authorization: Bearer <token>
            try:
                hdr_auth = request.headers.get("Authorization") or ""
            except Exception:
                hdr_auth = ""
            if hdr_auth and hdr_auth.lower().startswith("bearer "):
                access_token = hdr_auth.split(" ", 1)[1].strip() or access_token
            if not instance_id:
                return make_response(jsonify({"success": False, "error": "missing instance_id"}), 400)

            base = (self._settings.get(["register_api_base"]) or self._settings.get(["auth_api_base"])).rstrip("/")
            if not re.match(r"^https?://", base):
                return make_response(jsonify({"success": False, "error": "invalid register_api_base"}), 500)

            url = f"{base}/api/printer/register"
            # 프린터 요약 정보(필요 시 확장)
            client_info = {
                "uuid": instance_id
            }
            printer_info = {
                "connection": self._printer.get_current_connection(),
                "state": (self._printer.get_current_data() or {}).get("state"),
                "registration": {
                    "is_new": not bool(self._settings.get(["registered"]) or False)
                }
            }
            camera_info = {
                "uuid": None,
                "stream_url": self._settings.get(["camera", "stream_url"]) or None
            }
            software_info = {
                "firmware_version": None,
                "firmware": None,
                "last_update": None,
                "uuid": None
            }
            # 권장 포맷: 헤더 Authorization: Bearer <token>, 바디 { payload: {...}, user: { id } }
            payload_obj = {"client": client_info, "printer": printer_info, "camera": camera_info, "software": software_info}
            body = {"payload": payload_obj}
            if isinstance(user, dict) and user.get("id"):
                body["user"] = {"id": user.get("id")}
            headers = {"Content-Type": "application/json"}
            if access_token:
                headers["Authorization"] = f"Bearer {access_token}"
            resp = requests.post(url, json=body, headers=headers, timeout=8)
            ok = 200 <= resp.status_code < 300
            try:
                out = resp.json()
            except Exception:
                out = {"raw": resp.text}
            if ok:
                try:
                    self._settings.set(["registered"], True)
                    self._settings.set(["instance_id"], instance_id)
                    self._settings.save()
                except Exception:
                    pass
            return make_response(jsonify(out), resp.status_code)
        except Exception as e:
            return make_response(jsonify({"success": False, "error": str(e)}), 500)

    @octoprint.plugin.BlueprintPlugin.route("/status", methods=["GET"])
    def get_mqtt_status(self):
        """MQTT 연결 상태를 반환합니다."""
        return {
            "connected": self.is_connected,
            "broker_host": self._settings.get(["broker_host"]),
            "broker_port": self._settings.get(["broker_port"]),
            # /api/files?recursive=true 의 sdcard 트리와 동일 구조
            "sd_files": self._get_sd_tree(),
            "registered": bool(self._settings.get(["registered"]) or False),
            "instance_id": self._settings.get(["instance_id"]) or None,
            "printer_summary": self._get_printer_summary(),
        }

    @octoprint.plugin.BlueprintPlugin.route("/device", methods=["POST"])
    def set_device_uuid(self):
        try:
            data = request.get_json(force=True, silent=True) or {}
            dev = (data.get("device_uuid") or "").strip()
            if not dev:
                return make_response(jsonify({"success": False, "error": "missing device_uuid"}), 400)
            self._settings.set(["instance_id"], dev)
            self._settings.set(["registered"], True)
            self._settings.save()
            return make_response(jsonify({"success": True, "instance_id": dev}), 200)
        except Exception as e:
            return make_response(jsonify({"success": False, "error": str(e)}), 500)

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

    @octoprint.plugin.BlueprintPlugin.route("/test", methods=["POST"])
    def test_mqtt_connection(self):
        import time, json, threading
        import paho.mqtt.client as mqtt

        data = request.get_json(force=True, silent=True) or {}
        host = data.get("broker_host", "localhost")
        port = int(data.get("broker_port", 1883))
        username = data.get("broker_username")
        pw = data.get("broker_password", "")
        do_publish = bool(data.get("publish", False))
        topic = data.get("test_topic") or f"{self._settings.get(['topic_prefix']) or 'octoprint'}/test"

        self._logger.info("[TEST] MQTT 연결 테스트 시작 host=%s port=%s user=%s pw=%s publish=%s topic=%s",
                        host, port, (username or "<none>"), ("***" if pw else "<none>"), do_publish, topic)

        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        try:
            client.enable_logger(self._logger.getChild("paho"))
        except Exception:
            pass
        if username:
            client.username_pw_set(username, pw)

        result = {"success": False, "error": None, "rc": None, "rtt_ms": None}
        connected_evt = threading.Event()
        published_evt = threading.Event()
        mid_ref = {"mid": None}

        # v2: (client, userdata, flags, reasonCode, properties)
        def on_connect(c, u, flags, reasonCode, properties=None):
            result["rc"] = _as_code(reasonCode)
            if result["rc"] == 0:
                self._logger.info("[TEST] MQTT CONNECT OK (rc=%s)", result["rc"])
                if do_publish:
                    payload = json.dumps({"plugin": "factor_mqtt", "status": "ok", "ts": time.time()})
                    info = c.publish(topic, payload, qos=1, retain=False)  # PUBACK 확인용 QoS 1
                    mid_ref["mid"] = info.mid
                    # 콜백 안에서는 wait 금지!
            else:
                self._logger.error("[TEST] MQTT CONNECT FAIL rc=%s", result["rc"])
                result["error"] = f"연결 실패 (코드: {result['rc']})"
            connected_evt.set()

        # paho 2.0: (client, userdata, mid, properties)
        # paho 2.1: (client, userdata, mid, reasonCode, properties)
        def on_publish(c, u, mid, *args, **kwargs):
            reasonCode = None
            properties = None
            if len(args) == 1:
                properties = args[0]
            elif len(args) >= 2:
                reasonCode, properties = args[0], args[1]
            if mid_ref["mid"] == mid:
                if reasonCode is not None:
                    self._logger.info("[TEST] MQTT PUBLISH OK topic=%s rc=%s", topic, _as_code(reasonCode))
                else:
                    self._logger.info("[TEST] MQTT PUBLISH OK topic=%s", topic)
                published_evt.set()

        # v2: (client, userdata, disconnect_flags, reasonCode, properties)
        def on_disconnect(c, u, disconnect_flags, reasonCode, properties=None):
            self._logger.info("[TEST] MQTT DISCONNECT flags=%s rc=%s",
                            str(disconnect_flags), _as_code(reasonCode))

        client.on_connect = on_connect
        client.on_publish = on_publish
        client.on_disconnect = on_disconnect

        t0 = time.time()
        try:
            self._logger.info("[TEST] MQTT connect() 시도...")
            client.connect(host, port, 10)
            client.loop_start()

            # 메인 쓰레드 대기(콜백 안에서는 절대 wait 하지 말기!)
            if not connected_evt.wait(6):
                result["error"] = "연결 시간 초과"
            elif result["rc"] == 0 and do_publish:
                if not published_evt.wait(3):
                    self._logger.warning("[TEST] MQTT PUBLISH TIMEOUT topic=%s", topic)
                else:
                    result["success"] = True
            else:
                result["success"] = (result["rc"] == 0)

        except Exception as e:
            result["error"] = str(e)
            self._logger.exception("[TEST] 예외 발생")
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
            client.loop_stop()

        result["rtt_ms"] = int((time.time() - t0) * 1000)
        if result["success"]:
            self._logger.info("[TEST] MQTT 연결 테스트 성공 rtt=%sms", result["rtt_ms"])
            # (선택) 메인 클라이언트가 붙어있다면 스냅샷 1회 발행
            try:
                if self.is_connected and self.mqtt_client:
                    inst = self._settings.get(["instance_id"]) or "unknown"
                    self._publish_message(f"{self._settings.get(['topic_prefix']) or 'octoprint'}/status/{inst}",
                                          json.dumps(self._make_snapshot()))
                    self._logger.info("[TEST] 스냅샷 전송 완료")
            except Exception as e:
                self._logger.warning("[TEST] 스냅샷 전송 실패: %s", e)
            return {"success": True, "message": "연결 테스트 성공", "rtt_ms": result["rtt_ms"], "rc": result["rc"]}
        else:
            err = result["error"] or "연결 시간 초과"
            self._logger.error("[TEST] MQTT 연결 테스트 실패: %s", err)
            return {"success": False, "error": err, "rtt_ms": result["rtt_ms"], "rc": result["rc"]}



    

    def get_update_information(self):
        return {
            "factor_mqtt": {
                "displayName": "MQTT-Plugin from FACTOR",
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
        if self._snapshot_timer:  # 중복 방지
            return
        interval = float(self._settings.get(["periodic_interval"]) or 1.0)
        self._snapshot_timer = RepeatedTimer(interval, self._snapshot_tick, run_first=True)
        self._snapshot_timer.start()
        self._logger.info(f"[FACTOR MQTT] snapshot timer started every {interval}s")

    def _stop_snapshot_timer(self):
        """스냅샷 전송 타이머를 중지합니다."""
        if self._snapshot_timer:
            self._snapshot_timer.cancel()
            self._snapshot_timer = None
            self._logger.info("[FACTOR MQTT] snapshot timer stopped")

    def _snapshot_tick(self):
        """스냅샷 타이머 콜백 함수"""
        # 연결되어 있지 않으면 아무것도 안 함 (MQTT 재연결을 기다림)
        if not (self.is_connected and self.mqtt_client):
            return
        # 스냅샷 만들어 퍼블리시 (이미 만들었던 함수 재사용)
        try:
            payload = self._make_snapshot()
            inst = self._settings.get(["instance_id"]) or "unknown"
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