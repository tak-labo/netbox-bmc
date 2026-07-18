# Changelog

## [Unreleased]

- Network/Sensors/Event Log/BMC Health are now persisted to the database and refreshed via a
  per-endpoint "Sync" button or an optional scheduled job (`*_sync_interval_minutes`), instead
  of being fetched live on every page load
- BMC Firmware is now refreshed as part of the Inventory scan (`detected_firmware_version`)
  rather than a dedicated job, since it rarely changes; BMC Health keeps its own
  `ManagerHealthSyncJob` since it can change independently
- Rename the ambiguous "Last Sync"/"Status" labels in the Sync Status card to "Inventory Last
  Sync"/"Inventory Scan Status" to disambiguate from the new per-feature sync timestamps
- Add `docs/DESIGN.md` detailed design document with architecture/sequence diagrams
- feat(network): show all BMC network interfaces (incl. IPv6), not just one (#50)
- fix(redfish): send If-Match ETag on Identify LED PATCH requests, fixing `HTTP 428
  Precondition Required` on strict Redfish implementations (#49)
- feat(ui): show "View BMC Endpoint" in the Device page's top button row when a BMC Endpoint
  exists for that Device (#48)
- feat: fetch and display the System Event Log (SEL) (#47)
- feat: fetch and display sensor telemetry (temperature/fan/voltage/power) (#46)
- feat: add Identify LED control (#45)
- feat: fetch and display the BMC's own firmware version and health (#44)
- feat: fetch and display the BMC's own network configuration (#43)
- refactor(ui): move power action buttons into a dedicated Power Control card above Sync
  Status (#42)
- fix(ui): remove Console quick-launch button from BMC Endpoint page (no working KVM launch
  target existed) (#41)
- docs: restore missing Apache-2.0 appendix section in LICENSE (#40)
- feat(ui): add Device Role filter on the BMC Endpoint add form, a pre-save Test Connection
  button, and English/Japanese (i18n) UI support across the plugin; keep `BMCEndpoint.Meta`'s
  `verbose_name` untranslated to avoid a broken Japanese plural (#39)
- feat(ui): add Web GUI and HTML5 console launch buttons (#38)
- fix(ui): fix device BMC panel fields not displaying (#37)

## [0.4.23] - 2026-07-08

- Add "Open Console" button to BMCEndpoint detail page with vendor-specific HTML5 KVM URL (Dell/HPE/Lenovo/Supermicro)
- Add "Web GUI" button to BMCEndpoint detail page
- Show IP and DNS variants of both buttons when `IPAddress.dns_name` is configured

- Add power action buttons (On / Off / Soft / Cycle / Reset) to BMCEndpoint detail page
- IPMI driver: tolerate SDR read errors so FRU 0 serial/model is preserved when SDR parsing fails (ASRockRack / Supermicro)
- AMT driver: populate memory `operating_speed_mhz` and `memory_device_type` in component extra; keep JEDEC manufacturer codes as-is
- AMT driver: write base clock from model name (`@ X.XXGHz`) instead of boost clock (`MaxClockSpeed`)
- Write `Device.serial` and `Device.asset_tag` from BMC scan result

## [0.4.15] - 2026-06-27

- IPMI driver: tolerate SDR read errors so FRU 0 serial/model is preserved when pyghmi SDR parsing fails (ASRockRack / Supermicro)

## [0.4.14] - 2026-06-27

- AMT driver: populate memory `operating_speed_mhz` and `memory_device_type` in component `extra`; module profile now receives `data_rate` and `class`
- AMT driver: remove JEDEC hex manufacturer filter — codes like `86E900000000` are kept as-is
- AMT driver: use base clock from model name (`@ X.XXGHz`) instead of boost/turbo `MaxClockSpeed`
- Write `Device.serial` to NetBox Device on BMC scan
- Write `Device.asset_tag` to NetBox Device on BMC scan (skips "Unknown" and empty values)
- CI: add `skip-existing: true` to PyPI publish workflow

## [0.4.13] - 2026-06-27

- AMT driver: CPU `part_id` and `manufacturer` now supplemented from `hw-proc.htm` when WS-MAN `CIM_Processor` returns empty Name/Manufacturer fields (AMT 12.0 behaviour)
- AMT driver: memory `Tag` falls back to `DeviceLocator` when Tag contains only digits (Asset Tag value); JEDEC hex manufacturer codes are discarded

## [0.4.12] - 2026-06-27

- AMT driver: `_parse_drives_from_html` now sets `part_id` (full model name) and `manufacturer` (first word of model name) on drive components
- Module sync: drive profile now writes `size` (GB) to `attribute_data` alongside `type`

## [0.4.11] - 2026-06-27

- AMT driver: scrape `hw-disk.htm` to retrieve disk Model and Serial Number (not available via WS-MAN in AMT 12.0); falls back to `CIM_MediaAccessDevice` (size-only)
- AMT driver: HTML fallback for system info (`hw-sys.htm`), CPU (`hw-proc.htm`), and memory (`hw-mem.htm`) when WS-MAN returns empty results

## [0.4.10] - 2026-06-27

- Add Firmware to module preview kind filters, default off

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
