
from dataclasses import asdict

from dcim.models import Device
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from ipam.models import IPAddress
from netbox.views import generic

from . import forms, tables
from .models import BMCEndpoint, Protocol


class BMCEndpointListView(generic.ObjectListView):
    queryset = BMCEndpoint.objects.all()
    table = tables.BMCEndpointTable
    template_name = "netbox_bmc/bmcendpoint_list.html"


class BMCEndpointView(generic.ObjectView):
    queryset = BMCEndpoint.objects.all()

    def get_extra_context(self, request, instance):
        secrets_available = False
        secret_found = False
        try:
            from dcim.models import Device
            from django.contrib.contenttypes.models import ContentType
            from netbox_secrets.models import Secret
            secrets_available = True
            device_ct = ContentType.objects.get_for_model(Device)
            secret_found = Secret.objects.filter(
                role__slug="bmc-credentials",
                assigned_object_type=device_ct,
                assigned_object_id=instance.device.pk,
            ).exists()
        except ImportError:
            pass
        return {
            "secrets_available": secrets_available,
            "secret_found": secret_found,
        }


class BMCEndpointEditView(generic.ObjectEditView):
    queryset = BMCEndpoint.objects.all()
    form = forms.BMCEndpointForm
    template_name = "netbox_bmc/bmcendpoint_edit.html"


class BMCEndpointDeleteView(generic.ObjectDeleteView):
    queryset = BMCEndpoint.objects.all()


class BuildModulesView(View):
    """POST: BMC スキャン → session 保存 → preview へリダイレクト。"""

    def post(self, request, pk):
        endpoint = get_object_or_404(BMCEndpoint, pk=pk)
        if not request.user.has_perm("netbox_bmc.change_bmcendpoint"):
            messages.error(request, _("Permission denied."))
            return redirect(endpoint.get_absolute_url())

        try:
            with endpoint.get_driver(request=request) as driver:
                result = driver.get_inventory()
        except Exception as e:
            endpoint.last_sync = timezone.now()
            endpoint.last_sync_status = f"Error: {e}"[:255]
            endpoint.save(update_fields=["last_sync", "last_sync_status"])
            messages.error(request, _("BMC scan failed: %(error)s") % {"error": e})
            return redirect(endpoint.get_absolute_url())

        from .module_sync import compute_diff, entry_to_dict
        from .normalizer import normalize

        serial = result.system.serial
        endpoint.detected_vendor = result.vendor
        endpoint.detected_protocol = result.protocol
        endpoint.detected_serial = (serial or "")[:255]
        endpoint.last_sync = timezone.now()
        endpoint.last_sync_status = "OK"
        endpoint.save(update_fields=[
            "detected_vendor", "detected_protocol", "detected_serial",
            "last_sync", "last_sync_status",
        ])

        asset_tag = result.system.asset_tag
        device_fields = []
        if serial and endpoint.device.serial != serial:
            endpoint.device.serial = serial
            device_fields.append("serial")
        if asset_tag and endpoint.device.asset_tag != asset_tag:
            endpoint.device.asset_tag = asset_tag
            device_fields.append("asset_tag")
        if device_fields:
            endpoint.device.save(update_fields=device_fields)

        firmware = {
            c.name: c.firmware
            for c in result.components
            if c.kind == "firmware"
        }
        ncs = normalize(result.components)
        entries = compute_diff(endpoint.device, ncs)

        session_key = f"bmc_module_preview_{pk}"
        request.session[session_key] = {
            "entries": [entry_to_dict(e) for e in entries],
            "firmware": firmware,
            "vendor": result.vendor,
            "protocol": result.protocol,
        }
        return redirect(
            reverse("plugins:netbox_bmc:bmcendpoint_build_modules_preview", args=[pk])
        )


