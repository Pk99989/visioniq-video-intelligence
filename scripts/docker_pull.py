#!/usr/bin/env python3
"""Pull a Docker image without the Docker daemon's registry client.

Why this exists: on this VM the egress proxy stalls the Go TLS
handshake (the daemon's registry client can never complete a TLS
handshake to registry-1.docker.io / CloudFront), while OpenSSL-based
clients (curl, Python ssl) work fine. So this script implements the
Docker Registry HTTP API v2 with urllib and writes a
`docker save`-format tarball that `docker load` accepts.

Usage:
    python3 scripts/docker_pull.py python:3.12-slim /tmp/python-3.12-slim.tar
    docker load -i /tmp/python-3.12-slim.tar

Only public images on Docker Hub (library or a named namespace).
Multi-arch manifests: picks the linux/amd64 entry.
"""
import hashlib
import io
import json
import os
import sys
import tarfile
import urllib.request

REGISTRY = "https://registry-1.docker.io"
AUTH = "https://auth.docker.io/token"


def _req_json(url, headers=None, token=None):
    """Fetch + parse a JSON document, retrying the whole request
    when the egress proxy drops the connection mid-response."""
    import time

    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    last = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=h)
            # urllib honours https_proxy/no_proxy from the environment.
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read()
                digest = resp.headers.get("Docker-Content-Digest")
            return json.loads(body), digest
        except Exception as exc:  # noqa: BLE001 - retry anything transient
            last = exc
            time.sleep(2 * (attempt + 1))
    raise last


def _req(url, headers=None, token=None):
    # Kept for callers that only need the response headers; body
    # reads go through _req_json / _fetch_blob so retries apply.
    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=120)


def _token(repo):
    url = f"{AUTH}?service=registry.docker.io&scope=repository:{repo}:pull"
    body, _ = _req_json(url)
    return body["token"]


def _fetch_blob(repo, digest, token, expect_size):
    """Download one blob with retries + Range resume (the egress
    proxy drops large chunked downloads mid-stream)."""
    import time

    data = bytearray()
    for attempt in range(6):
        headers = {}
        if data:
            headers["Range"] = f"bytes={len(data)}-"
        try:
            req = urllib.request.Request(
                f"{REGISTRY}/v2/{repo}/blobs/{digest}", headers=headers)
            req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=180) as resp:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    data += chunk
            if len(data) == expect_size:
                break
            print(f"    short read ({len(data)}/{expect_size}), retrying", flush=True)
        except Exception as exc:  # noqa: BLE001 - retry anything transient
            print(f"    blob fetch failed (attempt {attempt + 1}): {exc}", flush=True)
            time.sleep(2 * (attempt + 1))
    if len(data) != expect_size:
        raise SystemExit(f"blob {digest}: got {len(data)} of {expect_size} bytes after retries")
    return bytes(data)


def pull(image, out_path):
    if ":" in image and "/" not in image.split(":")[-1]:
        name, tag = image.rsplit(":", 1)
    else:
        name, tag = image, "latest"
    repo = name if "/" in name else f"library/{name}"
    token = _token(repo)
    print(f"token ok for {repo}:{tag}", flush=True)

    manifest_headers = {
        "Accept": "application/vnd.docker.distribution.manifest.list.v2+json,"
                  "application/vnd.docker.distribution.manifest.v2+json,"
                  "application/vnd.oci.image.index.v1+json,"
                  "application/vnd.oci.image.manifest.v1+json",
    }
    manifest, manifest_digest = _req_json(
        f"{REGISTRY}/v2/{repo}/manifests/{tag}", manifest_headers, token)
    if manifest.get("mediaType", "").endswith("index.v1+json") or "manifests" in manifest:
        entry = next(m for m in manifest["manifests"]
                     if m["platform"]["architecture"] == "amd64"
                     and m["platform"]["os"] == "linux")
        print(f"multi-arch: using {entry['digest']}", flush=True)
        manifest, manifest_digest = _req_json(
            f"{REGISTRY}/v2/{repo}/manifests/{entry['digest']}",
            {"Accept": "application/vnd.oci.image.manifest.v1+json,"
                       "application/vnd.docker.distribution.manifest.v2+json"},
            token)
    config_digest = manifest["config"]["digest"]
    layers = [l["digest"] for l in manifest["layers"]]
    print(f"config {config_digest[:19]}... + {len(layers)} layers", flush=True)

    blobs = {}
    for digest in [config_digest] + layers:
        size = next((b["size"] for b in [manifest["config"]] + manifest["layers"]
                     if b["digest"] == digest), 0)
        print(f"  fetching {digest[:19]}... ({size // 1024} KiB)", flush=True)
        data = _fetch_blob(repo, digest, token, size)
        assert hashlib.sha256(data).hexdigest() == digest.split(":")[1], f"hash mismatch {digest}"
        blobs[digest] = data

    # docker-save tarball: manifest.json + config json + layer tars.
    # The layer files are the raw (compressed) blobs; Docker accepts
    # that in a save file (it re-compresses on load if needed).
    manifest_json = [{
        "Config": f"{config_digest.split(':')[1]}.json",
        "RepoTags": [f"{name}:{tag}"],
        "Layers": [f"{d.split(':')[1]}/layer.tar" for d in layers],
    }]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        def add(name, data):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        add("manifest.json", json.dumps(manifest_json).encode())
        add(f"{config_digest.split(':')[1]}.json", blobs[config_digest])
        for d in layers:
            add(f"{d.split(':')[1]}/layer.tar", blobs[d])
    with open(out_path, "wb") as f:
        f.write(buf.getvalue())
    print(f"wrote {out_path} ({len(buf.getvalue()) // (1024 * 1024)} MiB)", flush=True)
    if manifest_digest:
        print(f"manifest digest: {manifest_digest}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    pull(sys.argv[1], sys.argv[2])
