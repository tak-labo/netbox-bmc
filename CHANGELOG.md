# Changelog

## [Unreleased]

- fix(nav): gate the "BMC Endpoints" menu item and its "Add" button behind
  `netbox_bmc.view_bmcendpoint` / `add_bmcendpoint` permissions — previously both were shown to
  every logged-in user regardless of permissions (the underlying views were already correctly
  permission-checked, so this was a menu-visibility issue, not an access-control gap)
- docs: expand the netbox-secrets service-account setup section in `docs/NETBOX_SECRETS.md`
  with detailed non-Docker/Docker steps (RSA keypair, User Key activation, bind-mounting the
  private key with correct permissions, the 2-layer permission model, and troubleshooting),
  mirroring the level of detail in netbox-pdu-control's `docs/netbox-secrets-setup.md`
- fix(ui): hide Power Control / Identify / Build Modules / Sync buttons on the BMC Endpoint
  detail page from users without `netbox_bmc.change_bmcendpoint` — the template rendered them
  unconditionally, so view-only users saw clickable action buttons that the corresponding views
  (`PowerActionView` / `IdentifyActionView` / `BuildModulesView` / `*SyncActionView`) already
  rejected server-side with "Permission denied." This was menu-visibility only, not an
  access-control gap, same class of issue as the earlier nav-menu fix
- fix(forms): make "Test Connection" on the Add/Edit BMC Endpoint form use the username/password
  actually typed into the form, instead of always resolving credentials through the normal
  priority (netbox-secrets Secret → plaintext fields) — previously, if the target Device already
  had a `bmc-credentials` Secret, Test Connection silently ignored whatever was typed in the
  form and validated against the stored Secret instead, so the result didn't reflect the input
  being tested. The result message now also reports which credential source was actually used
  (`credential=form input (not yet saved)` / `netbox-secrets` / `plaintext field`)
- feat(secrets): add a "Use netbox-secrets" checkbox to the BMC Endpoint Add/Edit form
  (`use_netbox_secrets`, default: on) so each endpoint can opt out of netbox-secrets and always
  use its plaintext username/password fields, even when a `bmc-credentials` Secret exists for
  the Device. The field is hidden entirely when netbox-secrets isn't installed. `get_credential()`
  now checks this flag before attempting Secret resolution, and the detail page's Credentials
  card and Test Connection's `credential=` label reflect it
- fix(forms): only override netbox-secrets with typed form input in Test Connection when
  *both* username and password are filled in — previously, typing only a username while
  leaving the password blank (e.g. correcting a typo on an endpoint whose password is meant
  to keep coming from an existing Secret) silently sent an empty password instead of falling
  back to `get_credential()`'s normal resolution, producing a misleading auth failure
- fix(forms): fold the credential source into the visible error message when Test Connection
  fails (`%(error)s (credential=%(source)s)`), not just the success message — previously a
  failed test never told the user which credential source (netbox-secrets / plaintext field /
  form input) was actually attempted, since the frontend only renders `message`, not the
  separate `credential_source` JSON key
- refactor: extract `BMCEndpoint.build_driver(username, password)` from `get_driver()` so
  `ConnectivityTestView` can reuse the documented driver-construction entry point instead of
  duplicating address extraction + `detect_and_build()` inline; also expose `use_netbox_secrets`
  on the REST API serializer and add the missing `help_text` to migration 0011 (kept in sync
  with the model field, per `makemigrations --check --dry-run`)

## [0.4.28] - 2026-07-19

- fix(ui): stop rendering the Device-page BMC panel for devices with no `BMCEndpoint` —
  `right_page()` unconditionally rendered the panel card even without one, so every Device
  (switches, firewalls, PDUs, etc.) showed an empty "BMC" card with a "No BMC endpoint
  configured" prompt. Guarded it the same way `buttons()` already was (#64)
- refactor(ui): split the Identify On/Off buttons out of the "Power Control" card on the BMC
  Endpoint page into their own "Identify" card — toggling the chassis identify LED isn't a
  power operation (#64)

## [0.4.27] - 2026-07-18

- fix(ipmi): purge stale pyghmi session cache before constructing each `IPMIDriver` to avoid
  a session-reuse crash. pyghmi caches sessions process-wide keyed by
  (bmc, userid, password, port), and since this plugin constructs a new driver per HTTP
  request, the reused session's `logoutexpiry`/`logging` state could desync and crash with
  `TypeError: '<' not supported between instances of 'float' and 'NoneType'` — surfacing as
  Power Status always showing "error" for IPMI-protocol endpoints, permanently until the
  worker process restarted. Verified with 10 consecutive successful calls against a real
  IPMI-capable BMC (previously failed 9/10) (#62)
- fix(drivers): pass `verify=` explicitly on every Redfish/AMT HTTP request instead of relying
  solely on `session.verify` — `requests` silently substitutes `REQUESTS_CA_BUNDLE` /
  `CURL_CA_BUNDLE` from the environment when the per-call `verify` kwarg isn't set explicitly,
  which overrode `verify_ssl=False` and caused Test Connection/BMC access to fail with
  `SSLCertVerificationError` even with "Verify SSL" unchecked, in any environment where one of
  those env vars happens to point at a custom CA bundle (#60)
- fix(forms): wire up the previously-unused `default_verify_ssl` plugin setting as the initial
  value of the `verify_ssl` checkbox when adding a new BMC Endpoint (#61)
- Update copyright year and owner in LICENSE file (#59)

## [0.4.26] - 2026-07-18

- fix(credentials): decrypt the netbox-secrets session-key path via the `SessionKey` model
  instead of `UserKey` — the previous code read the session cookie under the wrong name
  (`session_key` instead of the actual `netbox_secrets_sessionid`) and called
  `UserKey.get_master_key()`, which is RSA-private-key-only and always failed when given a
  session key. This silently fell back to the plaintext username/password fields for every
  UI-triggered action (Build Modules, power control, Identify, Test Connection, etc.), so a
  BMCEndpoint relying purely on netbox-secrets would connect with empty credentials. Verified
  end-to-end against the real netbox-secrets library for both the UI (SessionKey) and
  background-job (service account) decryption paths (#57)
- docs: add `docs/NETBOX_SECRETS.md` setup and verification guide for the netbox-secrets
  integration (#57)

## [0.4.25] - 2026-07-18

- fix(forms): make `password` optional on the BMC Endpoint add/edit form — it was forced
  `required=True`, ignoring the model field's `blank=True`, so users relying entirely on
  netbox-secrets had to type something into an unused field just to pass validation (#55)
- fix(docs): fix Mermaid `erDiagram` syntax in `docs/DESIGN.md` (attribute key must come after
  the type/name, not before) so the BMCEndpoint data model diagram renders on GitHub (#54)

## [0.4.24] - 2026-07-18

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