class BuildModulesPreviewView(View):
    """GET: プレビューページ表示。"""

    def get(self, request, pk):
        endpoint = get_object_or_404(BMCEndpoint, pk=pk)
        if not request.user.has_perm("netbox_bmc.view_bmcendpoint"):
            messages.error(request, _("Permission denied."))
            return redirect(endpoint.get_absolute_url())

        session_key = f"bmc_module_preview_{pk}"
        session_data = request.session.get(session_key)
        if not session_data:
            messages.warning(request, _("No scan data found. Please run a scan first."))
            return redirect(endpoint.get_absolute_url())

        # (kind, label, default_checked)
        KIND_FILTERS = [
            ("cpu",      _("CPU"),      True),
            ("memory",   _("Memory"),   True),
            ("drive",    _("Drive"),    True),
            ("psu",      _("PSU"),      True),
            ("fan",      _("Fan"),      False),
            ("pci",      _("PCI"),      False),
            ("firmware", _("Firmware"), False),
        ]
        unchecked_kinds = {k for k, _label, checked in KIND_FILTERS if not checked}

        return render(request, "netbox_bmc/module_preview.html", {
            "object": endpoint,
            "entries": session_data["entries"],
            "vendor": session_data.get("vendor", ""),
            "protocol": session_data.get("protocol", ""),
            "apply_url": reverse(
                "plugins:netbox_bmc:bmcendpoint_build_modules_apply", args=[pk]
            ),
            "scan_url": reverse(
                "plugins:netbox_bmc:bmcendpoint_build_modules", args=[pk]
            ),
            "kind_filters": KIND_FILTERS,
            "unchecked_kinds": unchecked_kinds,
        })


class BuildModulesApplyView(View):
    """POST: 選択されたエントリを Module として適用。"""

    def post(self, request, pk):
        endpoint = get_object_or_404(BMCEndpoint, pk=pk)
        if not request.user.has_perm("netbox_bmc.change_bmcendpoint"):
            messages.error(request, _("Permission denied."))
            return redirect(endpoint.get_absolute_url())

        session_key = f"bmc_module_preview_{pk}"
        session_data = request.session.get(session_key)
        if not session_data:
            messages.error(request, _("Session expired. Please run a scan again."))
            return redirect(endpoint.get_absolute_url())

        selected_names = set(request.POST.getlist("selected"))
        delete_names = set(request.POST.getlist("delete"))

        from .module_sync import apply_firmware_to_device, apply_module_sync
        report = apply_module_sync(
            endpoint.device, session_data["entries"], selected_names, delete_names,
        )
        firmware = session_data.get("firmware", {})
        if firmware:
            apply_firmware_to_device(endpoint.device, firmware)

        del request.session[session_key]
        fw_count = len(firmware)
        if fw_count:
            summary_msg = _("Modules applied: %(summary)s (firmware entries updated: %(count)s)") % {
                "summary": report.summary(), "count": fw_count,
            }
        else:
            summary_msg = _("Modules applied: %(summary)s") % {"summary": report.summary()}
        messages.success(request, summary_msg)
        for msg in report.messages:
            messages.warning(request, msg)
        return redirect(endpoint.get_absolute_url())


_POWER_ACTIONS = {"on", "off", "soft", "cycle", "reset"}


class PowerActionView(View):
    """POST: BMC 電源操作 (on / off / soft / cycle / reset)。"""

    def post(self, request, pk):
        endpoint = get_object_or_404(BMCEndpoint, pk=pk)
        if not request.user.has_perm("netbox_bmc.change_bmcendpoint"):
            messages.error(request, _("Permission denied."))
            return redirect(endpoint.get_absolute_url())

        action = request.POST.get("action", "")
        if action not in _POWER_ACTIONS:
            messages.error(request, _("Unknown power action: %(action)s") % {"action": action})
            return redirect(endpoint.get_absolute_url())

        try:
            with endpoint.get_driver(request=request) as driver:
                driver.set_power(action)
        except Exception as e:
            messages.error(request, _("Power action failed: %(error)s") % {"error": e})
            return redirect(endpoint.get_absolute_url())

        messages.success(
            request,
            _("Power action '%(action)s' sent successfully.") % {"action": action},
        )
        return redirect(endpoint.get_absolute_url())


