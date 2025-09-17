/* globals OctoPrint, ko, $, API_BASEURL */
$(function () {
    function MqttViewModel(parameters) {
      var self = this;
  
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
  
      self.connectionStatus = ko.observable("연결 확인 중...");
      self.isConnected = ko.observable(false);
      self.onBeforeBinding = function () {
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
  
        self.checkConnectionStatus();
      };
  
      // Settings 저장 직전에 파이썬 설정(observable)으로 되돌려 넣기
      self.onSettingsBeforeSave = function () {
        if (!self.pluginSettings) return;
  
        self.pluginSettings.broker_host(self.brokerHost());
        self.pluginSettings.broker_port(parseInt(self.brokerPort() || 1883, 10));
        self.pluginSettings.broker_username(self.brokerUsername());
        self.pluginSettings.broker_password(self.brokerPassword());
        self.pluginSettings.topic_prefix(self.topicPrefix());
        self.pluginSettings.qos_level(parseInt(self.qosLevel() || 1, 10));
        self.pluginSettings.retain_messages(!!self.retainMessages());
        self.pluginSettings.publish_status(!!self.publishStatus());
        self.pluginSettings.publish_progress(!!self.publishProgress());
         self.pluginSettings.publish_temperature(!!self.publishTemperature());
         self.pluginSettings.publish_gcode(!!self.publishGcode());
         self.pluginSettings.publish_snapshot(!!self.publishSnapshot());
         self.pluginSettings.periodic_interval(parseFloat(self.periodicInterval()) || 1.0);
  
        // 저장 후 플러그인에서 _connect_mqtt 재시도하므로 조금 기다렸다 상태 재확인
        setTimeout(self.checkConnectionStatus, 1000);
      };
  
      // 상태 확인 (GET)
      self.checkConnectionStatus = function () {
        if (!self.loginState.isUser()) {
          self.connectionStatus("로그인이 필요합니다.");
          self.isConnected(false);
          return;
        }
        // OctoPrint.ajax: 세션/CSRF 자동 처리
        OctoPrint.ajax("GET", "plugin/factor_mqtt/status")
          .done(function (r) {
            if (r && r.connected) {
              self.connectionStatus("MQTT 브로커에 연결됨");
              self.isConnected(true);
            } else {
              self.connectionStatus("MQTT 브로커에 연결되지 않음");
              self.isConnected(false);
            }
          })
          .fail(function () {
            self.connectionStatus("연결 상태를 확인할 수 없습니다.");
            self.isConnected(false);
          });
      };
  
      // 연결 테스트 (POST)
      self.testConnection = function () {
        self.connectionStatus("연결 테스트 중...");
  
        var payload = {
          broker_host: self.brokerHost(),
          broker_port: parseInt(self.brokerPort() || 0, 10),
          broker_username: self.brokerUsername(),
          broker_password: self.brokerPassword(),
          publish: true,
          // 서버 쪽에서 topic_prefix 키를 쓰므로 test_topic 지정 안 해도 되지만,
          // 명시적으로 넣고 싶다면 아래처럼:
          test_topic: (self.topicPrefix() || "octoprint") + "/test"
        };
  
        // OctoPrint.postJson: CSRF/세션/헤더 자동
        OctoPrint.postJson("plugin/factor_mqtt/test", payload)
          .done(function (r) {
            if (r && r.success) {
              self.connectionStatus("연결 테스트 성공!");
              self.isConnected(true);
            } else {
              self.connectionStatus("연결 테스트 실패: " + (r && r.error ? r.error : "알 수 없는 오류"));
              self.isConnected(false);
            }
          })
          .fail(function (xhr) {
            var err = "연결 테스트 중 오류 발생";
            try {
              if (xhr && xhr.responseJSON && xhr.responseJSON.error) {
                err += ": " + xhr.responseJSON.error;
              }
            } catch (e) {}
            self.connectionStatus(err);
            self.isConnected(false);
          });
      };
    }
  
    OCTOPRINT_VIEWMODELS.push({
      construct: MqttViewModel,
      dependencies: ["settingsViewModel", "loginStateViewModel"],
      elements: ["#settings_plugin_factor_mqtt"] // settings 템플릿의 root 요소 id와 일치해야 함
    });
  });
  