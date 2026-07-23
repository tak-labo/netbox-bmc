from netbox.plugins import PluginMenuButton, PluginMenuItem

menu_items = (
    PluginMenuItem(
        link="plugins:netbox_bmc:bmcendpoint_list",
        link_text="BMC Endpoints",
        permissions=["netbox_bmc.view_bmcendpoint"],
        buttons=(
            PluginMenuButton(
                link="plugins:netbox_bmc:bmcendpoint_add",
                title="Add",
                icon_class="mdi mdi-plus-thick",
                permissions=["netbox_bmc.add_bmcendpoint"],
            ),
        ),
    ),
)
