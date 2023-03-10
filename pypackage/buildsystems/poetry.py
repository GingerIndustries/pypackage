import subprocess
import json
import sys

from hashlib import sha256
from itertools import chain

from tomli import load as loadToml
from packaging.version import Version
from packaging.specifiers import SpecifierSet
from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from pypackage.util import ProjectMeta
from pypackage.util.dependency import Dependency

class PoetryBuildSystem:
    LEGACY_KEYS = ["dependencies", "source", "extras", "dev-dependencies"]
    RELEVANT_KEYS = [*LEGACY_KEYS, "group"]
    def __init__(self, console, pyproject):
        self.console = console
        self.pyproject = pyproject["tool"]["poetry"]
        with open("poetry.lock", "rb") as lock:
            self.lockfile = loadToml(lock)

    def _get_content_hash(self):
        # Yoinked from Poetry
        relevant_content = {}
        for key in PoetryBuildSystem.RELEVANT_KEYS:
            if data := self.pyproject.get(key) is None and key not in PoetryBuildSystem.LEGACY_KEYS:
                continue
            relevant_content[key] = data
        return sha256(json.dumps(relevant_content,
                                 sort_keys=True).encode()).hexdigest()

    def makeDepTree(self, dependencies):
        tree = {}
        basePackages = set(chain(*[set(self.pyproject.get(i, {}).keys()) for i in PoetryBuildSystem.RELEVANT_KEYS]))
        for name, dependency in dependencies.items():
            if name in basePackages:
                dependency.toTree(dependencies, tree)
        return tree

    def processLockEntryDeps(self, dependencies):
        result = []
        for name, rawReqs in dependencies.items():
            name = canonicalize_name(name)
            if isinstance(rawReqs, str):
                if rawReqs == "*":
                    reqs = SpecifierSet(">=0.0.0")
                else:
                    reqs = SpecifierSet(rawReqs)
            else:
                if rawReqs["version"] == "*":
                    reqs = SpecifierSet(">=0.0.0")
                else:
                    reqs = SpecifierSet(rawReqs["version"])
                if "markers" in rawReqs:
                    if isinstance(rawReqs["markers"], list):
                        if not all(map(lambda i: i.evaluate(), map(Marker, rawReqs["markers"]))):
                            continue
                    else:
                        if not Marker(rawReqs["markers"]).evaluate():
                            continue
                if rawReqs.get("optional", False):
                    self.console.print(f"[bold blue]NOTE[/bold blue]: Excluding optional dependency {name} ({str(reqs)})")
                    continue
            result.append(Requirement(name + str(reqs)))
        return result
        
    
    def depFromLock(self, lockEntry):
        return Dependency(lockEntry["name"], Version(lockEntry["version"]), self.processLockEntryDeps(lockEntry.get("dependencies", {})))
    
    def resolveDeps(self):
        if self._get_content_hash() != self.lockfile["metadata"]["content-hash"]:
            self.console.print("[bold yellow]WARNING[/bold yellow]: lockfile does not match, you may be getting incorrect dependencies! Run \"poetry lock\" to fix.")

        return {canonicalize_name(dependency["name"]): self.depFromLock(dependency) for dependency in self.lockfile["package"]}

    def generateMeta(self) -> ProjectMeta:
        return ProjectMeta(self.pyproject["name"], Version(self.pyproject["version"]), self.pyproject["description"], SpecifierSet(self.pyproject["dependencies"]["python"]))