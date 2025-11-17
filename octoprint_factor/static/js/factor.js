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

      self.onBeforeBinding = function () {
        // Initialize i18n and translations
        FactorMQTT_i18n.init(function() {
          FactorMQTT_i18n.applyTranslations();
          initLanguageSelector();
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
        });
      };
    }

    OCTOPRINT_VIEWMODELS.push({
      construct: MqttWizardViewModel,
      elements: ["#wizard_plugin_factor_mqtt"]
    });
});
