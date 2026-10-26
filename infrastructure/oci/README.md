# NutriLens X OCI-only AI worker

This directory defines the final server-inference topology:

`Render API -> authenticated HTTPS -> Cloudflare Tunnel -> OCI A1 worker`

The worker binds only to `127.0.0.1:8000` on the VM. Cloudflare Tunnel makes
an outbound connection; OCI security lists must not expose port 8000. The
server-to-server bearer token remains required by the worker even behind the
tunnel.

## Owner gate before provisioning

The OCI tenancy must exist before any infrastructure command is run. Account
creation, address/payment identity verification, the Oracle Cloud Services
Agreement, and any financial or legal confirmation are owner actions.

The console must visibly label every selected resource **Always Free
Eligible**. Do not proceed from historical limits alone. As of 2026-09-27,
Oracle's current public Free Tier documentation says an Always Free tenancy is
equivalent to 2 A1 OCPUs and 12 GB RAM, while 200 GB combined boot/block storage
is included in the home region. The console and tenancy service limits are the
authoritative gate for this account:

- <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm>
- <https://docs.oracle.com/iaas/Content/FreeTier/freetier.htm>

## Provisioning constraints

1. Use only the tenancy home region.
2. Create one `VM.Standard.A1.Flex` instance only when it displays the Always
   Free label and the estimated monthly cost is zero.
3. Allocate no more than the actual remaining free OCPU/RAM limits. The intended
   target is 2 OCPUs and 12 GB RAM, but reduce it if the tenancy reports less.
4. Use the minimum console-supported boot volume and verify it remains within
   the tenancy's unused Always Free block-volume allowance.
5. Do not create a load balancer, database, paid public IP, paid monitoring, or
   extra block volume.
6. Allow no inbound worker port. Restrict administrative SSH to the owner's
   current IP or use an explicitly verified zero-cost OCI administration path.
7. Transfer the private custom YOLO checkpoint and cached Paddle models through
   an authenticated private channel. Never publish them to GitHub, a public
   image registry, or public Object Storage.

## Native ARM64 build

Use Ubuntu 24.04 AArch64 or another supported AArch64 image. Install Docker from
the operating-system repository, clone the private source, transfer the private
model cache, and run:

```bash
sudo bash scripts/oci/build_and_install_worker.sh
```

The script fails closed unless:

- the host reports `aarch64`;
- the custom checkpoint matches its governed SHA-256;
- both cached PP-OCRv5 model directories are complete;
- Torch, PaddlePaddle, OpenCV and Ultralytics import natively in the built
  image; and
- the worker health endpoint becomes ready.

The Paddle ARM wheel comes from Paddle's official stable CPU wheel index. Its
mere existence is not acceptance: native import, model load, and the real milk
fixture must pass on the OCI VM.

## Secrets and service supervision

Install the two examples as root-owned `0600` files under `/etc/nutrilens`:

- `worker.env.example` -> `worker.env` (replace the token locally);
- `worker-service.env.example` -> `worker-service.env`.

The systemd unit applies restart supervision, a read-only container filesystem,
dropped Linux capabilities, bounded PIDs, CPU/RAM limits, loopback-only port
binding and bounded Docker logs.

Create a named Cloudflare Tunnel in the existing Yash AI Technologies account,
store its credentials JSON at `/etc/nutrilens/cloudflared-credentials.json`,
install the example tunnel config as `/etc/nutrilens/cloudflared.yml`, and enable
`nutrilens-cloudflared.service`. Keep worker environment files root-only. Give
only the dedicated `cloudflared` group traversal on `/etc/nutrilens` and read
access to the tunnel config and credential JSON (for example directory mode
`0750`, group-owned `0640` tunnel files, and no membership for the application
user). Creating tunnel credentials is a distinct owner-approved credential
action; never commit the credentials file.

## Required acceptance before Render cutover

1. Restart the VM and prove both services recover without ACR or any Azure
   credential.
2. Run `scripts/oci/worker_health_snapshot.sh`.
3. Run the exact Country Delight milk fixture through the authenticated worker.
4. Require the accepted product, brand, `PER_100_ML`, serving size, 11 rows,
   ingredient and explicit Milk allergen evidence, truthful model/OCR
   provenance, and no fabricated date.
5. Capture cold start, warm inference, stage timings, CPU, RAM, disk and restart
   count.
6. Only after equivalence passes, set Render's `AI_WORKER_PROVIDER=oci`, worker
   URL and token, then run durable fallback, refresh/resume, idempotency, quota,
   persistence and owner-isolation acceptance with disposable QA accounts.

Azure deletion is intentionally after these gates. ACR is deleted last, after a
VM restart proves the local image has no registry dependency.
