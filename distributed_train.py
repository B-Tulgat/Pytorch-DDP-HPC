import os
import torch
import torch.nn as nn
import torch.optim as optim
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP
from torchvision import datasets, transforms
from torch.utils.data import DataLoader, DistributedSampler

def setup(rank, world_size, backend='gloo'): # Default to gloo for CPU, or if GPUs are not definitely used
    """
    Initializes the distributed environment.
    'nccl' is preferred for GPU training, 'gloo' for CPU.
    """
    # Environment variables set by torchrun/Slurm
    # These are usually provided by torchrun, but fallback to localhost for local testing
    os.environ['MASTER_ADDR'] = os.environ.get('MASTER_ADDR', 'localhost')
    os.environ['MASTER_PORT'] = os.environ.get('MASTER_PORT', '29500') # Default port for DDP

    print(f"Rank {rank}: Initializing process group with MASTER_ADDR={os.environ['MASTER_ADDR']}, MASTER_PORT={os.environ['MASTER_PORT']}, WORLD_SIZE={world_size}, BACKEND={backend}")
    dist.init_process_group(backend, rank=rank, world_size=world_size)
    if torch.cuda.is_available() and backend == 'nccl':
        torch.cuda.set_device(rank) # Each process uses a specific GPU

def cleanup():
    """Destroys the distributed process group."""
    dist.destroy_process_group()

class SimpleModel(nn.Module):
    """A simple linear model for demonstration (e.g., for MNIST)."""
    def __init__(self):
        super(SimpleModel, self).__init__()
        self.fc = nn.Linear(784, 10) # MNIST: 28*28 = 784 input, 10 output classes

    def forward(self, x):
        x = x.view(x.size(0), -1) # Flatten the input
        return self.fc(x)

def train_model(rank, world_size, epochs):
    """Distributed training function for a single process."""
    print(f"Rank {rank}/{world_size}: Starting training...")
    # Dynamically choose backend: NCCL for GPU, Gloo for CPU
    backend = 'nccl' if torch.cuda.is_available() else 'gloo'
    setup(rank, world_size, backend)

    device = torch.device(f'cuda:{rank}' if torch.cuda.is_available() else 'cpu')
    print(f"Rank {rank}/{world_size}: Using device {device}")

    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.1307,), (0.3081,))
    ])

    # Download MNIST dataset (done only once by rank 0 to avoid race conditions)
    if rank == 0:
        datasets.MNIST('./data', train=True, download=True, transform=transform)
    dist.barrier() # Ensure dataset is downloaded before other ranks try to use it
    dataset = datasets.MNIST('./data', train=True, download=False, transform=transform)

    # DistributedSampler ensures each process gets a unique subset of the data
    sampler = DistributedSampler(dataset, num_replicas=world_size, rank=rank, shuffle=True)
    train_loader = DataLoader(dataset, batch_size=64, sampler=sampler, num_workers=4)

    model = SimpleModel().to(device)
    # DDP should be wrapped around the model. For CPU-only, device_ids=None is fine.
    ddp_model = DDP(model, device_ids=[rank] if torch.cuda.is_available() else None)

    optimizer = optim.SGD(ddp_model.parameters(), lr=0.01)
    criterion = nn.CrossEntropyLoss()

    for epoch in range(epochs):
        sampler.set_epoch(epoch) # Ensures data shuffling is different for each epoch
        ddp_model.train()
        running_loss = 0.0
        for batch_idx, (data, target) in enumerate(train_loader):
            data, target = data.to(device), target.to(device)
            optimizer.zero_grad()
            output = ddp_model(data)
            loss = criterion(output, target)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()

            if rank == 0 and batch_idx % 100 == 0:
                print(f"Epoch {epoch+1}, Batch {batch_idx}/{len(train_loader)}, Loss: {loss.item():.4f}")

        avg_loss = running_loss / len(train_loader)
        print(f"Rank {rank}, Epoch {epoch+1} finished. Average Loss: {avg_loss:.4f}")

    cleanup()

if __name__ == '__main__':
    # These environment variables are automatically set by torchrun.
    # The script reads them from os.environ.
    _rank = int(os.environ["RANK"])
    _world_size = int(os.environ["WORLD_SIZE"])
    _epochs = 5 # Number of training epochs

    train_model(_rank, _world_size, _epochs)
