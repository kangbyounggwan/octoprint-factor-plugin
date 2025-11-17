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

      // Load setup URL with instance ID
      function loadSetupUrl() {
        OctoPrint.ajax("GET", "plugin/factor_mqtt/setup-url")
          .done(function(data) {
            if (data && data.success) {
              setupUrl = data.setup_url;
              instanceId = data.instance_id;

              // Update button href with instance ID
              $("#fm-open-setup").attr("href", setupUrl);

              console.log("Setup URL loaded:", setupUrl);
            }
          })
          .fail(function(xhr) {
            console.error("Failed to get setup URL:", xhr);
          });
      }

      self.onBeforeBinding = function () {
        // Initialize i18n and translations
        FactorMQTT_i18n.init(function() {
          FactorMQTT_i18n.applyTranslations();
          initLanguageSelector();

          // Load setup URL to get instance ID
          loadSetupUrl();

          // Bind "Open Setup Page" button click
          $("#fm-open-setup").on("click", function() {
            // Call start-setup API to subscribe to MQTT topics
            OctoPrint.ajax("POST", "plugin/factor_mqtt/start-setup")
              .done(function() {
                console.log("Started setup - subscribed to registration topic");
              })
              .fail(function(xhr) {
                console.error("Failed to start setup:", xhr);
              });
            // Continue with opening the URL (don't prevent default)
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

      // Load setup URL with instance ID for wizard
      function loadWizardSetupUrl() {
        OctoPrint.ajax("GET", "plugin/factor_mqtt/setup-url")
          .done(function(data) {
            if (data && data.success) {
              setupUrl = data.setup_url;
              instanceId = data.instance_id;

              // Update wizard button href with instance ID
              $("#wizard-open-setup").attr("href", setupUrl);

              console.log("Wizard setup URL loaded:", setupUrl);
            }
          })
          .fail(function(xhr) {
            console.error("Failed to get wizard setup URL:", xhr);
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

          // Load setup URL to get instance ID
          loadWizardSetupUrl();
        });
      };
    }

    OCTOPRINT_VIEWMODELS.push({
      construct: MqttWizardViewModel,
      elements: ["#wizard_plugin_factor_mqtt"]
    });
});
