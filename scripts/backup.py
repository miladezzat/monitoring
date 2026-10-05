#!/usr/bin/env python3
"""Quiesced local-volume backup and restore into an empty Compose project."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from common import ROOT, compose

HELPER = "python:3.13-alpine@" + json.loads((ROOT / "image-lock.json").read_text())["python:3.13-alpine"]


def docker(*arguments):
    subprocess.run(["docker", *arguments], check=True, stdout=subprocess.DEVNULL)


def helper(volume, folder, script, readonly=True):
    docker("run", "--rm", "--network", "none", "--security-opt", "no-new-privileges:true",
           "-v", volume + ":/data" + (":ro" if readonly else ""),
           "-v", str(folder) + ":/backup" + ("" if readonly else ":ro"),
           HELPER, "python", "-c", script)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    folder = args.directory.resolve()
    config = json.loads(compose("--profile", "demo", "config", "--format", "json", capture=True).stdout)
    volumes = config["volumes"]
    running = compose("ps", "--services", "--status", "running", capture=True).stdout.split()
    if args.action == "backup":
        folder.mkdir(mode=0o700, parents=True, exist_ok=False)
        manifest = {"format": 1, "volumes": {}}
        try:
            compose("stop")
            for key, value in volumes.items():
                filename = key + ".tar.gz"
                script = f"import tarfile,os; t=tarfile.open('/backup/{filename}','w:gz'); t.add('/data',arcname='.'); t.close(); os.chmod('/backup/{filename}',0o600)"
                helper(value["name"], folder, script)
                with open(folder / filename, "rb") as archive:
                    manifest["volumes"][key] = {"file": filename, "sha256": hashlib.file_digest(archive, "sha256").hexdigest()}
            (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            os.chmod(folder / "manifest.json", 0o600)
        finally:
            if running:
                compose("up", "-d", *running)
        print("Created quiesced backup at " + str(folder))
    else:
        if running:
            raise SystemExit("Stop the target project before restore. Use an empty, separate project for recovery drills.")
        manifest = json.loads((folder / "manifest.json").read_text())
        if manifest.get("format") != 1 or set(manifest["volumes"]) != set(volumes):
            raise SystemExit("Backup volume set does not match this starter version.")
        for key, item in manifest["volumes"].items():
            if item["file"] != key + ".tar.gz":
                raise SystemExit("Unexpected archive path")
            with open(folder / item["file"], "rb") as file:
                if hashlib.file_digest(file, "sha256").hexdigest() != item["sha256"]:
                    raise SystemExit("Archive checksum mismatch: " + key)
        # Check all targets before extracting anything; never overwrite existing data.
        for key, value in volumes.items():
            docker("volume", "create", "--label", "com.docker.compose.project=" + config["name"],
                   "--label", "com.docker.compose.volume=" + key, value["name"])
            helper(value["name"], folder, "import os; assert not os.listdir('/data'), 'Target volume is not empty'")
        for key, value in volumes.items():
            script = f'''import tarfile
def checked(member, destination):
    safe = tarfile.data_filter(member, destination)
    if safe:
        safe.uid, safe.gid = member.uid, member.gid
        safe.uname = safe.gname = None
    return safe
with tarfile.open('/backup/{key}.tar.gz') as archive:
    archive.extractall('/data', filter=checked)
'''
            helper(value["name"], folder, script, readonly=False)
        print("Restored into empty target volumes. Start the target project and verify readiness and stored data.")


if __name__ == "__main__":
    main()
