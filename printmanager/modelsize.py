"""Measure STL and 3MF files (overall size in mm) and check them against the bed.

Only the bounding box matters, so nothing here builds or renders the mesh.
STL has no units; millimeters are assumed. 3MF files say what unit they use.
"""
import itertools
import math
import re
import struct
import zipfile
from xml.parsers import expat

CHUNK_TRIANGLES = 20000
MAX_MODEL_XML = 500 * 1024 * 1024
UNITS_MM = {
    "micron": 0.001, "millimeter": 1.0, "centimeter": 10.0,
    "inch": 25.4, "foot": 304.8, "meter": 1000.0,
}
_VERTEX = re.compile(rb"^\s*vertex\s+(\S+)\s+(\S+)\s+(\S+)", re.IGNORECASE)


class _Box:
    """Running min/max of points."""

    def __init__(self):
        self.lo = [math.inf] * 3
        self.hi = [-math.inf] * 3

    def add(self, x, y, z):
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            return
        lo, hi = self.lo, self.hi
        if x < lo[0]: lo[0] = x
        if x > hi[0]: hi[0] = x
        if y < lo[1]: lo[1] = y
        if y > hi[1]: hi[1] = y
        if z < lo[2]: lo[2] = z
        if z > hi[2]: hi[2] = z

    @property
    def empty(self):
        return self.lo[0] > self.hi[0]

    def corners(self):
        return [
            (x, y, z)
            for x in (self.lo[0], self.hi[0])
            for y in (self.lo[1], self.hi[1])
            for z in (self.lo[2], self.hi[2])
        ]

    def size(self):
        return tuple(h - l for l, h in zip(self.lo, self.hi))


def stl_size(path):
    """(x, y, z) of an STL in its own units, or None."""
    box = _Box()
    with open(path, "rb") as fh:
        head = fh.read(84)
        fh.seek(0, 2)
        total = fh.tell()
        count = struct.unpack("<I", head[80:84])[0] if len(head) == 84 else -1
        if len(head) == 84 and total == 84 + 50 * count:
            fh.seek(84)
            record = struct.Struct("<12fH")
            while True:
                data = fh.read(record.size * CHUNK_TRIANGLES)
                if not data:
                    break
                for t in record.iter_unpack(data[: len(data) - len(data) % record.size]):
                    box.add(t[3], t[4], t[5])
                    box.add(t[6], t[7], t[8])
                    box.add(t[9], t[10], t[11])
        else:
            fh.seek(0)
            for line in fh:
                m = _VERTEX.match(line)
                if m:
                    try:
                        box.add(float(m.group(1)), float(m.group(2)), float(m.group(3)))
                    except ValueError:
                        continue
    return None if box.empty else box.size()


def _transform(points, matrix):
    """Apply a 3MF transform ("m00 m01 m02 m10 ... m32", row vectors)."""
    m = matrix
    return [
        (
            x * m[0] + y * m[3] + z * m[6] + m[9],
            x * m[1] + y * m[4] + z * m[7] + m[10],
            x * m[2] + y * m[5] + z * m[8] + m[11],
        )
        for x, y, z in points
    ]


def _matrix(text):
    try:
        values = [float(v) for v in (text or "").split()]
    except ValueError:
        return None
    return values if len(values) == 12 else None


def _local(tag):
    return tag.rsplit(":", 1)[-1].rsplit("}", 1)[-1]


