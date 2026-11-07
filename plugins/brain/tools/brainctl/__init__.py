"""brainctl: the deterministic helper for a second-brain vault (docs/plans/11-brainctl-helper.md).

Runs inside the vault's Python workspace (`.brain/python/brainctl/`), needs `ruamel.yaml`, and never prompts or commits.
"""

__version__ = "0.4.0"
CORE_VERSION = 1  # the core model version this helper understands (docs/plans/02)
