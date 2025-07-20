# Pytorch-DPP-HPC
This guide demonstrates how to deploy a high-performance compute (HPC) cluster using Juju, LXD, and Slurm with shared storage powered by CephFS.


🧱 Architecture Overview

| Component           | Count        | Role                                         |
|---------------------|--------------|----------------------------------------------|
| `slurmctld`         | 1            | Slurm controller                             |
| `slurmdbd`          | 1            | Slurm accounting daemon                      |
| `slurmd`            | 2            | Compute nodes                                |
| `sackd`             | 1            | For slurm control                            |
| `mysql`             | 1            | Backend DB for SlurmDBD                      |
| `slurmrestd `       | 1            | Slurm rest daemon                            |
| `cephfs-server`     | 1            | High bandwidth access file system server     |
| `filesystem-client` | 1 per `slurmd` | Mounts CephFS at `/mnt/shared`             |

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

### Bootstrap Juju Controller on LXD

Before bootstrapping if your system has `docker` already installed due to security and isolation reasons docker automatically disables NAT forwarding. Therefore check if NAT FORWARD is disabled by:
`sudo iptables -L FORWARD -v -n`

if it is disabled then enable FORWARD by:

`sudo iptables -P FORWARD ACCEPT`

The reason for doing this is because when the controller LXC container starts when the FORWARD is disabled there would be no internet connection. Therefore by enabling this you are able to start the controller.

`juju bootstrap localhost lxd-controller`

Create a new model:

`juju add-model slurm-hpc`



### Deploy Slurm Components
```
juju deploy sackd --base "ubuntu@24.04" --channel "edge" --constraints="virt-type=virtual-machine"
juju deploy slurmctld --base "ubuntu@24.04" --channel "edge" --constraints="virt-type=virtual-machine"
juju deploy slurmd --base "ubuntu@24.04" --channel edge --num-units 2 --constraints "virt-type=virtual-machine"
juju deploy slurmdbd --base "ubuntu@24.04" --channel "edge" --constraints="virt-type=virtual-machine"
juju deploy slurmrestd --base "ubuntu@24.04" --channel "edge" --constraints="virt-type=virtual-machine"
juju deploy mysql --channel "8.0/stable" --constraints="virt-type=virtual-machine"
```
### Integrate Slurm Components
```
juju integrate slurmctld sackd
juju integrate slurmctld slurmd
juju integrate slurmctld slurmdbd
juju integrate slurmctld slurmrestd
juju integrate slurmdbd mysql:database
```
Wait until all the applications are running:
```
watch juju status --color
```
Check if the SLURM is working with:
```
juju exec -u sackd/0 -- sinfo
```

SLURM by default sets the nodes to state `DOWN` therefore you can update the state to `RESUME` by:
```
juju exec -u sackd/0 -- scontrol update NodeName=all State=RESUME
```

### Deploy Ceph Cluster

First deploy a LXC VM with 30GB of storage size. CephFS requires atleast 3 OSD instances therefore if you are considering to store a usable data size of `X` GB, you will need to provision approximately `3*X` GB of raw storage across all your OSDs, plus additional overhead for the rest of the VM. In this example we will have 3, 7GB of OSD instances.

```
lxc launch ubuntu:24.04 cephfs-server --vm -c limits.cpu=2 -c limits.memory=4GB -d root,size=30GB
```

Shell inside the LXC VM:
```
lxc shell cephfs-server
```
Common problem:
Before doing anything try pinging `ubuntu.com` with ```ping -c 4 ubuntu.com```. Sometimes LXC is unable to resolve the DNS resulting in a failure to bootstrap microceph cluster. If your VM cannot resolve the DNS:

```
# Temporarily disable systemd-resolved as it will wipe the change you made on /etc/resolv.conf
systemctl stop systemd-resolved
systemctl disable systemd-resolved
```

Edit the /etc/resolv.conf and add nameservers `1.1.1.1` and `8.8.8.8`. The result should look like this:
```
# This is /run/systemd/resolve/stub-resolv.conf managed by man:systemd-resolved(8).
# Do not edit.
#
# This file might be symlinked as /etc/resolv.conf. If you're looking at
# /etc/resolv.conf and seeing this text, you have followed the symlink.
#
# This is a dynamic resolv.conf file for connecting local clients to the
# internal DNS stub resolver of systemd-resolved. This file lists all
# configured search domains.
#
# Run "resolvectl status" to see details about the uplink DNS servers
# currently in use.
#
# Third party programs should typically not access this file directly, but only
# through the symlink at /etc/resolv.conf. To manage man:resolv.conf(5) in a
# different way, replace this symlink by a static file or a different symlink.
#
# See man:systemd-resolved.service(8) for details about the supported modes of
# operation for /etc/resolv.conf.

nameserver 1.1.1.1
nameserver 8.8.8.8
nameserver 127.0.0.53
options edns0 trust-ad
search lxd
```

