# Pytorch-DPP-HPC
This guide demonstrates how to deploy a high-performance compute (HPC) cluster using Juju, LXD, and Slurm with shared storage powered by CephFS.

    ✅ Designed for local testing, but follows production-grade principles: 3 MONs, 3 OSDs, real shared FS, and VMs instead of containers.

🧱 Architecture Overview

|Component	| Count |	Role
|slurmctld	| 1 |	Slurm controller
|slurmdbd	| 1 |	Slurm accounting daemon
|slurmd	| 2 |	Compute nodes
|mysql	| 1 |	Backend DB for SlurmDBD
|ceph-mon |	3 |	Ceph monitors (quorum)
|ceph-osd |	3 |	Ceph OSDs with dedicated loop storage
|ceph-mgr |	1 |	Ceph manager
|ceph-mds |	1 |	Ceph metadata server (for CephFS)
|filesystem-client |	1 per slurmd |	Mounts CephFS at /mnt/shared
📦 Requirements

    Ubuntu 22.04+ (host system)

    LXD installed and initialized:
```
sudo snap install lxd
sudo lxd init --auto

Add yourself to the LXD group:

sudo usermod -aG lxd $USER
newgrp lxd
```
Juju installed (v3.6+):

   ` sudo snap install juju --classic --channel=3.6/stable`

1️⃣ Bootstrap Juju Controller on LXD

Before bootstrapping if your system has `docker` already installed due to security and isolation reasons docker automatically disables NAT forwarding. Therefore check if NAT FORWARD is disabled by:
`sudo iptables -L FORWARD -v -n`

if it is disabled then enable FORWARD by:

`sudo iptables -P FORWARD ACCEPT`

The reason for doing this is because when the controller LXC container starts when the FORWARD is disabled there would be no internet connection. Therefore by enabling this you are able to start the controller.

`juju bootstrap localhost lxd-controller`

Create a new model:

`juju add-model slurm-hpc`

2️⃣ Deploy Ceph Cluster (MONs + OSDs + MGR + MDS)
Deploy 3 Ceph MONs

`juju deploy ceph-mon --channel "edge" --num-units=3 --constraints="virt-type=virtual-machine"`

Deploy 3 Ceph OSDs with loop-backed disks

```
juju deploy ceph-osd \
  --channel quincy/stable \
  --num-units=3 \
  --constraints="virt-type=virtual-machine" \
  --storage osd-devices=loop,10G
```

Integrate OSDs and MONs

`juju relate ceph-osd ceph-mon`

3️⃣ Create a CephFS Volume

`juju deploy ceph-fs --channel quincy/stable --constraints="virt-type=virtual-machine" --num-units 2`

and relate:

`juju relate ceph-fs ceph-mon`


4️⃣ Deploy Slurm Components
```
juju deploy slurmctld --channel edge --constraints="virt-type=virtual-machine"
juju deploy slurmd    --channel edge --num-units=2 --constraints="virt-type=virtual-machine"
juju deploy slurmdbd  --channel edge --constraints="virt-type=virtual-machine"
juju deploy mysql     --channel 8.0/stable --constraints="virt-type=virtual-machine"
```
5️⃣ Integrate Slurm Components
```
juju integrate slurmctld slurmd
juju integrate slurmctld slurmdbd
juju integrate slurmdbd mysql
```
6️⃣ Mount CephFS on Compute Nodes
Deploy filesystem-client and integrate
```
juju deploy filesystem-client --channel latest/edge \
  --config mountpoint="/mnt/shared" \
  --config noexec=true

juju integrate slurmd:juju-info filesystem-client:juju-info
juju integrate filesystem-client:ceph-fs ceph-mds:ceph-fs
```

    🔁 This mounts the CephFS volume (cephfs:/) at /mnt/shared on each slurmd node.

7️⃣ Initialize Compute Nodes in Slurm

Mark compute nodes as IDLE (not DOWN) so Slurm can schedule jobs:
```
juju run --application slurmctld resume
```
Then verify with:
```
juju ssh slurmctld/0
sinfo
```

✅ Validation Checklist
Component	Test Command
Slurm cluster active	sinfo, scontrol show nodes
Ceph health	juju ssh ceph-mgr/0 -- ceph -s
CephFS mounted	`juju ssh slurmd/0 -- mount
Shared dir writable	juju ssh slurmd/0 -- touch /mnt/shared/testfile
💡 Notes & Best Practices

   - Ceph OSDs need real or loopback disks — use --storage osd-devices=loop,10G.

   - Always use VMs, not containers, for Slurm and Ceph, due to cgroup, systemd, and block device limitations.

   - 3 MONs are essential for quorum — don't run production with 1.

   - CephFS is scalable and ideal for HPC-style shared job directories.

🧼 Cleanup
```
juju destroy-model slurm-hpc --destroy-storage
juju destroy-controller lxd-controller --destroy-all-models --destroy-storage
```
📁 License

MIT. Feel free to modify and reuse for cluster bootstrapping or educational HPC work.
