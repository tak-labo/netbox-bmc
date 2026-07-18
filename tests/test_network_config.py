"""Tests for BMC-self network configuration (get_network_config())."""
from unittest.mock import MagicMock, patch

from netbox_bmc.drivers.ipmi import IPMIDriver
from netbox_bmc.drivers.redfish import RedfishDriver

# --- Redfish -----------------------------------------------------------

def make_redfish_driver():
    with patch.object(RedfishDriver, "_login"):
        return RedfishDriver("bmc.example.com", "admin", "pass")


def test_redfish_network_config_from_ethernet_interface():
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    mgr = {"EthernetInterfaces": {"@odata.id": "/redfish/v1/Managers/1/EthernetInterfaces"}}
    iface = {
        "LinkStatus": "LinkUp",
        "DHCPv4": {"DHCPEnabled": False},
        "IPv4Addresses": [{
            "Address": "10.0.0.5", "SubnetMask": "255.255.255.0", "Gateway": "10.0.0.1",
        }],
        "NameServers": ["8.8.8.8", "8.8.4.4"],
        "MACAddress": "aa:bb:cc:dd:ee:ff",
        "HostName": "idrac-host",
        "FQDN": "idrac-host.example.com",
        "VLAN": {"VLANEnable": True, "VLANId": 10},
    }
    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", side_effect=[[mgr], [iface]]):
        net = driver.get_network_config()

    assert net.dhcp_enabled is False
    assert net.ipv4_address == "10.0.0.5"
    assert net.ipv4_subnet_mask == "255.255.255.0"
    assert net.ipv4_gateway == "10.0.0.1"
    assert net.dns_servers == ["8.8.8.8", "8.8.4.4"]
    assert net.mac_address == "AA:BB:CC:DD:EE:FF"
    assert net.hostname == "idrac-host"
    assert net.fqdn == "idrac-host.example.com"
    assert net.vlan_id == 10
    assert net.vlan_enabled is True
    assert net.link_status == "LinkUp"


def test_redfish_network_config_hostname_fallback_to_networkprotocol():
    """When the EthernetInterface omits HostName/FQDN, fall back to NetworkProtocol."""
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    mgr = {
        "EthernetInterfaces": {"@odata.id": "/redfish/v1/Managers/1/EthernetInterfaces"},
        "NetworkProtocol": {"@odata.id": "/redfish/v1/Managers/1/NetworkProtocol"},
    }
    iface = {"IPv4Addresses": [{}], "VLAN": {}, "DHCPv4": {}}
    netproto = {"HostName": "bmc1", "FQDN": "bmc1.example.com"}
    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", side_effect=[[mgr], [iface]]), \
         patch.object(driver, "_get_optional", return_value=netproto):
        net = driver.get_network_config()

    assert net.hostname == "bmc1"
    assert net.fqdn == "bmc1.example.com"


# --- IPMI ----------------------------------------------------------------

def make_ipmi_driver():
    with patch("pyghmi.ipmi.command.Command", return_value=MagicMock()):
        return IPMIDriver("192.168.0.1", "admin", "admin")


def test_ipmi_network_config_static():
    driver = make_ipmi_driver()
    driver.cmd.get_network_channel.return_value = 1
    driver.cmd.get_net_configuration.return_value = {
        "ipv4_address": "192.168.1.50/24",
        "ipv4_configuration": "Static",
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "ipv4_gateway": "192.168.1.1",
        "vlan_id": 100,
    }
    driver.cmd.get_hostname.return_value = "bmc-host"

    net = driver.get_network_config()

    assert net.dhcp_enabled is False
    assert net.ipv4_address == "192.168.1.50"
    assert net.ipv4_subnet_mask == "255.255.255.0"
    assert net.ipv4_gateway == "192.168.1.1"
    assert net.mac_address == "AA:BB:CC:DD:EE:FF"
    assert net.hostname == "bmc-host"
    assert net.vlan_id == 100


def test_ipmi_network_config_dhcp():
    driver = make_ipmi_driver()
    driver.cmd.get_network_channel.return_value = 1
    driver.cmd.get_net_configuration.return_value = {
        "ipv4_address": "192.168.1.60/24",
        "ipv4_configuration": "DHCP",
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "ipv4_gateway": "192.168.1.1",
        "vlan_id": 0,
    }
    driver.cmd.get_hostname.return_value = "bmc-host"

    net = driver.get_network_config()

    assert net.dhcp_enabled is True
    assert net.vlan_id is None  # 0 normalized to None (no VLAN)


def test_ipmi_network_config_hostname_failure_is_best_effort():
    """get_hostname() may raise on OEM-unsupported BMCs; hostname stays empty."""
    driver = make_ipmi_driver()
    driver.cmd.get_network_channel.return_value = 1
    driver.cmd.get_net_configuration.return_value = {
        "ipv4_address": "192.168.1.50/24",
        "ipv4_configuration": "Static",
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "ipv4_gateway": "192.168.1.1",
        "vlan_id": None,
    }
    driver.cmd.get_hostname.side_effect = Exception("unsupported")

    net = driver.get_network_config()

    assert net.hostname == ""
    assert net.ipv4_address == "192.168.1.50"
