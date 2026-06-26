# netbox-bmc

[![NetBox](https://img.shields.io/badge/NetBox-4.5%20|%204.6-blue)](https://github.com/netbox-community/netbox)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)

[日本語](README_ja.md)

Unified out-of-band management plugin for NetBox.  
Inventory sync and power control via Redfish & IPMI.

## Supported Protocols / Vendors

| Protocol | Vendors |
|---|---|
| Redfish | Dell iDRAC, HPE iLO, Lenovo XCC, Supermicro, AMI, Generic |
| WS-MAN | Intel AMT (vPro) |
| IPMI | Fallback for any IPMI-capable BMC |

Protocol is auto-detected: probes `/redfish/v1` first, then WS-MAN port 16993 (Intel AMT), falls back to IPMI.

## Tested Hardware

| Manufacturer | Model Series | BMC | Protocol | Status |
|---|---|---|---|---|
| Dell | PowerEdge | iDRAC 9 | Redfish | Expected to work |
| HPE | ProLiant | iLO 5 | Redfish | Expected to work |
| HPE | ProLiant | iLO 6 | Redfish | Expected to work |
| Lenovo | ThinkSystem | XCC2 / XCC3 | Redfish | Expected to work |
| Supermicro | X12 / X13 | BMC | Redfish | Expected to work |
| AMI | ASMB-based servers | AMI Redfish Server | Redfish | Expected to work |
| Intel | vPro-enabled desktops/workstations | AMT 6.0+ | WS-MAN | Expected to work |
| Generic | — | Any IPMI-capable BMC | IPMI | Expected to work (fallback) |

## Features

- **Module Builder**: Sync BMC hardware inventory to NetBox Modules
  - Scan via Redfish → preview detected components with diff badges (new / updated / unchanged / removed)
  - Select individual components before applying
  - Auto-create ModuleBays when missing (warned in preview)
  - Detect serial number changes after FRU replacement and apply diff updates
  - Only manages `bmc-synced`-tagged Modules; never touches manually created Modules
- **Collected components**: CPU, Memory, Drive, PSU, Fan, Firmware, PCI devices
  - PSU and Fan collected via Chassis link; PCIe via PCIeDevices collection
- **Vendor auto-detection**: Dispatches to Dell / HPE / Lenovo subclass drivers based on ServiceRoot `Vendor` / `Oem` keys
- **Power control**: on / off / soft / cycle / reset (both protocols)

## Install

### Standard (non-Docker)

```bash
pip install netbox-bmc
python manage.py migrate
```

Add to `configuration.py`:

```python
PLUGINS = ["netbox_bmc"]
PLUGINS_CONFIG = {
    "netbox_bmc": {
        "sync_interval_minutes": 0,
        "default_verify_ssl": False,
    },
}
```

### Docker (netbox-docker)

Follow the [official plugin installation guide](https://github.com/netbox-community/netbox-docker/wiki/Using-Netbox-Plugins).

**`plugin_requirements.txt`**
```
netbox-bmc
```

**`Dockerfile-Plugins`**
```dockerfile
FROM netboxcommunity/netbox:latest

COPY ./plugin_requirements.txt /opt/netbox/
RUN /usr/local/bin/uv pip install -r /opt/netbox/plugin_requirements.txt
```

**`docker-compose.override.yml`**
```yaml
services:
  netbox:
    image: netbox:latest-plugins
    pull_policy: never
    build:
      context: .
      dockerfile: Dockerfile-Plugins
  netbox-worker:
    image: netbox:latest-plugins
    pull_policy: never
```

**`configuration/plugins.py`**
```python
PLUGINS = ["netbox_bmc"]
PLUGINS_CONFIG = {
    "netbox_bmc": {
        "sync_interval_minutes": 0,
        "default_verify_ssl": False,
    },
}
```

Build and start:
```bash
docker compose build --no-cache
docker compose up -d
```

## Configure

Edit `PLUGINS_CONFIG["netbox_bmc"]` in `configuration.py`:

| Key | Default | Description |
|---|---|---|
| `sync_interval_minutes` | `0` | Scheduled bulk sync interval in minutes. `0` disables. |
| `default_verify_ssl` | `False` | Default SSL verification for new BMC Endpoints. |
| `service_account` | — | Service account name for background jobs (netbox-secrets). |
| `service_private_key_path` | — | Path to private key for service account (netbox-secrets). |

## Use

1. Open a Device in NetBox and click **BMC Endpoints** → **Add**
2. Enter the BMC address and credentials, then save
3. On the Endpoint detail page, click **[Build Modules]**
4. Review the component preview (new / updated / unchanged / removed)
5. Check the components to sync and click **[Apply Selected]**

ModuleBays, ModuleTypes, and Modules are created or updated automatically.

### Module Naming

Vendor-specific names are normalized to a consistent format:

| Raw name (Redfish) | Normalized |
|---|---|
| `CPU.Socket.1` / `Processor 0` | `CPU 0` |
| `DIMM.A1` / `Memory 0` | `Memory 0` |
| `Disk.Bay.0` | `Drive 0` |
| `NIC.Slot.1` (PCIe) | `PCI 0` |

### Custom Fields

The following custom fields are set automatically on each Module:

| Field | Content |
|---|---|
| `bmc_redfish_path` | Source Redfish URI |
| `bmc_firmware_version` | Firmware version string |

## Versions

| netbox-bmc | NetBox |
|---|---|
| 0.4.x | 4.5, 4.6 |

## Vendor Notes

### Dell iDRAC

iDRAC 9 (Redfish 1.x) is the primary target. URI traversal starts from `ServiceRoot` links — no hardcoded paths — so firmware variations should be absorbed automatically.

### HPE iLO

iLO 5 and iLO 6 are supported via the HPE subclass driver. iLO 4 (Redfish 1.0 partial compliance) is **not tested** and may not work correctly.

### Lenovo XCC

XCC2 and XCC3 are supported. Some older XCC firmware versions expose non-standard collection URIs; the link-traversal approach handles most variations.

### Supermicro

Generic Redfish driver is used. Supermicro BMC firmware varies significantly; behaviour may differ across firmware versions.

### AMI (American Megatrends)

AMI Redfish Server (detected via `Vendor: "AMI"` in ServiceRoot). PCIe devices are exposed under `Chassis/PCIeDevices` rather than `Systems/PCIeDevices`; the AMI subclass driver handles this automatically. Hardware inventory (CPU, Memory) populates only when the host is powered on.

### Intel AMT (Active Management Technology)

Intel AMT is built into vPro-enabled CPUs (6th gen+). Accessed via WS-MAN (SOAP/XML over HTTPS on port 16993) with HTTP Digest authentication.

Auto-detection: if Redfish is unavailable, `detect_and_build()` probes port 16993 with a WS-MAN `Identify` request. If AMT responds, `IntelAmtDriver` is selected; otherwise falls back to IPMI.

To force AMT: set `protocol = "wsman"` on the `BMCEndpoint`.

Collected: CPU (CIM_Processor), Memory (CIM_PhysicalMemory), AMT firmware version (WS-MAN Identity). Storage and PCIe are not available via AMT WS-MAN.

AMT must be provisioned and the management port must be reachable (not firewalled). AMT 5.x and below are not tested.

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Run tests
uv run pytest
```

### Adding a New Vendor

1. Add a subclass in `netbox_bmc/drivers/redfish.py` extending `RedfishDriver`
2. Register it in `detect_and_build()` in `netbox_bmc/drivers/base.py` by matching `ServiceRoot` vendor keys
3. Add unit tests in `tests/test_redfish_extensions.py`

### Adding a New Protocol

Implement `BaseDriver` (`netbox_bmc/drivers/base.py`) and return `InventoryResult` from `get_inventory()`.

## Credentials

netbox-bmc resolves BMC credentials in the following order:

1. **netbox-secrets** (preferred) — `Secret` with role `bmc-credentials` assigned to the Device.  
   `Secret.name` = BMC username, `Secret.plaintext` = BMC password (RSA-encrypted).
2. **Plaintext fallback** — `username` / `password` fields on `BMCEndpoint`, used when netbox-secrets is not installed or no matching secret is found.

For background jobs (scheduled sync), set `service_account` and `service_private_key_path` in `PLUGINS_CONFIG` so the job can decrypt secrets without an HTTP session.

## Known Limitations

- REST API (serializers / viewsets) not yet implemented
- Multi-node chassis (multiple `Systems`) not supported
- Scheduled bulk sync (`ScheduledInventorySyncJob`) not yet implemented
- KVM / SOL console not yet ported from the predecessor plugin
- Old BMCs with low Redfish compliance (e.g. HPE iLO 4) not validated

## License

Apache License 2.0 — see [LICENSE](LICENSE).
