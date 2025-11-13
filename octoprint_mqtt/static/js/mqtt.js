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
        $("#fm-qr-loading").show();
        $("#fm-qr-code").hide();

        // Get setup URL first
        OctoPrint.ajax("GET", "plugin/factor_mqtt/setup-url")
          .done(function(data) {
            if (data && data.success) {
              setupUrl = data.setup_url;
              instanceId = data.instance_id;

              // Update button href
              $("#fm-open-setup").attr("href", setupUrl);

              // Load QR code image
              var qrUrl = "plugin/factor_mqtt/qrcode?" + Date.now();
              var $img = $("#fm-qr-code");

              $img.on("load", function() {
                $("#fm-qr-loading").hide();
                $img.show();
              }).on("error", function() {
                $("#fm-qr-loading").html('<i class="icon-warning-sign"></i><br><span>Failed to load QR code</span>');
              });

              $img.attr("src", qrUrl);
            }
          })
          .fail(function(xhr) {
            console.error("Failed to get setup URL:", xhr);
            $("#fm-qr-loading").html('<i class="icon-warning-sign"></i><br><span>Failed to load setup URL</span>');
          });
      }

      self.onBeforeBinding = function () {
        // Initialize i18n and translations
        FactorMQTT_i18n.init(function() {
          FactorMQTT_i18n.applyTranslations();
          initLanguageSelector();

          // Load QR code
          loadQRCode();

          // Bind events
          $("#fm-refresh-qr").on("click", function() {
            loadQRCode();
          });
        });
      };
    }

    OCTOPRINT_VIEWMODELS.push({
      construct: MqttViewModel,
      dependencies: ["settingsViewModel"],
      elements: ["#settings_plugin_factor_mqtt"]
    });

    // Wizard ViewModel
    function MqttWizardViewModel(parameters) {
      var self = this;
      var t = FactorMQTT_i18n.t;

      var setupUrl = "";
      var instanceId = "";

      // Load QR code for wizard
      function loadWizardQRCode() {
        $("#wizard-qr-loading").show();
        $("#wizard-qr-code").hide();

        OctoPrint.ajax("GET", "plugin/factor_mqtt/setup-url")
          .done(function(data) {
            if (data && data.success) {
              setupUrl = data.setup_url;
              instanceId = data.instance_id;

              $("#wizard-open-setup").attr("href", setupUrl);

              var qrUrl = "plugin/factor_mqtt/qrcode?" + Date.now();
              var $img = $("#wizard-qr-code");

              $img.on("load", function() {
                $("#wizard-qr-loading").hide();
                $img.show();
              }).on("error", function() {
                $("#wizard-qr-loading").html('<i class="icon-warning-sign"></i><br><span>Failed to load QR code</span>');
              });

              $img.attr("src", qrUrl);
            }
          })
          .fail(function(xhr) {
            console.error("Failed to get setup URL:", xhr);
            $("#wizard-qr-loading").html('<i class="icon-warning-sign"></i><br><span>Failed to load setup URL</span>');
          });
      }

      self.onBeforeWizardTabChange = function(next, current) {
        return true;
      };

      self.onBeforeWizardFinish = function() {
        return true;
      };

      self.onWizardFinish = function() {
        // Mark as configured (optional)
      };

      self.onAfterBinding = function() {
        // Initialize i18n for wizard
        FactorMQTT_i18n.init(function() {
          FactorMQTT_i18n.applyTranslations();

          // Initialize language selector for wizard
          var currentLang = FactorMQTT_i18n.getCurrentLanguage();
          $("#wizard-lang-selector .btn").removeClass("active");
          $("#wizard-lang-selector .btn[data-lang='" + currentLang + "']").addClass("active");

          $("#wizard-lang-selector .btn").on("click", function() {
            var lang = $(this).attr("data-lang");
            FactorMQTT_i18n.setLanguage(lang);
            $("#wizard-lang-selector .btn").removeClass("active");
            $(this).addClass("active");
          });

          // Load QR code
          loadWizardQRCode();
        });
      };
    }

    OCTOPRINT_VIEWMODELS.push({
      construct: MqttWizardViewModel,
      elements: ["#wizard_plugin_factor_mqtt"]
    });
});
