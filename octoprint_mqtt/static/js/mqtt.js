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
  
      self.connectionStatus = ko.observable("연결 확인 중...");
      self.isConnected = ko.observable(false);
  
      self.pluginSettings = null; // 🔸 생성자에선 접근하지 않음
  
      self.onBeforeBinding = function () {
        // 🔸 이 시점에 settings가 준비됨
        var s = self.settingsViewModel && self.settingsViewModel.settings;
        if (!s || !s.plugins || !s.plugins.factor_mqtt) {
          console.warn("factor_mqtt settings not ready");
          return;
        }
        self.pluginSettings = s.plugins.factor_mqtt;
  
        // KO observable 읽기 (JS에서는 () 호출)
        self.brokerHost(        self.pluginSettings.broker_host()        );
        self.brokerPort(        self.pluginSettings.broker_port()        );
        self.brokerUsername(    self.pluginSettings.broker_username()    );
        self.brokerPassword(    self.pluginSettings.broker_password()    );
        self.topicPrefix(       self.pluginSettings.topic_prefix()       );
        self.qosLevel(          String(self.pluginSettings.qos_level())  );
        self.retainMessages(    !!self.pluginSettings.retain_messages()  );
        self.publishStatus(     !!self.pluginSettings.publish_status()   );
        self.publishProgress(   !!self.pluginSettings.publish_progress() );
        self.publishTemperature(!!self.pluginSettings.publish_temperature());
        self.publishGcode(      !!self.pluginSettings.publish_gcode()    );
  
        self.checkConnectionStatus();
      };
  
      self.onSettingsBeforeSave = function () {
        if (!self.pluginSettings) return;
        self.pluginSettings.broker_host(        self.brokerHost() );
        self.pluginSettings.broker_port(        parseInt(self.brokerPort() || 0, 10) );
        self.pluginSettings.broker_username(    self.brokerUsername() );
        self.pluginSettings.broker_password(    self.brokerPassword() );
        self.pluginSettings.topic_prefix(       self.topicPrefix() );
        self.pluginSettings.qos_level(          parseInt(self.qosLevel() || 0, 10) );
        self.pluginSettings.retain_messages(    !!self.retainMessages() );
        self.pluginSettings.publish_status(     !!self.publishStatus() );
        self.pluginSettings.publish_progress(   !!self.publishProgress() );
        self.pluginSettings.publish_temperature(!!self.publishTemperature() );
        self.pluginSettings.publish_gcode(      !!self.publishGcode() );
  
        setTimeout(self.checkConnectionStatus, 1000);
      };
  
      self.checkConnectionStatus = function () {
        if (!self.loginState.isUser()) {
          self.connectionStatus("로그인이 필요합니다.");
          self.isConnected(false);
          return;
        }
        $.ajax({
          url: API_BASEURL + "plugin/factor_mqtt/status", // 🔸 식별자 반영
          type: "GET",
          dataType: "json",
          success: function (r) {
            if (r && r.connected) {
              self.connectionStatus("MQTT 브로커에 연결됨");
              self.isConnected(true);
            } else {
              self.connectionStatus("MQTT 브로커에 연결되지 않음");
              self.isConnected(false);
            }
          },
          error: function () {
            self.connectionStatus("연결 상태를 확인할 수 없습니다.");
            self.isConnected(false);
          }
        });
      };
  
      self.testConnection = function () {
        self.connectionStatus("연결 테스트 중...");
        $.ajax({
          url: API_BASEURL + "plugin/factor_mqtt/test", // 🔸 식별자 반영
          type: "POST",
          dataType: "json",
          data: JSON.stringify({
            broker_host:     self.brokerHost(),
            broker_port:     parseInt(self.brokerPort() || 0, 10),
            broker_username: self.brokerUsername(),
            broker_password: self.brokerPassword()
          }),
          contentType: "application/json",
          success: function (r) {
            if (r && r.success) {
              self.connectionStatus("연결 테스트 성공!");
              self.isConnected(true);
            } else {
              self.connectionStatus("연결 테스트 실패: " + (r && r.error ? r.error : "알 수 없는 오류"));
              self.isConnected(false);
            }
          },
          error: function (xhr) {
            var err = "연결 테스트 중 오류 발생";
            if (xhr.responseJSON && xhr.responseJSON.error) err += ": " + xhr.responseJSON.error;
            self.connectionStatus(err);
            self.isConnected(false);
          }
        });
      };
    }
  
    OCTOPRINT_VIEWMODELS.push({
      construct: MqttViewModel,
      dependencies: ["settingsViewModel", "loginStateViewModel"],
      elements: ["#settings_plugin_factor_mqtt"] // 🔸 HTML id와 일치
    });
  });
  