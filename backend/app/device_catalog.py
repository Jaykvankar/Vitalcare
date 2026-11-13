"""Which kinds of devices Vitalcare can connect, described in plain language.

This is the single source of truth for the "Connect a device" wizard, the Device guide page and the
device list. Device *categories* only: no brand names, because no specific model has been certified.

status:
  ready              works today with what is in this project
  needs_adapter      works through a gateway once a small adapter for the device model is written
  needs_integration  needs the hospital's integration engine (HL7 / FHIR) to feed an adapter
"""
from __future__ import annotations

from typing import TypedDict


class DeviceType(TypedDict):
    id: str
    name: str
    icon: str
    measures: list[str]
    connects_through: str
    status: str
    admin_only: bool
    default_label: str
    what_you_need: list[str]
    how_to_connect: list[str]
    patient_tips: list[str]


GATEWAY_STEPS = [
    "Switch on the Vitalcare gateway next to the patient and make sure it is online.",
    "On the gateway, choose Add device and scan the QR code (or type the pairing code).",
    "Wait for Connected on this screen, then switch on the sensors.",
]

CATALOG: list[DeviceType] = [
    {
        "id": "gateway_kit",
        "name": "Vitalcare gateway",
        "icon": "Watch",
        "measures": ["Heart rate", "SpO₂", "Breathing rate", "Blood pressure", "Temperature"],
        "connects_through": "A small computer next to the patient that combines the sensors and sends encrypted readings",
        "status": "ready",
        "admin_only": False,
        "default_label": "Home monitoring gateway",
        "what_you_need": [
            "A gateway (Raspberry Pi, mini PC or laptop) with the Vitalcare device program installed",
            "Internet or hospital Wi-Fi at the patient's bedside",
            "The sensors the patient will use, within Bluetooth range of the gateway",
        ],
        "how_to_connect": GATEWAY_STEPS,
        "patient_tips": [
            "Keep the gateway plugged in and switched on.",
            "Stay within the same room as the gateway so the sensors can reach it.",
        ],
    },
    {
        "id": "pulse_oximeter",
        "name": "Fingertip pulse oximeter",
        "icon": "Drop",
        "measures": ["SpO₂", "Heart rate"],
        "connects_through": "Bluetooth to the gateway (standard Pulse Oximeter service, 0x1822)",
        "status": "needs_adapter",
        "admin_only": False,
        "default_label": "Pulse oximeter",
        "what_you_need": [
            "An oximeter that uses the standard Bluetooth Pulse Oximeter service",
            "A Vitalcare gateway with the oximeter adapter installed",
        ],
        "how_to_connect": GATEWAY_STEPS,
        "patient_tips": [
            "Warm your hands first and keep the finger still.",
            "Remove nail polish on that finger; it can block the reading.",
        ],
    },
    {
        "id": "bp_cuff",
        "name": "Blood-pressure cuff",
        "icon": "Gauge",
        "measures": ["Blood pressure"],
        "connects_through": "Bluetooth to the gateway (standard Blood Pressure service, 0x1810)",
        "status": "needs_adapter",
        "admin_only": False,
        "default_label": "Blood-pressure cuff",
        "what_you_need": [
            "A cuff that uses the standard Bluetooth Blood Pressure service",
            "A Vitalcare gateway with the cuff adapter installed",
        ],
        "how_to_connect": GATEWAY_STEPS,
        "patient_tips": [
            "Sit quietly for 5 minutes before measuring, feet flat, arm resting at heart level.",
            "Use the same arm each time.",
        ],
    },
    {
        "id": "thermometer",
        "name": "Thermometer",
        "icon": "Thermo",
        "measures": ["Temperature"],
        "connects_through": "Bluetooth to the gateway (standard Health Thermometer service, 0x1809)",
        "status": "needs_adapter",
        "admin_only": False,
        "default_label": "Thermometer",
        "what_you_need": [
            "A thermometer that uses the standard Bluetooth Health Thermometer service",
            "A Vitalcare gateway with the thermometer adapter installed",
        ],
        "how_to_connect": GATEWAY_STEPS,
        "patient_tips": ["Wait 15 minutes after eating, drinking or exercise before measuring."],
    },
    {
        "id": "hr_strap",
        "name": "Heart-rate strap or watch",
        "icon": "Heart",
        "measures": ["Heart rate"],
        "connects_through": "Bluetooth to the gateway (standard Heart Rate service, 0x180D)",
        "status": "needs_adapter",
        "admin_only": False,
        "default_label": "Heart-rate strap",
        "what_you_need": [
            "A strap or watch that broadcasts the standard Bluetooth Heart Rate service",
            "A Vitalcare gateway with the heart-rate adapter installed",
        ],
        "how_to_connect": GATEWAY_STEPS,
        "patient_tips": ["Wear the strap snugly; moisten the contact pads if readings drop out."],
    },
    {
        "id": "ward_monitor",
        "name": "Hospital bedside monitor",
        "icon": "Monitor",
        "measures": ["Heart rate", "SpO₂", "Breathing rate", "Blood pressure", "Temperature"],
        "connects_through": "The hospital's integration engine (HL7 or FHIR feed) to an adapter",
        "status": "needs_integration",
        "admin_only": False,
        "default_label": "Bedside monitor",
        "what_you_need": [
            "Hospital IT to route the monitor's feed for this bed to a Vitalcare adapter",
            "The adapter configured with this pairing code",
        ],
        "how_to_connect": [
            "Give the pairing code to hospital IT (or send them this screen).",
            "IT adds the code to the adapter for this patient's bed.",
            "Wait for Connected on this screen.",
        ],
        "patient_tips": ["Nothing to do: the ward monitor sends readings automatically."],
    },
    {
        "id": "simulator",
        "name": "Built-in test monitor",
        "icon": "Play",
        "measures": ["Heart rate", "SpO₂", "Breathing rate", "Blood pressure", "Temperature"],
        "connects_through": "Runs inside Vitalcare for demonstrations and training",
        "status": "ready",
        "admin_only": True,
        "default_label": "Test monitor",
        "what_you_need": ["Nothing: Vitalcare plays the device itself"],
        "how_to_connect": ["Select Use the built-in test monitor below."],
        "patient_tips": ["This is a test device; it does not measure you."],
    },
]

IDS = {d["id"] for d in CATALOG}


def for_role(role: str) -> list[DeviceType]:
    return [d for d in CATALOG if role == "admin" or not d["admin_only"]]


def is_allowed(device_type: str, role: str) -> bool:
    return any(d["id"] == device_type for d in for_role(role))
