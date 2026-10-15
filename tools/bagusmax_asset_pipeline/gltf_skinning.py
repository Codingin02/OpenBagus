"""Independent NumPy glTF LBS/morph evaluation; no Blender imports or modifiers."""

import copy
import json
import math
import struct
from pathlib import Path

import numpy as np

BLENDER_TO_GLTF = np.array(((1, 0, 0), (0, 0, 1), (0, -1, 0)), dtype=float)
DTYPES = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def rotation_xyz(angles):
    x, y, z = angles
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return np.array(((cz, -sz, 0), (sz, cz, 0), (0, 0, 1))) @ np.array(
        ((cy, 0, sy), (0, 1, 0), (-sy, 0, cy))) @ np.array(((1, 0, 0), (0, cx, -sx), (0, sx, cx)))


def quaternion_matrix(q):
    x, y, z, w = np.asarray(q, dtype=float)/np.linalg.norm(q)
    return np.array(((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
                     (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
                     (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y))))


def rotation_fraction(matrix, fraction):
    angle = math.acos(float(np.clip((np.trace(matrix)-1)/2, -1, 1)))
    if angle < 1e-9:
        return np.eye(3)
    if abs(math.pi-angle) < 1e-5:
        values, vectors = np.linalg.eig(matrix)
        axis = vectors[:, np.argmin(abs(values-1))].real
    else:
        axis = np.array((matrix[2, 1]-matrix[1, 2], matrix[0, 2]-matrix[2, 0],
                         matrix[1, 0]-matrix[0, 1]))/(2*math.sin(angle))
    axis /= np.linalg.norm(axis)
    x, y, z = axis
    cross = np.array(((0, -z, y), (z, 0, -x), (-y, x, 0)))
    return np.eye(3)+math.sin(angle*fraction)*cross+(1-math.cos(angle*fraction))*(cross @ cross)


class GLBSkin:
    def __init__(self, path):
        self.path = Path(path)
        blob = self.path.read_bytes()
        assert struct.unpack_from("<4sII", blob) == (b"glTF", 2, len(blob))
        size, kind = struct.unpack_from("<II", blob, 12)
        assert kind == 0x4E4F534A
        self.doc = json.loads(blob[20:20+size])
        size_bin, kind_bin = struct.unpack_from("<II", blob, 20+size)
        assert kind_bin == 0x004E4942
        self.binary = memoryview(blob)[28+size:28+size+size_bin]
        self.nodes = self.doc["nodes"]
        self.parents = {child: i for i, node in enumerate(self.nodes) for child in node.get("children", [])}
        self.names = {node.get("name", str(i)): i for i, node in enumerate(self.nodes)}
        self.local = []
        for node in self.nodes:
            if "matrix" in node:
                matrix = np.array(node["matrix"]).reshape(4, 4).T
            else:
                matrix = np.eye(4)
                matrix[:3, :3] = quaternion_matrix(node.get("rotation", (0, 0, 0, 1))) @ np.diag(node.get("scale", (1, 1, 1)))
                matrix[:3, 3] = node.get("translation", (0, 0, 0))
            self.local.append(matrix)
        self.rest = self.globals(self.local)
        self.bind = [self.accessor(s["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
                     if "inverseBindMatrices" in s else np.repeat(np.eye(4)[None], len(s["joints"]), axis=0)
                     for s in self.doc["skins"]]
        self.primitives = []
        for node_index, node in enumerate(self.nodes):
            if "mesh" not in node or "skin" not in node:
                continue
            mesh = self.doc["meshes"][node["mesh"]]
            for primitive in mesh["primitives"]:
                assert primitive.get("mode", 4) == 4
                attrs = primitive["attributes"]
                assert not any(k.startswith("JOINTS_") and k != "JOINTS_0" for k in attrs)
                weights = self.accessor(attrs["WEIGHTS_0"])
                joints = self.accessor(attrs["JOINTS_0"]).astype(int)
                assert np.all(abs(weights.sum(axis=1)-1) < 1e-5) and np.all(weights >= 0)
                assert joints.max() < len(self.doc["skins"][node["skin"]]["joints"])
                self.primitives.append({"node": node_index, "name": node.get("name"), "skin": node["skin"],
                    "position": self.accessor(attrs["POSITION"]), "normal": self.accessor(attrs["NORMAL"]),
                    "weights": weights, "joints": joints,
                    "indices": self.accessor(primitive["indices"]).reshape(-1, 3).astype(int),
                    "colors": self.accessor(attrs["COLOR_0"]) if "COLOR_0" in attrs else None,
                    "target_names": mesh.get("extras", {}).get("targetNames", []),
                    "target_accessors": primitive.get("targets", []),
                    "targets": [{k: self.accessor(a) for k, a in t.items()} for t in primitive.get("targets", [])],
                    "defaults": node.get("weights", mesh.get("weights", [0]*len(primitive.get("targets", [])))),
                    "material": primitive.get("material")})

    def raw(self, view_index, offset, count, width, dtype):
        view = self.doc["bufferViews"][view_index]
        dtype = np.dtype(dtype)
        return np.ndarray((count, width), dtype=dtype, buffer=self.binary,
            offset=view.get("byteOffset", 0)+offset,
            strides=(view.get("byteStride", width*dtype.itemsize), dtype.itemsize)).copy()

    def accessor(self, index):
        accessor = self.doc["accessors"][index]
        count, width = accessor["count"], WIDTHS[accessor["type"]]
        dtype = DTYPES[accessor["componentType"]]
        data = self.raw(accessor["bufferView"], accessor.get("byteOffset", 0), count, width, dtype) if "bufferView" in accessor else np.zeros((count, width), dtype=dtype)
        if "sparse" in accessor:
            sparse = accessor["sparse"]
            inds, vals = sparse["indices"], sparse["values"]
            indices = self.raw(inds["bufferView"], inds.get("byteOffset", 0), sparse["count"], 1, DTYPES[inds["componentType"]]).ravel()
            data[indices] = self.raw(vals["bufferView"], vals.get("byteOffset", 0), sparse["count"], width, dtype)
        if accessor.get("normalized"):
            limit = np.iinfo(data.dtype).max
            data = np.maximum(data.astype(float)/limit, -1)
        return data.astype(float) if accessor["componentType"] == 5126 else data

    def globals(self, local):
        result = {}
        def visit(i):
            if i not in result:
                result[i] = visit(self.parents[i]) @ local[i] if i in self.parents else local[i]
            return result[i]
        return np.array([visit(i) for i in range(len(local))])

    def posed_globals(self, changes):
        local = [m.copy() for m in self.local]
        world_deltas = {}
        for name, angles in changes.items():
            if name not in self.names:
                continue
            i = self.names[name]
            world = BLENDER_TO_GLTF @ rotation_xyz(angles) @ BLENDER_TO_GLTF.T
            rest = self.rest[i, :3, :3]
            local[i][:3, :3] = self.local[i][:3, :3] @ (np.linalg.inv(rest) @ world @ rest)
            world_deltas[name] = world
        for side in ("L", "R"):
            for helper, primary in (("ShoulderVolume", "UpperArm"), ("ElbowVolume", "Forearm")):
                name, source = f"{helper}_{side}", f"{primary}_{side}"
                if name not in self.names:
                    continue
                i = self.names[name]
                rest = self.rest[i, :3, :3]
                half = rotation_fraction(world_deltas.get(source, np.eye(3)), .5)
                local[i][:3, :3] = self.local[i][:3, :3] @ (np.linalg.inv(rest) @ half @ rest)
        return self.globals(local)

    def skin_matrices(self, changes):
        posed = self.posed_globals(changes)
        return [posed[skin["joints"]] @ bind for skin, bind in zip(self.doc["skins"], self.bind)]

    @staticmethod
    def blend(primitive, matrices):
        result = np.zeros((len(primitive["position"]), 4, 4))
        for influence in range(4):
            result += primitive["weights"][:, influence, None, None]*matrices[primitive["skin"]][primitive["joints"][:, influence]]
        return result

    def evaluate(self, changes, morphs=None):
        matrices = self.skin_matrices(changes)
        output = []
        for primitive in self.primitives:
            position = primitive["position"].copy()
            normal = primitive["normal"].copy()
            for i, target in enumerate(primitive["targets"]):
                name = primitive["target_names"][i]
                value = (morphs or {}).get(name, primitive["defaults"][i])
                position += value*target.get("POSITION", 0)
                normal += value*target.get("NORMAL", 0)
            blended = self.blend(primitive, matrices)
            result = np.einsum("nij,nj->ni", blended[:, :3, :3], position)+blended[:, :3, 3]
            # All exported joints are rigid; blend per-joint normal transforms.
            normal = np.einsum("nij,nj->ni", blended[:, :3, :3], normal)
            normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
            assert np.isfinite(result).all()
            output.append({**primitive, "position": result, "normal": normal})
        return output

    def replace_normal_targets(self, overrides):
        assert not self.doc.get("animations") and not self.doc.get("images")
        doc = copy.deepcopy(self.doc)
        refs = []
        for mesh in doc["meshes"]:
            for primitive in mesh["primitives"]:
                refs.extend((primitive["attributes"], k) for k in primitive["attributes"])
                refs.append((primitive, "indices"))
                for target in primitive.get("targets", []):
                    refs.extend((target, k) for k in target)
        refs.extend((skin, "inverseBindMatrices") for skin in doc["skins"] if "inverseBindMatrices" in skin)
        used = sorted({container[key] for container, key in refs})
        payload, views, accessors, view_mapping = bytearray(), [], [], {}

        def append_view(data, metadata=None):
            payload.extend(b"\0"*((-len(payload)) % 4))
            view = dict(metadata or {})
            view.update(buffer=0, byteOffset=len(payload), byteLength=len(data))
            payload.extend(data)
            views.append(view)
            return len(views)-1

        def copy_view(index):
            if index not in view_mapping:
                view = self.doc["bufferViews"][index]
                start = view.get("byteOffset", 0)
                view_mapping[index] = append_view(self.binary[start:start+view["byteLength"]], view)
            return view_mapping[index]

        mapping = {}
        for old in used:
            mapping[old] = len(accessors)
            if old in overrides:
                values = np.asarray(overrides[old], dtype="<f4")
                selected = np.flatnonzero(np.linalg.norm(values, axis=1) > 1e-4)
                accessor = {"componentType": 5126, "type": "VEC3", "count": len(values)}
                if 0 < len(selected) < len(values)*.8:
                    indices_type = 5123 if len(values) <= 65535 else 5125
                    accessor["sparse"] = {"count": len(selected),
                        "indices": {"bufferView": append_view(selected.astype(DTYPES[indices_type]).tobytes()), "componentType": indices_type},
                        "values": {"bufferView": append_view(values[selected].tobytes())}}
                else:
                    accessor["bufferView"] = append_view(values.tobytes(), {"target": 34962})
            else:
                accessor = copy.deepcopy(self.doc["accessors"][old])
                if "bufferView" in accessor:
                    accessor["bufferView"] = copy_view(accessor["bufferView"])
                if "sparse" in accessor:
                    for field in ("indices", "values"):
                        section = accessor["sparse"][field]
                        section["bufferView"] = copy_view(section["bufferView"])
            accessors.append(accessor)
        for container, key in refs:
            container[key] = mapping[container[key]]
        payload.extend(b"\0"*((-len(payload)) % 4))
        doc.update(accessors=accessors, bufferViews=views, buffers=[{"byteLength": len(payload)}])
        encoded = json.dumps(doc, separators=(",", ":")).encode("utf-8")
        encoded += b" "*((-len(encoded)) % 4)
        total = 12+8+len(encoded)+8+len(payload)
        self.path.write_bytes(struct.pack("<4sII", b"glTF", 2, total)+
            struct.pack("<II", len(encoded), 0x4E4F534A)+encoded+
            struct.pack("<II", len(payload), 0x004E4942)+payload)


def self_test():
    rotation = rotation_xyz((.8, -.4, .2))
    half = rotation_fraction(rotation, .5)
    assert np.allclose(half @ half, rotation)
    assert np.allclose(quaternion_matrix((0, 0, 0, 1)), np.eye(3))
    assert np.allclose(BLENDER_TO_GLTF @ (1, 2, 3), (1, 3, -2))
