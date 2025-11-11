/* globals OctoPrint, ko, $, API_BASEURL, FactorMQTT_i18n */
$(function () {
    // i18n 초기화 및 DOM 업데이트 함수
    function applyTranslations() {
      var t = FactorMQTT_i18n.t;

      // data-i18n 속성으로 텍스트 번역
      $("[data-i18n]").each(function() {
        var key = $(this).attr("data-i18n");
        $(this).text(t(key));
      });

      // data-i18n-html 속성으로 HTML 번역
      $("[data-i18n-html]").each(function() {
        var key = $(this).attr("data-i18n-html");
        $(this).html(t(key));
      });

      // data-i18n-placeholder 속성으로 placeholder 번역
      $("[data-i18n-placeholder]").each(function() {
        var key = $(this).attr("data-i18n-placeholder");
        $(this).attr("placeholder", t(key));
      });
    }

    function MqttViewModel(parameters) {
      var self = this;
    var t = FactorMQTT_i18n.t;
    // [AUTH ADD] 설정: 실제 서버 주소로 교체하세요
    var AUTH_URL = "plugin/factor_mqtt/auth/login";

    // [AUTH ADD] 상태 저장 (서버 세션 기반, sessionStorage는 임시 UI 상태용)
    // 보안: 토큰은 서버 측에만 저장되며, 클라이언트는 세션 쿠키로만 인증
    self.isAuthed = ko.observable(false);
    self.authResp = ko.observable(null);
    // [WIZARD] 단계 및 인스턴스ID
    self.wizardStep = ko.observable(1); // 1: 로그인, 2: 등록, 3: MQTT 설정
    self.instanceId = ko.observable("");

    // [AUTH ADD] 공용 가드: 입력/저장 비활성화
    function setInputsDisabled(disabled) {
      var root = $("#settings_plugin_factor_mqtt");
      if (!root.length) return;
      root.find("input, select, textarea, button")
        .not("#factor-mqtt-auth-overlay *, #factor-mqtt-register-overlay *, #tab-login *, #tab-register *")
        .prop("disabled", !!disabled);
      $("#settings_dialog .modal-footer .btn-primary").prop("disabled", !!disabled);
    }

    // [WIZARD] 로그인 탭 이벤트 바인딩
    self.bindLoginTab = function () {
      // 중복 바인딩 방지
      if ($("#fm-login-btn").data("bound")) return;
      $("#fm-login-btn").data("bound", true);
      $("#fm-login-btn").on("click", function () {
        var email = ($("#fm-login-id").val() || "").trim();
        var pw = $("#fm-login-pw").val() || "";
        if (!email || !pw) { $("#fm-login-status").text(t("ui.login.error")); return; }
        $("#fm-login-status").text(t("ui.login.status"));
        // OctoPrint.postJson: 자동으로 /api/ prefix와 X-Api-Key 헤더 포함
        OctoPrint.postJson(AUTH_URL, { email: email, password: pw })
          .done(function (data) {
            var ok = !!(data && (data.success === true || (!data.error && (data.user || data.session))));
            if (ok) {
              // 보안: 민감정보는 sessionStorage에 저장하지 않음
              // 서버 세션에만 저장하고, UI 상태만 메모리에 유지
              self.authResp(data); self.isAuthed(true);
              self.wizardStep(2);
              self.renderRegisterTab();
              self.updateAuthBarrier();
            } else {
              var msg = (data && data.error && data.error.message) ? data.error.message : "인증 실패";
              $("#fm-login-status").text(msg); self.isAuthed(false);
            }
          })
          .fail(function (xhr) { var m = (xhr && xhr.responseJSON && (xhr.responseJSON.error || xhr.responseJSON.message)) || t("ui.login.failed"); $("#fm-login-status").text(m); self.isAuthed(false); });
      });
    };

    // [AUTH ADD] 오버레이 토글 + 가드 적용
    self.updateAuthBarrier = function () {
      var authed = !!self.isAuthed();
      // 3단계는 웹 이동 화면이므로 특별한 가드 불필요
      setInputsDisabled(!authed);
    };

    // [WIZARD] 2단계: 등록 오버레이
    function genUuid() {
      if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
      return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c){ var r=Math.random()*16|0, v=c==='x'?r:(r&0x3|0x8); return v.toString(16); });
    }

    self.renderRegisterTab = function () {
      var root = $("#settings_plugin_factor_mqtt");
      if (!root.length) return;
      // 바인딩(중복 방지)
      // 초기 Instance ID는 셀렉트 상태에 따라 동적으로 설정합니다.
      if (!$("#fm-register-btn").data("bound")) {
        $("#fm-register-btn").data("bound", true);
        // 토큰 선택 셀렉트 채우기: 현재는 로그인 토큰 1개만 존재하므로, "신규 등록"과 "로그인 토큰 사용" 두 옵션 제공
        var auth = self.authResp() || {}; var token = auth.access_token || auth.accessToken;
        var sel = $("#fm-register-select");
        sel.empty();
        sel.append('<option value="__new__">신규 등록</option>');
        // 기존 등록된 UUID 조회(API)
        // 기존 UUID 목록은 서버 프록시로 안전하게 호출
        if (token) {
          OctoPrint.ajax("GET", "plugin/factor_mqtt/summary", { headers: { "Authorization": "Bearer " + token } })
            .done(function (resp) {
              try {
                var list = (resp && resp.items) || resp || [];
                list.forEach(function (it) {
                  var id = it.device_uuid || it.uuid || it.instance_id || it.id;
                  var name = it.model || it.name || it.label || "Unknown";
                  if (!id) return; // UUID 없으면 제외
                  sel.append('<option value="' + id + '">' + name + ' (' + id + ')</option>');
                });
              } catch (e) {}
            });
        }

        // 셀렉트 변경 시 UI 토글 및 UUID 반영
        sel.off("change").on("change", function () {
          var v = $(this).val();
          var isNew = (v === "__new__");
          $("#fm-instance-id, #fm-instance-gen, #fm-register-btn").toggle(isNew);
          $("#fm-register-next").toggle(!isNew);
          if (isNew) {
            // 신규 등록 선택 시마다 새 UUID 생성
            var newId = genUuid();
            self.instanceId(newId);
            $("#fm-instance-id").val(newId);
          } else if (v && v !== "__token__") {
            // 기존 UUID 선택 시 해당 값 사용
            self.instanceId(v);
            $("#fm-instance-id").val(v);
          }
        });

        // 기본값을 항상 신규로 설정하고 즉시 새 UUID 생성
        sel.val("__new__").trigger("change");

        $("#fm-register-next").on("click", function () {
          // 기존 등록 선택 시 바로 3단계로 이동
          var v = sel.val();
          if (v && v !== "__new__") {
            if (v !== "__token__") self.instanceId(v);
            // 서버에 저장 요청
            try {
              OctoPrint.postJson("plugin/factor_mqtt/device", { device_uuid: self.instanceId() });
            } catch (e) {}
            self.wizardStep(3); self.updateAuthBarrier();
          }
        });
        // 상태 패널 채우기: 서버 status에서 요약 읽기
        OctoPrint.ajax("GET", "plugin/factor_mqtt/status").done(function (r) {
          try {
            var ps = (r && r.printer_summary) || {};
            var c = ps.connection || {}; var prof = (c.profile || {});
            var size = ps.size || {};
            var lines = [];
            var iid = r && r.instance_id;
            if (iid) lines.push("Instance ID: " + iid);
            if (c.state) lines.push("상태: " + c.state);
            if (c.port) lines.push("포트: " + c.port);
            if (c.baudrate) lines.push("속도: " + c.baudrate);
            if (prof.name) lines.push("프로필: " + prof.name);
            if (prof.model) lines.push("모델: " + prof.model);
            if (size.width || size.depth || size.height) {
              lines.push("사이즈: " + [size.width, size.depth, size.height].filter(Boolean).join(" x "));
            }
            var html = lines.map(function (t){ return '<div class="text-info">' + t + '</div>'; }).join("");
            $("#fm-register-conn").html(html || '<div class="text-muted">프린터 연결 정보가 없습니다.</div>');
          } catch (e) {}
        });
        $("#fm-instance-gen").on("click", function () {
          var iid = genUuid(); self.instanceId(iid); $("#fm-instance-id").val(iid);
        });
        $("#fm-register-btn").on("click", function () {
          var iid = ($("#fm-instance-id").val() || "").trim();
          if (!iid) { $("#fm-register-status").text(t("ui.register.error")); return; }
          $("#fm-register-status").text(t("ui.register.status"));

          // Device UUID 저장
          self.instanceId(iid);
          try {
            OctoPrint.postJson("plugin/factor_mqtt/device", { device_uuid: iid });
          } catch (e) {}

          $("#fm-register-status").text(t("ui.register.success"));
          self.wizardStep(3);
          self.updateAuthBarrier();

          // 3단계 웹 이동 버튼 바인딩
          setTimeout(bindWebTab, 100);
        });
      }
    };
  
      self.settingsViewModel = parameters[0];
      self.loginState = parameters[1];
  
      // 화면용 observable들
      self.brokerHost = ko.observable();
      self.brokerPort = ko.observable();
      self.brokerUsername = ko.observable();
      self.brokerPassword = ko.observable();
      self.topicPrefix = ko.observable();
      self.qosLevel = ko.observable();
      self.retainMessages = ko.observable(false);
      self.publishStatus = ko.observable(false);
      self.publishProgress = ko.observable(false);
       self.publishTemperature = ko.observable(false);
       self.publishGcode = ko.observable(false);
       self.publishSnapshot = ko.observable(false);
       self.periodicInterval = ko.observable(1.0);
      // 카메라 URL
      self.cameraStreamUrl = ko.observable("");
  
      self.connectionStatus = ko.observable("연결 확인 중...");
      self.isConnected = ko.observable(false);

      // 로그인/마법사 초기화 유틸 (모달 열릴 때마다 1. 로그인으로 강제)
      function resetWizardToLogin() {
        // 보안: sessionStorage 사용하지 않음
        self.isAuthed(false);
        self.authResp(null);
        self.wizardStep(1);
        self.updateAuthBarrier();
        self.bindLoginTab();
      }
      self.onBeforeBinding = function () {
        // i18n 초기화 및 번역 적용
        FactorMQTT_i18n.init(function() {
          applyTranslations();
        });

        // 모달 재오픈 시 항상 1. 로그인 탭으로 이동
        resetWizardToLogin();
        var s = self.settingsViewModel && self.settingsViewModel.settings;
        if (!s || !s.plugins || !s.plugins.factor_mqtt) {   // ✅ 여기
          console.warn("factor_mqtt settings not ready");
          return;
        }
        self.pluginSettings = s.plugins.factor_mqtt;        // ✅ 여기
  
        // KO observable 읽기 (JS에서는 () 호출)
        self.brokerHost(self.pluginSettings.broker_host());
        self.brokerPort(self.pluginSettings.broker_port());
        self.brokerUsername(self.pluginSettings.broker_username());
        self.brokerPassword(self.pluginSettings.broker_password());
        self.topicPrefix(self.pluginSettings.topic_prefix());
        self.qosLevel(String(self.pluginSettings.qos_level()));
        self.retainMessages(!!self.pluginSettings.retain_messages());
        self.publishStatus(!!self.pluginSettings.publish_status());
        self.publishProgress(!!self.pluginSettings.publish_progress());
         self.publishTemperature(!!self.pluginSettings.publish_temperature());
         self.publishGcode(!!self.pluginSettings.publish_gcode());
         self.publishSnapshot(!!self.pluginSettings.publish_snapshot());
         self.periodicInterval(parseFloat(self.pluginSettings.periodic_interval()) || 1.0);
        // 카메라 URL (observable/문자열 모두 처리)
        try {
          var cam = self.pluginSettings.camera;
          if (cam) {
            var val = (typeof cam.stream_url === "function") ? cam.stream_url() : (cam.stream_url || "");
            self.cameraStreamUrl(val || "");
          }
        } catch (e) {}
  
        // [WIZARD] 탭 클릭: 뒤로는 허용, 앞으로는 금지
        $("#settings_plugin_factor_mqtt .nav-tabs a[data-step]").off("click").on("click", function (e) {
          e.preventDefault();
          var target = parseInt($(this).attr("data-step"), 10) || 1;
          var cur = self.wizardStep();
          if (target <= cur) {
            self.wizardStep(target);
            self.updateAuthBarrier();
            if (target === 2) {
              self.renderRegisterTab();
              setTimeout(bindCameraSection, 0);
            } else if (target === 3) {
              setTimeout(bindWebTab, 0);
            }
          }
        });

        // [WIZARD] 초기 단계 결정 (강제 로그인 탭 유지)
        self.bindLoginTab();
        var authed = !!self.isAuthed();
        // 서버 상태에서 registered/instance_id 참고
        OctoPrint.ajax("GET", "plugin/factor_mqtt/status")
          .done(function (r) {
            var registered = !!(r && r.registered);
            var iid = (r && r.instance_id) || "";
            if (iid) { self.instanceId(iid); }
            if (!authed) {
              self.wizardStep(1);
              self.updateAuthBarrier();
            } else if (!registered) {
              self.wizardStep(2);
              self.renderRegisterTab();
              setTimeout(bindCameraSection, 0);
              self.updateAuthBarrier();
            } else {
              self.wizardStep(3);
              self.updateAuthBarrier();
              setTimeout(bindWebTab, 0);
            }
            self.checkConnectionStatus();
          })
          .fail(function () {
            if (!authed) {
              self.wizardStep(1);
            } else {
              // 상태 실패 시 등록여부는 서버 상태로만 결정
              self.wizardStep(2);
              self.renderRegisterTab();
              setTimeout(bindCameraSection, 0);
            }
            self.updateAuthBarrier();
            self.checkConnectionStatus();
          });

        // settings 모달이 열릴 때마다 로그인 탭으로 리셋
        try {
          $(document).off("shown shown.bs.modal", "#settings_dialog").on("shown shown.bs.modal", "#settings_dialog", function(){
            if ($("#settings_plugin_factor_mqtt").is(":visible")) {
              resetWizardToLogin();
            }
          });
        } catch (e) {}
      };

      // --- 3단계 웹 이동 버튼 바인딩 ---
      function bindWebTab() {
        var $btn = $("#fm-goto-web");
        if (!$btn.length) return;
        if (!$btn.data("bound")) {
          $btn.data("bound", true);
          $btn.off("click").on("click", function() {
            var iid = self.instanceId() || "";
            if (!iid) {
              alert(t("ui.web.error"));
              return;
            }
            var url = "https://factor.io.kr/devices/register?code=" + encodeURIComponent(iid);
            window.open(url, "_blank");
          });
        }
      }

      // --- 카메라 UI 바인딩 (등록 탭) ---
      function bindCameraSection() {
        var $url = $("#fm-camera-url");
        if (!$url.length) return;
        if (!$url.data("inited")) {
          $url.data("inited", true);
          $url.val(self.cameraStreamUrl() || "");
          $("#fm-camera-test").on("click", function(){
            var url = ($url.val() || "").trim();
            if (!url) { $("#fm-camera-status").text(t("ui.camera.status.urlRequired")); return; }
            self.cameraStreamUrl(url);
            var $modal = $("#cameraStreamModal");
            // settings 모달 내부라 중첩 모달 z-index 문제가 있을 수 있어 body로 이동
            try { if (!$modal.parent().is("body")) { $modal.appendTo("body"); } } catch(e) {}
            if (!$modal.data("bound")) {
              $modal.data("bound", true);
              // 명시적으로 닫기 동작 바인딩 (부트스트랩 2/3 호환)
              $modal.on("click", ".close, [data-dismiss='modal']", function(ev){
                ev.preventDefault();
                try { $modal.modal("hide"); } catch(e) { $modal.hide(); }
                return false;
              });
              // 숨김 시 미리보기 해제
              $modal.on("hidden hidden.bs.modal", function(){
                $("#cameraStreamPreview").attr("src", "");
              });
            }
            $("#cameraStreamPreview").attr("src", url);
            $modal.modal({show:true, backdrop:true, keyboard:true});
          });
          $("#fm-camera-save").on("click", function(){
            var url = ($url.val() || "").trim();
            self.cameraStreamUrl(url);
            $("#fm-camera-status").text(t("ui.camera.status.saving"));
            OctoPrint.postJson("plugin/factor_mqtt/camera", { stream_url: url })
              .done(function(){
                $("#fm-camera-status").text(t("ui.camera.status.success"));
                try {
                  var cam = self.pluginSettings && self.pluginSettings.camera;
                  if (cam) {
                    if (typeof cam.stream_url === "function") cam.stream_url(url); else cam.stream_url = url;
                  }
                } catch (e) {}
                // 서버 등록 API에 반영 (토큰/instance_id 자동 전송)
                try {
                  var auth = self.authResp() || {}; var token = auth.access_token || auth.accessToken;
                  var iid = self.instanceId() || (self.pluginSettings && self.pluginSettings.instance_id && self.pluginSettings.instance_id());
                  var body = { instance_id: iid };
                  if (token) body.access_token = token;
                  OctoPrint.postJson("plugin/factor_mqtt/register", body);
                } catch (e) {}
              })
              .fail(function(xhr){
                var msg = (xhr && xhr.responseJSON && (xhr.responseJSON.error || xhr.responseJSON.message)) || ("HTTP " + (xhr && xhr.status));
                $("#fm-camera-status").text(t("ui.camera.status.failed") + ": " + msg);
              });
          });
        }
      }
  
      // Settings 저장 (간소화 버전)
      self.onSettingsBeforeSave = function () {
        // 카메라 URL만 저장
        try {
          if (self.pluginSettings && self.pluginSettings.camera) {
            if (typeof self.pluginSettings.camera.stream_url === "function") {
              self.pluginSettings.camera.stream_url(self.cameraStreamUrl());
            } else {
              self.pluginSettings.camera.stream_url = self.cameraStreamUrl();
            }
          }
        } catch (e) {}
      };
  
      // 상태 확인 제거 (더 이상 MQTT 설정 화면 없음)
      self.checkConnectionStatus = function () {
        // No-op: 3단계는 웹 이동 화면
      };
    }
  
    OCTOPRINT_VIEWMODELS.push({
      construct: MqttViewModel,
      dependencies: ["settingsViewModel", "loginStateViewModel"],
      elements: ["#settings_plugin_factor_mqtt"] // settings 템플릿의 root 요소 id와 일치해야 함
    });
  });
  

