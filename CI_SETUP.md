# CI/CD setup (manual steps only)

These are the steps GitHub Actions cannot do for you. Do not put secret values in this repo.

## 1. Dedicated SSH key for CI

On your laptop (not the droplet):

```bash
ssh-keygen -t ed25519 -C "github-actions-kisna-prod" -f kisna-prod-deploy -N ""
```

This writes `kisna-prod-deploy` (private) and `kisna-prod-deploy.pub` (public). Use this key only for CI deploy. Do not reuse your personal SSH key.

## 2. Authorize the public key on the droplet

```bash
ssh root@YOUR_DROPLET_IP
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo 'PASTE_CONTENTS_OF_kisna-prod-deploy.pub_HERE' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Confirm you can connect with the new key before adding GitHub secrets:

```bash
ssh -i kisna-prod-deploy root@YOUR_DROPLET_IP 'echo ok'
```

## 3. GitHub secrets

Repo → Settings → Secrets and variables → Actions → New repository secret.

| Secret | Value comes from |
|---|---|
| `VULTR_REGISTRY_USERNAME` | Vultr Container Registry login user for `blr.vultrcr.com` (registry `qlink01`) |
| `VULTR_REGISTRY_PASSWORD` | Vultr Container Registry password / robot token for that user |
| `DROPLET_HOST` | Droplet public IPv4 (the host you SSH to today) |
| `DROPLET_SSH_KEY` | Full contents of `kisna-prod-deploy` including the `BEGIN` and `END` lines |

`DROPLET_SSH_KEY` must be the **private** key. Paste the whole PEM block. `/opt/kisna/.env` stays on the droplet; do not add it as a GitHub secret.

## 4. Verify the first run

1. Push this workflow to `prod`, or run **Actions → Deploy prod → Run workflow**.
2. Confirm job `test` is green, then `build-and-deploy` is green.
3. On the droplet:

```bash
docker ps --filter name=kisna-backend
curl -sS http://127.0.0.1:8000/ping
```

Expect `{"status":"ok"}`. Check the running image is `blr.vultrcr.com/qlink01/kisna-backend:<commit-sha>` of that workflow run.

If deploy fails, the workflow attempts rollback from `/opt/kisna/.previous-image`. If that file is empty (first deploy with no prior container), rollback fails loudly by design.
