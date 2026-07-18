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
        "Id": "eth0",
        "LinkStatus": "LinkUp",
        "DHCPv4": {"DHCPEnabled": False},
        "IPv4Addresses": [{
            "Address": "10.0.0.5", "SubnetMask": "255.255.255.0", "Gateway": "10.0.0.1",
        }],
        "IPv6Addresses": [{"Address": "fe80::1", "PrefixLength": 64}],
        "IPv6DefaultGateway": "fe80::ff",
        "NameServers": ["8.8.8.8", "8.8.4.4"],
        "MACAddress": "aa:bb:cc:dd:ee:ff",
        "HostName": "idrac-host",
        "FQDN": "idrac-host.example.com",
        "VLAN": {"VLANEnable": True, "VLANId": 10},
    }
    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", side_effect=[[mgr], [iface]]):
        ifaces = driver.get_network_config()

    assert len(ifaces) == 1
    net = ifaces[0]
    assert net.name == "eth0"
    assert net.dhcp_enabled is False
    assert net.ipv4_address == "10.0.0.5"
    assert net.ipv4_subnet_mask == "255.255.255.0"
    assert net.ipv4_gateway == "10.0.0.1"
    assert net.ipv6_addresses == ["fe80::1/64"]
    assert net.ipv6_gateway == "fe80::ff"
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
    iface = {"Id": "eth0", "IPv4Addresses": [{}], "VLAN": {}, "DHCPv4": {}}
    netproto = {"HostName": "bmc1", "FQDN": "bmc1.example.com"}
    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", side_effect=[[mgr], [iface]]), \
         patch.object(driver, "_get_optional", return_value=netproto):
        ifaces = driver.get_network_config()

    assert ifaces[0].hostname == "bmc1"
    assert ifaces[0].fqdn == "bmc1.example.com"


def test_redfish_network_config_excludes_usb_interfaces():
    """USB-based management interfaces (e.g. AMI "usb0") aren't physical LAN ports."""
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    mgr = {"EthernetInterfaces": {"@odata.id": "/redfish/v1/Managers/1/EthernetInterfaces"}}
    eth0 = {"Id": "eth0", "IPv4Addresses": [{"Address": "10.0.0.5"}]}
    eth1 = {"Id": "eth1", "IPv4Addresses": []}
    usb0 = {"Id": "usb0", "IPv4Addresses": [{"Address": "169.254.0.17"}]}
    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", side_effect=[[mgr], [eth0, eth1, usb0]]):
        ifaces = driver.get_network_config()

    names = [i.name for i in ifaces]
    assert names == ["eth0", "eth1"]
    assert "usb0" not in names


def test_redfish_network_config_returns_multiple_interfaces():
    driver = make_redfish_driver()
    root = {"Managers": {"@odata.id": "/redfish/v1/Managers"}}
    mgr = {"EthernetInterfaces": {"@odata.id": "/redfish/v1/Managers/1/EthernetInterfaces"}}
    bond0 = {"Id": "bond0", "InterfaceEnabled": False, "LinkStatus": "LinkDown"}
    eth0 = {"Id": "eth0", "LinkStatus": "LinkUp", "IPv4Addresses": [{"Address": "10.0.0.5"}]}
    eth1 = {"Id": "eth1", "LinkStatus": "NoLink"}
    with patch.object(driver, "_get", return_value=root), \
         patch.object(driver, "_collection", side_effect=[[mgr], [bond0, eth0, eth1]]):
        ifaces = driver.get_network_config()

    assert [i.name for i in ifaces] == ["bond0", "eth0", "eth1"]
    assert ifaces[1].ipv4_address == "10.0.0.5"


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
    driver.cmd.get_net6_configuration.return_value = {
        "static_addrs": ["fe80::1/64"], "static_gateway": "fe80::ff",
    }

    ifaces = driver.get_network_config()

    assert len(ifaces) == 1
    net = ifaces[0]
    assert net.dhcp_enabled is False
    assert net.ipv4_address == "192.168.1.50"
    assert net.ipv4_subnet_mask == "255.255.255.0"
    assert net.ipv4_gateway == "192.168.1.1"
    assert net.ipv6_addresses == ["fe80::1/64"]
    assert net.ipv6_gateway == "fe80::ff"
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
    driver.cmd.get_net6_configuration.side_effect = Exception("not supported")

    ifaces = driver.get_network_config()

    assert ifaces[0].dhcp_enabled is True
    assert ifaces[0].vlan_id is None  # 0 normalized to None (no VLAN)
    assert ifaces[0].ipv6_addresses == []


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
    driver.cmd.get_net6_configuration.side_effect = Exception("not supported")

    ifaces = driver.get_network_config()

    assert ifaces[0].hostname == ""
    assert ifaces[0].ipv4_address == "192.168.1.50"
