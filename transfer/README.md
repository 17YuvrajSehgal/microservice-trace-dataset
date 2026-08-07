# Moving the StrataTrace datasets to Trillium (then Nibi)

Two datasets, both on stopped GCP collector VMs:

| App | VM | zone | source dir | on-disk |
|---|---|---|---|---|
| Train Ticket | `strata-tt-collector` | us-east4-c | `/mnt/data/traces` (+ `~/*_metrics`, `~/*_load.csv`) | 287 GB / 49 runs |
| Sock Shop | `stratatrace-collector` | us-east1-d | `~/traces` (+ `~/*_metrics`) | 246 GB / 60 bundles |

Target: `/scratch/yuvraj17/microservice-trace-dataset/{sockshop,trainticket}/` on Trillium.

## Why per-recipe `tar.gz` streamed over ssh (not one big tarball, not loose rsync)
- The **kernel CTF is already gzipped** (~62% of the bytes) → re-compressing the whole tree is
  wasted CPU; `pigz` compresses the text and passes the gz straight through.
- **Streamed to Trillium** (written there, no local tarball) → needs **no scratch space on the VM**
  (Sock Shop's boot disk can't hold a 246 GB tarball beside the data).
- **One archive per recipe** → tiny `/scratch` **inode** footprint (SciNet quotas file counts, not
  just bytes) and **unambiguous extraction** — each archive is one fault family's runs, so nothing
  mixes when unpacked.
- **Parallel across recipes** + a fast AES-NI cipher fill the WAN pipe; **atomic + resumable**.

## Step 0 — auth: let the VM reach Trillium (one-time; pick ONE)
The push runs ON the GCP VM and needs key-based SSH from the VM to Trillium.
- **A. VM key (lets Claude/the VM run the push unattended):** generate a key on the VM, add its
  PUBLIC key to Trillium `~/.ssh/authorized_keys`:
  ```bash
  # on the VM:
  ssh-keygen -t ed25519 -N '' -f ~/.ssh/trillium -C strata-tt-collector
  cat ~/.ssh/trillium.pub          # <- add this line to Trillium ~/.ssh/authorized_keys
  # then set SSH_KEY=~/.ssh/trillium for the push
  ```
- **B. Agent forwarding (you run it, your key never leaves your laptop):**
  ```bash
  gcloud compute ssh strata-tt-collector --zone=us-east4-c --ssh-flag="-A"   # local agent must hold your Trillium key
  # then on the VM, run the push (it uses the forwarded agent)
  ```
Test either way:  `ssh ${SSH_KEY:+-i $SSH_KEY} yuvraj17@trillium.scinet.utoronto.ca hostname`

## Step 1 — push each app (on its VM, after `git pull`)
```bash
sudo apt-get install -y pigz                        # parallel gzip (big speedup)
cd ~/microservice-trace-dataset/transfer

# Train Ticket (on strata-tt-collector):
TRILLIUM_USER=yuvraj17 SRC=/mnt/data/traces APP=trainticket PAR=4 SSH_KEY=~/.ssh/trillium bash push_to_trillium.sh
bash push_to_trillium.sh --verify                    # tar-tests every archive + run counts

# Sock Shop (on stratatrace-collector):
TRILLIUM_USER=yuvraj17 SRC=$HOME/traces APP=sockshop PAR=4 SSH_KEY=~/.ssh/trillium bash push_to_trillium.sh
```
Resumable: re-run anytime — archives already present are skipped.

## Step 2 — extract on Trillium (organized, no mixing)
```bash
cd /scratch/yuvraj17/microservice-trace-dataset/trainticket
bash ~/…/transfer/extract_on_trillium.sh --list      # sanity: run count per archive
bash ~/…/transfer/extract_on_trillium.sh             # -> <recipe>/<run>/...
# (or keep them as .tar.gz on /scratch and extract to node-local $SLURM_TMPDIR at compute time)
```

## Step 3 — Trillium -> Nibi
Both are Alliance/SciNet systems, so the robust, fastest option is **Globus** (parallel, checksummed,
retries, no babysitting): endpoints `SciNet Trillium` -> `Alliance Nibi`, transfer the whole
`microservice-trace-dataset/` folder. Or, matching your existing workflow, rsync the archives
(few large files = fast) from a Trillium login node:
```bash
ssh -A -i ~/.ssh/id_ed25519 yuvraj17@trillium.scinet.utoronto.ca
rsync -aHh --info=progress2 \
  /scratch/yuvraj17/microservice-trace-dataset/ \
  yuvraj17@nibi.alliancecan.ca:/scratch/yuvraj17/microservice-trace-dataset/
# NOTE: -a (no -z): the archives are already compressed, so skip rsync compression.
```

## Notes
- The per-run Prometheus **metrics** + client **load CSVs** live in `~` (not inside the trace
  bundles); the push ships them as `_aux_metrics_load.tar.gz` per app.
- "Very carefully": writes are atomic (`.partial`→`mv`), the push is resumable, and `--verify`
  tar-tests each archive and checks its run count against the source before you delete anything.
