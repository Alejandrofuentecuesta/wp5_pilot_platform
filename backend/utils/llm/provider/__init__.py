# Provider clients are imported lazily by llm_manager._create_client()
# to avoid requiring all provider packages to be installed.
#
# This module defines the canonical list of supported providers and their
# suggested models.  When adding a new provider, update both
# PROVIDER_REGISTRY below and the if/elif chain in llm_manager._create_client().

PROVIDER_REGISTRY: dict[str, list[str]] = {
    "anthropic": [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ],
    "gemini": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ],
    "huggingface": [
        "meta-llama/Llama-3.3-70B-Instruct",
    ],
    "mistral": [
        "mistral-large-latest",
        "mistral-medium-latest",
        "mistral-small-latest",
    ],
    "konstanz": [
        "BSC-LT/ALIA-40b-instruct-2601",
    ],
    "bsc": [
        "incivility",
    ],
}

# Declares which sampling parameters each provider actually honours.
# The frontend uses this to warn users about ignored / mutually-exclusive params.
PROVIDER_PARAMS: dict[str, dict] = {
    "anthropic": {
        "temperature": True,
        "top_p": True,
        "max_tokens": True,
        "mutual_exclusion": ["temperature", "top_p"],  # API rejects both at once
    },
    "gemini": {
        "temperature": True,
        "top_p": True,
        "max_tokens": True,
    },
    "huggingface": {
        "temperature": True,
        "top_p": True,
        "max_tokens": True,
    },
    "mistral": {
        "temperature": True,
        "top_p": True,
        "max_tokens": True,
    },
    "konstanz": {
        "temperature": True,
        "top_p": True,
        "max_tokens": True,
    },
    "bsc": {
        "temperature": True,
        "top_p": True,
        "max_tokens": True,
    },
}
