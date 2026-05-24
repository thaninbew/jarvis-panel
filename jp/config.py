"""Load and validate named panel configs."""
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[jp] PyYAML required for config loading: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

PANELS_DIR = Path(__file__).parent / "panels"
VALID_LAYOUTS = [1, 2, 3, 4, 6, 8]


def load(name: str) -> dict:
    path = PANELS_DIR / f"{name}.yaml"
    if not path.exists():
        print(f"[jp] config '{name}' not found at {path}", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        cfg = yaml.safe_load(f) or {}

    layout = cfg.get("layout")
    if layout not in VALID_LAYOUTS:
        print(f"[jp] config '{name}': layout must be one of {VALID_LAYOUTS}", file=sys.stderr)
        sys.exit(1)

    panes = cfg.get("panes", []) or []
    if len(panes) > layout:
        print(
            f"[jp] config '{name}': {len(panes)} panes defined but layout is {layout}",
            file=sys.stderr
        )
        sys.exit(1)

    cfg["panes"] = panes
    return cfg


def list_configs() -> list[str]:
    if not PANELS_DIR.exists():
        return []
    return [p.stem for p in sorted(PANELS_DIR.glob("*.yaml"))]
