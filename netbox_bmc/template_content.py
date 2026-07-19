from netbox.plugins import PluginTemplateExtension


class DeviceBMCPanel(PluginTemplateExtension):
    models = ["dcim.device"]

    def _get_bmc_endpoint(self):
        device = self.context["object"]
        try:
            return device.bmc_endpoint
        except Exception:
            return None

    def buttons(self):
        endpoint = self._get_bmc_endpoint()
        if not endpoint:
            return ""
        return self.render(
            "netbox_bmc/inc/device_bmc_button.html",
            extra_context={"bmc_endpoint": endpoint},
        )

    def right_page(self):
        endpoint = self._get_bmc_endpoint()
        if not endpoint:
            return ""
        return self.render(
            "netbox_bmc/inc/device_bmc_panel.html",
            extra_context={"bmc_endpoint": endpoint},
        )


template_extensions = [DeviceBMCPanel]
