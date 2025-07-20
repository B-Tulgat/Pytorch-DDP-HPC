#!/bin/bash
#SBATCH --job-name=pytorch_ddp_mnist      # Job name
#SBATCH --output=logs/ddp_job_%j.out      # Standard output file
#SBATCH --error=logs/ddp_job_%j.err       # Standard error file
#SBATCH --nodes=1                         # Number of nodes to request
#SBATCH --ntasks-per-node=2               # Number of processes (tasks) per node
#SBATCH --cpus-per-task=4                 # Number of CPUs per task (for data loading etc.)
#SBATCH --mem=16G                         # Total memory per node (e.g., 8GB per task if 2 tasks)
#SBATCH --time=00:30:00                   # Wall-clock time limit

# --- Environment Setup ---
cd /mnt/shared

# Create logs directory if it doesn't exist
mkdir -p logs

# Activate your Python virtual environment.
source pytorch_env/bin/activate

torchrun \
  --nproc_per_node=$SLURM_NTASKS_PER_NODE \
  --rdzv_id=$SLURM_JOB_ID \
  --rdzv_backend=c10d \
  --rdzv_endpoint=$MASTER_ADDR:$MASTER_PORT \
  distributed_train.py

echo "Distributed training job finished."
