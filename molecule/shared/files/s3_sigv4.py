"""Send one AWS SigV4-signed S3 request (region us-east-1, service s3).

Test helper of the Molecule scenarios, run on the target with its
/usr/bin/python3 (3.9 on EL 9, so standard library only and no newer
syntax). It replaces curl --aws-sigv4, whose SigV4 signature in curl 7.76.1
(EL 9) RustFS rejects with SignatureDoesNotMatch.

    python3 s3_sigv4.py [--cacert FILE] [--upload FILE] [--status] METHOD URL

The credentials are read as JSON from stdin, {"access_key": ..., "secret_key":
...}, so they stay out of argv (the command module's stdin parameter; a task
environment would put them on the remote shell command line).

Prints the response body and exits 1 on a status outside 2xx (like curl
--fail), or with --status prints only the status code and exits 0 on any HTTP
response (like curl --write-out '%{http_code}').
"""
import argparse
import datetime
import hashlib
import hmac
import http.client
import json
import ssl
import sys
import urllib.parse

REGION = "us-east-1"
SERVICE = "s3"


def _hmac(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cacert", help="CA file that must sign the server certificate")
    parser.add_argument("--upload", help="file to send as the request body")
    parser.add_argument("--status", action="store_true", help="print only the HTTP status code")
    parser.add_argument("method")
    parser.add_argument("url")
    args = parser.parse_args()

    creds = json.load(sys.stdin)
    url = urllib.parse.urlsplit(args.url)
    body = b""
    if args.upload:
        with open(args.upload, "rb") as f:
            body = f.read()

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()
    path = urllib.parse.quote(url.path or "/", safe="/~")
    query = "&".join(
        "%s=%s" % (urllib.parse.quote(k, safe="~"), urllib.parse.quote(v, safe="~"))
        for k, v in sorted(urllib.parse.parse_qsl(url.query, keep_blank_values=True))
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join([
        args.method,
        path,
        query,
        "host:%s\nx-amz-content-sha256:%s\nx-amz-date:%s\n" % (url.netloc, payload_hash, amz_date),
        signed_headers,
        payload_hash,
    ])
    scope = "%s/%s/%s/aws4_request" % (day, REGION, SERVICE)
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    key = ("AWS4" + creds["secret_key"]).encode("utf-8")
    for part in (day, REGION, SERVICE, "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    headers = {
        "Host": url.netloc,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
        "Authorization": "AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s"
        % (creds["access_key"], scope, signed_headers, signature),
    }
    if url.scheme == "https":
        conn = http.client.HTTPSConnection(
            url.hostname, url.port, context=ssl.create_default_context(cafile=args.cacert), timeout=30
        )
    else:
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=30)
    conn.request(args.method, path + ("?" + query if query else ""), body=body, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()

    if args.status:
        print(resp.status)
        return 0
    if not 200 <= resp.status < 300:
        sys.stderr.write("HTTP %d: %s\n" % (resp.status, data[:500].decode("utf-8", "replace")))
        return 1
    sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
