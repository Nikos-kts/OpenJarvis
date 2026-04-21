from __future__ import annotations

from typing import Any, Dict, Optional

from openjarvis.core.config import HardwareInfo, detect_hardware


def _parse_param_count(model_name: str) -> float:
    import re

    match = re.search(r":(\d+(?:\.\d+)?)b", (model_name or "").lower())
    return float(match.group(1)) if match else 0.0


def _available_memory_gb(hw: HardwareInfo) -> float:
    gpu = hw.gpu
    if gpu and gpu.vram_gb > 0:
        return gpu.vram_gb * max(gpu.count, 1) * 0.9
    if hw.ram_gb > 0:
        return max(0.0, (hw.ram_gb - 4.0) * 0.8)
    return 0.0


def _balanced_generation_tokens(available_gb: float, model_name: str) -> int:
    params_b = _parse_param_count(model_name)

    if available_gb <= 8:
        tokens = 768
    elif available_gb <= 12:
        tokens = 1024
    elif available_gb <= 18:
        tokens = 1536
    elif available_gb <= 32:
        tokens = 2048
    else:
        tokens = 3072

    if params_b >= 20:
        tokens = max(768, tokens - 512)
    elif params_b >= 9:
        tokens = max(1024, tokens - 256)

    return tokens


def _profile_from_generation_tokens(generation_max_tokens: int) -> Dict[str, Dict[str, int]]:
    conservative_generation = max(512, int(round(generation_max_tokens * 0.66 / 128.0) * 128))
    balanced_generation = max(768, int(round(generation_max_tokens / 128.0) * 128))
    quality_generation = max(
        1024,
        int(round(min(4096, balanced_generation * 1.33) / 128.0) * 128),
    )

    return {
        "conservative": {
            "generation_max_tokens": conservative_generation,
            "budget_max_tokens": conservative_generation * 8,
        },
        "balanced": {
            "generation_max_tokens": balanced_generation,
            "budget_max_tokens": balanced_generation * 16,
        },
        "quality": {
            "generation_max_tokens": quality_generation,
            "budget_max_tokens": quality_generation * 20,
        },
    }


def recommend_managed_agent_token_policy(
    model_name: str = "",
    hw: Optional[HardwareInfo] = None,
) -> Dict[str, Any]:
    hw = hw or detect_hardware()
    available_gb = _available_memory_gb(hw)
    profiles = _profile_from_generation_tokens(
        _balanced_generation_tokens(available_gb, model_name),
    )
    recommended_profile = "balanced"

    notes = [
        "generation_max_tokens limits a single model response",
        "budget_max_tokens limits cumulative agent usage before budget_exceeded",
    ]
    if hw.platform == "darwin" and hw.gpu and hw.gpu.vendor == "apple":
        notes.append(
            "Apple Silicon uses unified memory, so larger generations increase latency and memory pressure together",
        )
    if hw.ram_gb and hw.ram_gb <= 18:
        notes.append(
            "For 18 GB-class systems, balanced defaults are safer than 4K generations for always-on agents",
        )

    return {
        "recommended_profile": recommended_profile,
        "profiles": profiles,
        "recommended": profiles[recommended_profile],
        "machine": {
            "platform": hw.platform,
            "cpu_brand": hw.cpu_brand,
            "ram_gb": hw.ram_gb,
            "gpu_vendor": hw.gpu.vendor if hw.gpu else "",
            "gpu_name": hw.gpu.name if hw.gpu else "",
            "available_memory_gb": round(available_gb, 1),
        },
        "notes": notes,
    }


def normalize_managed_agent_config(
    config: Optional[Dict[str, Any]],
    *,
    hw: Optional[HardwareInfo] = None,
) -> Dict[str, Any]:
    normalized = dict(config or {})

    # Legacy key migration: old max_tokens meant per-generation cap in practice.
    if "generation_max_tokens" not in normalized:
        legacy_max_tokens = normalized.get("max_tokens")
        if legacy_max_tokens not in (None, ""):
            normalized["generation_max_tokens"] = legacy_max_tokens

    recommendation = recommend_managed_agent_token_policy(
        str(normalized.get("model", "")),
        hw=hw,
    )
    recommended = recommendation["recommended"]

    if normalized.get("generation_max_tokens") in (None, ""):
        normalized["generation_max_tokens"] = recommended["generation_max_tokens"]
    if normalized.get("budget_max_tokens") in (None, ""):
        normalized["budget_max_tokens"] = recommended["budget_max_tokens"]

    try:
        normalized["generation_max_tokens"] = int(normalized["generation_max_tokens"])
    except (TypeError, ValueError):
        normalized["generation_max_tokens"] = recommended["generation_max_tokens"]

    try:
        normalized["budget_max_tokens"] = int(normalized["budget_max_tokens"])
    except (TypeError, ValueError):
        normalized["budget_max_tokens"] = recommended["budget_max_tokens"]

    normalized.setdefault("token_profile", recommendation["recommended_profile"])
    return normalized