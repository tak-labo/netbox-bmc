# Changelog

## [0.4.9] - 2026-06-27

- Fix: AMT driver no longer probes HTTPS:16993 on init when port is unset — defaults to HTTP:16992 immediately, eliminating the 5s timeout delay
- Fix: `probe_amt()` now tries HTTP:16992 before HTTPS:16993 (more common deployment)
- Fix: `_probe_url()` treated HTTP 401 as failure when response body lacked "wsman" text — 401 from `/wsman` is now accepted unconditionally as proof of WS-MAN presence (was causing 105s scan time via fallback to HTTPS:16993)

## [0.4.8] - 2026-06-27

- AMT driver: `_collect_system()` now reads serial/model/manufacturer from `CIM_Chassis` (was `CIM_ComputerSystemPackage` which returns empty on AMT 12.0)
- AMT driver: add `_collect_drives()` via `CIM_MediaAccessDevice` (size only; model/serial not exposed by WS-MAN in AMT 12.0)
- AMT driver: add `_collect_fans()` via `CIM_Fan`
- AMT driver: add `_collect_bios()` via `CIM_BIOSElement` (BIOS firmware version)

## [0.4.7] - 2026-06-27

- Fix: module sync errors (Skipped entries) now shown as warning messages in UI

## [0.4.6] - 2026-06-27

- Add HTTP (port 16992) support for Intel AMT — auto-detects HTTPS:16993 then HTTP:16992
- Add WS-MAN to Protocol choices for explicit selection on BMCEndpoint
- Fix memory speed: fall back to ConfiguredMemoryClockSpeed when Speed=0

## [0.4.5] - 2026-06-27

- Fix: `__version__` is now read from package metadata (`importlib.metadata`) instead of a hardcoded string — prevents version mismatch when only `pyproject.toml` is updated

## [0.4.4] - 2026-06-26

- Add Intel AMT (Active Management Technology) support via WS-MAN (SOAP/XML over HTTPS port 16993)
  - `IntelAmtDriver`: CPU via `CIM_Processor`, Memory via `CIM_PhysicalMemory`, AMT firmware version via WS-MAN Identity
  - Power control: on / off / soft / cycle / reset via `CIM_PowerManagementService`
  - Auto-detection: `detect_and_build()` probes port 16993 after Redfish fails (before IPMI fallback)
  - `protocol = "wsman"` forces AMT driver on `BMCEndpoint`
- `probe_redfish()` now accepts optional `port` argument for non-standard Redfish ports
- Fix IPMI driver `Board *` field fallback for ASRockRack and similar boards (included in 0.4.4)

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
