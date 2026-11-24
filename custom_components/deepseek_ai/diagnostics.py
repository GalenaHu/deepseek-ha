"""HA's administrator-only diagnostics, containing operational metadata only."""

from .const import VERSION


async def async_get_config_entry_diagnostics(hass, entry):
    return {
        "integration_version": VERSION,
        "agents": [{"kind": subentry.subentry_type, "model": subentry.data.get("model", "deepseek-flash"), "web": bool(subentry.data.get("web", False))} for subentry in entry.subentries.values()],
        "metrics": entry.runtime_data.metrics.values.copy(),
        "pending_owned_files": len(entry.runtime_data.attachments.owned),
        "experimental_evaluation": any(item.subentry_type == "evaluation" for item in entry.subentries.values()),
    }