def threemf_size(path):
    """(x, y, z) of a 3MF in millimeters (what its build items span), or None.

    A transformed object is measured by its transformed bounding box, which is
    exact for plain moves and can run a little large for objects turned at an angle.
    """
    objects = {}  # id -> {"box": _Box, "components": [(id, matrix)]}
    items = []  # (object id, matrix)
    unit = 1.0
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".model")]
        # The main model is normally 3D/3dmodel.model; others only hold extra objects.
        names.sort(key=lambda n: (n.lower() != "3d/3dmodel.model", n))
        for name in names:
            info = archive.getinfo(name)
            if info.file_size > MAX_MODEL_XML:
                raise ValueError("model data too large")
            main = name == names[0]
            state = {"current": None}

            def start_el(tag, attrs, main=main, state=state):
                nonlocal unit
                tag = _local(tag)
                if tag == "model" and main:
                    unit = UNITS_MM.get((attrs.get("unit") or "millimeter").lower(), 1.0)
                elif tag == "object":
                    state["current"] = objects.setdefault(
                        attrs.get("id"), {"box": _Box(), "components": []}
                    )
                elif tag == "vertex" and state["current"] is not None:
                    try:
                        state["current"]["box"].add(
                            float(attrs["x"]), float(attrs["y"]), float(attrs["z"])
                        )
                    except (KeyError, ValueError):
                        pass
                elif tag == "component" and state["current"] is not None:
                    state["current"]["components"].append(
                        (attrs.get("objectid"), _matrix(attrs.get("transform")))
                    )
                elif tag == "item" and main:
                    items.append((attrs.get("objectid"), _matrix(attrs.get("transform"))))

            def end_el(tag, state=state):
                if _local(tag) == "object":
                    state["current"] = None

            parser = expat.ParserCreate()
            parser.StartElementHandler = start_el
            parser.EndElementHandler = end_el
            with archive.open(name) as fh:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    parser.Parse(chunk, False)
                parser.Parse(b"", True)

    def points_of(object_id, depth=0):
        obj = objects.get(object_id)
        if obj is None or depth > 8:
            return []
        points = [] if obj["box"].empty else obj["box"].corners()
        for child_id, matrix in obj["components"]:
            child = points_of(child_id, depth + 1)
            points.extend(_transform(child, matrix) if matrix else child)
        return points

    box = _Box()
    sources = items or [(oid, None) for oid in objects]
    for object_id, matrix in sources:
        pts = points_of(object_id)
        for x, y, z in (_transform(pts, matrix) if matrix else pts):
            box.add(x, y, z)
    if box.empty:
        return None
    return tuple(v * unit for v in box.size())


def model_size(path, ext):
    """(x, y, z) in mm, or None when the file can't be measured."""
    try:
        size = stl_size(path) if ext == "stl" else threemf_size(path) if ext == "3mf" else None
    except (OSError, ValueError, struct.error, zipfile.BadZipFile, expat.ExpatError, RecursionError):
        return None
    if size is None or not all(math.isfinite(v) for v in size):
        return None
    return size


AXES = ("wide (X)", "deep (Y)", "tall (Z)")
EPS = 0.01


def check_fit(dims, bed, margin):
    """Compare a model with the bed.

    dims: (x, y, z) in mm. bed: (x, y, z) build volume. margin: mm kept free on
    each side in X and Y. Returns a dict with status "fits", "rotate" or "big".
    """
    limits = (bed[0] - 2 * margin, bed[1] - 2 * margin, bed[2])
    if min(limits) <= 0:
        return {"status": "big", "text": "The margin is bigger than the bed", "over": None}

    def overflow(order):
        return max(dims[order[i]] - limits[i] for i in range(3))

    # Flat on the bed, then turned 90 degrees flat, then on its side.
    orders = [(0, 1, 2), (1, 0, 2)] + [
        p for p in itertools.permutations(range(3)) if p not in ((0, 1, 2), (1, 0, 2))
    ]
    if overflow(orders[0]) <= EPS:
        return {"status": "fits", "text": "Fits", "over": 0}
    for order in orders[1:]:
        if overflow(order) <= EPS:
            how = "turned flat" if order == (1, 0, 2) else "on its side"
            return {"status": "rotate", "text": f"Fits {how}", "over": 0}
    best = min(orders, key=overflow)
    over = overflow(best)
    axis = max(range(3), key=lambda i: dims[best[i]] - limits[i])
    return {
        "status": "big",
        "text": f"Too big by {over:.1f} mm (too {AXES[axis]})",
        "over": over,
    }
