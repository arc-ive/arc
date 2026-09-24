#!/usr/bin/env python3
"""Load the synthetic demo knowledge pack into a tenant.

Goes through the real HTTP API with a real session, so it exercises
authentication, tenant context, authorization, chunking, embedding and
indexing exactly as a person using the product would. It never writes to
the database directly: a loader that bypassed the API would prove
nothing about whether ingestion works.

Development use only — it authenticates through the dev reference-persona
endpoint, which exists only when APP_ENV=development.

    python demo/load_knowledge.py \
        --tenant ref-acme-technologies \
        --user ref-acme-technologies-company-admin
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

# (filename, KnowledgeSource, provenance shown as the document's identity)
DOCUMENTS = [
    ("company-overview.md", "internal_knowledge", "Acme Technologies Company Overview"),
    ("leave-policy.md", "policy", "Acme Technologies Leave Policy v3.1"),
    ("it-security-policy.md", "policy", "Acme Technologies IT and Security Policy v5.0"),
    ("onboarding.md", "procedure", "Acme Technologies Joining Acme"),
    ("benefits.md", "policy", "Acme Technologies Benefits"),
    ("departments.md", "internal_knowledge", "Acme Technologies Departments"),
    ("product-catalogue.md", "internal_knowledge", "Acme Technologies Service Catalogue"),
]

# The same documents in the formats a customer actually sends, generated
# from the Markdown by demo/build_formats.py. Loading these exercises
# extraction -- a fact has to survive a real parser, not just a text file
# Arc never had to parse.
FILE_DOCUMENTS = [
    ("leave-policy.docx", "policy"),
    ("product-catalogue.docx", "internal_knowledge"),
    ("it-security-policy.pdf", "policy"),
    ("benefits.pdf", "policy"),
]

PACK = Path(__file__).parent / "knowledge"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument(
        "--formats",
        action="store_true",
        help="Load the PDF and Word renderings instead of the Markdown, "
        "to exercise extraction.",
    )
    args = parser.parse_args()

    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def post(path: str, payload: dict) -> tuple[int, str]:
        import json

        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{args.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # CSRF double-submit: the cookie is the token.
        for cookie in jar:
            if "csrf" in cookie.name.lower():
                request.add_header("X-CSRF-Token", cookie.value)
        try:
            with opener.open(request, timeout=120) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def post_file(path: str, file_path, source: str) -> tuple[int, str]:
        """Upload one file as multipart/form-data.

        Hand-built rather than pulled from a library: the loader has no
        dependencies today, and one more just to assemble a multipart
        body is a dependency the demo path then has to carry.
        """
        import uuid as _uuid

        boundary = f"----arc{_uuid.uuid4().hex}"
        parts: list[bytes] = []

        def field(name: str, value: str) -> None:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                f"\r\n\r\n{value}\r\n".encode()
            )

        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{file_path.name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n".encode()
        )
        parts.append(file_path.read_bytes())
        parts.append(b"\r\n")
        field("source", source)
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)

        request = urllib.request.Request(
            f"{args.base_url}{path}",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        for cookie in jar:
            if "csrf" in cookie.name.lower():
                request.add_header("X-CSRF-Token", cookie.value)
        try:
            with opener.open(request, timeout=180) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    status, _ = post("/internal/dev/auth/login", {"user_id": args.user})
    if status != 200:
        print(f"Sign-in failed as {args.user} (HTTP {status}).", file=sys.stderr)
        print("Is the backend running with APP_ENV=development?", file=sys.stderr)
        return 1
    print(f"Signed in as {args.user}")

    loaded = 0

    if args.formats:
        for filename, source in FILE_DOCUMENTS:
            path = PACK / filename
            if not path.exists():
                print(f"  missing  {filename} — run demo/build_formats.py", file=sys.stderr)
                continue
            status, body = post_file(
                f"/tenants/{args.tenant}/knowledge/upload", path, source
            )
            if status in (200, 201):
                loaded += 1
                import json as _json

                extraction = _json.loads(body).get("extraction", {})
                print(
                    f"  loaded   {filename} "
                    f"({extraction.get('detected_format')}, "
                    f"{extraction.get('extracted_characters')} chars)"
                )
            else:
                print(f"  FAILED   {filename} (HTTP {status}) {body[:180]}", file=sys.stderr)
        print(f"\n{loaded} of {len(FILE_DOCUMENTS)} files loaded into {args.tenant}.")
        return 0 if loaded == len(FILE_DOCUMENTS) else 1

    for filename, source, provenance in DOCUMENTS:
        path = PACK / filename
        if not path.exists():
            print(f"  missing  {filename}", file=sys.stderr)
            continue
        status, body = post(
            f"/tenants/{args.tenant}/knowledge",
            {
                "source": source,
                "provenance": provenance,
                "content": path.read_text(encoding="utf-8"),
                "version": 1,
            },
        )
        if status in (200, 201):
            loaded += 1
            print(f"  loaded   {provenance}")
        else:
            # Never claim success on a failure — an ingestion loader that
            # lies is worse than one that does nothing.
            print(f"  FAILED   {provenance} (HTTP {status}) {body[:180]}", file=sys.stderr)

    print(f"\n{loaded} of {len(DOCUMENTS)} documents loaded into {args.tenant}.")
    if loaded != len(DOCUMENTS):
        return 1
    print("Verify retrieval against demo/knowledge/EXPECTED_ANSWERS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
