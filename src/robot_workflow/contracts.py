"""Deterministic, standard-library-only semantic extractors."""

import ast
import hashlib
import json
import re
import tomllib
import xml.etree.ElementTree as ET


def digest(value):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def xml_value(element):
    """Keep child order: order can be meaningful for URDF consumers."""
    if element is None:
        return None
    return {"tag": element.tag, "attrs": dict(sorted(element.attrib.items())),
            "text": (element.text or "").strip(), "children": [xml_value(c) for c in element]}


def urdf(text):
    root = ET.fromstring(text)
    if root.tag != "robot":
        raise ValueError("URDF root must be <robot>")
    joints = root.findall("joint")
    links = root.findall("link")
    names = [j.get("name") for j in joints]
    if None in names or len(set(names)) != len(names):
        raise ValueError("URDF has missing or duplicate joint names")
    kinematics = {}
    dynamics = {}
    for joint in joints:
        name = joint.get("name")
        kinematics[name] = {"type": joint.get("type"), **{
            tag: xml_value(joint.find(tag))
            for tag in ("parent", "child", "origin", "axis", "limit", "mimic", "calibration", "safety_controller")}}
        dynamics[name] = xml_value(joint.find("dynamics"))
    return {
        "joint_order": [j.get("name") for j in joints if j.get("type") != "fixed"],
        "kinematics": {"joints": kinematics, "links": [l.get("name") for l in links]},
        "dynamics": {"joints": dynamics, "links": {l.get("name"): {
            "inertial": xml_value(l.find("inertial")),
            "collision": [xml_value(c) for c in l.findall("collision")]} for l in links}},
        "visuals": {l.get("name"): [xml_value(v) for v in l.findall("visual")] for l in links},
        "extensions": [xml_value(c) for c in root if c.tag not in {"joint", "link"}],
    }


def without_docstrings(node):
    """Remove documentation only; preserve executable string expressions."""
    for item in ast.walk(node):
        if isinstance(item, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.body and isinstance(item.body[0], ast.Expr):
                value = item.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    item.body = item.body[1:]
    return node


def python_source(text):
    tree = without_docstrings(ast.parse(text))
    symbols = {}
    for item in tree.body:
        if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols[item.name] = ast.dump(item, include_attributes=False)
        elif isinstance(item, (ast.Assign, ast.AnnAssign)):
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    symbols[target.id] = ast.dump(item, include_attributes=False)
    return {"implementation": ast.dump(tree, include_attributes=False), "symbols": symbols}


def yaml_lines(text):
    """Conservative lexical YAML extractor, not a complete YAML parser."""
    # Keep inline comments and quote contents. Only standalone comments and blank lines are ignored.
    return [line.rstrip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def extract(data, parser):
    if data.startswith(b"version https://git-lfs.github.com/spec/v1"):
        raise ValueError("Git LFS pointer: fetch the artifact before claiming coverage")
    if parser == "binary":
        return {"artifact": hashlib.sha256(data).hexdigest()}
    text = data.decode("utf-8")
    if parser == "urdf":
        return urdf(text)
    if parser == "python":
        return python_source(text)
    if parser == "json":
        return {"data": json.loads(text)}
    if parser == "toml":
        return {"config": tomllib.loads(text)}
    if parser == "yaml":
        return {"config": yaml_lines(text)}
    if parser == "ros":
        fields = [line.split("#", 1)[0].strip() for line in text.splitlines()]
        return {"interface": [re.sub(r"\s+", " ", line) for line in fields if line]}
    if parser == "markdown":
        return {"documentation": text.replace("\r\n", "\n")}
    if parser == "text":
        return {"content": text.replace("\r\n", "\n")}
    raise ValueError(f"Unknown parser: {parser}")


PARSERS = {"urdf", "python", "json", "toml", "yaml", "ros", "markdown", "text", "binary"}
