
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import View
from netbox.views import generic

from . import forms, tables
from .models import BMCEndpoint


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


class BMCEndpointDeleteView(generic.ObjectDeleteView):
    queryset = BMCEndpoint.objects.all()


class BuildModulesView(View):
    """POST: BMC スキャン → session 保存 → preview へリダイレクト。"""

    def post(self, request, pk):
        endpoint = get_object_or_404(BMCEndpoint, pk=pk)
        if not request.user.has_perm("netbox_bmc.change_bmcendpoint"):
            messages.error(request, "Permission denied.")
            return redirect(endpoint.get_absolute_url())

        try:
            with endpoint.get_driver(request=request) as driver:
                result = driver.get_inventory()
        except Exception as e:
            messages.error(request, f"BMC scan failed: {e}")
            return redirect(endpoint.get_absolute_url())

        from .module_sync import compute_diff, entry_to_dict
        from .normalizer import normalize

        serial = result.system.serial
        endpoint.detected_vendor = result.vendor
        endpoint.detected_protocol = result.protocol
        endpoint.detected_serial = serial
        endpoint.save(update_fields=["detected_vendor", "detected_protocol", "detected_serial"])

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
            messages.error(request, "Permission denied.")
            return redirect(endpoint.get_absolute_url())

        session_key = f"bmc_module_preview_{pk}"
        session_data = request.session.get(session_key)
        if not session_data:
            messages.warning(request, "No scan data found. Please run a scan first.")
            return redirect(endpoint.get_absolute_url())

        # (kind, label, default_checked)
        KIND_FILTERS = [
            ("cpu",      "CPU",      True),
            ("memory",   "Memory",   True),
            ("drive",    "Drive",    True),
            ("psu",      "PSU",      True),
            ("fan",      "Fan",      False),
            ("pci",      "PCI",      False),
            ("firmware", "Firmware", False),
        ]
        unchecked_kinds = {k for k, _, checked in KIND_FILTERS if not checked}

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
            messages.error(request, "Permission denied.")
            return redirect(endpoint.get_absolute_url())

        session_key = f"bmc_module_preview_{pk}"
        session_data = request.session.get(session_key)
        if not session_data:
            messages.error(request, "Session expired. Please run a scan again.")
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
        messages.success(
            request,
            f"Modules applied: {report.summary()}"
            + (f", firmware entries updated: {fw_count}" if fw_count else ""),
        )
        for msg in report.messages:
            messages.warning(request, msg)
        return redirect(endpoint.get_absolute_url())


_POWER_ACTIONS = {"on", "off", "soft", "cycle", "reset"}


class PowerActionView(View):
    """POST: BMC 電源操作 (on / off / soft / cycle / reset)。"""

    def post(self, request, pk):
        endpoint = get_object_or_404(BMCEndpoint, pk=pk)
        if not request.user.has_perm("netbox_bmc.change_bmcendpoint"):
            messages.error(request, "Permission denied.")
            return redirect(endpoint.get_absolute_url())

        action = request.POST.get("action", "")
        if action not in _POWER_ACTIONS:
            messages.error(request, f"Unknown power action: {action}")
            return redirect(endpoint.get_absolute_url())

        try:
            with endpoint.get_driver(request=request) as driver:
                driver.set_power(action)
        except Exception as e:
            messages.error(request, f"Power action failed: {e}")
            return redirect(endpoint.get_absolute_url())

        messages.success(request, f"Power action '{action}' sent successfully.")
        return redirect(endpoint.get_absolute_url())


class PowerStatusView(View):
    """GET: 現在の電源状態を JSON で返す。"""

    def get(self, request, pk):
        endpoint = get_object_or_404(BMCEndpoint, pk=pk)
        if not request.user.has_perm("netbox_bmc.view_bmcendpoint"):
            return JsonResponse({"error": "Permission denied."}, status=403)

        try:
            with endpoint.get_driver(request=request) as driver:
                state = driver.get_power_state()
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

        return JsonResponse({"state": state})


class FetchRawView(View):
    """Redfish の生 JSON をブラウザに返すデバッグビュー (GET)。"""

    def get(self, request, pk):
        endpoint = get_object_or_404(BMCEndpoint, pk=pk)
        if not request.user.has_perm("netbox_bmc.view_bmcendpoint"):
            return JsonResponse({"error": "Permission denied."}, status=403)

        try:
            depth = min(int(request.GET.get("depth", 2)), 5)
        except (ValueError, TypeError):
            depth = 2

        try:
            with endpoint.get_driver(request=request) as driver:
                if hasattr(driver, "fetch_raw"):
                    data = driver.fetch_raw(max_depth=depth)
                else:
                    data = {"error": "fetch_raw not supported for this protocol"}
        except Exception as e:
            data = {"error": str(e)}

        return JsonResponse(data, json_dumps_params={"indent": 2, "ensure_ascii": False})
