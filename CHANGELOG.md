# Changelog

## [0.4.3] - 2026-06-25

- Add `detected_serial` field to `BMCEndpoint` — stores system serial number after each scan
- Display Detected Serial on endpoint detail page

## [0.4.2] - 2026-06-25

- Fix: `detected_vendor` and `detected_protocol` fields were never persisted after BMC scan

## [0.4.1] - 2026-06-25

- Add AMI (American Megatrends) Redfish driver (`AmiRedfishDriver`)
  - Vendor auto-detection via `Vendor: "AMI"` / `Oem.Ami` in ServiceRoot
  - PCIe devices collected from `Chassis/PCIeDevices` (AMI-specific path)
  - SystemInfo filled from `Systems/Self/FruInfo` Board section when standard fields are empty

## [0.4.0] - 2026-06-25

Initial public release.

- Redfish inventory sync (CPU, Memory, Drive, PSU, Fan, PCIe, Firmware)
- IPMI fallback for non-Redfish BMCs
- Vendor auto-detection: Dell iDRAC, HPE iLO, Lenovo XCC, Supermicro
- Module diff preview with per-component selection before apply
- `bmc-synced` tag-based diff management (never touches manually created Modules)
- netbox-secrets integration for credential storage (plaintext fallback)
- Power control: on / off / soft / cycle / reset
- NetBox 4.5 and 4.6 support