Wait 1-2 minutes and try again pinging `ubuntu.com`. If you can proceed to setup MicroCeph.


Set up MicroCeph to export a Ceph filesystem:
```
# Setup environment
ln -s /bin/true /usr/local/bin/udevadm
apt-get -y update
apt-get -y install ceph-common jq
snap install microceph

# Bootstrap Microceph should not take long
microceph cluster bootstrap

# Add a storage disk to Microceph
microceph disk add loop,7G,3
```
After running above command you shall see a success:
+-----------+---------+
|   PATH    | STATUS  |
+-----------+---------+
| loop,7G,3 | Success |
+-----------+---------+

We will create two new disk pools, then assign the two pools to a new filesystem with the name `cephfs`:
```
# Create a new data pool for our filesystem
microceph.ceph osd pool create cephfs_data

# and a metadata pool for the same filesystem
microceph.ceph osd pool create cephfs_metadata

# Create a new filesystem that uses the two created data pools
microceph.ceph fs new cephfs cephfs_metadata cephfs_data
```

We will also use fs-client as the username for the clients, and expose the whole directory tree (/) in read-write mode (rw):
```
microceph.ceph fs authorize cephfs client.fs-client / rw
```

In order to juju deploy cephfs-server-proxy you need:
- IP address of the HOST (cephfs-server)
- FSID
- CLIENT_KEY

```
export HOST=$(hostname -I)
export FSID=$(microceph.ceph -s -f json | jq -r '.fsid')
export CLIENT_KEY=$(microceph.ceph auth print-key client.fs-client)
```

Print the required information for reference and then exit the current shell session:
```
echo $HOST
echo $FSID
echo $CLIENT_KEY
exit
```

For example you will get the following:
```
10.207.31.97 fd42:c31a:7bb2:2eea:216:3eff:fe0f:1d83
30b66f9a-6776-4413-99d1-c3e778d42f71
AQD6EX1o+RmFCRAARC2XeoR4QA0FTWHX40h0eg==
logout
```
- HOST=10.207.31.97
- FSID=30b66f9a-6776-4413-99d1-c3e778d42f71
- CLIENT_KEY=AQD6EX1o+RmFCRAARC2XeoR4QA0FTWHX40h0eg==

Juju deploy `cephfs-server-proxy`

```
juju deploy cephfs-server-proxy \
  --channel latest/edge \
  --config fsid=<value of $FSID> \
  --config sharepoint=cephfs:/ \
  --config monitor-hosts="<value of $HOST>" \
  --config auth-info=fs-client:<value of $CLIENT_KEY>
```


### Mount CephFS on Compute Nodes
Deploy filesystem-client and integrate
```
juju deploy filesystem-client --channel latest/edge \
  --config mountpoint="/mnt/shared" \
  --config noexec=false

juju integrate slurmd:juju-info filesystem-client:juju-info
juju integrate filesystem-client:ceph-fs ceph-mds:ceph-fs
```

This mounts the CephFS volume (cephfs:/) at /mnt/shared on each slurmd node.

### Initialize Compute Nodes in Slurm

Mark compute nodes as IDLE (not DOWN) so Slurm can schedule jobs:
```
juju exec -u sackd/0 -- scontrol update NodeName=all State=RESUME
```
Then verify with:
```
juju exec -u sackd/0 -- srun -p slurmd hostname
```
### Setup Pytorch CPU for demonstration
Shell into one of the worker nodes to configure pytorch env:

```
juju ssh slurmd/1
```

Change permission:
```
sudo chown -R ubuntu:ubuntu /mnt/shared
```

Create `venv pytorch`:
```
cd /mnt/shared
python3 -m venv pytorch_env
source pytorch_env/bin/activate
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

Verify:
```
python
>>> import torch
>>> print(torch.__version__)
```

### Distributed training Pytorch DDP demonstration

create `run_ddp_job.sh` and `distributed_train.py` files on `/mnt/shared`

```
juju exec -u slurmd/` -- sbatch /mnt/shared/run_ddp_job.sh
```


🧼 Cleanup
```
juju destroy-model slurm-hpc --destroy-storage
juju destroy-controller lxd-controller --destroy-all-models --destroy-storage
```
📁 License

MIT. Feel free to modify and reuse for cluster bootstrapping or educational HPC work.
