import octoprint.plugin
from octoprint.filemanager.destinations import FileDestinations
from octoprint.filemanager.util import DiskFileWrapper
import tempfile
import os
import base64
import json
import time


# Track unknown job_ids to prevent log spam (only warn once per job_id)
_unknown_job_ids_warned = set()


def _publish_upload_result(self, job_id, success, filename, error=None, target=None, file_size=None):
    """Publish upload result to MQTT topic: octoprint/gcode_out/{instance_id}"""
    try:
        instance_id = self._temp_instance_id or self._settings.get(["instance_id"])
        if not instance_id or not self.mqtt_client or not self.is_connected:
            return

        result = {
            "type": "upload_result",
            "job_id": job_id,
            "success": success,
            "filename": filename,
            "timestamp": time.time(),
        }

        if success:
            result["target"] = target
            if file_size is not None:
                result["file_size"] = file_size
        else:
            result["error"] = error or "Unknown error"

        topic = f"octoprint/gcode_out/{instance_id}"
        self.mqtt_client.publish(topic, json.dumps(result), qos=1)
        self._logger.info(f"[FACTOR MQTT] Published upload result to {topic}: success={success}")
    except Exception as e:
        self._logger.error(f"[FACTOR MQTT] Failed to publish upload result: {e}")


def _validate_filename(filename: str) -> bool:
    """Validate filename to prevent path traversal and injection."""
    if not filename:
        return False
    # Prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return False
    # Block dangerous characters (control chars, shell metacharacters)
    # Allow Unicode letters (Korean, etc.), numbers, underscore, hyphen, dot, space
    dangerous_chars = set('<>:"|?*\x00\n\r\t')
    if any(c in dangerous_chars for c in filename):
        return False
    # Must end with valid G-code extensions
    valid_extensions = ('.gcode', '.gco', '.g')
    if not filename.lower().endswith(valid_extensions):
        return False
    # Reasonable length limit
    if len(filename) > 255:
        return False
    return True


def _validate_gcode_content(content: bytes, max_size_mb: int = 100) -> tuple:
    """Validate G-code content size. Returns (is_valid, error_message)."""
    if len(content) > max_size_mb * 1024 * 1024:
        return False, f"File too large (max {max_size_mb}MB)"
    return True, None


def handle_gcode_message(self, data: dict):
    """Handle G-code message received via MQTT"""
    action = (data.get("action") or "").lower()
    job_id = data.get("job_id")
    now = __import__("time").time()
    
    if not job_id:
        self._logger.warning("[FACTOR MQTT] job_id missing")
        return

    # Print uploaded file immediately (based on upload whitelist)
    if action == "print":
        try:
            name = (data.get("filename") or "").strip()
            origin = (data.get("origin") or "local").lower()  # local | sd | sdcard
            if not name:
                self._logger.warning("[FACTOR MQTT] print filename missing")
                return

            # Validate filename
            if not _validate_filename(name):
                self._logger.error(f"[FACTOR MQTT] Invalid filename: {name}")
                return

            is_sd = origin in ("sd", "sdcard", "sd_card")
            if is_sd:
                whitelist = getattr(self, "_uploaded_sd_files", set())
            else:
                whitelist = getattr(self, "_uploaded_local_files", set())
            if whitelist and name not in whitelist:
                self._logger.warning(f"[FACTOR MQTT] Unauthorized print request: {name}")
                return
            self._printer.select_file(name, sd=is_sd, printAfterSelect=True)
            self._logger.info(f"[FACTOR MQTT] Print started: origin={'sd' if is_sd else 'local'} name={name}")
        except Exception as e:
            self._logger.error(f"[FACTOR MQTT] Print failed: {e}")
        return

    if action == "start":
        # Start logic
        filename = data.get("filename") or f"{job_id}.gcode"
        total = int(data.get("total_chunks") or 0)
        upload_target = (data.get("upload_traget") or data.get("upload_target") or "").lower()

        # Validate filename
        if not _validate_filename(filename):
            self._logger.error(f"[FACTOR MQTT] Invalid filename: {filename}")
            return

        # Validate chunk count
        if total <= 0 or total > 10000:  # Reasonable limit
            self._logger.warning(f"[FACTOR MQTT] total_chunks out of range: {total}")
            return

        self._gcode_jobs[job_id] = {
            "filename": filename,
            "total": total,
            "chunks": {},
            "created_ts": now,
            "last_ts": now,
            "upload_target": upload_target
        }
        self._logger.info(f"[FACTOR MQTT] GCODE reception started job={job_id} file={filename} total={total}")
        return

    state = self._gcode_jobs.get(job_id)
    if not state:
        # Only warn once per unknown job_id to prevent log spam
        if job_id not in _unknown_job_ids_warned:
            _unknown_job_ids_warned.add(job_id)
            self._logger.warning(f"[FACTOR MQTT] Unknown job_id={job_id} (further messages suppressed)")
            # Limit cache size to prevent memory leak
            if len(_unknown_job_ids_warned) > 1000:
                _unknown_job_ids_warned.clear()
        return

    state["last_ts"] = now

    if action == "chunk":
        # Chunk processing logic
        try:
            seq = int(data.get("seq"))
            base64_data = data.get("data_b64") or ""
            if seq < 0 or not base64_data:
                raise ValueError("seq/data_b64 invalid")
            chunk = base64.b64decode(base64_data)
            state["chunks"][seq] = chunk
            if len(state["chunks"]) % 50 == 0 or len(state["chunks"]) == 1:
                self._logger.info(f"[FACTOR MQTT] chunk received job={job_id} {len(state['chunks'])}/{state['total']}")
        except Exception as e:
            self._logger.warning(f"[FACTOR MQTT] chunk processing failed: {e}")
        return

    if action == "cancel":
        self._gcode_jobs.pop(job_id, None)
        self._logger.info(f"[FACTOR MQTT] GCODE reception canceled job={job_id}")
        return

    if action == "end":
        # Combine chunks and upload
        total = state["total"]
        got = len(state["chunks"])
        filename = state.get("filename", "")

        if got != total:
            self._logger.warning(f"[FACTOR MQTT] end received but chunk mismatch {got}/{total}")
            _publish_upload_result(self, job_id, False, filename, f"chunk mismatch {got}/{total}")
            self._gcode_jobs.pop(job_id, None)
            return

        ordered = [state["chunks"][i] for i in range(total)]
        content = b"".join(ordered)

        # Validate G-code content
        is_valid, error_msg = _validate_gcode_content(content)
        if not is_valid:
            self._logger.error(f"[FACTOR MQTT] G-code validation failed: {error_msg}")
            _publish_upload_result(self, job_id, False, filename, error_msg)
            self._gcode_jobs.pop(job_id, None)
            return

        target = (data.get("target") or state.get("upload_target") or "").lower()
        if target not in ("sd", "local", "local_print"):
            target = (self._settings.get(["receive_target_default"]) or "local").lower()

        # Clean up chunk data
        self._gcode_jobs.pop(job_id, None)

        # Upload processing (reuse your logic)
        upload_result = _upload_gcode_content(self, content, filename, target)

        if upload_result.get("success"):
            self._logger.info(f"[FACTOR MQTT] Upload successful job={job_id} file={filename} target={target}")
            _publish_upload_result(self, job_id, True, filename, None, target, len(content))
        else:
            self._logger.error(f"[FACTOR MQTT] Upload failed job={job_id}: {upload_result.get('error')}")
            _publish_upload_result(self, job_id, False, filename, upload_result.get("error"))
        return