class PowerStatusView(View):
    """GET: 現在の電源状態を JSON で返す。"""

    def get(self, request, pk):
        endpoint = get_object_or_404(BMCEndpoint, pk=pk)
        if not request.user.has_perm("netbox_bmc.view_bmcendpoint"):
            return JsonResponse({"error": _("Permission denied.")}, status=403)

        try:
            with endpoint.get_driver(request=request) as driver:
                state = driver.get_power_state()
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

        return JsonResponse({"state": state})


class ManagerInfoView(View):
    """GET: BMC 自身のファームウェア/ヘルスを JSON で返す (ライブ取得、DB保存なし)。"""

    def get(self, request, pk):
        endpoint = get_object_or_404(BMCEndpoint, pk=pk)
        if not request.user.has_perm("netbox_bmc.view_bmcendpoint"):
            return JsonResponse({"error": _("Permission denied.")}, status=403)

        try:
            with endpoint.get_driver(request=request) as driver:
                info = driver.get_manager_info()
        except NotImplementedError:
            return JsonResponse(
                {"error": _("Not supported for this protocol")}, status=501,
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

        return JsonResponse(asdict(info))


class FetchRawView(View):
    """Redfish の生 JSON をブラウザに返すデバッグビュー (GET)。"""

    def get(self, request, pk):
        endpoint = get_object_or_404(BMCEndpoint, pk=pk)
        if not request.user.has_perm("netbox_bmc.view_bmcendpoint"):
            return JsonResponse({"error": _("Permission denied.")}, status=403)

        try:
            depth = min(int(request.GET.get("depth", 2)), 5)
        except (ValueError, TypeError):
            depth = 2

        try:
            with endpoint.get_driver(request=request) as driver:
                if hasattr(driver, "fetch_raw"):
                    data = driver.fetch_raw(max_depth=depth)
                else:
                    data = {"error": _("fetch_raw not supported for this protocol")}
        except Exception as e:
            data = {"error": str(e)}

        return JsonResponse(data, json_dumps_params={"indent": 2, "ensure_ascii": False})


class ConnectivityTestView(View):
    """POST: 保存前の Add/Edit フォーム入力値で BMC 接続確認を行う。"""

    def post(self, request):
        if not (request.user.has_perm("netbox_bmc.add_bmcendpoint")
                or request.user.has_perm("netbox_bmc.change_bmcendpoint")):
            return JsonResponse({"ok": False, "message": _("Permission denied.")}, status=403)

        device_id = request.POST.get("device")
        if not device_id:
            return JsonResponse({"ok": False, "message": _("Please select a Device first.")})
        device = Device.objects.filter(pk=device_id).first()
        if device is None:
            return JsonResponse({"ok": False, "message": _("The specified Device was not found.")})

        ip_address_id = request.POST.get("ip_address")
        if not ip_address_id:
            return JsonResponse({"ok": False, "message": _("Please select an IP Address.")})
        ip_address = IPAddress.objects.filter(pk=ip_address_id).first()
        if ip_address is None:
            return JsonResponse({"ok": False, "message": _("The specified IP Address was not found.")})

        port = request.POST.get("port") or None
        try:
            port = int(port) if port else None
        except ValueError:
            return JsonResponse({"ok": False, "message": _("Port must be a number.")})

        endpoint = BMCEndpoint(
            device=device,
            ip_address=ip_address,
            port=port,
            protocol=request.POST.get("protocol") or Protocol.AUTO,
            verify_ssl=request.POST.get("verify_ssl") == "true",
            username=request.POST.get("username", ""),
            password=request.POST.get("password", ""),
        )

        try:
            with endpoint.get_driver(request=request) as driver:
                power_state = driver.get_power_state()
                vendor = getattr(driver, "vendor", "")
                protocol = driver.protocol
        except Exception as e:
            return JsonResponse({"ok": False, "message": str(e)[:500]})

        parts = [f"protocol={protocol}"]
        if vendor:
            parts.append(f"vendor={vendor}")
        parts.append(f"power={power_state}")
        message = _("Connected (%(details)s)") % {"details": ", ".join(parts)}
        return JsonResponse({"ok": True, "message": message})
