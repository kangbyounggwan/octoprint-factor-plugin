/* globals OctoPrint, ko, $, FactorMQTT_i18n */
$(function () {
    // Language selector initialization
    function initLanguageSelector() {
      var currentLang = FactorMQTT_i18n.getCurrentLanguage();

      // Set active state
      $("#fm-lang-selector .btn").removeClass("active");
      $("#fm-lang-selector .btn[data-lang='" + currentLang + "']").addClass("active");

      // Button click event
      $("#fm-lang-selector .btn").off("click").on("click", function() {
        var lang = $(this).attr("data-lang");
        FactorMQTT_i18n.setLanguage(lang);

        // Update UI
        $("#fm-lang-selector .btn").removeClass("active");
        $(this).addClass("active");
      });
    }

    function MqttViewModel(parameters) {
      var self = this;
      var t = FactorMQTT_i18n.t;

      self.settingsViewModel = parameters[0];

      var setupUrl = "";
      var instanceId = "";

      // Load QR code
      function loadQRCode() {
        $("#fm-qr-loading").removeClass("hidden");
        $("#fm-qr-code").removeClass("loaded");

        // Get setup URL first
        OctoPrint.ajax("GET", "plugin/factor_mqtt/setup-url")
          .done(function(data) {
            if (data && data.success) {
              setupUrl = data.setup_url;
              instanceId = data.instance_id;

              // Update UI
              $("#fm-instance-display").text(instanceId);
              $("#fm-setup-url").val(setupUrl);
              $("#fm-open-setup").attr("href", setupUrl);

              // Load QR code image
              var qrUrl = "plugin/factor_mqtt/qrcode?" + Date.now();
              $("#fm-qr-code").attr("src", qrUrl).on("load", function() {
                $("#fm-qr-loading").addClass("hidden");
                $(this).addClass("loaded");
              });

              // Update status
              checkStatus();
            }
          })
          .fail(function() {
            $("#fm-qr-loading").text("Failed to load QR code");
          });
      }

      // Check connection status
      function checkStatus() {
        OctoPrint.ajax("GET", "plugin/factor_mqtt/status")
          .done(function(data) {
            if (data) {
              // Registered status
              var registered = data.registered || false;
              var $regStatus = $("#fm-status-registered");
              if (registered) {
                $regStatus.html('<i class="icon-ok"></i> <span data-i18n="setup.status.yes">' + t("setup.status.yes") + '</span>')
                  .removeClass("error").addClass("success");
              } else {
                $regStatus.html('<i class="icon-remove"></i> <span data-i18n="setup.status.no">' + t("setup.status.no") + '</span>')
                  .removeClass("success").addClass("error");
              }

              // MQTT status
              var mqttConnected = data.is_mqtt_connected || false;
              var $mqttStatus = $("#fm-status-mqtt");
              if (mqttConnected) {
                $mqttStatus.html('<i class="icon-ok"></i> <span data-i18n="setup.status.connected">' + t("setup.status.connected") + '</span>')
                  .removeClass("error").addClass("success");
              } else {
                $mqttStatus.html('<i class="icon-remove"></i> <span data-i18n="setup.status.disconnected">' + t("setup.status.disconnected") + '</span>')
                  .removeClass("success").addClass("error");
              }
            }
          });
      }

      // Copy URL to clipboard
      function copyToClipboard(text) {
        var $temp = $("<input>");
        $("body").append($temp);
        $temp.val(text).select();
        document.execCommand("copy");
        $temp.remove();

        // Show feedback
        var $btn = $("#fm-copy-url");
        var originalHtml = $btn.html();
        $btn.html('<i class="icon-ok"></i>').prop("disabled", true);
        setTimeout(function() {
          $btn.html(originalHtml).prop("disabled", false);
        }, 1500);
      }

      self.onBeforeBinding = function () {
        // Initialize i18n and translations
        FactorMQTT_i18n.init(function() {
          FactorMQTT_i18n.applyTranslations();
          initLanguageSelector();

          // Load QR code
          loadQRCode();

          // Bind events
          $("#fm-copy-url").on("click", function() {
            copyToClipboard(setupUrl);
          });

          $("#fm-refresh-qr").on("click", function() {
            loadQRCode();
          });

          // Auto-refresh status every 10 seconds
          setInterval(checkStatus, 10000);
        });
      };
    }

    OCTOPRINT_VIEWMODELS.push({
      construct: MqttViewModel,
      dependencies: ["settingsViewModel"],
      elements: ["#settings_plugin_factor_mqtt"]
    });
});
