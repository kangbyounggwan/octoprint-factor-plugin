import base64
import hashlib


def handle_gcode_message(plugin, data: dict):
    action = (data.get("action") or "").lower()
    job_id = data.get("job_id")
    now = __import__("time").time()
    if not job_id:
        plugin._logger.warning("[FACTOR MQTT] job_id 누락")
        return

    plugin._gc_expired_jobs(now)

    if action == "start":
        filename = data.get("filename") or f"{job_id}.gcode"
        total = int(data.get("total_chunks") or 0)
        upload_target = (data.get("upload_traget") or data.get("upload_target") or "").lower()
        if total <= 0:
            plugin._logger.warning("[FACTOR MQTT] total_chunks 누락/잘못됨")
            return
        plugin._gcode_jobs[job_id] = {
            "filename": filename,
            "total": total,
            "chunks": {},
            "created_ts": now,
            "last_ts": now,
            "upload_target": upload_target
        }
        plugin._logger.info(f"[FACTOR MQTT] GCODE 수신 시작 job={job_id} file={filename} total={total}")
        return

    state = plugin._gcode_jobs.get(job_id)
    if not state:
        plugin._logger.warning(f"[FACTOR MQTT] 알 수 없는 job_id={job_id}, start 먼저 필요")
        return

    state["last_ts"] = now

    if action == "chunk":
        try:
            seq = int(data.get("seq"))
            b64 = data.get("data_b64") or ""
            if seq < 0 or not b64:
                raise ValueError("seq/data_b64 invalid")
            chunk = base64.b64decode(b64)
            state["chunks"][seq] = chunk
            if len(state["chunks"]) % 50 == 0 or len(state["chunks"]) == 1:
                plugin._logger.info(f"[FACTOR MQTT] chunk 수신 job={job_id} {len(state['chunks'])}/{state['total']}")
        except Exception as e:
            plugin._logger.warning(f"[FACTOR MQTT] chunk 처리 실패: {e}")
        return

    if action == "cancel":
        plugin._gcode_jobs.pop(job_id, None)
        plugin._logger.info(f"[FACTOR MQTT] GCODE 수신 취소 job={job_id}")
        return

    if action == "end":
        total = state["total"]
        got = len(state["chunks"])
        if got != total:
            plugin._logger.warning(f"[FACTOR MQTT] end 수신 but chunk 불일치 {got}/{total}, 조합 중단")
            return

        ordered = [state["chunks"][i] for i in range(total)]
        content = b"".join(ordered)

        expect_md5 = (data.get("md5") or "").lower()
        if expect_md5:
            calc_md5 = hashlib.md5(content).hexdigest()
            if calc_md5 != expect_md5:
                plugin._logger.warning(f"[FACTOR MQTT] MD5 불일치 expect={expect_md5} got={calc_md5}")

        filename = state["filename"]
        # 우선순위: end.target > start.upload_traget > 설정 기본값
        target = (data.get("target") or state.get("upload_target") or "").lower()
        if target not in ("sd", "local_print"):
            target = (plugin._settings.get(["receive_target_default"]) or "local_print").lower()

        try:
            if target == "sd":
                _finalize_job_to_sd(plugin, filename, content)
                plugin._logger.info(f"[FACTOR MQTT] SD 저장 완료 file={filename}")
            else:
                _finalize_job_to_local_and_print(plugin, filename, content)
                plugin._logger.info(f"[FACTOR MQTT] 로컬 저장+인쇄 시작 file={filename}")
        except Exception as e:
            plugin._logger.exception(f"[FACTOR MQTT] 최종 처리 실패: {e}")
            return
        finally:
            plugin._gcode_jobs.pop(job_id, None)
        return

    plugin._logger.warning(f"[FACTOR MQTT] 지원되지 않는 action={action}")


def _finalize_job_to_sd(plugin, filename: str, content: bytes):
    from octoprint.filemanager.destinations import FileDestinations
    import io
    stream = io.BytesIO(content)
    stream.seek(0)
    plugin._file_manager.add_file(FileDestinations.SDCARD, filename, stream, allow_overwrite=True)


def _finalize_job_to_local_and_print(plugin, filename: str, content: bytes):
    from octoprint.filemanager.destinations import FileDestinations
    import io
    stream = io.BytesIO(content)
    stream.seek(0)
    plugin._file_manager.add_file(FileDestinations.LOCAL, filename, stream, allow_overwrite=True)
    plugin._printer.select_file(filename, False, printAfterSelect=True)


