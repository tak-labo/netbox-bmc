from netbox.plugins import PluginTemplateExtension


class DeviceBMCPanel(PluginTemplateExtension):
    models = ["dcim.device"]

    def right_page(self):
        device = self.context["object"]
        try:
            endpoint = device.bmc_endpoint
        except Exception:
            endpoint = None
        return self.render(
            "netbox_bmc/inc/device_bmc_panel.html",
            extra_context={"bmc_endpoint": endpoint},
        )


template_extensions = [DeviceBMCPanel]
