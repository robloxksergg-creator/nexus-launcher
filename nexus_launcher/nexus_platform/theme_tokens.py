"""Canonical NEXUS design foundation, shared by Qt and browser adapters."""
TOKENS = {"background": "#0a0e14", "sidebar": "#10161f", "surface": "#18212c",
          "accent": "#a6c9ff", "wash": "#20334b", "text": "#f1f4f8", "muted": "#a5b1c2",
          "border": "#2b3747", "hover": "#233044", "success": "#9edbb8",
          "warning": "#eac28b", "danger": "#f4a4ab"}
SPACING = (4, 8, 12, 16, 24, 32, 48, 64, 96)
TYPE = {"display": 56, "heading": 36, "section": 24, "body": 15,
        "caption": 13, "metadata": 12, "label": 14}
RADIUS = {"control": 8, "surface": 16, "hero": 20}
MOTION = {"fast": 160, "normal": 220, "hero": 300}
LAYOUT = {"sidebar": 232, "collapsed": 72, "content": 1760, "compact": 1280, "wide": 1920}


def browser_tokens():
    values = {**TOKENS, **{f"type-{key}": f"{value}px" for key, value in TYPE.items()},
              **{f"space-{value}": f"{value}px" for value in SPACING},
              **{f"radius-{key}": f"{value}px" for key, value in RADIUS.items()},
              **{f"motion-{key}": f"{value}ms" for key, value in MOTION.items()},
              **{f"layout-{key}": f"{value}px" for key, value in LAYOUT.items()}}
    return ":root{" + ";".join(f"--{key}:{value}" for key, value in values.items()) + "}"