def _upload_gcode_content(self, content: bytes, filename: str, target: str):
    """Upload chunk data according to target"""
    try:
        if target == "sd":
            return _upload_bytes_to_sd(self, content, filename)
        elif target in ("local", "local_print"):
            res = _upload_bytes_to_local(self, content, filename)
            # local_print prints immediately after saving
            if target == "local_print" and res.get("success"):
                try:
                    # Call select_file with filename (LOCAL root)
                    self._printer.select_file(filename, False, printAfterSelect=True)
                except Exception:
                    pass
            return res
        else:
            return {"success": False, "error": f"Unknown target: {target}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _upload_bytes_to_local(self, content: bytes, filename: str):
    """Upload byte data to local"""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.gcode') as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name

        file_object = DiskFileWrapper(filename, tmp_path)
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
            FileDestinations.LOCAL,
            filename,
            file_object,
            allow_overwrite=True,
            user=username
        )

        try:
            if not hasattr(self, "_uploaded_local_files"):
                self._uploaded_local_files = set()
            self._uploaded_local_files.add(filename)
        except Exception:
            pass

        return {
            "success": True,
            "path": saved_path,
            "message": f"File saved to local: {saved_path}"
        }

    except Exception as e:
        return {"success": False, "error": f"Local upload failed: {str(e)}"}
    finally:
        # Always clean up temporary files
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

def _upload_bytes_to_sd(self, content: bytes, filename: str):
    """Upload byte data to SD card"""
    tmp_path = None
    try:
        if not getattr(self._printer, "is_sd_ready", lambda: False)():
            return {"success": False, "error": "SD card not ready"}

        if self._printer.is_printing():
            return {"success": False, "error": "Cannot upload to SD card while printing"}

        # Save as temporary local file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.gcode') as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name

        file_object = DiskFileWrapper(filename, tmp_path)
        username = None
        try:
            user = getattr(self, "_user_manager", None)
            if user:
                cu = user.get_current_user()
                if cu:
                    username = cu.get_name()
        except Exception:
            pass

        # Save as temporary local file
        temp_filename = f"temp_{filename}"
        local_path = self._file_manager.add_file(
            FileDestinations.LOCAL,
            temp_filename,
            file_object,
            allow_overwrite=True,
            user=username
        )

        def on_success(local, remote, elapsed=None, *args, **kwargs):
            try:
                self._logger.info(f"SD card upload successful:remote={remote}, local={local}")
                # Delete temporary local file

                try:
                    self._printer.refresh_sd_files()
                except Exception:
                    pass
                try:
                    self._file_manager.remove_file(FileDestinations.LOCAL, temp_filename)
                except:
                    pass
            except Exception:
                pass

        def on_failure(local, remote, elapsed=None, *args, **kwargs):
            try:
                self._logger.error(f"SD card upload failed: remote={remote}, local={local}")
                # Delete temporary local file
                try:
                    self._file_manager.remove_file(FileDestinations.LOCAL, temp_filename)
                except:
                    pass
            except Exception:
                pass

        remote_filename = self._printer.add_sd_file(
            filename,
            self._file_manager.path_on_disk(FileDestinations.LOCAL, temp_filename),
            on_success=on_success,
            on_failure=on_failure,
            tags={"source:plugin", "mqtt:upload"}
        )

        try:
            if not hasattr(self, "_uploaded_sd_files"):
                self._uploaded_sd_files = set()
            # SD may use remote filename (printer's path/name). Manage with requested filename for now
            self._uploaded_sd_files.add(filename)
        except Exception:
            pass

        return {
            "success": True,
            "remote_filename": remote_filename,
            "message": f"File uploaded to SD card: {remote_filename}"
        }

    except Exception as e:
        return {"success": False, "error": f"SD card upload failed: {str(e)}"}
    finally:
        # Always clean up temporary files
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass