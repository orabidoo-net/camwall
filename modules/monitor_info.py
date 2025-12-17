import re
import subprocess


def _fallback_geometries():
    return {"left": "1920x1080+0+0", "right": "1920x1080+0+0"}


def get_xrandr_geometries():
    try:
        result = subprocess.run(
            ["xrandr", "--listmonitors"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return _fallback_geometries()

    lines = result.stdout.splitlines()
    geometries = []
    pattern = re.compile(
        r"(?P<width>\d+)/(?:\d+)x(?P<height>\d+)/(?:\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)"
    )

    for line in lines:
        match = pattern.search(line)
        if not match:
            continue
        width = match.group("width")
        height = match.group("height")
        x = int(match.group("x"))
        y = match.group("y")
        geom = f"{width}x{height}+{x}+{y}"
        geometries.append({"geom": geom, "x": x})

    if not geometries:
        return _fallback_geometries()

    geometries.sort(key=lambda g: g["x"])

    result_map = {"left": geometries[0]["geom"]}
    result_map["right"] = geometries[-1]["geom"] if len(geometries) > 1 else geometries[0]["geom"]
    return result_map
